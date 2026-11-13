"""Full-pipeline tests with simulated dependencies.

None touches the network: the classifier and the LibreDesk client are replaced by
doubles returning the exact shapes verified against the real APIs. What is tested
here is ORCHESTRATION: call order, when it aborts and what gets
publica.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.rules import load_rules
from app.core.state import STATE
from app.jev import composer
from app.jev.classifier import Decision
from app.jev.libredesk import AssistantConfig, LibreDeskClient, PublishResult
from app.jev.pipeline import EnforcementPipeline, build_history, pick_customer_message

from tests.conftest import FIXTURE_ASSISTANT_ID as AID, FIXTURE_CHOICE


@pytest.fixture(autouse=True)
def _clean_state():
    STATE._seen.clear()
    STATE._channels.clear()
    STATE._corrections.clear()
    yield
    STATE._seen.clear()
    STATE._channels.clear()
    STATE._corrections.clear()


class FakeClassifier:
    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self.calls: list[dict] = []

    async def classify(self, state, instructions, criteria, *, min_confidence,
                       min_probability):
        self.calls.append({"state": state, "criteria": dict(criteria),
                           "min_confidence": min_confidence,
                           "min_probability": min_probability})
        return self._decision


class FakeLibreDesk:
    def __init__(self, *, assistant=None, messages=None, completion="<p>respuesta corregida</p>",
                 publish_error: str | None = None,
                 snippets: list[dict] | None = None) -> None:
        self._assistant = assistant if assistant is not None else AssistantConfig(
            assistant_id=AID, name="Fixture Agent", instructions="Habla de tu.",
            guardrails="No prometas plazos.", enabled=True, max_turns=6, user_id=9011,
        )
        self._messages = messages or [
            {"uuid": "m1", "sender_type": "contact", "private": False,
             "text_content": "Tengo un bug en produccion"},
            {"uuid": "m2", "sender_type": "agent", "private": False,
             "text_content": "Respuesta original del agente",
             "meta": {"ai_assistant_id": AID}},
        ]
        self._completion = completion
        self._publish_error = publish_error
        # Synthetic snippet rows only: real content lives in the database and
        # changes without restarting hub-api, so tests never wire it (conftest
        # rule: contract over shape, never over business content).
        self._snippets = snippets if snippets is not None else []
        self.snippet_reads = 0
        self.published: list[dict] = []
        self.team_calls: list[tuple[str, int]] = []
        self.assign_calls: list[tuple[str, int]] = []
        self.completion_calls: list[tuple[str, str]] = []
        self.copilot_calls: list[dict] = []

    async def get_assistant(self, assistant_id):
        return self._assistant
        return self._assistant

    async def get_snippets(self):
        from app.jev.libredesk import SnippetRow
        self.snippet_reads += 1
        return [SnippetRow(**row) for row in self._snippets]

    async def get_conversation_messages(self, conversation_uuid, page_size=10):
        return list(self._messages)
    async def copilot(self, *, conversation_uuid, message, assistant_id):
        self.copilot_calls.append({"conversation_uuid": conversation_uuid,
                                   "message": message, "assistant_id": assistant_id})
        return self._completion

    async def complete(self, prompt_key, content):
        self.completion_calls.append((prompt_key, content))
        return self._completion

    async def first_prompt_key(self):
        # Mirrors the D8/G9 fallback: only reached when the settings key is empty.
        self.prompt_fallback_reads = getattr(self, "prompt_fallback_reads", 0) + 1
        return "fallback-prompt-key" if getattr(self, "_fallback_key", True) else None

    async def assign_team(self, conversation_uuid, team_id):
        self.team_calls.append((conversation_uuid, team_id))
        return True

    async def publish_correction(self, **kwargs):
        if self._publish_error:
            return PublishResult(False, self._publish_error)
        self.published.append(kwargs)
        return PublishResult(True, "accepted", message_uuid="new-1", status="pending")


def make_pipeline(rules, *, decision=None, libredesk, classifier=None,
                  settings=None, use_copilot=False) -> EnforcementPipeline:
    s = settings or Settings()
    if use_copilot:
        # model_copy skips revalidation: it only swaps the engine under test.
        s = s.model_copy(update={"jev_use_copilot": True})
    clf = classifier or FakeClassifier(decision)
    return EnforcementPipeline(
        rules=rules, settings=s, classifier=clf, libredesk=libredesk,
    )


def item(**over):
    base = {
        "conversation_uuid": "conv-1",
        "message_uuid": "m2",
        "assistant_id": AID,
        "channel": "chat",
        "payload": {
            "uuid": "m2", "type": "outgoing", "private": False,
            "conversation_uuid": "conv-1", "text_content": "Respuesta original del agente",
            "meta": {"ai_assistant_id": 1, "to": ["cliente@example.com"]},
            "author": {"id": 9011, "type": "ai_assistant"},
        },
    }
    base.update(over)
    return base


ACT = Decision(True, "accepted", choice=FIXTURE_CHOICE, confidence=0.93,
               probability=0.95, cost_usd=2.7e-05)
SKIP_NONE = Decision(False, "jev_said_none", choice="none", confidence=0.68,
                     probability=0.76)


# --- Historial --------------------------------------------------------------

def test_build_history_excludes_private_and_self():
    msgs = [
        {"uuid": "a", "sender_type": "contact", "private": False, "text_content": "hola"},
        {"uuid": "priv", "sender_type": "agent", "private": True, "text_content": "nota interna"},
        {"uuid": "b", "sender_type": "agent", "private": False, "text_content": "adios"},
    ]
    hist = build_history(msgs, exclude_uuid="b")
    assert hist == [("contact", "hola")]


def test_pick_customer_message_returns_last_contact():
    hist = [("contact", "primero"), ("agent", "r"), ("contact", "ultimo")]
    assert pick_customer_message(hist) == "ultimo"


# --- Camino feliz -----------------------------------------------------------

async def test_full_cycle_publishes_with_prefix_and_echo(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, use_copilot=False, decision=ACT, libredesk=ld)
    out = await pipe.run(item())

    assert out["outcome"] == "corrected"
    assert len(ld.published) == 1
    sent = ld.published[0]
    assert sent["echo_id"] == "jev-retry:m2"
    assert sent["conversation_uuid"] == "conv-1"
    # D7 prefix applied as its own paragraph.
    # The prefix comes from agents.yaml (fixture). Derived, never copied: if the
    # that text changes live, the test still measures "a prefix was prepended".
    import html as _html
    expected_prefix = "<p>%s</p>" % _html.escape(rules.agent(AID).prefix_for("chat").strip())
    assert sent["html_body"].startswith(expected_prefix)
    # Recipient reused from the agent message (email requires `to`).
    assert sent["to"] == ["cliente@example.com"]
    # The live assistant persona was requested.
    assert ld.completion_calls, "nothing was generated"


async def test_prompt_includes_action_person_and_material(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, use_copilot=False, decision=ACT, libredesk=ld)
    await pipe.run(item())
    prompt_key, content = ld.completion_calls[0]

    assert prompt_key  # viene de config, no hardcodeado
    # The ACTION block sent to the LLM must be the DESCRIPTION declared in the
    # fixture YAML. It is derived from the Rules object; if content changes live,
    # the test still measures the same thing without breaking.
    action_block = rules.action_text(FIXTURE_CHOICE)
    assert action_block, "the fixture action must exist"
    assert action_block.lower() in content.lower(), "the injected action block must come from the fixture YAML"
    assert "Habla de tu." in content          # instructions del asistente (V12)
    assert "No prometas plazos." in content   # guardrails
    assert "Tengo un bug en produccion" in content  # mensaje del cliente
    assert "Respuesta original del agente" in content


async def test_jev_receives_all_yaml_options_as_criteria(rules):
    """Every YAML option reaches JEV once the handoff evidence is present.

    Without handed_off the conditional option is withheld on purpose (see
    test_handoff_option_only_offered_after_a_real_handoff), so this case asserts
    the full mapping with the flag set.
    """
    ld = FakeLibreDesk()
    clf = FakeClassifier(ACT)
    pipe = EnforcementPipeline(rules=rules, settings=Settings(),
                               classifier=clf, libredesk=ld)
    await pipe.run(item(handed_off=True))
    assert set(clf.calls[0]["criteria"]) == set(rules.options)
    assert "none" in clf.calls[0]["criteria"]


# --- Abortos sin publicar ---------------------------------------------------

async def test_none_decision_never_generates_or_publishes(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=SKIP_NONE, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "skipped" and out["reason"] == "jev_said_none"
    assert ld.completion_calls == []
    assert ld.published == []


async def test_unreadable_assistant_is_fail_closed(rules):
    """Deleted assistant: GET 404 -> None -> nothing is touched (G3/V3)."""
    ld = FakeLibreDesk(assistant=None)
    ld.get_assistant = _returns_none
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "ignored" and out["reason"] == "assistant_unreadable"
    assert ld.published == []


async def _returns_none(assistant_id):  # noqa: ANN001 - doble minimo
    return None


async def test_disabled_assistant_stops_the_pipeline(rules):
    ld = FakeLibreDesk(assistant=AssistantConfig(
        assistant_id=AID, name="X", instructions="", guardrails="", enabled=False))
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "ignored" and out["reason"] == "assistant_disabled_now"


async def test_empty_generation_does_not_publish(rules):
    ld = FakeLibreDesk(completion="")
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "failed" and out["reason"] == "generation_empty"
    assert ld.published == []


async def test_missing_channel_blocks_publication(rules):
    """Without a prefix for the channel nothing publishes: the label is mandatory."""
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel="telegram"))
    assert out["outcome"] == "ignored"
    assert out["reason"].startswith("no_prefix_for_channel")
    assert ld.published == []


async def test_unknown_choice_in_yaml_is_fail_closed(rules):
    weird = Decision(True, "accepted", choice="undeclared-action-key", confidence=0.9,
                     probability=0.9)
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=weird, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "ignored" and "action_missing" in out["reason"]
    assert ld.published == []


async def test_publish_failure_reports_failed_not_corrected(rules):
    ld = FakeLibreDesk(publish_error="http_400")
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item())
    assert out["outcome"] == "failed"


# --- Per-conversation cap ---------------------------------------------------

async def test_correction_limit_stops_after_max(rules):
    s = Settings(JEV_MAX_CORRECTIONS="2")
    for i in range(2):
        ld = FakeLibreDesk()
        pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=s)
        out = await pipe.run(item(message_uuid=f"m{i}",
                                  conversation_uuid="conv-limit"))
        assert out["outcome"] == "corrected", f"iteracion {i}"
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=s)
    out = await pipe.run(item(message_uuid="m9", conversation_uuid="conv-limit"))
    assert out["outcome"] == "skipped" and out["reason"] == "correction_limit_reached"
    assert ld.published == []


async def test_limit_applies_per_conversation(rules):
    s = Settings(JEV_MAX_CORRECTIONS="1")
    for conv in ("conv-a", "conv-b"):
        ld = FakeLibreDesk()
        pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=s)
        out = await pipe.run(item(conversation_uuid=conv))
        assert out["outcome"] == "corrected", conv


# --- Fallback by reading the conversation ------------------------------------

class ConversationAwareLibreDesk(FakeLibreDesk):
    """Double that does not know the channel until the conversation is read."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.conversation_reads = 0

    async def get_conversation(self, conversation_uuid):
        self.conversation_reads += 1
        return {"uuid": conversation_uuid, "inbox_channel": "email",
                "contact": {"email": "contacto@ejemplo.com"}}


