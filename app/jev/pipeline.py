"""Enforcement pipeline: JEV -> generate -> publish.

Orchestrates the stages on FastAPI's event loop. The 202 was already answered by
the router when this runs; everything here may take seconds without affecting
LibreDesk.

Concurrency: asyncio.Semaphore(JEV_CONCURRENCY) around the COMPLETE pipeline, not
just the single slow step. Plan R1: an uncapped burst of agent messages would open
N simultaneous LLM connections and could exhaust quota.

Cross-cutting rule: any failure => do not publish. Misclassifying is fixable; a
wrong message already sent to a customer is not.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings
from app.core.rules import Rules
from app.core.state import STATE
from app.jev import composer
from app.jev.classifier import Classifier
from app.jev.intake import normalize_channel
from app.jev.libredesk import LibreDeskClient

log = logging.getLogger("hub-api.jev.pipeline")


def _text_of(message: dict[str, Any]) -> str:
    """Readable text of a message. Prefers text_content (plain) over content."""
    for key in ("text_content", "content"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_contact(message: dict[str, Any]) -> bool:
    return message.get("sender_type") == "contact" or (
        (message.get("author") or {}).get("type") in ("contact", "visitor")
    )


def build_history(messages: list[dict[str, Any]], *, exclude_uuid: str | None,
                  limit: int = 8) -> list[tuple[str, str]]:
    """Chronological history (role, text) excluding private notes and the msg itself.

    `private` messages are filtered out: they are team-internal and must not enter
    a prompt that generates customer-visible text.
    """
    out: list[tuple[str, str]] = []
    for m in messages:
        if m.get("private"):
            continue
        uuid = m.get("uuid")
        if exclude_uuid and uuid == exclude_uuid:
            continue
        text = _text_of(m)
        if not text:
            continue
        out.append(("contact" if _is_contact(m) else "agent", text))
    return out[-limit:]


def pick_customer_message(history: list[tuple[str, str]]) -> str:
    """Last customer message within the already trimmed history."""
    for role, text in reversed(history):
        if role == "contact":
            return text
    return ""


class EnforcementPipeline:
    def __init__(self, *, rules: Rules, settings: Settings, classifier: Classifier,
                 libredesk: LibreDeskClient) -> None:
        self._rules = rules
        self._settings = settings
        self._classifier = classifier
        self._libredesk = libredesk

    async def run(self, item: dict[str, Any]) -> dict[str, Any]:
        """Runs the full cycle for a message already accepted by intake.py.

        Returns a summary for logging. Never raises: a failure here stays in logs,
        it does not crash the task nor retry against LibreDesk.
        """
        conv = item.get("conversation_uuid")
        msg_uuid = item.get("message_uuid")
        assistant_id = item.get("assistant_id")
        payload = item.get("payload") or {}
        base = {"conversation_uuid": conv, "message_uuid": msg_uuid,
                "assistant_id": assistant_id}

        if not conv or not msg_uuid or not assistant_id:
            return {**base, "outcome": "skipped", "reason": "incomplete_input"}

        # G3 second pass: the assistant may have been deleted after rules loaded.
        cfg = await self._libredesk.get_assistant(assistant_id)
        if cfg is None:
            log.warning("assistant %s not readable; ignoring (fail-closed)", assistant_id)
            return {**base, "outcome": "ignored", "reason": "assistant_unreadable"}
        if not cfg.usable:
            return {**base, "outcome": "ignored", "reason": "assistant_disabled_now"}

        agent_text = _text_of(payload)
        if not agent_text:
            return {**base, "outcome": "ignored", "reason": "empty_agent_message"}

        # --- State for JEV: customer + reply + recent history (O1). ---
        messages = await self._libredesk.get_conversation_messages(conv)
        conv_row: dict[str, Any] | None = None
        history = build_history(messages, exclude_uuid=msg_uuid)
        customer = pick_customer_message(history) or _text_of(
            next((m for m in reversed(messages)
                  if _is_contact(m) and not m.get("private")), {})
        )
        # The assistant policy is the criterion JEV needs to decide what to
        # improve against; it is read from the live assistant (cached) and clipped.
        guard = getattr(cfg, "guardrails", "") or ""
        policy = composer.build_policy_header(
            getattr(cfg, "instructions", "") or "", guard,
        )
        state = composer.build_state_for_jev(
            customer_message=customer, agent_message=agent_text,
            history=history[:-1], policy=policy,
            turn_structure=_extract_turn_structure(guard),
        )

        # Offer handoff-too-early only when a handoff was actually observed. Always
        # presenting it invites JEV to prefer "hand the lead over" to a plain
        # rewrite; measured 2026-11-12 that cost a real correction its revive.
        criteria = dict(self._rules.options)
        if not item.get("handed_off"):
            criteria.pop("handoff-too-early", None)

        min_conf, min_prob = self._settings.jev_thresholds
        decision = await self._classifier.classify(
            state, self._rules.question_instructions, criteria,
            min_confidence=min_conf, min_probability=min_prob,
        )
        if not decision.should_act or decision.choice is None:
            return {**base, "outcome": "skipped", "reason": decision.reason,
                    "choice": decision.choice, "confidence": decision.confidence}

        action_text = self._rules.action_text(decision.choice)
        if not action_text:
            # Chosen action missing from the YAML: total fail-closed.
            return {**base, "outcome": "ignored", "reason": f"action_missing:{decision.choice}"}

        # --- Per-conversation cap BEFORE spending generation. ---
        if not STATE.take_correction_slot(
            conv, self._settings.jev_max_corrections
        ):
            return {**base, "outcome": "skipped", "reason": "correction_limit_reached",
                    "choice": decision.choice}

        # Contextual generation: /ai/copilot rebuilds history, persona and the
        # knowledge base on the LibreDesk side. compose_prompt()/
        # complete() remain reachable explicitly through JEV_USE_COPILOT=false.
        if self._settings.jev_use_copilot:
            instruction = composer.build_correction_instruction(
                action_text=action_text, assistant_name=cfg.name,
                last_agent_reply=agent_text,
            )
            generated = await self._libredesk.copilot(
                conversation_uuid=conv, message=instruction,
                assistant_id=assistant_id,
            )
        else:
            prompt = composer.compose_prompt(
                action_text=action_text,
                assistant_name=cfg.name,
                instructions=cfg.instructions,
                guardrails=cfg.guardrails,
                customer_message=customer,
                agent_message=agent_text,
            )
            generated = await self._libredesk.complete(
                self._settings.jev_completion_prompt_key, prompt
            )
        if not generated:
            return {**base, "outcome": "failed", "reason": "generation_empty",
                    "choice": decision.choice}

        safe_body = composer.strip_dangerous_template_syntax(generated)

        # Prefix per channel (D7). The channel comes from conversation.created or,
        # resolved by reading the conversation: without a prefix nothing publishes,
        # because the label is what tells the correction from the agent message.
        # Channel: cached from conversation.created; if missing (e.g. the
        # conversation predates this process), its header is read instead.
        # Normalize every source. The webhook path stores an already-mapped value,
        # but get_conversation returns the raw inbox_channel ("whatsapp"), which has
        # no prefix key in agents.yaml -- measured 2026-11-12: a valid correction was
        # discarded AFTER paying for JEV and generation (no_prefix_for_channel:whatsapp).
        channel = normalize_channel(item.get("channel") or STATE.channel_for(conv))
        if not channel:
            conv_row = await self._libredesk.get_conversation(conv) or {}
            raw = (conv_row or {}).get("inbox_channel")
            if isinstance(raw, str) and raw:
                channel = normalize_channel(raw)
                STATE.remember_channel(conv, channel)
        rule = self._rules.agent(assistant_id)
        prefix = rule.prefix_for(channel) if rule else None
        if not prefix:
            return {**base, "outcome": "ignored", "reason": f"no_prefix_for_channel:{channel}",
                    "choice": decision.choice}

        html_body = composer.with_prefix(prefix, safe_body)

        to = _recipients_for(payload, messages)
        if not to:
            to = _contact_email(conv_row)
        result = await self._libredesk.publish_correction(
            conversation_uuid=conv, html_body=html_body, to=to,
            echo_id=f"jev-retry:{msg_uuid}",
        )

        # Declarative post-action (rules/prompts.yaml `post_action`): options like
        # revive-assistant change channel STATE, not text. They run only after a
        # successful publish -- reassigning with nothing published would leave the
        # bot with nothing to pick up and reset its turn budget in vain.
        summary_extra: dict[str, Any] = {}
        if result.ok:
            post = self._rules.post_action(decision.choice)
            if post == "revive-assistant":
                # Reassign by TEAM (never by bare user id): the operator's
                # automation rule watches team events and assigns the bot itself.
                team = rule.revive_team_id if rule else None
                if team:
                    revived = await self._libredesk.assign_team(conv, team)
                    if revived:
                        STATE.clear_handoff(conv)
                    summary_extra = {"revived_assistant": revived,
                                     "revive_team_id": team}
                else:
                    log.warning("revive skipped: no revive_team_id configured for "
                                "assistant %s", assistant_id)
                    summary_extra = {"revived_assistant": False}
        outcome = "corrected" if result.ok else "failed"
        log.info(
            "pipeline done outcome=%s conv=%s choice=%s conf=%.3f status=%s reason=%s",
            outcome, conv, decision.choice, decision.confidence,
            result.status, result.reason,
        )
        return {**base, "outcome": outcome, "choice": decision.choice,
                "confidence": decision.confidence, "cost_usd": decision.cost_usd,
                "published_status": result.status, "reason": result.reason,
                "new_message_uuid": result.message_uuid, **summary_extra}


def _extract_turn_structure(guardrails: str) -> str:
    """Pull the mandatory turn-structure clause out of the guardrail blob.

    Only the first rule block is quoted so JEV sees the exact contract a reply
    must satisfy without the rest of the policy diluting attention. Counting
    questions is otherwise undecidable from the message alone.
    """
    start = guardrails.find("ESTRUCTURA OBLIGATORIA")
    if start < 0:
        return ""
    end = len(guardrails)
    for marker in ("\nB.", "\nb."):
        i = guardrails.find(marker, start)
        if i > 0:
            end = min(end, i)
    chunk = guardrails[start:end].strip()
    return ("MANDATORY TURN STRUCTURE (check the reply against this):\n"
            + chunk[:1200])


def _contact_email(conversation_row: dict[str, Any] | None) -> list[str] | None:
    """Contact email, as last resort for `to` in email."""
    contact = (conversation_row or {}).get("contact")
    if isinstance(contact, dict):
        email = contact.get("email")
        if isinstance(email, str) and email.strip():
            return [email.strip()]
    return None


def _recipients_for(payload: dict[str, Any],
                    messages: list[dict[str, Any]]) -> list[str] | None:
    """Recipients for email. Verified: an empty `to` returns HTTP 500 "`to` empty".

    Reuses the agent message's own `to` (meta.to), which already resolves
    threads and aliases; when absent it looks in the latest outgoing message.
    """
    meta = payload.get("meta")
    if isinstance(meta, dict):
        to = meta.get("to")
        if isinstance(to, list) and [x for x in to if isinstance(x, str) and x]:
            return [x for x in to if isinstance(x, str) and x]
    for m in reversed(messages):
        m_meta = m.get("meta")
        if isinstance(m_meta, dict):
            to = m_meta.get("to")
            if isinstance(to, list) and [x for x in to if isinstance(x, str) and x]:
                return [x for x in to if isinstance(x, str) and x]
    return None
