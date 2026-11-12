"""Official LibreDesk API client: read assistant, generate, publish.

ONLY the public API is used. Writing directly into LibreDesk tables is rejected
(plan risk R6: it breaks on every migration).

Authentication verified against the development instance:
    Authorization: token <api_key>:<api_secret>
(Basic is also accepted). Current credentials live in LibreDesk/.env and belong to
a user of type `agent` with messages:write and conversations:read_all.

Publish contract verified with a real POST in development:

    {message, sender_type:"agent", to:[...], echo_id:"jev-retry:<uuid>"}
      -> 200 {data:{status:"pending", type:"outgoing", private:false,
                    content_type:"html", sender_id:2, author.type:"agent",
                    meta:{echo_id, to, send_from}}}

Three measured consequences this module respects:

  1. `sender_type` only accepts "agent" or "contact" (cmd/messages.go rejects the
     rest and the DB enum is ('agent','contact')). There is no "publish as the AI":
     hub-api signs with its own user. That is why it does NOT consume turns of
     max_turns (count-ai-turns-since-assignment filters by sender_id).
  2. author.type of the published message is "agent", never "ai_assistant". That
     is why filter D3 breaks the loop without depending on echo_id.
  3. In email an empty `to` returns HTTP 500 "`to` empty". It must always be populated.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("hub-api.libredesk")

# Channels that require explicit recipients in the POST (verified: email needs
# `to`; whatsapp resolves the destination from the contact).
CHANNELS_NEEDING_TO = ("email",)


@dataclass(frozen=True)
class AssistantConfig:
    """What hub-api needs from the assistant to compose the prompt."""

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
    """Wraps the four calls this feature uses."""

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
        # Format verified in internal/user/user.go -> ValidateAPIKey and in the
        # the API authentication documentation.
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
        """GET /api/v1/ai/assistants/{id}. Cached by id (D8: invalidated on restart).

        Requires permission ai:manage. If the assistant was deleted, LibreDesk answers
        404 (get-assistant JOINs users.deleted_at IS NULL): we return None and
        the pipeline treats it as fail-closed, consistent with G3.
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
        """Recent history for the JEV `state` (O1: customer + context).

        GET returns the newest page first (ORDER BY created_at DESC); it is
        reversed to rebuild chronological order.
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
        """Conversation header: carries inbox_channel and the contact.

        Exists because of two verified limitations:

          - message.created does not include the channel (V13) and the in-memory
            cache is lost on restart: if conversation.created happened before this
            process started, without this read there would be no prefix and nothing
            would publish.
          - In email an empty `to` returns HTTP 500 "`to` empty" (measured). The
            contact supplies the recipient when meta.to is missing too.

        GET /api/v1/conversations/{uuid} requires conversations:read; verified to
        return inbox_channel, inbox_id and contact.email.
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
        """POST /api/v1/ai/completion. Returns the text or None when something failed.

        Accepted limitation (D6/R7): the endpoint takes ONE flat `content` and does
        not separate system/user roles; it also prepends its own rewrite framing.
        It uses the Completion provider configured in LibreDesk, so hub-api does not
        duplicate the base URL, model or LLM keys.
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
        """POST /api/v1/ai/copilot: generation with the REAL conversation context.

        Chosen over /ai/completion (measured 2026-11-12): the copilot builds the
        system prompt server-side from the assistant persona (instructions plus
        guardrails), the conversation transcript and its tools -- including
        knowledge-base search, which is how snippets reach the model without us
        shipping them. Verified live: it recited the official requirements process
        that appeared in no prompt we sent. Measured ~4500 prompt tokens, 15 s.

        Verified limitations:
          - It errors out when the instruction reads like chat; the message must
            demand customer-ready text (composer.build_correction_instruction).
          - The reply arrives already wrapped as an HTML fragment.
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


    async def assign_team(self, conversation_uuid: str, team_id: int) -> bool:
        """PUT /conversations/{uuid}/assignee/team {assignee_id}.

        The revive targets the agent's TEAM, never its user id directly: a bare
        user assignment bypasses LibreDesk automation rules entirely. Assigning
        the team fires EventConversationTeamAssigned and the operator's rule maps
        that team to the AI agent user. Dev mapping verified in DB: team 2
        "Live Ai Agent" -> user 11.
        """
        code, data = await self._request(
            "PUT", f"/api/v1/conversations/{conversation_uuid}/assignee/team",
            json_body={"assignee_id": team_id},
        )
        ok = code == 200 and isinstance(data, dict) and data.get("status") == "success"
        if not ok:
            log.warning("team %s assignment failed conv=%s HTTP %s",
                        team_id, conversation_uuid, code)
        return ok

    # --- Publicacion --------------------------------------------------------

    async def simulate_handoff(self, conversation_uuid: str) -> bool:
        """TEST ONLY: reproduce an assistant handoff through the public API.

        PUT .../assignee/user/remove run with the AGENT's own credentials makes
        LibreDesk treat the actor as the assistant (apiAuth resolves the key
        owner), which posts the private note and unassigns the bot -- exactly what
        the worker does when the model returns nothing. Verified in
        cmd/conversation.go handleRemoveUserAssignee. Never called by the pipeline;
        used by scripts/livechat/turn.mjs in handoff mode.
        """
        code, data = await self._request(
            "PUT", f"/api/v1/conversations/{conversation_uuid}/assignee/user/remove",
            json_body={})
        ok = code == 200 and isinstance(data, dict) and data.get("status") == "success"
        if not ok:
            log.warning("simulated handoff failed conv=%s HTTP %s",
                        conversation_uuid, code)
        return ok

    async def publish_correction(self, *, conversation_uuid: str, html_body: str,
                                 to: list[str] | None, echo_id: str,
                                 source_id: str | None = None) -> PublishResult:
        """POST /api/v1/conversations/{uuid}/messages as our own agent user.

        `echo_id` goes into meta (verified: cmd/messages.go copies it when not
        empty). It serves as a human-visible marker and secondary defense against
        loops; the primary one remains D3.
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
        # Delivery is ASYNCHRONOUS: QueueReply inserts with status=pending and a worker
        # worker delivers it later (50 ms scan). A channel rejection (e.g. the
        # WhatsApp window) arrives afterwards, via message.updated. We record it
        # as-is: pending is NOT confirmed success.
        log.info("published conv=%s msg=%s status=%s echo=%s",
                 conversation_uuid, uuid, status, echo_id)
        return PublishResult(True, "accepted", message_uuid=uuid, status=status)