async def test_channel_is_resolved_by_reading_the_conversation(rules):
    """After a restart there is no cache: the prefix comes from reading the conversation.

    Covers V13 (message.created carries no channel) without depending on having
    conversation.created correspondiente.
    """
    ld = ConversationAwareLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel=None))
    assert out["outcome"] == "corrected"
    assert ld.conversation_reads == 1
    # ConversationAwareLibreDesk reports inbox_channel="email": the applied prefix
    # must be the EMAIL one, proving the channel came from the READ, not the item.
    assert sent_prefix(ld) == expected_prefix_of(rules, "email")


async def test_read_channel_is_cached_for_next_messages(rules):
    ld = ConversationAwareLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item(channel=None, conversation_uuid="conv-cache"))
    assert STATE.channel_for("conv-cache") == "email"
    # The second time it does not read again: the cache is already populated. Force
    # the item so the only possible source is STATE.
    ld2 = ConversationAwareLibreDesk()
    pipe2 = make_pipeline(rules, decision=ACT, libredesk=ld2)
    out2 = await pipe2.run(item(conversation_uuid="conv-cache", channel=None))
    assert out2["outcome"] == "corrected"
    assert ld2.conversation_reads == 0, "should have used the cache, not re-read the conversation"
    assert sent_prefix(ld2) == expected_prefix_of(rules, "email")


