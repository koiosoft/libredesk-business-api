"""Pipeline de enforcement: JEV -> generar -> publicar.

Orquesta las etapas sobre el event loop de FastAPI. El 202 ya se respondio en el
router cuando esto corre; aqui todo puede tardar segundos sin afectar a LibreDesk.

Concurrencia: asyncio.Semaphore(JEV_CONCURRENCY) alrededor del pipeline COMPLETO,
no solo del paso lento individual. R1 del plan: una rafaga de mensajes del agente
sin tope abriria N conexiones simultaneas al LLM y podia agotar la cuota.

Regla transversal: cualquier fallo => no publicar. Clasificar mal se corrige; un
mensaje erroneo enviado a un cliente ya esta enviado.
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
    """Texto legible de un mensaje. Prioriza text_content (plain) sobre content."""
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
    """Historial cronologico (rol, texto) excluyendo notas privadas y el propio msg.

    Se filtran los mensajes `private`: son internas del equipo y no deben entrar en
    un prompt que genera texto visible para el cliente.
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
    """Ultimo mensaje del cliente dentro del historial ya recortado."""
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
        """Ejecuta el ciclo completo para un mensaje ya aceptado por intake.py.

        Devuelve un resumen para loggear. No lanza: un fallo aqui debe quedar en
        logs, no tumbar la tarea ni reintentar contra LibreDesk.
        """
        conv = item.get("conversation_uuid")
        msg_uuid = item.get("message_uuid")
        assistant_id = item.get("assistant_id")
        payload = item.get("payload") or {}
        base = {"conversation_uuid": conv, "message_uuid": msg_uuid,
                "assistant_id": assistant_id}

        if not conv or not msg_uuid or not assistant_id:
            return {**base, "outcome": "skipped", "reason": "incomplete_input"}

        # G3 segunda pasada: el asistente pudo borrarse despues de cargar las reglas.
        cfg = await self._libredesk.get_assistant(assistant_id)
        if cfg is None:
            log.warning("assistant %s not readable; ignoring (fail-closed)", assistant_id)
            return {**base, "outcome": "ignored", "reason": "assistant_unreadable"}
        if not cfg.usable:
            return {**base, "outcome": "ignored", "reason": "assistant_disabled_now"}

        agent_text = _text_of(payload)
        if not agent_text:
            return {**base, "outcome": "ignored", "reason": "empty_agent_message"}

        # --- Estado para JEV: cliente + respuesta + historial reciente (O1). ---
        messages = await self._libredesk.get_conversation_messages(conv)
        conv_row: dict[str, Any] | None = None
        history = build_history(messages, exclude_uuid=msg_uuid)
        customer = pick_customer_message(history) or _text_of(
            next((m for m in reversed(messages)
                  if _is_contact(m) and not m.get("private")), {})
        )
        # La politica del asistente es el criterio que JEV necesita para elegir
        # "en base a que mejorar". Se lee del asistente real (cacheado), recortado.
        cfg_now = cfg  # ya fetched arriba via get_assistant
        policy = composer.build_policy_header(
            getattr(cfg_now, "instructions", "") or "",
            getattr(cfg_now, "guardrails", "") or "",
        )
        state = composer.build_state_for_jev(
            customer_message=customer, agent_message=agent_text,
            history=history[:-1], policy=policy,
        )

        min_conf, min_prob = self._settings.jev_thresholds
        decision = await self._classifier.classify(
            state, self._rules.question_instructions, self._rules.options,
            min_confidence=min_conf, min_probability=min_prob,
        )
        if not decision.should_act or decision.choice is None:
            return {**base, "outcome": "skipped", "reason": decision.reason,
                    "choice": decision.choice, "confidence": decision.confidence}

        action_text = self._rules.action_text(decision.choice)
        if not action_text:
            # Accion elegida pero ausente del YAML: fail-closed total.
            return {**base, "outcome": "ignored", "reason": f"action_missing:{decision.choice}"}

        # --- Tope por conversacion, ANTES de gastar la generacion. ---
        if not STATE.take_correction_slot(
            conv, self._settings.jev_max_corrections
        ):
            return {**base, "outcome": "skipped", "reason": "correction_limit_reached",
                    "choice": decision.choice}

        # Generacion contextual: /ai/copilot reconstruye el historial, la persona
        # y la base de conocimiento del lado de LibreDesk. compose_prompt()/
        # complete() quedan como respaldo explicito via JEV_USE_COPILOT=false.
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

        # Prefijo por canal (D7). El canal llega de conversation.created o, si no,
        # se resuelve leyendo la conversacion: sin prefijo NO se publica, porque la
        # etiqueta es lo que distingue la correccion del mensaje del agente.
        # Canal: preferencia cache del evento conversation.created; si falta (p.ej.
        # la conversacion nacio antes de arrancar este proceso), se lee la cabecera.
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

        # Post-action declarativa (rules/prompts.yaml `post_action`): las acciones
        # tipo revive-agent-ia no cambian el TEXTO sino el ESTADO del canal. Solo
        # tras publicacion exitosa: reasignar sin mensaje publicado dejaría al bot
        # sin nada que retomar y resetea turnos en vano.
        if result.ok:
            post = self._rules.post_action(decision.choice)
            if post == "revive-assistant":
                # El ID a re-asignar viene de rules/agents.yaml (assign_user_id).
                # Fallback: el user_id leido del asistente en vivo. Sin ambos, se
                # omite el revive sin fallar la correccion ya publicada.
                target = rule.assign_user_id if rule else None
                target = target or cfg.user_id
                if target:
                    revived = await self._libredesk.assign_assistant(conv, target)
                    summary_extra = {"revived_assistant": revived,
                                     "revived_assignee_id": target}
                else:
                    log.warning("revive skipped: no assign_user_id configured for "
                                "assistant %s", assistant_id)
                    summary_extra = {"revived_assistant": False}
            else:
                summary_extra = {}
        else:
            summary_extra = {}
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


def _contact_email(conversation_row: dict[str, Any] | None) -> list[str] | None:
    """Correo del contacto, como ultimo recurso para `to` en email."""
    contact = (conversation_row or {}).get("contact")
    if isinstance(contact, dict):
        email = contact.get("email")
        if isinstance(email, str) and email.strip():
            return [email.strip()]
    return None


def _recipients_for(payload: dict[str, Any],
                    messages: list[dict[str, Any]]) -> list[str] | None:
    """Destinatarios para email. Verificado: `to` vacio devuelve 500 "`to` empty".

    Se reutiliza el `to` del propio mensaje del agente (meta.to), que ya resuelve
    hilos y alias; si no existe, se busca en el ultimo saliente con destinatarios.
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
