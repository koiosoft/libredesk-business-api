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
from app.core.rules import NONE_OPTION, Rules
from app.core.state import STATE
from app.jev import composer
from app.jev.classifier import Classifier
from app.jev.intake import normalize_channel
from app.jev.libredesk import LibreDeskClient
from app.jev.snippets import TableSnippetSource, format_snippets

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
        # Snippet backend behind the D4 interface. Constructed here, injected
        # nowhere else: swapping the table for a semantic source later touches
        # one line (its own docstring records why that source is unreachable).
        self._snippets = TableSnippetSource(libredesk.get_snippets)
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

        # --- Closed-conversation guard (owner decision 2026-11-14, layer 1). ----
        # A resolved/closed conversation is NOT correctable: measured in conv
        # 03b9aace, "correcting" the bot's own closing message published a SECOND
        # farewell on top of the first. The status comes from the webhook payload
        # when it carries one; otherwise the conversation header is read ONCE and
        # reused below for channel/contact too (no extra GET per stage). Whatever
        # races past this read -- LibreDesk marks Resolved in the same second it
        # posts the reply -- is covered by the closing-message guardrail that
        # lives in question.instructions (layer 2).
        conv_row: dict[str, Any] | None = None
        # The webhook payload CANNOT carry this check: the envelope is
        # {event, timestamp, payload=<message row>} (webhook.go deliverSingleWebhook)
        # and Message.Status is the MESSAGE's delivery state (sent/received/
        # pending, models.go:346), never the conversation's. So the guard reads
        # cached state first (status_changed / conversation.created populate it)
        # and pays for one header GET only when state says "never seen".
        known = STATE.conversation_state(conv)
        if known is False:
            log.info("conversation %s already closed; nothing to correct", conv)
            return {**base, "outcome": "skipped", "reason": "conversation_closed"}
        if known is None:
            conv_row = await self._libredesk.get_conversation(conv) or {}
            st = str(conv_row.get("status") or "").lower()
            if st in ("resolved", "closed"):
                STATE.mark_closed(conv)
                log.info("conversation %s already %s; nothing to correct", conv, st)
                return {**base, "outcome": "skipped", "reason": "conversation_closed"}
            STATE.remember_open(conv)

        # --- State for JEV: customer + reply + recent history (O1). ---
        messages = await self._libredesk.get_conversation_messages(conv)
        history = build_history(messages, exclude_uuid=msg_uuid)
        customer = pick_customer_message(history) or _text_of(
            next((m for m in reversed(messages)
                  if _is_contact(m) and not m.get("private")), {}))
        # The assistant policy is the criterion JEV needs to decide what to
        # improve against; it is read from the live assistant (cached) and sent
        # whole (D1/G2: no character limit on policy fields).
        guard = getattr(cfg, "guardrails", "") or ""
        policy = composer.build_policy_header(
            getattr(cfg, "instructions", "") or "", guard,
        )
        # The judge resolves the same compliance material the policy points at
        # (T3.4). Before a decision exists there is no single chosen option, so
        # every id declared by any option travels: the set is small by design
        # (snippets are few and hand-curated) and a stable block keeps the §9
        # layout identical across events. Failures never block a classification
        # (G4): an empty result simply omits the block.
        state = composer.build_state_for_jev(
            customer_message=customer, agent_message=agent_text,
            history=history[:-1], policy=policy,
            turn_structure=_extract_turn_structure(guard),
            snippets=await self._snippet_block(self._rules.all_snippet_ids()),
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

        # --- Multi-action composition (opt-in: JEV_MULTI_ACTION, default false). --
        # JEV's `probabilities` map covers every criterion (verified live against
        # /api/alpha/decisions: keys == criteria keys, sums to 1). When enabled,
        # secondary options are added in descending probability while the running
        # mass stays below JEV_MULTI_PROB_CEILING (default 0.6): the moment the
        # sum reaches it, no more are added ("un pelito mas" is allowed because
        # the check runs BEFORE each addition, never after). `none` is always
        # excluded: it means "publish nothing" and contradicts any action text.
        choices = [decision.choice]
        probs = decision.probabilities or {}
        if self._settings.jev_multi_action and probs:
            total = decision.probability
            for prob, cand in sorted(((p, c) for c, p in probs.items()
                                      if c != decision.choice and c != NONE_OPTION),
                                     reverse=True):
                if total >= self._settings.jev_multi_prob_ceiling:
                    break
                if self._rules.action_text(cand):      # must exist in YAML
                    choices.append(cand)
                    total += prob
        # Texts are emitted ASCENDING by probability so the chosen option -- the
        # strongest, and the one JEV actually picked -- lands LAST inside ACCION:
        # precedence here is positional (G6), what the model reads last wins.
        # (flag off -> choices is just [decision.choice], exactly one text). A
        # secondary whose text is missing from YAML drops out; if the CHOSEN one
        # is missing, fail-closed below. `choices` was built in descending order;
        # reversed, the sequence reads weakest-first / strongest-last.
        action_texts = []
        snippet_ids: list[int] = []
        for choice in reversed(choices):
            text = self._rules.action_text(choice)
            if not text:
                continue
            action_texts.append(text)
            for sid in self._rules.snippet_ids(choice):
                if sid not in snippet_ids:
                    snippet_ids.append(sid)
        action_text = "\n\n".join(action_texts)
        if not action_text:
            # Chosen action missing from the YAML: total fail-closed.
            return {**base, "outcome": "ignored", "reason": f"action_missing:{decision.choice}"}

        # Snippets of every composed action reach the corrector (D2): the rules
        # bind actions to compliance material, retrieval decides nothing.
        chosen_snippets = await self._snippet_block(snippet_ids)
        # --- Per-conversation cap BEFORE spending generation. ---
        if not STATE.take_correction_slot(
            conv, self._settings.jev_max_corrections
        ):
            return {**base, "outcome": "skipped", "reason": "correction_limit_reached",
                    "choice": decision.choice}

        # Multi-action is opt-in and experimental: when it fired, the extra mass
        # must be visible in the log to evaluate the feature offline (which
        # secondary actions rode along, with what probabilities).
        if len(choices) > 1:
            log.info("multi-action conv=%s choices=%s probs=%s", conv,
                     "->".join(reversed(choices)),
                     {c: round(probs.get(c, 0.0), 3) for c in choices})

        # Generation engine (D3/G8): /ai/completion with the full composed
        # prompt is the active path -- the corrector must see exactly what the
        # generator saw, plus JEV's action last (§9). /ai/copilot remains
        # reachable explicitly through JEV_USE_COPILOT=true, but its persona
        # omits guardrails server-side (V15), so it is no longer the default.
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
                history=history[:-1],
                snippets=chosen_snippets,
            )
            prompt_key = self._settings.jev_completion_prompt_key
            if not prompt_key:
                # D8/G9: the variable is required in production; without it the
                # first ai_prompts row is used and the omission lands in logs.
                prompt_key = await self._libredesk.first_prompt_key()
            generated = (await self._libredesk.complete(prompt_key, prompt)
                         if prompt_key else None)
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
            if conv_row is None:
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


    async def _snippet_block(self, ids) -> str:  # noqa: ANN001 - Sequence[int]
        """Resolve ids to the formatted block both prompts share (G7).

        Never raises: snippet availability enriches context, it does not gate
        enforcement (G4). A source failure logs and yields "" -- the pipeline
        then composes exactly the pre-feature state minus nothing else.
        """
        if not ids:
            return ""
        try:
            found = await self._snippets.resolve(ids)
        except Exception as exc:  # noqa: BLE001 - fail-open by contract G4
            log.warning("snippet resolution failed (%s); continuing without them", exc)
            return ""
        return format_snippets(found)


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