async def test_recipients_fall_back_to_contact_email(rules):
    """In email an empty `to` returns 500 (measured). Without meta.to the contact wins."""
    payload_no_to = {
        "uuid": "m2", "type": "outgoing", "private": False, "conversation_uuid": "conv-1",
        "text_content": "Respuesta original del agente",
        "meta": {"ai_assistant_id": AID},
        "author": {"id": 9011, "type": "ai_assistant"},
    }
    ld = ConversationAwareLibreDesk(messages=[
        {"uuid": "c1", "sender_type": "contact", "private": False,
         "text_content": "necesito ayuda"},
    ])
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item(payload=payload_no_to, channel=None))
    assert ld.published[0]["to"] == ["contacto@ejemplo.com"]


def expected_prefix_of(rules, channel: str) -> str:
    """Como with_prefix(): parrafo propio, texto plano escapado y sin bordes."""
    import html as _html
    return "<p>%s</p>" % _html.escape(rules.agent(AID).prefix_for(channel).strip())


def sent_prefix(ld) -> str:
    body = ld.published[0]["html_body"]
    return body.split("</p>")[0] + "</p>"


# --- the state JEV receives ---------------------------------------------------

def test_state_does_not_duplicate_the_agent_reply_under_review():
    """The history already ends with the agent reply: it is not repeated.

    Measured live (2026-11-12): an empty `Asistente:` line at the end made JEV
    would read the newest turn as missing and answer `none`.
    """
    history = [("contact", "mi sistema esta caido"), ("agent", "agende una sesion")]
    st = composer.build_state_for_jev(
        customer_message="mi sistema esta caido",
        agent_message="agende una sesion", history=history)
    assert st.count("agende una sesion") == 1
    assert not st.rstrip().endswith("Asistente:")


