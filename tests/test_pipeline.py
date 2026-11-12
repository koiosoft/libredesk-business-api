"""Pruebas del pipeline completo con dependencias simuladas.

Ninguna hace red: el clasificador y el cliente de LibreDesk se sustituyen por dobles
que devuelven las formas exactas verificadas contra las APIs reales. Lo que se
prueba aqui es la ORQUESTACION: en que orden se llama, cuando se aborta y que se
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
                 publish_error: str | None = None) -> None:
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
        self.published: list[dict] = []
        self.assign_calls: list[tuple[str, int]] = []
        self.completion_calls: list[tuple[str, str]] = []
        self.copilot_calls: list[dict] = []

    async def get_assistant(self, assistant_id):
        return self._assistant

    async def get_conversation_messages(self, conversation_uuid, page_size=10):
        return list(self._messages)

    async def copilot(self, *, conversation_uuid, message, assistant_id):
        self.copilot_calls.append({"conversation_uuid": conversation_uuid,
                                   "message": message, "assistant_id": assistant_id})
        return self._completion

    async def complete(self, prompt_key, content):
        self.completion_calls.append((prompt_key, content))
        return self._completion

    async def assign_assistant(self, conversation_uuid, user_id):
        self.assign_calls.append((conversation_uuid, user_id))
        return True

    async def publish_correction(self, **kwargs):
        if self._publish_error:
            return PublishResult(False, self._publish_error)
        self.published.append(kwargs)
        return PublishResult(True, "accepted", message_uuid="new-1", status="pending")


def make_pipeline(rules, *, decision=None, libredesk, classifier=None,
                  settings=None, use_copilot=True) -> EnforcementPipeline:
    s = settings or Settings()
    if not use_copilot:
        # model_copy no re-valida: cambia solo el motor bajo prueba.
        s = s.model_copy(update={"jev_use_copilot": False})
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
    # Prefijo D7 aplicado como parrafo propio.
    # El prefijo viene de agents.yaml (fixture). Se deriva, no se copia: si manana
    # ese texto cambia en vivo, la prueba sigue midiendo "se anteponio el prefijo".
    import html as _html
    expected_prefix = "<p>%s</p>" % _html.escape(rules.agent(AID).prefix_for("chat").strip())
    assert sent["html_body"].startswith(expected_prefix)
    # Destinatario reutilizado del mensaje del agente (email exige `to`).
    assert sent["to"] == ["cliente@example.com"]
    # Se pidio al asistente real su persona.
    assert ld.completion_calls, "nothing was generated"


async def test_prompt_includes_action_person_and_material(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, use_copilot=False, decision=ACT, libredesk=ld)
    await pipe.run(item())
    prompt_key, content = ld.completion_calls[0]

    assert prompt_key  # viene de config, no hardcodeado
    # El bloque ACCION que se envia al LLM debe ser la DESCRIPCION declarada en el
    # YAML de fixture. Se deriva del objeto Rules; si el contenido cambia en vivo,
    # la prueba sigue midiendo lo mismo sin romperse.
    action_block = rules.action_text(FIXTURE_CHOICE)
    assert action_block, "the fixture action must exist"
    assert action_block.lower() in content.lower(), "the injected action block must come from the fixture YAML"
    assert "Habla de tu." in content          # instructions del asistente (V12)
    assert "No prometas plazos." in content   # guardrails
    assert "Tengo un bug en produccion" in content  # mensaje del cliente
    assert "Respuesta original del agente" in content


async def test_jev_receives_all_yaml_options_as_criteria(rules):
    ld = FakeLibreDesk()
    clf = FakeClassifier(ACT)
    pipe = EnforcementPipeline(rules=rules, settings=Settings(),
                               classifier=clf, libredesk=ld)
    await pipe.run(item())
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
    """Asistente borrado: GET 404 -> None -> no se toca nada (G3/V3)."""
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
    """Sin prefijo para el canal no se publica: la etiqueta es obligatoria (D7)."""
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


# --- Tope por conversacion --------------------------------------------------

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


# --- Respaldo por lectura de la conversacion --------------------------------

class ConversationAwareLibreDesk(FakeLibreDesk):
    """Doble que simula no conocer el canal hasta que se lee la conversacion."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.conversation_reads = 0

    async def get_conversation(self, conversation_uuid):
        self.conversation_reads += 1
        return {"uuid": conversation_uuid, "inbox_channel": "email",
                "contact": {"email": "contacto@ejemplo.com"}}


