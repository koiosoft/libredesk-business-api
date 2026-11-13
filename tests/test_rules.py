"""Rule loading contract (rules/*.yaml) and the JEV settings validators.

These tests are the automated equivalent of "it does not boot with broken rules":
each case reproduces one concrete way a YAML can end up incomplete and verifies
that startup aborts instead of degrading into publishing without evaluation.

Nothing here touches network, database or LibreDesk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import ConfigError, Settings
from app.core.rules import NONE_OPTION, RulesError, load_rules

REPO_RULES = Path(__file__).resolve().parent.parent / "rules"


# --- The format contract (fixtures, NEVER the real rules/) ------------------
#
# Rules are edited live. No contract test may depend on prompts.yaml keeping
# specific keys, prefixes or agent ids: that changes on purpose and would break
# CI with no bug involved. These cases write minimal YAML into tmp_path. The only
# exception is test_repo_rules_load(), which reads rules/ solely to verify
# parseability and shape invariants -- never content.

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
    """Writes a contract-valid rule directory.

    Defaults let a case mutate ONE thing while leaving the other untouched. No
    case copies the repo's rules/: those files change live on purpose.
    """
    d = tmp_path / "rules"
    d.mkdir(exist_ok=True)
    (d / "prompts.yaml").write_text(options_yaml, encoding="utf-8")
    (d / "agents.yaml").write_text(agents_yaml, encoding="utf-8")
    (d / "prompt-augmenter.md").write_text(augmenter_md, encoding="utf-8")
    return d


def test_repo_rules_load():
    """Versioned YAML must be valid: if someone breaks it, this fails.

    The only test that reads rules/. It verifies ONLY that loading succeeds and
    the contract invariants hold (`none` present, at least one action, hashes with
    the right shape). It asserts no content: that changes live on purpose.
    """
    rules = load_rules(REPO_RULES)
    assert rules.options, "prompts.yaml declared no action"
    assert NONE_OPTION in rules.options, "the 'none' option is missing"
    assert rules.agents, "agents.yaml declared no agent"
    assert len(rules.rules_hash) == 12 and len(rules.rules_version) == 8


def test_none_never_produces_an_action(tmp_path: Path):
    """`none` is a valid choice but never text to inject."""
    rules = load_rules(write_rules(tmp_path, MINIMAL_OPTIONS, MINIMAL_AGENTS))
    assert rules.action_text(NONE_OPTION) is None
    assert rules.action_text(None) is None
    assert rules.action_text("inexistente") is None
    for key in rules.options:
        if key != NONE_OPTION:
            assert rules.action_text(key)


def test_agent_ids_are_assistant_ids_not_user_ids(tmp_path: Path):
    """The allowlist is keyed by ai_assistants.id, not by the bot's user_id."""
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
    # An undeclared or unknown channel means nothing is published.
    assert agent.prefix_for("telegram") is None
    assert agent.prefix_for(None) is None


def test_extended_option_shape_exposes_post_action(tmp_path):
    """`{text, post_action}` is a valid shape; text still reaches JEV."""
    rules = load_rules(write_rules(tmp_path))   # the fixture carries one extended option
    key = "handoff-too-early"
    assert rules.action_text(key) == rules.options[key]
    assert rules.action_text(key) != MINIMAL_OPTIONS.split("options:")[0]  # sanity
    assert rules.post_action(key) == "revive-assistant"
    assert rules.post_action(FIXTURE_CHOICE) is None
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
    # The hash must change when a post_action changes (it is part of the contract).
    other = load_rules(write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n  ext: Reescribe Y.\n")))
    assert rules.rules_hash != other.rules_hash


def test_revive_team_id_is_parsed_and_validated(tmp_path):
    from tests.conftest import (FIXTURE_ASSISTANT_ID as AID,
                                FIXTURE_REVIVE_TEAM_ID as TEAM)

    rules = load_rules(write_rules(tmp_path))
    assert rules.agent(AID).revive_team_id == TEAM
    # Optional: an agent without the field stays valid; the revive is skipped.
    d = write_rules(tmp_path, agents_yaml=(
        "agents:\n  %d:\n    enabled: true\n    prefixes:\n      chat: Nota\n" % AID))
    assert load_rules(d).agent(AID).revive_team_id is None


def test_bad_revive_team_id_aborts(tmp_path):
    d = write_rules(tmp_path, agents_yaml=(
        "agents:\n  42:\n    enabled: true\n    revive_team_id: bot\n"
        "    prefixes:\n      chat: Nota\n"))
    with pytest.raises(RulesError, match="not an integer"):
        load_rules(d)


# --- Arranque abortado ante reglas incompletas ------------------------------

@pytest.fixture
def broken_rules(tmp_path: Path) -> Path:
    """Minimal VALID rules, ready to mutate one thing per case.

    It does not copy the repo rules/: that content changes live and contract tests
    contrato no pueden depender de cadenas especificas de prompts.yaml.
    """
    return write_rules(tmp_path)


def test_missing_none_option_aborts(broken_rules):
    """Without `none` publishing becomes the default: startup must be refused."""
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
    """A disabled agent is declared to document it, not to publish through it."""
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
    """The autouse fixture pins test CLASSIFIER_* values, so they are cleared here.

    Without clearing them, what would be verified are the fixture values and not the
    real defaults the container boots with when nobody defines them.
    """
    for name in ("CLASSIFIER_MODEL", "CLASSIFIER_URL", "PROMPT_AUGMENTER_RULE_PATH"):
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
