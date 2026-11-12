"""Network diagnostics and service state.

`whoami` exists because of a problem measured on this installation: with Docker Desktop
on macOS, traffic entering the container from the host arrives with Docker's NAT address
(192.168.65.x), not the LAN address (192.168.1.x). Operators who put only their LAN IP in
HUB_ALLOWED_IPS get 403 with no obvious cause. This route reveals the IP the service
actually sees.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.config import get_settings
from app.core.security import client_ip, require_api_key, require_internal_origin
from app.core.state import STATE

router = APIRouter(tags=["meta"])


@router.get("/healthz")
def healthz():
    """No auth, no IP filter: confirms the process is alive. Exposes no data."""
    return {"status": "ok"}


@router.get("/meta/whoami")
def whoami(request: Request, caller: str = Depends(require_internal_origin)):
    """Real origin IP from the TCP handshake, plus the headers the caller sent.

    Headers are echoed back only so they can be compared against `client_ip`, proving
    that access control deliberately ignores X-Forwarded-For.
    """
    settings = get_settings()
    interesting = ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "x-libredesk-signature")
    return {
        "client_ip": client_ip(request),
        "allowlist": [str(n) for n in settings.networks],
        "headers_seen": {k: v for k, v in request.headers.items() if k.lower() in interesting},
        "note": (
            "Access control uses client_ip (TCP handshake). If you expected your LAN IP "
            "and see a Docker NAT address instead, list that range in HUB_ALLOWED_IPS."
        ),
    }


def _rules_summary(rules) -> dict:
    """Version/hash of active rules. No secrets and no prompt text."""
    if rules is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "version": rules.rules_version,
        "hash": rules.rules_hash,
        "actions": sorted(rules.options),
        "agents": {
            str(aid): {
                "name": rule.name,
                "enabled": rule.enabled,
                "channels": sorted(rule.prefixes),
            }
            for aid, rule in sorted(rules.agents.items())
        },
    }


@router.get("/meta/config")
def config_summary(caller: str = Depends(require_api_key)):
    """Configuration state without revealing secrets."""
    s = get_settings()
    from app import main as hub_main

    rules = hub_main.RULES
    return {
        "bind": f"{s.hub_api_bind}:{s.hub_api_port}",
        "allowlist": [str(n) for n in s.networks],
        "api_key_set": True,
        "webhook_secret_set": bool(s.webhook_secret),
        "db_target": f"{s.db_user}@{s.db_host}:{s.db_port}/{s.db_name}",
        "libredesk_api": s.libredesk_base_url,
        "libredesk_api_credentials_set": bool(s.libredesk_api_key and s.libredesk_api_secret),
        "classifier": {
            "url": s.classifier_url,
            "model": s.classifier_model,
            "api_key_set": bool(s.classifier_api_key),
            "log_request": s.classifier_log_request,
        },
        "jev": {
            "min_confidence": s.jev_min_confidence,
            "min_probability": s.jev_min_probability,
            "max_corrections_per_conversation": s.jev_max_corrections,
            "concurrency": s.jev_concurrency,
        },
        "rules": _rules_summary(rules),
        # Volumes of in-memory state (dedupe, channels, corrections). Useful to
        # watch the cache filling up and to detect the day it must move to a
        # shared store.
        "state": STATE.snapshot(),
    }
