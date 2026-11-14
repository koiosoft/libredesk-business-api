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

    # --- JEV (TypeSafe) classifier, served by OpenRouter ---------------------
    # Path verified 2026-11-11: /api/alpha/decisions. The standard chat/completions
    # endpoint REJECTS this model with "typesafe/jev-1.14 is a decisions model and
    # cannot be used with the chat/completions endpoint", so the URL is configurable
    # and is not derived from nemotron's base URL.
    classifier_url: str = Field(
        "https://openrouter.ai/api/alpha/decisions", alias="CLASSIFIER_URL"
    )
    classifier_api_key: str = Field("", alias="CLASSIFIER_API_KEY")
    classifier_model: str = Field("typesafe/jev-1.14", alias="CLASSIFIER_MODEL")
    # Log the exact JSON body sent to JEV before each call, so "what did we ask it"
    # is answerable without reading code. Off by default: `state` contains customer
    # messages, which are personal data and must not land in logs unintentionally.
    classifier_log_request: bool = Field(False, alias="CLASSIFIER_LOG_REQUEST")
    # Deliberately no CLASSIFIER_TEMPERATURE / _REASONING_EFFORT / _MAX_TOKENS:
    # GET /models/typesafe/jev-1.14/endpoints returns supported_parameters: [].
    # Sending them does not error, but OpenRouter silently ignores them.

    # --- Business controls of the enforcement loop ----------------------------
    # Two axes, not one. `confidence` measures how peaked the distribution is, NOT
    # the probability of the chosen option (verified with real data: choice
    # close-forward-human at 0.37 probability returned confidence 0.16).
    # A single confidence threshold (the original suggestion was 0.7) would leave
    # the feature as an obvious-case detector: it discards the ambiguous ones,
    # which is where the value lives. Both axes are required.
    jev_min_confidence: float = Field(0.5, alias="JEV_MIN_CONFIDENCE")
    jev_min_probability: float = Field(0.45, alias="JEV_MIN_PROBABILITY")
    jev_max_corrections: int = Field(3, alias="JEV_MAX_CORRECTIONS")
    jev_concurrency: int = Field(4, alias="JEV_CONCURRENCY")

    # prompt_key from LibreDesk's ai_prompts table used for generation. The
    # /api/v1/ai/completion endpoint requires the key to EXIST (get-prompt fails
    # with notFoundTemplate otherwise). Verified: a fresh install ships only the 6
    # factory prompts (make_friendly, make_concise, ...), none suited for
    # correcting, so a custom one must be created in Admin -> AI -> Prompt editor.
    # Optional at import on purpose (a deployment mid-setup must still boot and
    # serve /healthz): when empty, startup logs a warning (main.py) and each
    # generation falls back to the first prompt returned by GET /api/v1/ai/prompts
    # -- taken as it arrives, no reordering -- logging which key was picked so the
    # omission is visible instead of silent (FEATURE.md D8/G9).
    jev_completion_prompt_key: str = Field("", alias="JEV_COMPLETION_PROMPT_KEY")
    # Log the exact JSON body sent to LibreDesk's completion endpoint (the prompt
    # that reaches Nemotron) before each generation. Off by default: it contains
    # the customer conversation. Same rationale as CLASSIFIER_LOG_REQUEST.
    completion_log_request: bool = Field(False, alias="COMPLETION_LOG_REQUEST")
    # Engine that produces the correction (FEATURE.md D3/G8). False (default):
    # /api/v1/ai/completion with the whole context composed here -- guardrails,
    # snippets and history included, ACCION last. True: /api/v1/ai/copilot, whose
    # server-side persona omits guardrails (verified in aiagent/prompt.go) and
    # which carries persistent chat history between events; kept only as an
    # explicit escape hatch.
    jev_use_copilot: bool = Field(False, alias="JEV_USE_COPILOT")
    # Wall-clock budget for the generation call. Measured: the contextual engine
    # (copilot) needs 15-34 s because LibreDesk rebuilds history, persona and KB
    # search before calling the model; the flat completion path answers in ~2 s.
    # A fixed 20 s cut off generations that would have succeeded (observed as
    # network_error at exactly 20.0 s), so this is configurable per environment.
    jev_generation_timeout_s: int = Field(90, alias="JEV_GENERATION_TIMEOUT_S")
    # Multi-action correction (experimental, opt-in). JEV returns a probability
    # for EVERY criterion; with this on, secondary options join the chosen one in
    # the ACCION block while their running mass stays under JEV_MULTI_PROB_CEILING
    # (the last addition may cross it slightly -- that is intentional: stop when
    # reaching the ceiling, not before). `none` never rides along: it means
    # "publish nothing" and contradicts any action. Texts are ordered ascending by
    # probability so the strongest -- the chosen option -- reads last (positional
    # precedence, G6). Default false: single action, the behavior everything was
    # calibrated with.
    jev_multi_action: bool = Field(False, alias="JEV_MULTI_ACTION")
    jev_multi_prob_ceiling: float = Field(0.6, alias="JEV_MULTI_PROB_CEILING")


    # --- Rules ---------------------------------------------------------------
    # Directory holding prompts.yaml, agents.yaml and prompt-augmenter.md.
    # Relative to the process CWD (/app in the container), where the Dockerfile
    # copies the whole rules/ tree. Convention: rules/example is the committed
    # reference set, rules/dev is this workstation's live policy (gitignored by
    # design, see .gitignore "rules/dev/*"), rules/prod is the reviewed
    # production policy. The DEFAULT must resolve from committed files alone:
    # pointing it at rules/dev makes a fresh clone abort in load_rules with
    # RulesError (only .gitkeep there) before the app can start, which fails
    # silently for anyone who forgets to set the variable. Editing any rule file
    # requires a restart; the loaded hash is exposed on GET /meta/config.
    rules_dir: str = Field("rules/example", alias="PROMPT_AUGMENTER_RULE_PATH")

    @field_validator("libredesk_api_key", "libredesk_api_secret")
    @classmethod
    def _validate_ascii_credentials(cls, v: str) -> str:
        """Credentials travel in an HTTP header, which httpx encodes as ASCII.

        Measured failure: a secret containing U+2026 raised UnicodeEncodeError inside
        httpx on every outbound call -- the pipeline crashed per event instead of
        failing once at boot. Non-ASCII here is always a truncated copy/paste.
        """
        if not v:
            return v
        bad = sorted({c for c in v if ord(c) > 127})
        if bad:
            raise ConfigError(
                "LibreDesk API credentials must be ASCII (they are sent in an HTTP "
                "header); got non-ASCII: %s" % ", ".join("U+%04X" % ord(c) for c in bad)
            )
        return v

    @field_validator("classifier_url")
    @classmethod
    def _validate_classifier_url(cls, v: str) -> str:
        """Without a classifier URL there is no feature: abort instead of degrading."""
        url = v.strip()
        if not url.startswith("https://"):
            raise ConfigError(
                f"CLASSIFIER_URL must be an https:// endpoint, got {v!r}."
            )
        return url

    @field_validator("classifier_api_key")
    @classmethod
    def _validate_classifier_key(cls, v: str) -> str:
        # Consistent with _validate_key: a short key is almost always a truncated
        # copy/paste, and failing at startup costs less than a 401 per event.
        if len(v) < 20:
            raise ConfigError(
                "CLASSIFIER_API_KEY missing or too short (minimum 20). It is the "
                "OpenRouter key; in this stack it is the same value as OPENAI_API_KEY."
            )
        return v

    @field_validator("classifier_model")
    @classmethod
    def _validate_classifier_model(cls, v: str) -> str:
        model = v.strip()
        if "/" not in model:
            raise ConfigError(
                f"CLASSIFIER_MODEL must be an OpenRouter slug (vendor/model), got {v!r}."
            )
        return model

    @field_validator("jev_min_confidence", "jev_min_probability",
                     "jev_multi_prob_ceiling")
    @classmethod
    def _validate_jev_thresholds(cls, v: float) -> float:
        if not 0.0 < v <= 1.0:
            raise ConfigError(f"JEV thresholds must be in (0, 1], got {v}.")
        return v

    @field_validator("jev_max_corrections", "jev_concurrency")
    @classmethod
    def _validate_jev_limits(cls, v: int) -> int:
        if v < 1:
            raise ConfigError(f"JEV limits must be >= 1, got {v}.")
        return v

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

    @property
    def jev_thresholds(self) -> tuple[float, float]:
        """(min_confidence, min_probability). Both must be exceeded to publish."""
        return self.jev_min_confidence, self.jev_min_probability



@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
