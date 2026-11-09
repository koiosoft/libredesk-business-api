"""Service configuration. Fail-closed by design.

If a required variable is missing or malformed, import fails and the container refuses
to start. A deployment that does not come up is preferable to a data-deleting service
listening without origin control.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    # In production these arrive as environment variables injected by the parent
    # compose's env_file (the .env files live in the libredesk repo, not here).
    # Locally they load from .env, which is gitignored, so editors and test runners
    # work without Docker.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Server ------------------------------------------------------------
    hub_api_bind: str = Field("127.0.0.1", alias="HUB_API_BIND")
    hub_api_port: int = Field(8091, alias="HUB_API_PORT")

    # --- Authentication ----------------------------------------------------
    api_key: str = Field("", alias="HUB_API_KEY")

    # Origin allowlist. Comma-separated single IPs or CIDRs.
    allowed_ips: str = Field("", alias="HUB_ALLOWED_IPS")

    # HMAC secret for LibreDesk outbound webhooks (X-Libredesk-Signature: sha256=<hex>).
    # Empty means the webhook receiver rejects everything.
    webhook_secret: str = Field("", alias="HUB_LIBREDESK_WEBHOOK_SECRET")

    # --- LibreDesk PostgreSQL ----------------------------------------------
    db_host: str = Field("db", alias="HUB_DB_HOST")
    db_port: int = Field(5432, alias="HUB_DB_PORT")
    db_name: str = Field("libredesk", alias="HUB_DB_NAME")
    db_user: str = Field("libredesk", alias="HUB_DB_USER")
    db_password: str = Field("", alias="HUB_DB_PASSWORD")

    # --- Official LibreDesk API (for operations it already exposes) --------
    libredesk_base_url: str = Field("http://app:9000", alias="HUB_LIBREDESK_API_URL")
    libredesk_api_key: str = Field("", alias="HUB_LIBREDESK_API_KEY")
    libredesk_api_secret: str = Field("", alias="HUB_LIBREDESK_API_SECRET")

    @field_validator("allowed_ips")
    @classmethod
    def _validate_allowlist(cls, v: str) -> str:
        entries = [e.strip() for e in v.split(",") if e.strip()]
        if not entries:
            raise ConfigError(
                "HUB_ALLOWED_IPS is empty: the service refuses to start without an allowlist."
            )
        for e in entries:
            try:
                net = ipaddress.ip_network(e, strict=False)
            except ValueError as exc:
                raise ConfigError(f"HUB_ALLOWED_IPS invalid entry: {e!r} ({exc})")
            if net.prefixlen == 0:
                raise ConfigError(
                    f"Rejected {e!r}: it covers the entire network and would disable "
                    "origin control."
                )
        return v

    @field_validator("api_key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if len(v) < 24:
            raise ConfigError(
                "HUB_API_KEY missing or too short (minimum 24). Generate with: "
                "openssl rand -hex 32"
            )
        return v

    @property
    def networks(self) -> list:
        return [
            ipaddress.ip_network(e.strip(), strict=False)
            for e in self.allowed_ips.split(",")
            if e.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
