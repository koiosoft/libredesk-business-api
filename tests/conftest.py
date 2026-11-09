"""Shared test fixtures.

Tests run in-process against the ASGI app: no network, no database, and nothing is ever
deleted while testing.

The installed Starlette TestClient does not accept a custom client_host, so origin is
injected by wrapping the app in a thin ASGI layer that rewrites `scope["client"]`. That
keeps the security assertions honest: they exercise the same code path production uses.
"""

from __future__ import annotations

import pytest

TEST_KEY = "test-api-key-0000000000000000"
TEST_WEBHOOK_SECRET = "test-webhook-secret"
ALLOWED_IP = "10.1.2.3"     # inside 10.0.0.0/8 from the fixture allowlist
BLOCKED_IP = "203.0.113.9"  # documentation range, never listed


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Settings are cached through lru_cache, so the cache must be reset too."""
    monkeypatch.setenv("HUB_API_KEY", TEST_KEY)
    monkeypatch.setenv("HUB_ALLOWED_IPS", "127.0.0.1,10.0.0.0/8")
    monkeypatch.setenv("HUB_LIBREDESK_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("HUB_DB_HOST", "localhost")
    monkeypatch.setenv("HUB_DB_PASSWORD", "unused-in-tests")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class ForcedOriginApp:
    """ASGI wrapper that pins scope["client"] to a chosen address."""

    def __init__(self, app, client_host: str):
        self.app = app
        self.client_host = client_host

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = dict(scope)
            scope["client"] = (self.client_host, 54321)
        await self.app(scope, receive, send)


def _make_client(client_host: str):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(ForcedOriginApp(app, client_host))


@pytest.fixture
def client():
    """Caller coming from an allowlisted address."""
    return _make_client(ALLOWED_IP)


@pytest.fixture
def outside_client():
    """Caller coming from an address that is NOT allowlisted."""
    return _make_client(BLOCKED_IP)


@pytest.fixture
def key_headers():
    return {"X-Api-Key": TEST_KEY}
