"""Guardas de entrada: decide si un evento debe entrar al pipeline, y por que no.

Separado del HTTP por dos razones: estas reglas son lo unico que impide publicar
basura en un canal de cliente, y necesitan probarse sin red ni base de datos.

Filtro D3 — las CUATRO condiciones, todas necesarias:

    payload.type == "outgoing"
    AND payload.private is False
    AND payload.meta.ai_assistant_id > 0
    AND payload.author.type == "ai_assistant"

Se exigen las dos senales de IA aunque parezcan redundantes, y son realmente
independientes: `meta.ai_assistant_id` la escribe postReply() en memoria
(internal/aiagent/worker.go:441) y `author.type` sale del JOIN a users en el
read-model (internal/conversation/queries.sql -> get-message). Que ambas coincidan
es una comprobacion de integridad barata antes de gastar JEV + LLM.

G2 (echo_id) es DEFENSA SECUNDARIA, no la barrera principal. Corrijo aqui el plan:
FEATURE.md le daba rol doble (anti-bucle + llave de idempotencia), pero lo unico
que vi garantizado en el fuente es su entrega por WebSocket
(internal/conversation/ws.go:53-54); su paso por el payload del webhook no esta
documentado. La barrera real es D3: un mensaje publicado por hub-api queda firmado
por un usuario tipo 'agent', nunca 'ai_assistant', y sin ai_assistant_id, asi que
D3 lo rechaza solo. La idempotencia se apoya en payload.uuid, que siempre llega.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

ECHO_PREFIX = "jev-retry:"

# Autor que produce nuestros propios mensajes. Verificado: sender_type valido es
# enum ('agent','contact') y cmd/messages.go rechaza cualquier otro valor, asi que
# hub-api publica como 'agent' con su propio usuario.
HUB_AUTHOR_TYPES = ("agent",)


@dataclass(frozen=True)
class IntakeResult:
    """Veredicto de la puerta de entrada."""

    accept: bool
    reason: str
    dedupe_key: str = ""
    conversation_uuid: str | None = None
    message_uuid: str | None = None
    assistant_id: int | None = None


def build_dedupe_key(event_name: str, body: dict[str, Any]) -> str:
    """Clave estable para idempotencia, derivada del contenido, no del timestamp.

    Para message.created/message.updated se usa el UUID del mensaje: es unico por
    definicion y sobrevive a reinicios y replicas.

    El fallback por hash del body existe porque `webhook.test` manda solo
    {id, name} (verificado en SendTestWebhook): sin entidad alguna, la clave vieja
    `event|timestamp|uuid_vacio` producia el mismo valor para todas las pruebas y la
    segunda del mismo segundo se descartaba en silencio.
    """
    payload = body.get("payload") or {}
    if isinstance(payload, dict):
        msg_uuid = payload.get("uuid")
        if isinstance(msg_uuid, str) and msg_uuid:
            return f"{event_name}:{msg_uuid}"
    raw = repr(sorted(body.items(), key=lambda kv: str(kv[0])))
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{event_name}:body:{digest}"


def _assistant_id(meta: Any) -> int | None:
    if not isinstance(meta, dict):
        return None
    value = meta.get("ai_assistant_id")
    if isinstance(value, bool):  # bool es int en Python; nunca es un ID valido.
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def evaluate_message_created(body: dict[str, Any], *, rules) -> IntakeResult:
    """Puerta de entrada para `message.created`. No hace I/O de ningun tipo."""
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        return IntakeResult(False, "payload_not_object",
                            dedupe_key=build_dedupe_key("message.created", body))

    msg_uuid = payload.get("uuid") or None
    conv_uuid = payload.get("conversation_uuid") or None
    meta = payload.get("meta") or {}
    assistant_id = _assistant_id(meta)

    base = dict(
        dedupe_key=build_dedupe_key("message.created", body),
        conversation_uuid=conv_uuid,
        message_uuid=msg_uuid,
        assistant_id=assistant_id,
    )

    # --- G2 (secundaria): nuestra propia salida, si el eco llegara. ---
    echo = meta.get("echo_id") if isinstance(meta, dict) else None
    if isinstance(echo, str) and echo.startswith(ECHO_PREFIX):
        return IntakeResult(False, "own_output_echo", **base)

    # --- D3: las cuatro condiciones, en orden de coste creciente de analisis. ---
    if payload.get("type") != "outgoing":
        return IntakeResult(False, "not_outgoing", **base)

    # private puede venir como bool o faltar; `is False` exige el booleano real.
    if payload.get("private") is not False:
        return IntakeResult(False, "private_or_missing", **base)

    if assistant_id is None:
        return IntakeResult(False, "no_ai_assistant_id", **base)

    author = payload.get("author") or {}
    author_type = author.get("type") if isinstance(author, dict) else None
    if author_type != "ai_assistant":
        return IntakeResult(False, "author_not_ai_assistant", **base)

    # --- G3: allowlist fail-closed. ID ausente = no se toca nada. ---
    if not rules.is_evaluable(assistant_id):
        declared = rules.agent(assistant_id) is not None
        reason = "agent_disabled" if declared else "agent_not_allowlisted"
        return IntakeResult(False, reason, **base)

    return IntakeResult(True, "accepted", **base)


def resolve_channel(body: dict[str, Any], *, known: dict[str, str] | None = None) -> str | None:
    """Canal del inbox para elegir prefijo.

    Limitacion verificada (V13): el payload de message.created NO incluye inbox_id
    ni inbox_channel — Message.InboxID es `json:"-"` y get-messages no proyecta el
    canal. Por eso el canal se obtiene de otra fuente:

      1. cache por conversacion alimentado por conversation.created (si trae
         inbox_channel, V14), o
      2. lectura directa por API/BD en el pipeline.

    Aqui solo se resuelve lo ya conocido; None significa "preguntar despues".
    """
    payload = body.get("payload") or {}
    if isinstance(payload, dict):
        direct = payload.get("inbox_channel")
        if isinstance(direct, str) and direct:
            return normalize_channel(direct)
        conv_uuid = payload.get("conversation_uuid")
        if known and conv_uuid in known:
            return known[conv_uuid]
    return None


def normalize_channel(channel: str) -> str:
    """Canal de LibreDesk -> clave de prefijo en agents.yaml.

    LiveChat y WhatsApp comparten tratamiento (`chat`); email tiene el suyo.
    Se normaliza aqui y no en YAML para que anadir un canal nuevo sea una linea,
    no editar tres archivos de reglas.
    """
    ch = (channel or "").strip().lower()
    if ch in ("livechat", "live_chat", "whatsapp"):
        return "chat"
    if ch == "email":
        return "email"
    return ch
