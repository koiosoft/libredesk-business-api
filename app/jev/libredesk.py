"""Cliente de la API oficial de LibreDesk: leer asistente, generar, publicar.

Se usa SOLO la API publica. La escritura directa en tablas de LibreDesk queda
descartada (riesgo R6 del plan: se rompe con cada migracion).

Autenticacion verificada contra la instancia de desarrollo:
    Authorization: token <api_key>:<api_secret>
(tambien acepta Basic). Las credenciales actuales viven en LibreDesk/.env y son de
un usuario tipo `agent` con messages:write y conversations:read_all.

Contrato de publicacion verificado con POST real en desarrollo:

    {message, sender_type:"agent", to:[...], echo_id:"jev-retry:<uuid>"}
      -> 200 {data:{status:"pending", type:"outgoing", private:false,
                    content_type:"html", sender_id:2, author.type:"agent",
                    meta:{echo_id, to, send_from}}}

Tres consecuencias medidas que este modulo respeta:

  1. `sender_type` solo admite "agent" o "contact" (cmd/messages.go rechaza lo demas
     y el enum de la BD es ('agent','contact')). No existe "publicar como el IA":
     hub-api firma con su propio usuario. Eso es lo que hace que NO consuma turnos
     de max_turns (count-ai-turns-since-assignment filtra por sender_id).
  2. author.type del mensaje publicado es "agent", nunca "ai_assistant". Por eso el
     filtro D3 corta el bucle sin depender de echo_id.
  3. En email, `to` vacio devuelve 500 "`to` empty". Hay que poblarlo siempre.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("hub-api.libredesk")

# Canales que requieren destinatario explicito en el POST (verificado: email exige
# `to`; whatsapp resuelve el destino desde el contacto).
CHANNELS_NEEDING_TO = ("email",)


@dataclass(frozen=True)
class AssistantConfig:
    """Lo que hub-api necesita del asistente para componer el prompt."""

    assistant_id: int
    name: str
    instructions: str
    guardrails: str
    enabled: bool
    max_turns: int = 0
    user_id: int = 0

    @property
    def usable(self) -> bool:
        return self.enabled


@dataclass
class PublishResult:
    ok: bool
    reason: str
    message_uuid: str | None = None
    status: str | None = None


class LibreDeskClient:
    """Encapsula las cuatro llamadas que usa esta feature."""

    def __init__(self, client: httpx.AsyncClient, *, base_url: str, api_key: str,
                 api_secret: str, timeout_s: float = 20.0,
                 log_request: bool = False) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._auth = (api_key, api_secret)
        self._timeout = timeout_s
        self._log_request = log_request
        self._cache: dict[int, AssistantConfig] = {}

    def _headers(self) -> dict[str, str]:
        # Formato verificado en internal/user/user.go -> ValidateAPIKey y en la
        # documentacion de autenticacion de la API.
        key, secret = self._auth
        return {"Authorization": f"token {key}:{secret}",
                "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, *,
                       json_body: dict[str, Any] | None = None) -> tuple[int, Any]:
        if not self._auth[0] or not self._auth[1]:
            return 0, {"error": "credentials_not_configured"}
        url = f"{self._base}{path}"
        try:
            resp = await self._client.request(
                method, url, json=json_body, headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("libredesk %s %s failed: %s", method, path, exc)
            return 0, {"error": "network_error"}
        try:
            data = resp.json()
        except ValueError:
            return resp.status_code, {"raw": resp.text[:200]}
        return resp.status_code, data

    # --- Lectura ------------------------------------------------------------

    async def get_assistant(self, assistant_id: int) -> AssistantConfig | None:
        """GET /api/v1/ai/assistants/{id}. Cacheado por id (D8: se invalida al reiniciar).

        Requiere permiso ai:manage. Si el asistente fue borrado, LibreDesk responde
        404 (get-assistant hace JOIN con users.deleted_at IS NULL): devolvemos None y
        el pipeline lo trata como fail-closed, coherente con G3.
        """
        cached = self._cache.get(assistant_id)
        if cached is not None:
            return cached

        code, data = await self._request("GET", f"/api/v1/ai/assistants/{assistant_id}")
        if code != 200 or not isinstance(data, dict):
            log.warning("assistant %s unreadable (HTTP %s): %s",
                        assistant_id, code, str(data)[:160])
            return None
        row = data.get("data")
        if not isinstance(row, dict):
            return None

        cfg = AssistantConfig(
            assistant_id=int(row.get("id") or assistant_id),
            name=str(row.get("name") or ""),
            instructions=str(row.get("instructions") or ""),
            guardrails=str(row.get("guardrails") or ""),
            enabled=bool(row.get("enabled")),
            max_turns=int(row.get("max_turns") or 0),
            user_id=int(row.get("user_id") or 0),
        )
        self._cache[assistant_id] = cfg
        return cfg

    async def get_conversation_messages(self, conversation_uuid: str,
                                        page_size: int = 10) -> list[dict[str, Any]]:
        """Historial reciente, para el `state` de JEV (O1: cliente + contexto).

        GET devuelve la pagina mas reciente primero (ORDER BY created_at DESC); se
        invierte para reconstruir el orden cronologico.
        """
        code, data = await self._request(
            "GET",
            f"/api/v1/conversations/{conversation_uuid}/messages?page_size={page_size}",
        )
        if code != 200 or not isinstance(data, dict):
            return []
        # Contract measured against the live API (2026-11-12): this endpoint is the
        # only one that paginates. `data` is an object, not a list:
        #   {"status":"success","data":{"results":[...],"total":2,"per_page":10,
        #    "total_pages":1,"page":1}}
        # Reading data as a list returned [] silently, so JEV got no history and
        # answered `none` on every message -- which looked like a model decision
        # instead of a broken parse. A flat list is still accepted defensively.
        payload = data.get("data")
        if isinstance(payload, dict):
            rows = payload.get("results")
        else:
            rows = payload
        if not isinstance(rows, list):
            log.warning(
                "unexpected messages payload shape for conv=%s: %r",
                conversation_uuid, type(payload).__name__,
            )
            return []
        return [m for m in reversed(rows) if isinstance(m, dict)]

    async def get_conversation(self, conversation_uuid: str) -> dict[str, Any] | None:
        """Cabecera de la conversacion: trae inbox_channel y el contacto.

        Existe por dos limitaciones verificadas:

          - message.created NO incluye canal (V13), y la cache en memoria se pierde
            al reiniciar: si el conversation.created ocurrio antes de arrancar este
            proceso, sin esta lectura no habria prefijo y no se publicaria.
          - En email, `to` vacio devuelve 500 "`to` empty" (medido). El contacto da
            el destinatario cuando meta.to tampoco existe.

        GET /api/v1/conversations/{uuid} requiere conversations:read; verificado que
        responde inbox_channel, inbox_id y contact.email.
        """
        code, data = await self._request(
            "GET", f"/api/v1/conversations/{conversation_uuid}"
        )
        if code != 200 or not isinstance(data, dict):
            log.warning("conversation %s unreadable (HTTP %s)", conversation_uuid, code)
            return None
        row = data.get("data")
        return row if isinstance(row, dict) else None

    # --- Generacion ---------------------------------------------------------

    async def complete(self, prompt_key: str, content: str) -> str | None:
        """POST /api/v1/ai/completion. Devuelve el texto o None si algo fallo.

        Limitacion aceptada (D6/R7): el endpoint recibe UN `content` plano y no
        separa system/user roles; ademas antepone su propio framing de reescritura.
        Usa el proveedor de Completion configurado en LibreDesk, asi hub-api no
        duplica base URL ni modelo ni llaves del LLM.
        """
        body = {"prompt_key": prompt_key, "content": content}
        if self._log_request:
            # The body exactly as serialized and sent. Note this is only what
            # hub-api hands to LibreDesk: the server prepends its own fixed
            # framing ("You are rewriting a support agent's draft reply...")
            # and appends an HTML-output instruction before reaching Nemotron.
            log.info(
                "completion request payload %s",
                json.dumps(body, ensure_ascii=False, sort_keys=True),
            )
        code, data = await self._request(
            "POST", "/api/v1/ai/completion", json_body=body,
        )
        if code != 200 or not isinstance(data, dict):
            log.warning("completion failed HTTP %s: %s", code, str(data)[:200])
            return None
        text = data.get("data")
        if not isinstance(text, str) or not text.strip():
            log.warning("completion returned no usable text: %s", str(text)[:120])
            return None
        return text

    async def copilot(self, *, conversation_uuid: str, message: str,
                      assistant_id: int) -> str | None:
        """POST /api/v1/ai/copilot: generacion con contexto REAL de la conversacion.

        Elegido sobre /ai/completion (medido 2026-11-12): el copilot arma el system
        prompt con la persona completa del asistente (instructions + guardrails del
        admin), el transcript de la conversacion y expone tools -- incluido
        search_articles, que responde por los snippets via help center. Confirmado
        en vivo: respondio el proceso oficial de levantamiento con detalle que NO
        estaba en nuestro prompt. Coste medido: ~4500 prompt tokens, 15 s.

        Limitaciones verificadas:
          - Responde vacio ("The AI returned an empty response") si la instruccion
            se interpreta como pedido de chat; el mensaje debe exigir texto listo
            para el cliente (ver composer.build_correction_instruction).
          - La respuesta llega como fragmento HTML ya envuelto por LibreDesk.
        """
        body = {
            "conversation_uuid": conversation_uuid,
            "message": message,
            "assistant_id": assistant_id,
        }
        if self._log_request:
            log.info("copilot request payload %s",
                     json.dumps(body, ensure_ascii=False, sort_keys=True))
        code, data = await self._request(
            "POST", "/api/v1/ai/copilot", json_body=body)
        if code != 200 or not isinstance(data, dict):
            log.warning("copilot failed HTTP %s: %s", code, str(data)[:200])
            return None
        inner = data.get("data")
        if not isinstance(inner, dict):
            log.warning("copilot unexpected payload: %r", type(inner).__name__)
            return None
        text = inner.get("content")
        status = inner.get("status")
        if not isinstance(text, str) or not text.strip():
            log.warning("copilot returned no usable text (status=%s)", status)
            return None
        if status not in ("completed", "done"):
            log.warning("copilot status=%s content ignored", status)
            return None
        return text


    async def assign_assistant(self, conversation_uuid: str, user_id: int) -> bool:
        """PUT /api/v1/conversations/{uuid}/assignee/user: reasigna al bot.

        Usado por la accion revive-agent-ia cuando el Agente IA se rindio
        (handoff automatico). Efectos verificados en el fuente:
          - UpdateUserAssignee llama HandleConversationEvent() => encola un job
            nuevo del asistente; si hay mensaje del cliente sin contestar, el
            agente retoma la conversacion.
          - El contador de turnos es "since assignment" (count-ai-turns-since-
            assignment), asi que reasignar RESETA los turnos disponibles.
          - Genera actividad visible "Assigned to <bot> by <hub-user>".
        Requiere conversations:update_user_assignee (verificado con la api-key
        del agente id=2: responde 200).
        """
        code, data = await self._request(
            "PUT", f"/api/v1/conversations/{conversation_uuid}/assignee/user",
            json_body={"assignee_id": user_id},
        )
        ok = code == 200 and isinstance(data, dict) and data.get("status") == "success"
        if not ok:
            log.warning("reassign assistant failed conv=%s HTTP %s: %s",
                        conversation_uuid, code, str(data)[:150])
        return ok


    # --- Publicacion --------------------------------------------------------

    async def publish_correction(self, *, conversation_uuid: str, html_body: str,
                                 to: list[str] | None, echo_id: str,
                                 source_id: str | None = None) -> PublishResult:
        """POST /api/v1/conversations/{uuid}/messages como agente propio.

        `echo_id` va en meta (verificado: cmd/messages.go lo copia a meta cuando no
        esta vacio). Sirve como marca visible para humanos y como defensa secundaria
        anti-bucle; la principal sigue siendo D3.
        """
        body: dict[str, Any] = {
            "message": html_body,
            "sender_type": "agent",
            "private": False,
            "echo_id": echo_id,
        }
        if to:
            body["to"] = list(to)
        if source_id:
            body["source_id"] = source_id

        code, data = await self._request(
            "POST", f"/api/v1/conversations/{conversation_uuid}/messages",
            json_body=body,
        )
        if code not in (200, 201) or not isinstance(data, dict):
            reason = str(data)[:200] if isinstance(data, dict) else str(data)[:200]
            log.error("publish failed HTTP %s: %s", code, reason)
            return PublishResult(False, f"http_{code}:{reason}")

        row = data.get("data")
        if not isinstance(row, dict):
            return PublishResult(False, "no_data_in_response")

        status = str(row.get("status") or "")
        uuid = str(row.get("uuid") or "") or None
        # El envio es ASINCRONO: QueueReply inserta con status=pending y un worker
        # lo entrega despues (scan cada 50ms). Un rechazo de canal (p.ej. ventana
        # WhatsApp cerrada) llega despues, via message.updated. Lo registramos tal
        # cual: pending NO es exito confirmado.
        log.info("published conv=%s msg=%s status=%s echo=%s",
                 conversation_uuid, uuid, status, echo_id)
        return PublishResult(True, "accepted", message_uuid=uuid, status=status)