async def test_channel_is_resolved_by_reading_the_conversation(rules):
    """Tras un reinicio no hay cache: el prefijo sale de leer la conversacion.

    Cubre V13 (message.created no trae canal) sin depender de haber visto el
    conversation.created correspondiente.
    """
    ld = ConversationAwareLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel=None))
    assert out["outcome"] == "corrected"
    assert ld.conversation_reads == 1
    # ConversationAwareLibreDesk reporta inbox_channel="email": el prefijo aplicado
    # debe ser el de EMAIL, lo que prueba que el canal vino de la LECTURA y no del item.
    assert sent_prefix(ld) == expected_prefix_of(rules, "email")


async def test_read_channel_is_cached_for_next_messages(rules):
    ld = ConversationAwareLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item(channel=None, conversation_uuid="conv-cache"))
    assert STATE.channel_for("conv-cache") == "email"
    # Segunda vez no vuelve a leer: usa la cache ya poblada. Se fuerza channel=None
    # en el item para que la unica fuente posible sea STATE.
    ld2 = ConversationAwareLibreDesk()
    pipe2 = make_pipeline(rules, decision=ACT, libredesk=ld2)
    out2 = await pipe2.run(item(conversation_uuid="conv-cache", channel=None))
    assert out2["outcome"] == "corrected"
    assert ld2.conversation_reads == 0, "should have used the cache, not re-read the conversation"
    assert sent_prefix(ld2) == expected_prefix_of(rules, "email")


async def test_recipients_fall_back_to_contact_email(rules):
    """En email, `to` vacio devuelve 500 (medido). Si meta.to no existe, se usa el contacto."""
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


# --- state que recibe JEV -----------------------------------------------------

def test_state_does_not_duplicate_the_agent_reply_under_review():
    """El historial ya termina en la respuesta del agente: no se repite.

    Medido en vivo (2026-11-12): un `Asistente:` vacio al final hacia que JEV
    leyera el turno mas reciente como ausente y respondiera `none`.
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
    """El pipeline pasa historial Y turnos extraidos; no se duplican lineas."""
    h = [("contact", "urgente: caido hace 2 horas"), ("agent", "le agendo sesion")]
    st = composer.build_state_for_jev(
        customer_message="urgente: caido hace 2 horas",
        agent_message="le agendo sesion", history=h)
    assert st.split("\n").count("Cliente: urgente: caido hace 2 horas") == 1
    assert st.endswith("Asistente: le agendo sesion")


def test_state_includes_agent_reply_when_history_is_empty():
    """Sin historial (o recortado), la respuesta evaluada SI debe aparecer."""
    st = composer.build_state_for_jev(customer_message="caido", agent_message="agende",
                                      history=[])
    assert "Cliente: caido" in st
    assert "Asistente: agende" in st


async def test_history_reaches_the_jev_state(rules):
    """Regresion del bug de paginacion: sin historial, JEV evalua a ciegas.

    El doble simula la forma paginada real; si el parser vuelve a leer `data` como
    lista, el state queda con una sola linea y esto falla.
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
    """Regresion medida (2026-11-12): inbox_channel="whatsapp" no tiene prefijo.

    agents.yaml declara `chat`/`email`. Si el respaldo por lectura guarda el valor
    bruto, prefix_for("whatsapp") es None y la correccion se descarta DESPUES de
    gastar JEV y generacion.
    """
    ld = ConversationAwareLibreDesk()  # reporta inbox_channel="email" crudo
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(channel=None, conversation_uuid="conv-normalize"))
    assert out["outcome"] == "corrected", out.get("reason")
    assert STATE.channel_for("conv-normalize") == "email"


