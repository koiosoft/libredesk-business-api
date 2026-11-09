"""Security: socket-IP allowlist, API key, and LibreDesk webhook HMAC verification.

Central rule: origin identity comes from request.client.host (the TCP handshake), never
from X-Forwarded-For or any other header, because the caller controls those.

Operational note measured on this installation: with Docker Desktop on macOS, traffic
entering a container from the host arrives with Docker's NAT address (192.168.65.x), not
the LAN address. GET /meta/whoami exists to reveal which IP the service actually sees in
a given environment instead of guessing it.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


def client_ip(request: Request) -> str:
    if request.client is None:  # pragma: no cover - only under a fake transport in tests
        return ""
    return request.client.host or ""


def ip_allowed(ip_str: str, settings: Settings) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in settings.networks)


def require_internal_origin(
    request: Request, settings: Settings = Depends(get_settings)
) -> str:
    """Dependency: allowlisted IPs only. Returns the verified IP for logging."""
    ip = client_ip(request)
    if not ip_allowed(ip, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"unauthorized origin: {ip or 'unknown'}",
        )
    return ip


def require_api_key(
    request: Request,
    ip: str = Depends(require_internal_origin),
    settings: Settings = Depends(get_settings),
) -> str:
    """Stacked dependency: allowlisted IP AND correct API key."""
    given = request.headers.get("X-Api-Key", "")
    if not given or not hmac.compare_digest(given, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing api key",
        )
    return ip


def verify_libredesk_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Validate X-Libredesk-Signature: sha256=<HMAC-SHA256 of the raw body>.

    LibreDesk signs the exact payload it sends, so verification must run against raw
    bytes. Re-serializing the parsed JSON changes spacing and key order and breaks it.
    """
    if not secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
