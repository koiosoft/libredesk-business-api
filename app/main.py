"""Entry point for the control plane (hub-api).

Plane separation: this service is NEVER on the critical path of a customer reply.
Webhooks, cleanup, tools and jobs may degrade without any lead noticing. The AI proxy
(ai-proxy, Go) is on that path and lives apart precisely because of that.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.rules import Rules, load_rules
from app.jev.deps import clients
from app.routers import cleanup, hooks, meta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s hub-api %(name)s %(message)s",
)

log = logging.getLogger("hub-api")

# Reglas cargadas en el arranque. Ningun handler debe leer el disco: se sirve esta
# instancia para que lo publicado corresponda exactamente a lo que subio.
RULES: Rules | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global RULES
    s = get_settings()

    # Fail-closed igual que config.py: un YAML roto impide subir. Un servicio que
    # arranca con reglas parciales publicaria correcciones mal compuestas.
    RULES = load_rules(s.rules_dir)
    app.state.rules = RULES

    # Tareas de fondo: la referencia se retiene aqui para que el event loop no las
    # recolecte a mitad (el fallo silencioso que teniamos con los hilos daemon).
    app.state.background_tasks = set()

    # Clientes HTTP compartidos + semaforo de concurrencia. Viven dentro del
    # lifespan para que el cierre sea ordenado.
    async with clients(s) as hub:
        app.state.hub = hub

        log.info(
            "hub-api ready | bind=%s:%s | allowlist=%s | rules=%s",
            s.hub_api_bind, s.hub_api_port, [str(n) for n in s.networks],
            RULES.rules_hash,
        )
        if not s.webhook_secret:
            log.warning(
                "HUB_LIBREDESK_WEBHOOK_SECRET not set: /hooks/libredesk will reject "
                "everything. Correct fail-closed behavior, but events go nowhere until "
                "it is configured."
            )
        if not s.classifier_api_key:
            log.warning(
                "CLASSIFIER_API_KEY not set: the pipeline cannot classify, so nothing "
                "is ever published. Events are still received and logged."
            )
        if s.hub_api_bind in ("0.0.0.0", "::"):
            log.warning(
                "BINDING ALL INTERFACES. The port is reachable on every network; the "
                "allowlist still applies. Consider pinning HUB_API_BIND to the specific "
                "LAN address."
            )

        yield

        # Drenado antes de cerrar: las tareas en vuelo usan el httpx client que se
        # cierra justo despues, y una tarea huespeda fallaria al intentar publicar.
        pending = [t for t in app.state.background_tasks if not t.done()]
        if pending:
            log.info("draining %s background task(s) before shutdown", len(pending))
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(
    title="Customer Hub — intranet control plane",
    version="0.2.0",
    lifespan=lifespan,
    summary=(
        "Internal service for LibreDesk/Koiosoft: webhook ingestion, JEV enforcement "
        "loop over AI-agent replies, test-conversation cleanup, custom AI tools and own "
        "LLM jobs. Never exposed to the internet."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    # Live Swagger is the main reason to use FastAPI instead of hand-rolled routing.
    openapi_url="/openapi.json",
)

app.include_router(meta.router)
app.include_router(hooks.router)
app.include_router(cleanup.router)