async def test_completion_logs_exact_payload_when_enabled(caplog):
    """Con COMPLETION_LOG_REQUEST, el log muestra el body literal a LibreDesk."""
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
    y la correccion se descarto por no_prefix_for_channel:livechat.

    El handler de conversation.created debia normalizar antes de cachear; ahora
    STATE guarda "chat" y el pipeline encuentra prefijo.
    """
    from app.core.state import STATE as ST
    from app.jev.intake import normalize_channel

    conv = "conv-livechat-regression"
    # Simula al handler: recibe inbox_channel crudo del webhook.
    ST.remember_channel(conv, normalize_channel("livechat"))
    assert ST.channel_for(conv) == "chat"

    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    out = await pipe.run(item(conversation_uuid=conv))
    assert out["outcome"] == "corrected", out.get("reason")
    assert expected_prefix_of(rules, "chat") in ld.published[0]["html_body"]


async def test_copilot_engine_is_the_default_and_gets_correction_instruction(rules):
    """JEV_USE_COPILOT=true (default): la generacion va a /ai/copilot con contexto."""
    ld = FakeLibreDesk()
    clf = SpyClassifier() if False else None  # noqa: F841
    seen_state = {}

    class StateSpy:
        async def classify(self, state, instructions, criteria, **kw):
            seen_state["state"] = state
            seen_state["criteria"] = criteria
            return ACT

    pipe = make_pipeline(rules, libredesk=ld, classifier=StateSpy())
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert len(ld.copilot_calls) == 1
    assert not ld.completion_calls, "el motor legacy no debe invocarse"
    call = ld.copilot_calls[0]
    assert call["conversation_uuid"] == "conv-1"
    assert "Corrige la respuesta del asistente" in call["message"]
    # La politica del asistente ahora SI llega a JEV dentro del state.
    st = seen_state["state"]
    assert "POLITICA DEL ASISTENTE" in st
    assert "Habla de tu." in st           # instructions del doble
    assert "No prometas plazos." in st    # guardrails


async def test_legacy_completion_engine_when_flag_off(rules, monkeypatch):
    monkeypatch.setenv("JEV_USE_COPILOT", "false")
    from app.core.config import get_settings
    get_settings.cache_clear()
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld,
                         settings=get_settings(), use_copilot=False)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    assert ld.completion_calls and not ld.copilot_calls
    get_settings.cache_clear()


async def test_revive_post_action_reassigns_after_publishing(rules):
    """La accion con post_action revive al bot SOLO si la publicacion exito."""
    ld = FakeLibreDesk()
    revive = Decision(True, "accepted", choice="revive-action", confidence=0.9,
                      probability=0.9)
    pipe = make_pipeline(rules, decision=revive, libredesk=ld)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "corrected"
    # El ID asignado es el declarada en agents.yaml (assign_user_id), no el
    # assistant_id (42) ni el user_id del doble si difirieran.
    from tests.conftest import FIXTURE_ASSIGN_USER_ID
    assert ld.assign_calls == [("conv-1", FIXTURE_ASSIGN_USER_ID)]
    assert out["revived_assignee_id"] == FIXTURE_ASSIGN_USER_ID
    assert out["revived_assistant"] is True


async def test_no_revive_when_publish_fails(rules):
    ld = FakeLibreDesk(publish_error="channel down")
    revive = Decision(True, "accepted", choice="revive-action", confidence=0.9,
                      probability=0.9)
    pipe = make_pipeline(rules, decision=revive, libredesk=ld)
    out = await pipe.run(item(channel="chat"))
    assert out["outcome"] == "failed"
    assert ld.assign_calls == [], "no se reasigna si no se publico nada"


async def test_plain_actions_never_reassign(rules):
    ld = FakeLibreDesk()
    pipe = make_pipeline(rules, decision=ACT, libredesk=ld)
    await pipe.run(item(channel="chat"))
    assert ld.assign_calls == []


# --- CLASSIFIER_LOG_REQUEST --------------------------------------------------

async def test_classifier_logs_exact_payload_when_enabled(rules, caplog):
    """Con el flag prendido, el log muestra el body literal que se mandaria."""
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
    """Off por defecto: `state` lleva datos del cliente y no va a logs sin permiso."""
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
