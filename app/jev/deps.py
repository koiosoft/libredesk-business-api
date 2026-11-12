"""Shared HTTP clients and the concurrency semaphore, created at startup.

One httpx.AsyncClient for the whole process: it reuses connections and avoids the
handshake cost per event. Closed on shutdown.

The semaphore bounds SIMULTANEOUS pipelines (plan R1). It does not bound intake:
the 202 is always answered fast; what queues is the slow work.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from app.core.config import Settings
from app.jev.classifier import Classifier
from app.jev.libredesk import LibreDeskClient
from app.jev.pipeline import EnforcementPipeline

log = logging.getLogger("hub-api.deps")


class HubClients:
    """Agregado de dependencias inyectables desde app.state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Generous global timeout: /api/v1/ai/completion takes seconds with
        # proveedor real (medido contra nemotron: 3-15s segun longitud).
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=8),
            follow_redirects=False,
        )
        self.classifier = Classifier(
            self.http,
            url=settings.classifier_url,
            api_key=settings.classifier_api_key,
            model=settings.classifier_model,
            log_request=settings.classifier_log_request,
        )
        self.libredesk = LibreDeskClient(
            self.http,
            base_url=settings.libredesk_base_url,
            api_key=settings.libredesk_api_key,
            api_secret=settings.libredesk_api_secret,
            log_request=settings.completion_log_request,
            timeout_s=settings.jev_generation_timeout_s,
        )
        self.semaphore = asyncio.Semaphore(settings.jev_concurrency)
        # Strong references for fire-and-forget diagnostics (confirming a handoff
        # from private notes). Without this the loop may collect them mid-flight.
        self.background_tasks: set[asyncio.Task] = set()

    async def aclose(self) -> None:
        await self.http.aclose()


@asynccontextmanager
async def clients(settings: Settings) -> AsyncIterator[HubClients]:
    hub = HubClients(settings)
    log.info(
        "http clients ready | classifier=%s model=%s | libredesk=%s credentials=%s "
        "| concurrency=%s",
        settings.classifier_url,
        settings.classifier_model,
        settings.libredesk_base_url,
        bool(settings.libredesk_api_key and settings.libredesk_api_secret),
        settings.jev_concurrency,
    )
    if not (settings.libredesk_api_key and settings.libredesk_api_secret):
        log.warning(
            "HUB_LIBREDESK_API_KEY/SECRET not set: the pipeline can classify but will "
            "never publish. Correct fail-closed behavior."
        )
    try:
        yield hub
    finally:
        await hub.aclose()


async def run_guarded(hub: HubClients, pipeline: EnforcementPipeline,
                      item: dict) -> dict:
    """Runs the pipeline under the semaphore.

    The limit covers JEV + generation + publishing as one unit: capping only the
    slow step would let a burst keep N jobs open waiting their turn inside the
    job itself.
    """
    async with hub.semaphore:
        return await pipeline.run(item)
