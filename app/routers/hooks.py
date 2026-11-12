"""LibreDesk webhook receiver (control plane, inbound events).

Constraints imposed by LibreDesk itself drive this design:

  - NO retries. A failure here means the event is lost permanently.
  - Events are dropped when the delivery queue is full ([webhook] queue_size).
  - Delivery timeout is 15s by default; the docs ask receivers to answer in under 3s.

Implemented consequences:
  1. HMAC signature verified against the RAW body before parsing.
  2. Immediate 202 response; processing happens as a background task on the event
     loop. Nothing slow runs before the response — no database write either, by the
     decision recorded in app/core/state.py.
  3. Deduplication on the message UUID (not the timestamp): two deliveries of the
     same message collapse into one, and `webhook.test` payloads, which carry only
     {id, name}, fall back to a content hash so consecutive tests stop discarding
     each other silently.
  4. Unknown events are logged and accepted, never rejected: a 4xx would not be
     retried anyway, and it only pollutes LibreDesk logs.

Route note: the path stays /hooks/libredesk deliberately. Renaming it would drop
every event, because LibreDesk never retries — the URL registered in Admin ->
Integrations -> Webhooks is the contract, not this file.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core.config import get_settings
from app.core.rules import Rules
from app.core.security import require_internal_origin
from app.core.state import STATE
from app.jev.intake import build_dedupe_key, evaluate_message_created, normalize_channel

log = logging.getLogger("hub-api.hooks")
router = APIRouter(prefix="/hooks", tags=["webhooks"])


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
# Handlers are coroutines: dispatch runs on FastAPI's event loop, not on one daemon
# thread per event (unbounded concurrency, silent death on restart).
HANDLERS: dict[str, list] = {}


def on(event: str):
    def deco(fn):
        HANDLERS.setdefault(event, []).append(fn)
        return fn

    return deco


@on("message.created")
async def handle_message_created(body: dict, ctx: dict[str, Any]) -> None:
    """Puerta de entrada del enforcement loop.

    Decide con las guardas puras de app/jev/intake.py si el mensaje entra al
    pipeline. El motivo del rechazo se loggea completo: es la unica trazabilidad
    que existe sin registro permanente.
    """
    rules: Rules | None = ctx.get("rules")
    if rules is None:
        log.error("message.created without rules loaded; skipping")
        return

    verdict = evaluate_message_created(body, rules=rules)

    if not verdict.accept:
        log.info("message.created ignored reason=%s msg=%s assistant=%s",
                 verdict.reason, verdict.message_uuid, verdict.assistant_id)
        return

    hub = ctx.get("hub")
    if hub is None:
        # Sin clientes HTTP no hay clasificador ni publicacion posibles. Se loggea
        # y se sale: nunca se asume exito.
        log.warning("pipeline skipped, http clients not initialised conv=%s",
                    verdict.conversation_uuid)
        return

    # El canal viene de conversation.created: message.created no lo trae (V13).
    channel = STATE.channel_for(verdict.conversation_uuid)

    log.info(
        "message.created entering pipeline conv=%s msg=%s assistant=%s channel=%s",
        verdict.conversation_uuid, verdict.message_uuid, verdict.assistant_id, channel,
    )
    item = {
        "conversation_uuid": verdict.conversation_uuid,
        "message_uuid": verdict.message_uuid,
        "assistant_id": verdict.assistant_id,
        "channel": channel,
        "payload": body.get("payload") or {},
    }

    from app.jev.deps import run_guarded
    from app.jev.pipeline import EnforcementPipeline

    pipeline = EnforcementPipeline(
        rules=rules, settings=get_settings(),
        classifier=hub.classifier, libredesk=hub.libredesk,
    )
    try:
        summary = await run_guarded(hub, pipeline, item)
    except Exception:  # noqa: BLE001 - el fallo queda en logs, no derriba la tarea
        log.exception("pipeline crashed conv=%s msg=%s",
                      verdict.conversation_uuid, verdict.message_uuid)
        return
    log.info("pipeline result %s", summary)


@on("conversation.assigned")
async def handle_assigned(body: dict, ctx: dict[str, Any]) -> None:
    p = body.get("payload", {})
    log.info("conversation.assigned uuid=%s to=%s",
             p.get("conversation_uuid"), p.get("assigned_to"))


@on("conversation.unassigned")
async def handle_unassigned(body: dict, ctx: dict[str, Any]) -> None:
    # Cleanest handoff signal available: actor_id is the assistant's user id when the
    # AI handed the conversation over.
    p = body.get("payload", {})
    log.info("conversation.unassigned uuid=%s actor=%s",
             p.get("conversation_uuid"), p.get("actor_id"))


@on("conversation.status_changed")
async def handle_status_changed(body: dict, ctx: dict[str, Any]) -> None:
    p = body.get("payload", {})
    log.info("status_changed uuid=%s %s -> %s",
             p.get("conversation_uuid"), p.get("previous_status"), p.get("new_status"))


@on("conversation.created")
async def handle_conversation_created(body: dict, ctx: dict[str, Any]) -> None:
    """Unica fuente del canal en el stream de eventos (V13/V14).

    message.created no incluye inbox_channel; conversation.created si. Se recuerda
    por conversacion para elegir prefijo cuando llegue el turno del agente.
    """
    p = body.get("payload", {})
    conv = p.get("uuid") or p.get("conversation_uuid")
    # Store the NORMALIZED channel. The webhook value is the raw inbox_channel
    # ("livechat"), while agents.yaml keys are "chat"/"email". Measured failure:
    # a generated correction was discarded with no_prefix_for_channel:livechat
    # because this cache held the raw string while the rest of the pipeline
    # normalized everywhere else.
    channel = normalize_channel(p.get("inbox_channel"))
    if conv and channel:
        STATE.remember_channel(conv, channel)
    log.info("conversation.created uuid=%s channel=%s", conv, channel)


async def _dispatch(event_name: str, body: dict, ctx: dict[str, Any]) -> None:
    for fn in HANDLERS.get(event_name, []):
        try:
            await fn(body, ctx)
        except Exception:  # noqa: BLE001 - an event handler must never kill the task
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

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body is not a JSON object")

    event_name = body.get("event", "")
    dedupe_key = build_dedupe_key(event_name, body)

    if STATE.seen_before(dedupe_key):
        log.info("duplicate event ignored key=%s", dedupe_key)
        return {"status": "duplicate_ignored", "event": event_name}

    ctx: dict[str, Any] = {
        "rules": getattr(request.app.state, "rules", None),
        "hub": getattr(request.app.state, "hub", None),
        "dedupe_key": dedupe_key,
    }

    # Background processing: the 202 goes out before anything slow (JEV ~300 ms
    # measured, LLM seconds). A task, not a thread.
    task = asyncio.create_task(_dispatch(event_name, body, ctx))
    tasks = getattr(request.app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        request.app.state.background_tasks = tasks
    # Retaining the reference matters: an unreferenced task can be garbage collected
    # before finishing, which is exactly the silent loss we removed.
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    if event_name not in HANDLERS:
        log.info("event with no registered handler: %s", event_name)

    return {"status": "accepted", "event": event_name}
