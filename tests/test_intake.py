"""Pruebas del contrato de entrada: filtro D3, guardas G1/G2/G3 y clave de dedupe.

Ninguna hace red ni base de datos: se ejecutan contra dict que replican el payload
real de `message.created` verificado en el fuente de LibreDesk (get-message proyecta
author.type; postReply() inyecta meta.ai_assistant_id).
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.core.rules import load_rules
from app.jev.intake import (
    ECHO_PREFIX,
    build_dedupe_key,
    evaluate_message_created,
    normalize_channel,
    resolve_channel,
)

from tests.conftest import FIXTURE_ASSISTANT_ID


def ai_message_body(**overrides) -> dict:
    """Payload real de message.created para un mensaje de Agente IA.

    Forma verificada en internal/conversation/models/models.go (Message) y en la
    documentacion de webhooks de LibreDesk.
    """
    payload = {
        "id": 987,
        "uuid": "123e4567-e89b-12d3-a456-426614174000",
        "type": "outgoing",
        "status": "pending",
        "conversation_uuid": "550e8400-e29b-41d4-a716-446655440000",
        "content": "<p>Hola! Como puedo ayudarte?</p>",
        "text_content": "Hola! Como puedo ayudarte?",
        "content_type": "html",
        "private": False,
        "sender_id": 9011,
        "sender_type": "agent",
        "meta": {"ai_assistant_id": FIXTURE_ASSISTANT_ID},
        "attachments": [],
        "author": {"id": 9011, "first_name": "Test Agent", "type": "ai_assistant"},
    }
    payload.update(overrides)
    return {"event": "message.created", "timestamp": "2026-11-11T20:00:00Z", "payload": payload}


# --- Camino feliz -----------------------------------------------------------

def test_ai_outgoing_public_message_is_accepted(rules):
    r = evaluate_message_created(ai_message_body(), rules=rules)
    assert r.accept is True
    assert r.reason == "accepted"
    assert r.assistant_id == FIXTURE_ASSISTANT_ID
    assert r.message_uuid == "123e4567-e89b-12d3-a456-426614174000"
    assert r.conversation_uuid == "550e8400-e29b-41d4-a716-446655440000"
    assert r.dedupe_key.endswith("123e4567-e89b-12d3-a456-426614174000")


# --- Filtro D3: cada condicion por separado --------------------------------

@pytest.mark.parametrize("override,expected", [
    ({"type": "incoming"}, "not_outgoing"),
    ({"type": "activity"}, "not_outgoing"),
    ({"private": True}, "private_or_missing"),
    ({"meta": {}}, "no_ai_assistant_id"),
    ({"meta": {"ai_assistant_id": 0}}, "no_ai_assistant_id"),
    ({"meta": {"ai_assistant_id": -3}}, "no_ai_assistant_id"),
    ({"meta": {"ai_assistant_id": None}}, "no_ai_assistant_id"),
    ({"meta": {"ai_assistant_id": True}}, "no_ai_assistant_id"),
    ({"meta": None}, "no_ai_assistant_id"),
    ({"author": {"id": 9011, "type": "agent"}}, "author_not_ai_assistant"),
    ({"author": {}}, "author_not_ai_assistant"),
    ({"author": None}, "author_not_ai_assistant"),
])
def test_each_d3_condition_alone_rejects(rules, override, expected):
    body = ai_message_body(**override)
    r = evaluate_message_created(body, rules=rules)
    assert r.accept is False
    assert r.reason == expected, f"{override} dio {r.reason}"


def test_private_missing_is_rejected_not_assumed_public(rules):
    """Sin clave `private` no se asume publico: fail-closed."""
    body = ai_message_body()
    del body["payload"]["private"]
    r = evaluate_message_created(body, rules=rules)
    assert r.accept is False and r.reason == "private_or_missing"


def test_non_dict_payload_is_rejected(rules):
    r = evaluate_message_created({"event": "message.created", "payload": "hola"}, rules=rules)
    assert r.accept is False and r.reason == "payload_not_object"


# --- G3: allowlist fail-closed ----------------------------------------------

def test_agent_not_in_allowlist_is_ignored(rules):
    """ID valido pero no declarado => no se evalua nada (V3: asistentes borrados
    siguen apareciendo como autores de mensajes viejos)."""
    body = ai_message_body(meta={"ai_assistant_id": 999})
    r = evaluate_message_created(body, rules=rules)
    assert r.accept is False
    assert r.reason == "agent_not_allowlisted"


def test_declared_but_disabled_agent_is_ignored(make_rules):
    """Agente en la allowlist pero apagado => ignorar en silencio.

    Se escriben ambas reglas desde cero: no se copia rules/ del repo porque su
    contenido (ids, acciones, prefijos) cambia en vivo.
    """
    d = make_rules(agents_yaml=(
        "agents:\n  %d:\n    enabled: false\n" % FIXTURE_ASSISTANT_ID))
    disabled = load_rules(d)
    r = evaluate_message_created(ai_message_body(), rules=disabled)
    assert r.accept is False
    assert r.reason == "agent_disabled"


# --- G2: eco propio (defensa secundaria) ------------------------------------

def test_own_echo_is_rejected_even_with_ai_signals(rules):
    """Si algun dia echo_id llegara en el payload, se ignora igual."""
    body = ai_message_body(meta={"ai_assistant_id": FIXTURE_ASSISTANT_ID, "echo_id": f"{ECHO_PREFIX}abc"})
    r = evaluate_message_created(body, rules=rules)
    assert r.accept is False and r.reason == "own_output_echo"


def test_hub_own_message_is_rejected_by_d3_alone(rules):
    """Prueba del circulo cerrado SIN depender de echo_id.

    Un mensaje publicado por hub-api va firmado por un usuario 'agent': author.type
    nunca es 'ai_assistant' y no hay ai_assistant_id. D3 lo rechaza dos veces.
    """
    hub_message = {
        "event": "message.created",
        "payload": {
            "uuid": "aaaa-bbbb",
            "type": "outgoing",
            "private": False,
            "conversation_uuid": "c1",
            "meta": {"echo_id": "jev-retry:xyz"},
            "sender_type": "agent",
            "author": {"id": 2, "type": "agent"},
        },
    }
    r = evaluate_message_created(hub_message, rules=rules)
    assert r.accept is False


# --- Clave de dedupe --------------------------------------------------------

def test_dedupe_key_uses_message_uuid_not_timestamp(rules):
    """Dos entregas del mismo mensaje -> misma clave (idempotencia duradera)."""
    a = ai_message_body(timestamp="2026-11-11T20:00:00Z")
    b = ai_message_body(timestamp="2026-11-11T20:00:59Z")
    assert build_dedupe_key("message.created", a) == build_dedupe_key("message.created", b)


def test_different_messages_get_different_keys():
    a = ai_message_body(uuid="msg-1")
    b = ai_message_body(uuid="msg-2")
    assert build_dedupe_key("message.created", a) != build_dedupe_key("message.created", b)


def test_webhook_test_events_do_not_collide():
    """Send test manda solo {id,name}: sin UUID, se cae a hash del body.

    Dos pruebas distintas (nombre diferente) no pueden compartir clave, y por tanto
    la segunda no se descarta en silencio — el bug que tenia la clave anterior.
    """
    t1 = {"event": "webhook.test", "timestamp": "2026-11-11T20:00:00Z",
          "payload": {"id": 1, "name": "Dev -> business-api"}}
    t2 = copy.deepcopy(t1)
    t2["payload"]["name"] = "Otro webhook"
    k1, k2 = build_dedupe_key("webhook.test", t1), build_dedupe_key("webhook.test", t2)
    assert k1 != k2
    assert k1.startswith("webhook.test:body:")


def test_same_webhook_test_is_still_idempotent():
    """Reentrega del mismo test si produce la misma clave."""
    t = {"event": "webhook.test", "timestamp": "X", "payload": {"id": 1, "name": "W"}}
    assert build_dedupe_key("webhook.test", t) == build_dedupe_key("webhook.test", t)


# --- Canal ------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("livechat", "chat"), ("whatsapp", "chat"), ("email", "email"),
    ("LiveChat", "chat"), (" EMAIL ", "email"), ("unknown", "unknown"),
])
def test_channel_normalization(raw, expected):
    assert normalize_channel(raw) == expected


def test_message_created_has_no_channel_and_returns_none():
    """V13: el payload NO trae inbox_id ni inbox_channel. Resuelve None = preguntar."""
    body = ai_message_body()
    assert "inbox_channel" not in body["payload"]
    assert resolve_channel(body) is None


def test_channel_from_conversation_cache():
    body = ai_message_body()
    conv = body["payload"]["conversation_uuid"]
    assert resolve_channel(body, known={conv: "chat"}) == "chat"


def test_channel_read_directly_when_present():
    """conversation.created si lo trae (V14); se normaliza igual."""
    body = {"event": "conversation.created", "payload": {"inbox_channel": "whatsapp"}}
    assert resolve_channel(body) == "chat"
