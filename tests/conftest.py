"""Shared test fixtures.

Tests run in-process against the ASGI app: no network, no database, and nothing is ever
deleted while testing.

The installed Starlette TestClient does not accept a custom client_host, so origin is
injected by wrapping the app in a thin ASGI layer that rewrites `scope["client"]`. That
keeps the security assertions honest: they exercise the same code path production uses.

Settings are fail-closed, so this fixture has to satisfy every validator — including the
JEV ones. Tests never reach the classifier: what is exercised here is the configuration
contract, not the pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Reglas de prueba: cumplen el CONTRATO (question.instructions, options con
# `none`, agente habilitado con prefijos por canal, augmenter presente) pero no
# are NOT the repo's. rules/*.yaml is edited live on purpose, so wiring contract
# tests to that content would break CI whenever an action or agent id changes --
# with no bug involved. Schema validation against the real files lives only in
# tests/test_rules.py::test_repo_rules_load.
FIXTURE_ASSISTANT_ID = 42
FIXTURE_CHOICE = "some-action"
FIXTURE_ASSIGN_USER_ID = 9011  # users.id del bot en la fixture

FIXTURE_OPTIONS = """\
question:
  instructions: Que debe hacer la correccion?
options:
  none: No intervenir.
  some-action: Reescribe la respuesta para cerrar y derivar a un humano.
  revive-action:
    text: Reescribe agregando una pregunta de levantamiento.
    post_action: revive-assistant
"""

FIXTURE_AGENTS = f"""\
agents:
  {FIXTURE_ASSISTANT_ID}:
    enabled: true
    name: Fixture Agent
    assign_user_id: {FIXTURE_ASSIGN_USER_ID}
    prefixes:
      # Texto PLANO a proposito: with_prefix() escapa y envuelve en <p>, asi que un
      # YAML con HTML ya hecho se publicaria doblemente escapado. Distintos por
      # canal para que los testes puedan discriminar cual se aplico.
      chat: "Nota de chat"
      email: "Nota de correo"
"""

FIXTURE_AUGMENTER = "# prompt-augmenter (fixture)\n\nComposicion: ROL, ACCION, PERSONA.\n"


def write_rules(tmp_path: Path, *, options_yaml: str = FIXTURE_OPTIONS,
                agents_yaml: str = FIXTURE_AGENTS,
                augmenter_md: str = FIXTURE_AUGMENTER) -> Path:
    """Directorio de reglas valido segun el contrato, listo para mutar por caso."""
    d = tmp_path / "rules"
    d.mkdir(exist_ok=True)
    (d / "prompts.yaml").write_text(options_yaml, encoding="utf-8")
    (d / "agents.yaml").write_text(agents_yaml, encoding="utf-8")
    (d / "prompt-augmenter.md").write_text(augmenter_md, encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def _rules_dir_for_app(monkeypatch, tmp_path_factory):
    """App-level rule source: fixture YAML, never rules/ from the repo.

    rules/*.yaml is edited live in production; booting the app inside a test must
    not depend on its content. Schema validation against the real files happens
    once, in tests/test_rules.py::test_repo_rules_load.
    """
    d = write_rules(tmp_path_factory.mktemp("app-rules"))
    monkeypatch.setenv("HUB_RULES_DIR", str(d))


@pytest.fixture
def make_rules(tmp_path: Path):
    """Factory para casos que necesitan reglas MUTADAS (una sola cosa por caso).

    Nombre distinto al helper para no pisarlo: los testes que solo quieren reglas
    validas usan `rules` / `rules_dir`.
    """
    def _factory(**kw) -> Path:
        return write_rules(tmp_path, **kw)
    return _factory


@pytest.fixture
def rules_dir(tmp_path: Path) -> Path:
    """Reglas minimas validas escritas en disco (carga real desde YAML)."""
    return write_rules(tmp_path)


@pytest.fixture
def rules(rules_dir):
    """Rules object for tests: built from fixture YAML, never from rules/."""
    from app.core.rules import load_rules

    return load_rules(rules_dir)

TEST_KEY = "test-api-key-0000000000000000"
TEST_WEBHOOK_SECRET = "test-webhook-secret"
# Satisfies the CLASSIFIER_API_KEY length validator; it is not a real credential.
TEST_CLASSIFIER_KEY = "test-classifier-key-0000000000"
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
    monkeypatch.setenv("CLASSIFIER_API_KEY", TEST_CLASSIFIER_KEY)
    monkeypatch.setenv("CLASSIFIER_URL", "https://openrouter.test/api/alpha/decisions")
    monkeypatch.setenv("CLASSIFIER_MODEL", "typesafe/jev-test")
    # HUB_RULES_DIR lo fija el fixture autouse _rules_dir_for_app con YAML de
    # prueba; nunca se apunta a rules/ del repo (ese contenido cambia en vivo).

    # El dedupe vive en memoria (app/core/state.py). Sin reinicio por test, el
    # segundo caso que enviara el mismo payload heredaria el evento como
    # "duplicado" del anterior y la prueba fallaria por contaminacion de estado.
    from app.core.state import STATE

    monkeypatch.setattr(STATE, "_seen", type(STATE._seen)())
    monkeypatch.setattr(STATE, "_channels", type(STATE._channels)())
    monkeypatch.setattr(STATE, "_corrections", {})

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