def test_state_keeps_customer_line_only_when_it_adds_information():
    history = [("contact", "urgente: caido hace 2 horas"), ("agent", "le agendo sesion")]
    st = composer.build_state_for_jev(
        customer_message="urgente: caido hace 2 horas",
        agent_message="le agendo sesion", history=history)
    lines = [l for l in st.split("\n") if l.strip()]
    assert lines[-1].startswith("Asistente:"), "el ultimo turno debe ser la respuesta evaluada"


def test_state_repeats_nothing_the_history_already_carries():
    """The pipeline passes history AND extracted turns; lines must not duplicate."""
    h = [("contact", "urgente: caido hace 2 horas"), ("agent", "le agendo sesion")]
    st = composer.build_state_for_jev(
        customer_message="urgente: caido hace 2 horas",
        agent_message="le agendo sesion", history=h)
    assert st.split("\n").count("Cliente: urgente: caido hace 2 horas") == 1
    assert st.endswith("Asistente: le agendo sesion")


def test_state_includes_agent_reply_when_history_is_empty():
    """With no history (or a trimmed one) the reply under review MUST appear."""
    st = composer.build_state_for_jev(customer_message="caido", agent_message="agende",
                                      history=[])
    assert "Cliente: caido" in st
    assert "Asistente: agende" in st


