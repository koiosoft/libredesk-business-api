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

# Rules loaded at startup. No handler may read disk: this instance is served so
# that what gets published matches exactly what came up.
RULES: Rules | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global RULES
    s = get_settings()

    # Fail-closed like config.py: a broken YAML prevents startup. A service that
    # boots with partial rules would publish badly composed corrections.
    RULES = load_rules(s.rules_dir)
    app.state.rules = RULES

    # Background tasks: the reference is held here so the event loop does not
    # collect them mid-flight (the silent failure we had with daemon threads).
    app.state.background_tasks = set()

    # Shared HTTP clients + concurrency semaphore. They live inside the
    # lifespan so shutdown is orderly.
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
        if not s.jev_completion_prompt_key:
            log.warning(
                "JEV_COMPLETION_PROMPT_KEY not set: corrections generate with the "
                "first prompt row LibreDesk returns (visible in every generation "
                "log). Required in production -- create the dedicated prompt in "
                "Admin -> AI and pin its key here (FEATURE.md D8)."
            )


        yield

        # Drained before closing: in-flight tasks use the httpx client that is
        # closed right after, and a stranded task would fail trying to publish.
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
