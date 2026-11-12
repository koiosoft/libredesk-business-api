"""Shape contract against the real LibreDesk HTTP responses.

The enforcement bug this file prevents: `get_conversation_messages` read `data` as a
list while the live endpoint returns a paginated object. It returned [] silently, JEV
saw no history and answered `none` on every message -- indistinguishable from a
legitimate model decision. Every double in the suite was shaped by my assumption, so
nothing caught it.

These tests feed the VERBATIM response bodies (captured with curl against the dev
instance on 2026-11-12) through httpx.MockTransport, so the parser is exercised
against the wire format instead of against my imagination.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.jev.libredesk import LibreDeskClient

BASE = dict(base_url="http://libredesk.test", api_key="k" * 32, api_secret="s" * 64)

CONV = "cb8e572f-1adf-403d-898f-da33fe57acad"


def client_for(path: str, payload: dict, *, method: str = "GET"):
    """AsyncClient whose only route answers with the captured body."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path, f"called {request.url.path}, expected {path}"
        return httpx.Response(200, json=payload)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Capturas literales de la API real --------------------------------------

MESSAGES_PAGINATED = {
    "status": "success",
    "data": {
        "results": [
            {"id": 59, "uuid": "m-new", "type": "incoming", "sender_type": "contact",
             "private": False, "text_content": "segundo mensaje"},
            {"id": 58, "uuid": "m-old", "type": "incoming", "sender_type": "contact",
             "private": False, "text_content": "URGENTE: sistema caido"},
        ],
        "total": 2, "per_page": 10, "total_pages": 1, "page": 1,
    },
}

ASSISTANT_OBJECT = {
    "status": "success",
    "data": {"id": 1, "user_id": 11, "name": "Test Agent", "enabled": True,
             "instructions": "Habla de tu.", "guardrails": "No prometas plazos.",
             "max_turns": 6},
}

CONVERSATION_OBJECT = {
    "status": "success",
    "data": {"id": 16, "uuid": CONV, "inbox_channel": "email",
             "contact": {"email": "notifications@zohocpaas.com"}},
}

COMPLETION_STRING = {
    "status": "success",
    "data": "<article class=\"reply\">\n  <p>Entiendo la urgencia.</p>\n</article>",
}

PUBLISHED_OBJECT = {
    "status": "success",
    "data": {"id": 61, "uuid": "fe2031ab-6c69-46bb-8557-819ced9ae1a7",
             "type": "outgoing", "status": "pending", "content_type": "html",
             "sender_type": "agent"},
}


@pytest.mark.asyncio
async def test_messages_are_read_from_the_paginated_results_key():
    async with client_for(f"/api/v1/conversations/{CONV}/messages",
                          MESSAGES_PAGINATED) as h:
        ld = LibreDeskClient(h, **BASE)
        rows = await ld.get_conversation_messages(CONV)
    assert [r["uuid"] for r in rows] == ["m-old", "m-new"], \
        "the API returns newest first; chronological order must be restored"


@pytest.mark.asyncio
async def test_flat_list_is_still_accepted_defensively():
    flat = {"status": "success", "data": [{"uuid": "a"}, {"uuid": "b"}]}
    async with client_for(f"/api/v1/conversations/{CONV}/messages", flat) as h:
        ld = LibreDeskClient(h, **BASE)
        rows = await ld.get_conversation_messages(CONV)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_unexpected_shape_is_logged_not_silent(caplog):
    """"data" ni lista ni paginada: debe quedar registro, no un [] mudo.

    The silent [] is what made the original bug look like a JEV decision.
    """
    weird = {"status": "success", "data": "nope"}
    async with client_for(f"/api/v1/conversations/{CONV}/messages", weird) as h:
        ld = LibreDeskClient(h, **BASE)
        rows = await ld.get_conversation_messages(CONV)
    assert rows == []
    assert any("unexpected messages payload shape" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_assistant_object_is_read_directly():
    async with client_for("/api/v1/ai/assistants/1", ASSISTANT_OBJECT) as h:
        ld = LibreDeskClient(h, **BASE)
        cfg = await ld.get_assistant(1)
    assert cfg is not None and cfg.user_id == 11 and cfg.enabled is True


@pytest.mark.asyncio
async def test_conversation_carries_channel_and_contact():
    async with client_for(f"/api/v1/conversations/{CONV}", CONVERSATION_OBJECT) as h:
        ld = LibreDeskClient(h, **BASE)
        row = await ld.get_conversation(CONV)
    assert row["inbox_channel"] == "email"
    assert row["contact"]["email"] == "notifications@zohocpaas.com"


@pytest.mark.asyncio
async def test_completion_returns_a_plain_string():
    async with client_for("/api/v1/ai/completion", COMPLETION_STRING) as h:
        ld = LibreDeskClient(h, **BASE)
        text = await ld.complete("add_empathy", "prompt")
    assert text.startswith("<article")


@pytest.mark.asyncio
async def test_publish_reads_status_and_uuid():
    async with client_for(f"/api/v1/conversations/{CONV}/messages",
                          PUBLISHED_OBJECT) as h:
        ld = LibreDeskClient(h, **BASE)
        res = await ld.publish_correction(conversation_uuid=CONV, html_body="<p>x</p>",
                                          to=["a@b.c"], echo_id="jev-retry:x")
    assert res.ok is True and res.status == "pending"
    assert res.message_uuid == "fe2031ab-6c69-46bb-8557-819ced9ae1a7"