async def test_history_reaches_the_jev_state(rules):
    """Pagination regression: without history, JEV evaluates blind.

    The double simulates the real paginated shape; if the parser reads `data` as a
    list again, the state keeps a single line and this fails.
    """
    ld = FakeLibreDesk(messages=[
        {"uuid": "c1", "sender_type": "contact", "private": False,
         "text_content": "URGENTE: nuestro sistema esta caido"},
        {"uuid": "m2", "sender_type": "agent", "private": False,
         "text_content": "Respuesta original del agente",
         "meta": {"ai_assistant_id": AID}},
    ])
    seen = {}

    class SpyClassifier:
        async def classify(self, state, instructions, criteria, **kw):
            seen["state"] = state
            return Decision(True, "accepted", choice=FIXTURE_CHOICE, confidence=0.9,
                            probability=0.9)

    pipe = make_pipeline(rules, libredesk=ld, classifier=SpyClassifier())
    await pipe.run(item(channel="chat"))
    assert "URGENTE: nuestro sistema esta caido" in seen["state"], \
        "the customer message must reach JEV, not just the agent reply"


async def test_raw_channel_from_conversation_read_is_normalized(rules):
    """Measured regression (2026-11-12): inbox_channel="whatsapp" has no prefix.

    agents.yaml declares `chat`/`email`. If the read fallback stores the raw value,
    prefix_for("whatsapp") is None and the correction is discarded AFTER spending
    JEV and generation.
    """
    ld = ConversationAwareLibreDesk()  # reporta inbox_channel="email" crudo
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel=None, conversation_uuid="conv-normalize"))
    assert out["outcome"] == "corrected", out.get("reason")
    assert STATE.channel_for("conv-normalize") == "email"


