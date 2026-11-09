"""Security contract tests.

These cover the rules that protect a data-deleting service: origin allowlist, API key,
webhook HMAC, fail-closed configuration and input validation. None of them touch a database.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from tests.conftest import TEST_KEY, TEST_WEBHOOK_SECRET

UUID = "c35890f5-9771-41e9-b2df-d1fc83adb707"


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_event(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/hooks/libredesk",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Libredesk-Signature": _sign(body, TEST_WEBHOOK_SECRET),
        },
    )


# --- Origin control -------------------------------------------------------

def test_unlisted_ip_is_rejected(outside_client):
    """A caller outside the allowlist gets 403 even with a valid API key."""
    r = outside_client.get("/meta/whoami", headers={"X-Api-Key": TEST_KEY})
    assert r.status_code == 403
    assert "unauthorized origin" in r.json()["detail"]


def test_listed_ip_is_accepted(client):
    r = client.get("/meta/whoami", headers={"X-Api-Key": TEST_KEY})
    assert r.status_code == 200
    assert r.json()["client_ip"] == "10.1.2.3"


def test_healthz_needs_no_auth(client):
    assert client.get("/healthz").status_code == 200


def test_forged_forwarded_header_does_not_grant_access(outside_client):
    """Access control reads the socket IP; X-Forwarded-For must be irrelevant."""
    r = outside_client.get(
        "/meta/whoami",
        headers={"X-Api-Key": TEST_KEY, "X-Forwarded-For": "10.1.2.3"},
    )
    assert r.status_code == 403


# --- API key --------------------------------------------------------------

def test_missing_api_key_is_401(client):
    r = client.get(f"/conversations/{UUID}")
    assert r.status_code == 401


def test_wrong_api_key_is_401(client):
    r = client.get(f"/conversations/{UUID}", headers={"X-Api-Key": "nope-nope-nope-nope"})
    assert r.status_code == 401


# --- Fail-closed configuration -------------------------------------------

@pytest.mark.parametrize(
    "key_value,allow_value",
    [
        (TEST_KEY, ""),                # empty allowlist
        (TEST_KEY, "0.0.0.0/0"),       # allowlist covering everything
        (TEST_KEY, "not-an-ip"),       # malformed entry
        ("short", "127.0.0.1"),       # api key shorter than 24 chars
    ],
)
def test_insecure_config_refuses_to_start(monkeypatch, key_value, allow_value):
    from app.core.config import Settings

    monkeypatch.setenv("HUB_API_KEY", key_value)
    monkeypatch.setenv("HUB_ALLOWED_IPS", allow_value)
    with pytest.raises(Exception):
        Settings()


# --- Webhook signature -----------------------------------------------------

def test_webhook_without_signature_is_rejected(client):
    body = json.dumps({"event": "message.created", "timestamp": "t"}).encode()
    r = client.post("/hooks/libredesk", content=body,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 403


def test_webhook_with_bad_signature_is_rejected(client):
    body = json.dumps({"event": "message.created", "timestamp": "t"}).encode()
    r = client.post("/hooks/libredesk", content=body,
                    headers={"Content-Type": "application/json",
                             "X-Libredesk-Signature": "sha256=deadbeef"})
    assert r.status_code == 403


def test_webhook_from_outside_is_rejected_before_signature_check(outside_client):
    """Origin is checked first: an unlisted host never reaches signature verification."""
    r = outside_client.post("/hooks/libredesk", content=b"{}",
                            headers={"Content-Type": "application/json",
                                     "X-Libredesk-Signature": "sha256=x"})
    assert r.status_code == 403


def test_webhook_with_valid_signature_is_accepted(client):
    payload = {"event": "message.created", "timestamp": "2026-01-01T00:00:00Z",
               "payload": {"uuid": "m-1", "conversation_uuid": "conv-1",
                           "type": "outgoing", "sender_type": "agent",
                           "private": True, "meta": {"ai_assistant_id": 2}}}
    r = _post_event(client, payload)
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_duplicate_event_is_deduplicated(client):
    payload = {"event": "conversation.assigned", "timestamp": "same-ts",
               "payload": {"conversation_uuid": "dup-1", "assigned_to": 22}}
    first = _post_event(client, payload)
    second = _post_event(client, payload)
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate_ignored"


def test_unknown_event_is_still_accepted(client):
    """Unknown events are acknowledged: rejecting them would not trigger a retry anyway."""
    r = _post_event(client, {"event": "some.future.event", "timestamp": "t2", "payload": {}})
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_malformed_json_is_400(client):
    body = b"{not json"
    r = client.post("/hooks/libredesk", content=body,
                    headers={"Content-Type": "application/json",
                             "X-Libredesk-Signature": _sign(body, TEST_WEBHOOK_SECRET)})
    assert r.status_code == 400


# --- Input validation ------------------------------------------------------

def test_invalid_uuid_is_400(client, key_headers):
    r = client.delete("/conversations/not-a-uuid", headers=key_headers)
    assert r.status_code == 400


def test_invalid_uuid_on_read_is_400(client, key_headers):
    r = client.get("/conversations/zzzz", headers=key_headers)
    assert r.status_code == 400
