"""Entry point for the control plane (hub-api).

Plane separation: this service is NEVER on the critical path of a customer reply.
Webhooks, cleanup, tools and jobs may degrade without any lead noticing. The AI proxy
(ai-proxy, Go) is on that path and lives apart precisely because of that.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.routers import cleanup, hooks, meta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s hub-api %(name)s %(message)s",
)

log = logging.getLogger("hub-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info(
        "hub-api ready | bind=%s:%s | allowlist=%s",
        s.hub_api_bind, s.hub_api_port, [str(n) for n in s.networks],
    )
    if not s.webhook_secret:
        log.warning(
            "HUB_LIBREDESK_WEBHOOK_SECRET not set: /hooks/libredesk will reject everything. "
            "Correct fail-closed behavior, but events go nowhere until it is configured."
        )
    if s.hub_api_bind in ("0.0.0.0", "::"):
        log.warning(
            "BINDING ALL INTERFACES. The port is reachable on every network; the allowlist "
            "still applies. Consider pinning HUB_API_BIND to the specific LAN address."
        )
    yield


app = FastAPI(
    title="Customer Hub — intranet control plane",
    version="0.1.0",
    lifespan=lifespan,
    summary=(
        "Internal service for LibreDesk/Koiosoft: webhook ingestion, test-conversation "
        "cleanup, custom AI tools and own LLM jobs. Never exposed to the internet."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    # Live Swagger is the main reason to use FastAPI instead of hand-rolled routing.
    openapi_url="/openapi.json",
)

app.include_router(meta.router)
app.include_router(hooks.router)
app.include_router(cleanup.router)