async def test_completion_logs_exact_payload_when_enabled(caplog):
    """With COMPLETION_LOG_REQUEST the log shows the literal body sent to LibreDesk."""
    import json
    import logging as lg

    import httpx

    sent = {}

    async def capture(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "success",
                                         "data": "<p>texto</p>"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as h:
        ld = LibreDeskClient(h, base_url="http://ld.test", api_key="k" * 32,
                             api_secret="s" * 64, log_request=True)
        with caplog.at_level(lg.INFO, logger="hub-api.libredesk"):
            await ld.complete("add_empathy", "PROMPT DE PRUEBA")

    logged = [r.getMessage() for r in caplog.records if "completion request payload" in r.getMessage()]
    assert len(logged) == 1
    payload = json.loads(logged[0].split("completion request payload ", 1)[1])
    assert payload == sent["body"], "the logged payload must be what was actually sent"
    assert payload["prompt_key"] == "add_empathy"


async def test_completion_stays_silent_by_default(caplog):
    import logging as lg

    import httpx

    async def capture(request):
        return httpx.Response(200, json={"status": "success", "data": "<p>x</p>"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as h:
        ld = LibreDeskClient(h, base_url="http://ld.test", api_key="k" * 32,
                             api_secret="s" * 64)
        with caplog.at_level(lg.INFO, logger="hub-api.libredesk"):
            await ld.complete("add_empathy", "datos del cliente aqui")

    assert not [r for r in caplog.records if "request payload" in r.getMessage()]
    assert "datos del cliente aqui" not in caplog.text


async def test_livechat_conversation_created_still_gets_prefixed_and_published(rules):
    """Regresion medida (conv 0cfc8689, 2026-11-12): JEV actuo, Nemotron genero,
    and the correction was discarded with no_prefix_for_channel:livechat.

    El handler de conversation.created debia normalizar antes de cachear; ahora
    STATE holds "chat" and the pipeline finds a prefix.
    """
    from app.core.state import STATE as ST
    from app.jev.intake import normalize_channel

    conv = "conv-livechat-regression"
    # Mimics the handler: it receives the raw inbox_channel from the webhook.
    ST.remember_channel(conv, normalize_channel("livechat"))
    assert ST.channel_for(conv) == "chat"

    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(conversation_uuid=conv))
    assert out["outcome"] == "corrected", out.get("reason")
    assert expected_prefix_of(rules, "chat") in ld.published[0]["html_body"]


async def test_completion_engine_is_the_default_and_gets_full_context(rules):
    """D3/G8: JEV_USE_COPILOT=false (default) -> /ai/completion with the composed prompt."""
    ld = FakeLibreDesk()
    seen_state = {}

    class StateSpy:
        async def classify(self, state, instructions, criteria, **kw):
            seen_state["state"] = state
            seen_state["criteria"] = criteria
            return ACT

    pipe = make_pipeline(rules, libredesk=ld, classifier=StateSpy())
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert len(ld.completion_calls) == 1
    assert not ld.copilot_calls, "the copilot engine must not run by default"
    # The assistant policy reaches JEV inside state, unclipped.
    st = seen_state["state"]
    assert "POLITICA DEL ASISTENTE" in st
    assert "Habla de tu." in st           # double's instructions
    assert "No prometas plazos." in st    # guardrails


async def test_copilot_engine_when_flag_on(rules, monkeypatch):
    """Escape hatch kept reachable: JEV_USE_COPILOT=true routes to /ai/copilot."""
    monkeypatch.setenv("JEV_USE_COPILOT", "true")
    from app.core.config import get_settings
    get_settings.cache_clear()
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld,
                         settings=get_settings(), use_copilot=True)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert ld.copilot_calls and not ld.completion_calls
    call = ld.copilot_calls[0]
    assert call["conversation_uuid"] == "conv-1"
    assert "Correct the assistant's reply" in call["message"]
    get_settings.cache_clear()


async def test_revive_post_action_reassigns_after_publishing(rules):
    """A post_action option revives the bot ONLY after a successful publish."""
    ld = FakeLibreDesk()
    revive = Decision(True, "accepted", choice="handoff-too-early", confidence=0.9,
                      probability=0.9)
    pipe = make_pipeline(rules, decision=revive, libredesk=ld)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    # The reassigned id comes from agents.yaml (revive_team_id), not the
    # assistant_id (42) nor the double's user_id.
    from tests.conftest import FIXTURE_REVIVE_TEAM_ID
    assert ld.team_calls == [("conv-1", FIXTURE_REVIVE_TEAM_ID)]
    assert out["revive_team_id"] == FIXTURE_REVIVE_TEAM_ID
    assert out["revived_assistant"] is True


async def test_no_revive_when_publish_fails(rules):
    ld = FakeLibreDesk(publish_error="channel down")
    revive = Decision(True, "accepted", choice="handoff-too-early", confidence=0.9,
                      probability=0.9)
    pipe = make_pipeline(rules, decision=revive, libredesk=ld)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "failed"
    assert ld.team_calls == [], "no se reasigna si no se publico nada"


async def test_plain_actions_never_reassign(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item(channel="chat"))
    assert ld.team_calls == []


# --- Handoff evidence gates the option ---------------------------------------

async def test_handoff_option_only_offered_after_a_real_handoff(rules):
    """Without evidence of abandonment, criteria MUST NOT include the option.

    Reason measured live: always presenting "hand off too early" made JEV prefer
    deriving over rewriting, so a correction that should have revived the bot ran
    its post_action against a conversation nobody had abandoned.
    """
    seen = {}

    class Spy:
        async def classify(self, state, instructions, criteria, **kw):
            seen["criteria"] = dict(criteria)
            return ACT

    pipe = make_pipeline(rules, libredesk=FakeLibreDesk(), classifier=Spy())
    await pipe.run(item(channel="chat"))
    assert "handoff-too-early" not in seen["criteria"]


async def test_handoff_option_offered_when_conversation_was_abandoned(rules):
    from app.core.state import STATE as ST

    ST.remember_handoff("conv-aband")
    seen = {}

    class Spy:
        async def classify(self, state, instructions, criteria, **kw):
            seen["criteria"] = dict(criteria)
            return Decision(True, "accepted", choice="handoff-too-early",
                            confidence=0.9, probability=0.9)

    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, libredesk=ld, classifier=Spy())
    out = await pipe.run(item(conversation_uuid="conv-aband", channel="chat",
                              handed_off=True))
    assert "handoff-too-early" in seen["criteria"]
    assert out["outcome"] == "corrected"
    # A successful revive clears the flag: the next reply is judged without it.
    assert ST.had_handoff("conv-aband") is False


# --- CLASSIFIER_LOG_REQUEST --------------------------------------------------

