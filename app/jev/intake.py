"""Entry guards: decide whether an event enters the pipeline, and why not.

Separated from HTTP for two reasons: these rules are the only thing preventing
garbage from reaching a customer channel, and they must be testable without
network or database.

Filter D3 -- the FOUR conditions, all required:

    payload.type == "outgoing"
    AND payload.private is False
    AND payload.meta.ai_assistant_id > 0
    AND payload.author.type == "ai_assistant"

Both AI signals are demanded even though they look redundant, and they really are
independent: `meta.ai_assistant_id` is written by postReply() in memory
(internal/aiagent/worker.go:441) while `author.type` comes from the JOIN to users
in the read-model (internal/conversation/queries.sql -> get-message). Requiring
both to agree is a cheap integrity check before spending JEV + LLM.

G2 (echo_id) is SECONDARY DEFENSE, not the main barrier. Correcting the plan here:
FEATURE.md gave it a double role (anti-loop + idempotency key), but the only thing
verified in the source is its WebSocket delivery
(internal/conversation/ws.go:53-54); its presence in the webhook payload is not
documented. The real barrier is D3: a message published by hub-api is signed by a
user of type 'agent', never 'ai_assistant', and with no ai_assistant_id, so D3
rejects it on its own. Idempotency relies on payload.uuid, which always arrives.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

ECHO_PREFIX = "jev-retry:"

# Author that produces our own messages. Verified: the valid sender_type enum is
# enum ('agent','contact') and cmd/messages.go rejects anything else, so
# hub-api publishes as 'agent' with its own user.
HUB_AUTHOR_TYPES = ("agent",)


@dataclass(frozen=True)
class IntakeResult:
    """Gatekeeper verdict."""

    accept: bool
    reason: str
    dedupe_key: str = ""
    conversation_uuid: str | None = None
    message_uuid: str | None = None
    assistant_id: int | None = None
    # True when the assistant had abandoned this conversation (seen through
    # conversation.unassigned or an assistant-authored handoff note). The pipeline
    # offers handoff-too-early only when it is set.
    handed_off: bool = False


def build_dedupe_key(event_name: str, body: dict[str, Any]) -> str:
    """Stable idempotency key, derived from content rather than the timestamp.

    For message.created/message.updated the message UUID is used: unique per
    definicion y sobrevive a reinicios y replicas.

    The body-hash fallback exists because `webhook.test` sends only
    {id, name} (verified in SendTestWebhook): with no entity at all, the old key
    `event|timestamp|empty_uuid` produced the same value for every test and the
    second one inside the same second was silently discarded.
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
    if isinstance(value, bool):  # bool is int in Python; never a valid ID.
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def evaluate_message_created(body: dict[str, Any], *, rules,
                             handed_off: bool = False) -> IntakeResult:
    """Entry gate for `message.created`. Performs no I/O of any kind."""
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
        handed_off=handed_off,
    )

    # --- G2 (secondary): our own output, if the echo ever arrives. ---
    echo = meta.get("echo_id") if isinstance(meta, dict) else None
    if isinstance(echo, str) and echo.startswith(ECHO_PREFIX):
        return IntakeResult(False, "own_output_echo", **base)

    # --- D3: the four conditions, ordered by rising analysis cost. ---
    if payload.get("type") != "outgoing":
        return IntakeResult(False, "not_outgoing", **base)

    # private may arrive as a bool or be absent; `is False` demands the real one.
    if payload.get("private") is not False:
        return IntakeResult(False, "private_or_missing", **base)

    if assistant_id is None:
        return IntakeResult(False, "no_ai_assistant_id", **base)

    author = payload.get("author") or {}
    author_type = author.get("type") if isinstance(author, dict) else None
    if author_type != "ai_assistant":
        return IntakeResult(False, "author_not_ai_assistant", **base)

    # --- G3: fail-closed allowlist. Absent id = touch nothing. ---
    if not rules.is_evaluable(assistant_id):
        declared = rules.agent(assistant_id) is not None
        reason = "agent_disabled" if declared else "agent_not_allowlisted"
        return IntakeResult(False, reason, **base)

    return IntakeResult(True, "accepted", **base)


def resolve_channel(body: dict[str, Any], *, known: dict[str, str] | None = None) -> str | None:
    """Inbox channel used to pick the prefix.

    Verified limitation (V13): the message.created payload includes neither
    inbox_id nor inbox_channel -- Message.InboxID is `json:"-"` and get-messages
    never projects the channel. So the channel comes from elsewhere:

      1. a per-conversation cache fed by conversation.created (when it carries
         inbox_channel, V14), or
      2. a direct API/DB read inside the pipeline.

    Only known sources are consulted here; None means "askeguntar despues".
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

    LiveChat and WhatsApp share treatment (`chat`); email has its own.
    Normalized here rather than in YAML so adding a channel is one line,
    no editar tres archivos de reglas.
    """
    ch = (channel or "").strip().lower()
    if ch in ("livechat", "live_chat", "whatsapp"):
        return "chat"
    if ch == "email":
        return "email"
    return ch
