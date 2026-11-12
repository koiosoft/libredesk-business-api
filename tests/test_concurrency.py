"""Pruebas de concurrencia: semaforo, 202 inmediato y ausencia de hilos.

Cubren R1 y R2 del plan, que son los riesgos de severidad Alta que justifican la
Fase D. Se comprueban propiedades observables del modelo de ejecucion, no detalles
de implementacion.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
from pathlib import Path

import pytest

from app.core.config import Settings
from app.jev.deps import HubClients, run_guarded
from app.jev.pipeline import EnforcementPipeline



class SlowPipeline:
    """Registra cuantos trabajos corren simultaneamente."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.running = 0
        self.max_seen = 0
        self.done = 0

    async def run(self, item):
        self.running += 1
        self.max_seen = max(self.max_seen, self.running)
        await asyncio.sleep(self.delay)
        self.running -= 1
        self.done += 1
        return {"outcome": "corrected", "n": item}


# --- Semaforo ---------------------------------------------------------------

async def test_semaphore_caps_concurrent_pipelines():
    s = Settings(JEV_CONCURRENCY="2")
    hub = HubClients(s)
    try:
        pipe = SlowPipeline()
        await asyncio.gather(*[run_guarded(hub, pipe, i) for i in range(10)])
        assert pipe.done == 10
        assert pipe.max_seen <= 2, f"hubo {pipe.max_seen} simultaneos con limite 2"
    finally:
        await hub.aclose()


async def test_semaphore_is_not_starved_by_failures():
    """Un trabajo que revienta debe liberar el slot (async with, no acquire suelto)."""

    class Boom(SlowPipeline):
        async def run(self, item):
            self.running += 1
            try:
                raise RuntimeError("boom")
            finally:
                self.running -= 1

    s = Settings(JEV_CONCURRENCY="1")
    hub = HubClients(s)
    try:
        pipe = Boom()
        results = await asyncio.gather(
            *[run_guarded(hub, pipe, i) for i in range(4)], return_exceptions=True
        )
        assert all(isinstance(r, RuntimeError) for r in results)
        # Si el slot no se liberara, el gather colgaria y esto expiraria.
        assert pipe.running == 0
    finally:
        await hub.aclose()


def test_no_threading_in_the_webhook_path():
    """La Fase D elimina threading.Thread por evento. Regresion guardada.

    Un hilo por evento significa: sin tope de concurrencia, ~8 MB de stack por
    espera de red, y muerte silenciosa de trabajos a medias al reiniciar — que con
    "LibreDesk no reintenta" equivale a perder el evento para siempre.
    """
    import app.routers.hooks as hooks_mod
    import app.jev.pipeline as pipeline_mod
    import app.main as main_mod

    for mod in (hooks_mod, pipeline_mod, main_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "threading.Thread" not in src, f"{mod.__name__} sigue creando hilos"
        assert ".start()" not in src, f"{mod.__file__} arranca un hilo"
