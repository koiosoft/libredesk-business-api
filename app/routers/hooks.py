"""LibreDesk webhook receiver (control plane, inbound events).

Constraints imposed by LibreDesk itself drive this design:

  - NO retries. A failure here means the event is lost permanently.
  - Events are dropped when the delivery queue is full ([webhook] queue_size).
  - Delivery timeout is 15s by default; the docs ask receivers to answer in under 3s.

Implemented consequences:
  1. HMAC signature verified against the RAW body before parsing.
  2. Immediate 202 response; processing happens in the background.
  3. Deduplication on (event, timestamp, entity id) since single delivery is not guaranteed.
  4. Unknown events are logged and accepted, never rejected: a 4xx would not be retried
     anyway, and it only pollutes LibreDesk logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from collections import OrderedDict

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core.config import get_settings
from app.core.security import require_internal_origin

log = logging.getLogger("hub-api.hooks")
router = APIRouter(prefix="/hooks", tags=["webhooks"])

# Bounded in-memory dedupe. Fine for a single process; if this ever runs multiple
# replicas, move it to Redis or to a table with a unique constraint.
_seen: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 5000
_lock = threading.Lock()


def _is_duplicate(key: str) -> bool:
    with _lock:
        if key in _seen:
            return True
        _seen[key] = None
        while len(_seen) > _SEEN_MAX:
            _seen.popitem(last=False)
        return False


def _signature_ok(raw: bytes, header_value: str, secret: str) -> bool:
    if not secret:
        # Without a configured secret nothing can be verified. Reject rather than
        # accept unauthenticated input.
        return False
    if not header_value:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)


# --- Handler registry -----------------------------------------------------
# Adding an event means registering a function. The dispatcher never changes.
HANDLERS: dict[str, list] = {}


def on(event: str):
    def deco(fn):
        HANDLERS.setdefault(event, []).append(fn)
        return fn

    return deco


@on("message.created")
def handle_message_created(body: dict) -> None:
    msg = body.get("payload", {})
    meta = msg.get("meta") or {}
    log.info(
        "message.created conv=%s type=%s sender=%s private=%s ai_assistant=%s",
        msg.get("conversation_uuid"), msg.get("type"),
        msg.get("sender_type"), msg.get("private"), meta.get("ai_assistant_id"),
    )
    # Extension points: assistant handoff detection, private-note filtering,
    # lead enrichment. Note that private notes arrive here too, with private=true.


@on("conversation.assigned")
def handle_assigned(body: dict) -> None:
    p = body.get("payload", {})
    log.info("conversation.assigned uuid=%s to=%s",
             p.get("conversation_uuid"), p.get("assigned_to"))


@on("conversation.unassigned")
def handle_unassigned(body: dict) -> None:
    # Cleanest handoff signal available: actor_id is the assistant's user id when the
    # AI handed the conversation over.
    p = body.get("payload", {})
    log.info("conversation.unassigned uuid=%s actor=%s",
             p.get("conversation_uuid"), p.get("actor_id"))


@on("conversation.status_changed")
def handle_status_changed(body: dict) -> None:
    p = body.get("payload", {})
    log.info("status_changed uuid=%s %s -> %s",
             p.get("conversation_uuid"), p.get("previous_status"), p.get("new_status"))


def _dispatch(event_name: str, body: dict) -> None:
    for fn in HANDLERS.get(event_name, []):
        try:
            fn(body)
        except Exception:  # noqa: BLE001 - an event handler must never kill the worker
            log.exception("handler failed event=%s fn=%s", event_name, fn.__name__)


@router.post("/libredesk", status_code=202)
async def receive_webhook(
    request: Request,
    caller: str = Depends(require_internal_origin),
    x_libredesk_signature: str | None = Header(default=None),
):
    """POST /hooks/libredesk — single receiver for every event type.

    Networking note: this route requires an allowlisted IP. When LibreDesk delivers from
    another container on the same Docker network, the source IP is the bridge address
    (172.x.x.x), NOT the host LAN. Discover it with GET /meta/whoami and add it to
    HUB_ALLOWED_IPS.
    """
    settings = get_settings()
    raw = await request.body()

    if not _signature_ok(raw, x_libredesk_signature or "", settings.webhook_secret):
        log.warning("webhook rejected: invalid or missing signature caller=%s", caller)
        raise HTTPException(
            status_code=403,
            detail="invalid signature or webhook secret not configured",
        )

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body is not valid JSON")

    event_name = body.get("event", "")
    ts = body.get("timestamp", "")
    payload = body.get("payload") or {}
    ent = payload.get("uuid") or payload.get("conversation_uuid") or ""
    key = f"{event_name}|{ts}|{ent}"

    if _is_duplicate(key):
        log.info("duplicate event ignored: %s", key)
        return {"status": "duplicate_ignored"}

    # Process in the background so the response returns immediately (<3s requirement).
    threading.Thread(target=_dispatch, args=(event_name, body), daemon=True).start()

    if event_name not in HANDLERS:
        log.info("event with no registered handler: %s", event_name)

    return {"status": "accepted", "event": event_name}