async def test_classifier_logs_exact_payload_when_enabled(rules, caplog):
    """With the flag on, the log shows the exact body that would be sent."""
    import json
    import logging as lg

    from app.jev.classifier import Classifier
    import httpx

    sent = {}

    async def capture(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": {"action": {
            "choice": "none", "confidence": 0.9, "probabilities": {"none": 0.9}}}})

    transport = httpx.MockTransport(capture)
    async with httpx.AsyncClient(transport=transport) as h:
        clf = Classifier(h, url="https://jev.test/decisions", api_key="k" * 24,
                         model="typesafe/jev-test", log_request=True)
        with caplog.at_level(lg.INFO, logger="hub-api.jev.classifier"):
            await clf.classify("Cliente: caido\nAsistente: agende", "pregunta?",
                               {"none": "no intervenir"}, min_confidence=0.5,
                               min_probability=0.45)

    logged = [r.getMessage() for r in caplog.records if "jev request payload" in r.getMessage()]
    assert len(logged) == 1
    payload = json.loads(logged[0].split("jev request payload ", 1)[1])
    assert payload == sent["body"], "the logged payload must be what was actually sent"
    assert payload["state"] == "Cliente: caido\nAsistente: agende"


async def test_classifier_stays_silent_by_default(caplog):
    """Off by default: `state` carries customer data and must not reach logs."""
    import logging as lg

    from app.jev.classifier import Classifier
    import httpx

    async def capture(request):
        return httpx.Response(200, json={"answers": {"action": {
            "choice": "none", "confidence": 0.9, "probabilities": {"none": 0.9}}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as h:
        clf = Classifier(h, url="https://jev.test/decisions", api_key="k" * 24,
                         model="typesafe/jev-test")
        with caplog.at_level(lg.INFO, logger="hub-api.jev.classifier"):
            await clf.classify("datos del cliente aqui", "pregunta?",
                               {"none": "no intervenir"}, min_confidence=0.5,
                               min_probability=0.45)

    assert not [r for r in caplog.records if "request payload" in r.getMessage()]
    assert "datos del cliente aqui" not in caplog.text


# --- Neutralizacion de plantillas ------------------------------------------

async def test_double_braces_are_neutralized_before_publishing(rules):
    ld = FakeLibreDesk(completion="<p>Hola {{.Nombre}} y {{ call .X }}</p>")
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item())
    body = ld.published[0]["html_body"]
    assert "{{" not in body and "}}" not in body
    assert "Nombre" in body  # el texto se conserva, solo se rompe el par


async def test_dangerous_html_is_stripped_before_publishing(rules):
    ld = FakeLibreDesk(completion='<p>ok</p><script>alert(1)</script>')
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item())
    body = ld.published[0]["html_body"]
    assert "<script" not in body and "alert(1)" in body


# --- Snippets through the pipeline (T3.4/T4.3, synthetic rows only) ------------

SNIP_A = {"id": 101, "title": "Snippet Alfa", "content": "contenido alfa de prueba",
          "enabled": True, "updated_at": "2026-11-09T00:00:00Z"}
SNIP_B = {"id": 102, "title": "Snippet Beta", "content": "contenido beta de prueba",
          "enabled": True, "updated_at": "2026-11-10T00:00:00Z"}
SNIP_OFF = {"id": 103, "title": "Snippet Gamma", "content": "gamma deshabilitado",
            "enabled": False, "updated_at": "2026-11-08T00:00:00Z"}


async def test_declared_snippets_reach_jev_state_and_the_corrector(rules):
    """The fixture option declares [102, 101]: declared order must survive to
    both prompts, and the disabled snippet must never appear (G4 filtering)."""
    ld = FakeLibreDesk(snippets=[SNIP_A, SNIP_B, SNIP_OFF])
    seen = {}

    class Spy:
        async def classify(self, state, instructions, criteria, **kw):
            seen["state"] = state
            return Decision(True, "accepted", choice="handoff-too-early",
                            confidence=0.9, probability=0.9)

    pipe = make_pipeline(rules, libredesk=ld, classifier=Spy())
    out = await pipe.run(item(channel="chat", handed_off=True))
    assert out["outcome"] == "corrected"

    block = "SNIPPETS OBLIGATORIOS DE CUMPLIMIENTO"
    assert block in seen["state"], "declared snippets must reach the judge"
    pos_a, pos_b = (seen["state"].find("Snippet Alfa"), seen["state"].find("Snippet Beta"))
    assert 0 < pos_b < pos_a, "declared order [102, 101] preserved, not server order"
    assert "Gamma" not in seen["state"], "disabled snippets are filtered (G4)"

    _, prompt = ld.completion_calls[0]
    assert "Snippets obligatorios de cumplimiento" in prompt
    assert "contenido beta de prueba" in prompt and "contenido alfa de prueba" in prompt
    assert "Gamma" not in prompt


async def test_options_without_snippets_change_nothing(rules):
    """FIXTURE_CHOICE declares no snippets: neither prompt grows a block."""
    ld = FakeLibreDesk(snippets=[SNIP_A])
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    _, prompt = ld.completion_calls[0]
    assert "Snippets obligatorios" not in prompt
    # The judge sees the union over all options; this choice's own set is empty.
    assert ld.snippet_reads >= 1


async def test_snippet_source_failure_never_blocks_the_correction(rules):
    """G4 end-to-end: a raising source logs and the pipeline behaves as if no
    snippets existed -- classification and publication continue regardless."""
    ld = FakeLibreDesk()

    async def explode():
        raise RuntimeError("libredesk down")
    ld.get_snippets = explode

    pipe = make_pipeline(rules, decision=revive_decision(), libredesk=ld)
    out = await pipe.run(item(channel="chat", handed_off=True))
    assert out["outcome"] == "corrected", out.get("reason")
    _, prompt = ld.completion_calls[0]
    assert "Snippets obligatorios" not in prompt


def revive_decision():
    return Decision(True, "accepted", choice="handoff-too-early",
                    confidence=0.9, probability=0.9)


# --- D8/G9: completion prompt key resolution ------------------------------------

async def test_configured_prompt_key_never_triggers_the_fallback(rules, monkeypatch):
    monkeypatch.setenv("JEV_COMPLETION_PROMPT_KEY", "mi_prompt_jev")
    from app.core.config import get_settings
    get_settings.cache_clear()
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=get_settings())
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert ld.completion_calls[0][0] == "mi_prompt_jev"
    assert not hasattr(ld, "prompt_fallback_reads"), "fallback must not be consulted"
    get_settings.cache_clear()


