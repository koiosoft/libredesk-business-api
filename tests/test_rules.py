"""Contrato de carga de reglas (rules/*.yaml) y de los validadores JEV.

Estas pruebas son el equivalente automatizado del "no sube con reglas rotas":
cada caso reproduce una forma concreta en que un YAML puede quedar incompleto y
verifica que el arranque aborta en vez de degradar a publicar sin evaluar.

Nada aqui toca red, base de datos ni LibreDesk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import ConfigError, Settings
from app.core.rules import NONE_OPTION, RulesError, load_rules

REPO_RULES = Path(__file__).resolve().parent.parent / "rules"


# --- El contrato del formato (fixtures, NUNCA rules/ reales) -----------------
#
# Las reglas se editan en vivo. Ninguna prueba de CONTRATO puede depender de
# que prompts.yaml conserve ciertos keys, prefijos o ids de agente: eso cambia
# a proposito y romperia CI sin que exista bug. Estos casos escriben YAML
# minimos en tmp_path. Unica excepcion: test_repo_rules_load(), que lee rules/
# solo para verificar parseabilidad e invariantes de forma, nunca contenido.

from tests.conftest import (
    FIXTURE_AGENTS as MINIMAL_AGENTS,
    FIXTURE_ASSISTANT_ID,
    FIXTURE_AUGMENTER as MINIMAL_AUGMENTER,
    FIXTURE_CHOICE,
    FIXTURE_OPTIONS as MINIMAL_OPTIONS,
)
from tests.conftest import write_rules as _fixture_write_rules


def write_rules(tmp_path: Path, options_yaml: str = MINIMAL_OPTIONS,
                agents_yaml: str = MINIMAL_AGENTS,
                augmenter_md: str = MINIMAL_AUGMENTER) -> Path:
    """Escribe un directorio de reglas valido segun el contrato.

    Defaults: quien muta UNA cosa deja la otra intacta sin repetir YAML.
    Ningun caso copia rules/ del repo; esos archivos cambian en vivo a proposito.
    """
    d = tmp_path / "rules"
    d.mkdir(exist_ok=True)
    (d / "prompts.yaml").write_text(options_yaml, encoding="utf-8")
    (d / "agents.yaml").write_text(agents_yaml, encoding="utf-8")
    (d / "prompt-augmenter.md").write_text(augmenter_md, encoding="utf-8")
    return d


def test_repo_rules_load():
    """Los YAML versionados deben ser validos: si alguien los rompe, esto falla.

    Unica prueba que lee rules/. Verifica SOLO que carga y las invariantes del
    contrato ('none' presente, al menos una accion, hashes con la forma debida).
    No afirma contenidos: esos se cambian en vivo a proposito.
    """
    rules = load_rules(REPO_RULES)
    assert rules.options, "prompts.yaml declared no action"
    assert NONE_OPTION in rules.options, "the 'none' option is missing"
    assert rules.agents, "agents.yaml declared no agent"
    assert len(rules.rules_hash) == 12 and len(rules.rules_version) == 8


def test_none_never_produces_an_action(tmp_path: Path):
    """`none` es valida como eleccion pero jamas como texto a inyectar."""
    rules = load_rules(write_rules(tmp_path, MINIMAL_OPTIONS, MINIMAL_AGENTS))
    assert rules.action_text(NONE_OPTION) is None
    assert rules.action_text(None) is None
    assert rules.action_text("inexistente") is None
    for key in rules.options:
        if key != NONE_OPTION:
            assert rules.action_text(key)


def test_agent_ids_are_assistant_ids_not_user_ids(tmp_path: Path):
    """La allowlist indexa por ai_assistants.id, no por el user_id del bot."""
    rules = load_rules(write_rules(tmp_path, MINIMAL_OPTIONS, MINIMAL_AGENTS))
    assert rules.is_evaluable(42) is True
    assert rules.is_evaluable(9999) is False


def test_unknown_agent_is_fail_closed(tmp_path: Path):
    rules = load_rules(write_rules(tmp_path, MINIMAL_OPTIONS, MINIMAL_AGENTS))
    assert rules.is_evaluable(7) is False
    assert rules.agent(7) is None


def test_prefix_resolution_is_per_channel_and_fail_closed(tmp_path: Path):
    rules = load_rules(write_rules(tmp_path, MINIMAL_OPTIONS, MINIMAL_AGENTS))
    agent = rules.agent(42)
    assert agent is not None
    assert agent.prefix_for("chat")
    assert agent.prefix_for("email")
    # Canal no declarado o desconocido => no se publica.
    assert agent.prefix_for("telegram") is None
    assert agent.prefix_for(None) is None


def test_extended_option_shape_exposes_post_action(tmp_path):
    """`{text, post_action}` es forma valida; el texto sigue llegando a JEV."""
    rules = load_rules(write_rules(tmp_path))   # la fixture trae revive-action
    assert rules.action_text("revive-action") == "Reescribe agregando una pregunta de levantamiento."
    assert rules.post_action("revive-action") == "revive-assistant"
    assert rules.post_action("some-action") is None
    assert rules.post_action(NONE_OPTION) is None


def test_unknown_post_action_aborts(tmp_path):
    d = write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n"
        "  x:\n    text: Reescribe Y.\n    post_action: delete-everything\n"))
    with pytest.raises(RulesError, match="unknown post_action"):
        load_rules(d)


def test_plain_and_extended_options_can_mingle(tmp_path):
    d = write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n"
        "  plain: Reescribe X.\n"
        "  ext:\n    text: Reescribe Y.\n    post_action: revive-assistant\n"))
    rules = load_rules(d)
    assert rules.action_text("plain") == "Reescribe X."
    assert rules.post_action("ext") == "revive-assistant"
    # El hash debe cambiar si cambia un post_action (forma parte del contrato).
    other = load_rules(write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n  ext: Reescribe Y.\n")))
    assert rules.rules_hash != other.rules_hash


def test_assign_user_id_is_parsed_and_validated(tmp_path):
    from tests.conftest import FIXTURE_ASSISTANT_ID as AID, FIXTURE_ASSIGN_USER_ID as UID

    rules = load_rules(write_rules(tmp_path))
    assert rules.agent(AID).assign_user_id == UID
    # opcional: un agente sin el campo sigue siendo valido (el revive se omite).
    d = write_rules(tmp_path, agents_yaml=(
        "agents:\n  %d:\n    enabled: true\n    prefixes:\n      chat: Nota\n" % AID))
    assert load_rules(d).agent(AID).assign_user_id is None


def test_bad_assign_user_id_aborts(tmp_path):
    d = write_rules(tmp_path, agents_yaml=(
        "agents:\n  42:\n    enabled: true\n    assign_user_id: bot\n"
        "    prefixes:\n      chat: Nota\n"))
    with pytest.raises(RulesError, match="not an integer"):
        load_rules(d)


# --- Arranque abortado ante reglas incompletas ------------------------------

@pytest.fixture
def broken_rules(tmp_path: Path) -> Path:
    """Reglas minimas VALIDAS listas para mutar una cosa por caso.

    No copia rules/ del repo: ese contenido cambia en vivo y los testes de
    contrato no pueden depender de cadenas especificas de prompts.yaml.
    """
    return write_rules(tmp_path)


def test_missing_none_option_aborts(broken_rules):
    """Sin `none` el default pasa a ser publicar: hay que rechazar el arranque."""
    (broken_rules / "prompts.yaml").write_text(
        "question:\n  instructions: ok\noptions:\n  solo-accion: Reescribe X.\n",
        encoding="utf-8",
    )
    with pytest.raises(RulesError, match="mandatory"):
        load_rules(broken_rules)


def test_empty_option_description_aborts(broken_rules):
    p = broken_rules / "prompts.yaml"
    p.write_text(
        "question:\n  instructions: ok\noptions:\n  none: \"   \"\n", encoding="utf-8"
    )
    with pytest.raises(RulesError, match="non-empty description"):
        load_rules(broken_rules)


def test_missing_question_instructions_aborts(broken_rules):
    (broken_rules / "prompts.yaml").write_text(
        "options:\n  none: ok\n", encoding="utf-8"
    )
    with pytest.raises(RulesError, match="question"):
        load_rules(broken_rules)


def test_invalid_yaml_aborts(broken_rules):
    (broken_rules / "prompts.yaml").write_text("options:\n  - : : :\n\t bad: [\n", encoding="utf-8")
    with pytest.raises(RulesError, match="invalid YAML"):
        load_rules(broken_rules)


def test_enabled_agent_without_prefixes_aborts(broken_rules):
    (broken_rules / "agents.yaml").write_text(
        "agents:\n  7:\n    enabled: true\n", encoding="utf-8"
    )
    with pytest.raises(RulesError, match="no prefixes"):
        load_rules(broken_rules)


def test_unknown_channel_aborts(broken_rules):
    (broken_rules / "agents.yaml").write_text(
        "agents:\n  7:\n    enabled: true\n    prefixes:\n      telegram: hola\n",
        encoding="utf-8",
    )
    with pytest.raises(RulesError, match="unknown channel"):
        load_rules(broken_rules)


def test_non_numeric_agent_id_aborts(broken_rules):
    (broken_rules / "agents.yaml").write_text(
        "agents:\n  sofia:\n    enabled: true\n    prefixes:\n      chat: hola\n",
        encoding="utf-8",
    )
    with pytest.raises(RulesError, match="not an integer"):
        load_rules(broken_rules)


def test_disabled_agent_needs_no_prefix(broken_rules):
    """Un agente deshabilitado se declara para documentar, no para publicar."""
    (broken_rules / "agents.yaml").write_text(
        "agents:\n  9:\n    enabled: false\n", encoding="utf-8"
    )
    rules = load_rules(broken_rules)
    assert rules.is_evaluable(9) is False


def test_missing_file_aborts(tmp_path):
    with pytest.raises(RulesError, match="not found"):
        load_rules(tmp_path)


def test_non_ascii_libredesk_credentials_abort(monkeypatch):
    """Credentials go into an HTTP header: non-ASCII crashes httpx at request time.

    Measured: a secret truncated with U+2026 made every pipeline call raise
    UnicodeEncodeError inside httpx. Startup must reject it instead.
    """
    from app.core.config import ConfigError as CE, Settings as S

    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HUB_LIBREDESK_API_SECRET", "rt7jDq\u202627AVA")
    with pytest.raises(CE, match="must be ASCII"):
        S()


def test_ascii_libredesk_credentials_are_accepted(monkeypatch):
    from app.core.config import Settings as S

    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HUB_LIBREDESK_API_KEY", "a" * 32)
    monkeypatch.setenv("HUB_LIBREDESK_API_SECRET", "b" * 64)
    st = S()
    assert st.libredesk_api_secret == "b" * 64


# --- Validadores de configuracion JEV ---------------------------------------

BASE_ENV = {
    "HUB_API_KEY": "test-api-key-0000000000000000",
    "HUB_ALLOWED_IPS": "127.0.0.1",
    "CLASSIFIER_API_KEY": "test-classifier-key-0000000000",
}


def _settings(monkeypatch, **extra):
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_defaults_are_the_approved_thresholds(monkeypatch):
    """El fixture autouse fija CLASSIFIER_* de prueba, asi que aqui se limpian.

    Sin borrarlas, lo que se verificaria serian los valores del fixture y no los
    defaults reales con los que el contenedor arranca si nadie los define.
    """
    for name in ("CLASSIFIER_MODEL", "CLASSIFIER_URL", "HUB_RULES_DIR"):
        monkeypatch.delenv(name, raising=False)
    s = _settings(monkeypatch)
    assert s.jev_min_confidence == 0.5
    assert s.jev_min_probability == 0.45
    assert s.jev_max_corrections == 3
    assert s.jev_concurrency == 4
    assert s.classifier_model == "typesafe/jev-1.14"
    assert s.classifier_url.endswith("/api/alpha/decisions")
    assert s.jev_thresholds == (0.5, 0.45)


def test_missing_classifier_key_aborts(monkeypatch):
    for bad in ("", "corta"):
        with pytest.raises(ConfigError, match="CLASSIFIER_API_KEY"):
            _settings(monkeypatch, CLASSIFIER_API_KEY=bad)


def test_http_classifier_url_aborts(monkeypatch):
    with pytest.raises(ConfigError, match="https"):
        _settings(monkeypatch, CLASSIFIER_URL="http://openrouter.ai/api/alpha/decisions")


def test_classifier_model_without_vendor_aborts(monkeypatch):
    with pytest.raises(ConfigError, match="OpenRouter slug"):
        _settings(monkeypatch, CLASSIFIER_MODEL="jev-1.14")


@pytest.mark.parametrize("bad", ["0", "1.5", "-0.2"])
def test_out_of_range_threshold_aborts(monkeypatch, bad):
    with pytest.raises(ConfigError, match=r"\(0, 1\]"):
        _settings(monkeypatch, JEV_MIN_CONFIDENCE=bad)


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_zero_limit_aborts(monkeypatch, bad):
    with pytest.raises(ConfigError, match=">= 1"):
        _settings(monkeypatch, JEV_MAX_CORRECTIONS=bad)