async def test_empty_prompt_key_falls_back_to_first_ai_prompt(rules, monkeypatch):
    """Default is empty now (D8): generation uses the first ai_prompts row and
    still succeeds -- the omission lands in logs, it never blocks a correction."""
    monkeypatch.delenv("JEV_COMPLETION_PROMPT_KEY", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.jev_completion_prompt_key == "", "empty default is the contract"
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=s)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert ld.prompt_fallback_reads == 1
    assert ld.completion_calls[0][0] == "fallback-prompt-key"
    get_settings.cache_clear()


async def test_fallback_without_any_prompt_row_fails_closed(rules, monkeypatch):
    """No configured key AND no rows to borrow from: nothing generates, nothing
    publishes. Fail-closed like every other stage."""
    monkeypatch.delenv("JEV_COMPLETION_PROMPT_KEY", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    ld = FakeLibreDesk()
    ld._fallback_key = False
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld, settings=get_settings())
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "failed" and out["reason"] == "generation_empty"
    assert ld.published == [] and ld.completion_calls == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_first_prompt_key_contract_on_http_shapes():
    """Real client against captured shapes: flat list under data, taken as-is."""
    import httpx

    from app.jev.libredesk import LibreDeskClient

    routes = {
        "ok": (200, {"status": "success", "data": [
            {"id": 3, "key": "make_concise", "title": "Make concise"},
            {"id": 1, "key": "add_empathy", "title": "Add empathy"}]}),
        "empty": (200, {"status": "success", "data": []}),
        "error": (500, {"status": "error", "message": "boom"}),
    }

    async def run(name):
        code, body = routes[name]
        def handler(request):
            assert request.url.path == "/api/v1/ai/prompts"
            return httpx.Response(code, json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
            ld = LibreDeskClient(h, base_url="http://ld.test",
                                 api_key="k" * 32, api_secret="s" * 64)
            return await ld.first_prompt_key()

    # First row as it arrives (ORDER BY title server-side); no reordering here.
    assert await run("ok") == "make_concise"
    assert await run("empty") is None
    assert await run("error") is None
