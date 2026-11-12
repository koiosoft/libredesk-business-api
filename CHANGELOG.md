# Changelog

## [0.2.0] - 2026-11-11
### Added
- **JEV enforcement loop (MVP)**: every public outgoing message authored by an AI agent is classified with JEV Choice (`typesafe/jev-1.14` via OpenRouter `/api/alpha/decisions`) and, when a correction applies, a rewritten reply is generated through LibreDesk's own completion provider and published as an additional message. Nothing is deleted, nothing is reassigned; the agent keeps the conversation.
- `rules/prompts.yaml`, `rules/agents.yaml`, `rules/prompt-augmenter.md`: closed allowlist of actions (with mandatory `none`) and per-assistant/channel prefixes. Loaded once at startup and validated fail-closed — a malformed or incomplete YAML aborts boot. Active version/hash exposed on `GET /meta/config`; `/healthz` stays data-free.
- `app/core/rules.py` (rule loading + hash), `app/core/state.py` (in-memory dedupe, channel cache, per-conversation correction counter), `app/jev/` (`intake`, `classifier`, `composer`, `libredesk`, `pipeline`, `deps`).
- New settings: `CLASSIFIER_URL`, `CLASSIFIER_API_KEY`, `CLASSIFIER_MODEL`, `JEV_MIN_CONFIDENCE`, `JEV_MIN_PROBABILITY`, `JEV_MAX_CORRECTIONS`, `JEV_CONCURRENCY`, `JEV_COMPLETION_PROMPT_KEY`, `HUB_RULES_DIR`.
- Handlers for `conversation.created` (sole source of `inbox_channel`, absent from `message.created`) and durable content-hash dedupe keys so repeated "Send test" clicks no longer collide.
- Test suite grew from 19 to 110 cases: rule contract, intake guards, in-memory state, pipeline orchestration with doubles, and concurrency limits.

### Changed
- **Concurrency model replaced** (not cosmetic): one `threading.Thread(daemon=True)` per event became a background task on FastAPI's event loop, guarded by `asyncio.Semaphore(JEV_CONCURRENCY)`, with references retained and drained on shutdown. Unbounded threads had no ceiling on concurrent LLM calls, cost ~8 MB of stack per idle wait, and silently killed half-finished work on restart — unrecoverable because LibreDesk never retries.
- The 202 acknowledgment still precedes every slow call; nothing but parsing runs before it.
- Webhook path deliberately kept at `/hooks/libredesk`: renaming would drop events permanently, since the URL registered in LibreDesk is the contract.
- `Dockerfile` now copies `rules/` into the image; without it the service aborted at boot.
- `PyYAML` added to `requirements.txt` (present in the image but missing from the manifest) and `pytest-asyncio` to `requirements-dev.txt`.

### Known debt (accepted for the MVP, measured rather than assumed)
- **No persistence table.** An earlier revision added `hub.events`/`hub.corrections`; it was removed by decision, trading D10's durable audit/replay for zero schema-migration surface. Consequences: restart resets the correction counter, single-process only (the Dockerfile pins one worker), and "why wasn't this corrected?" is answered from logs, not SQL.
- **Outbound delivery is asynchronous and unconfirmed.** `POST .../messages` returns `status:"pending"`; channel rejection happens later in LibreDesk's worker. Verified live: WhatsApp free-form fails with *"The 24-hour reply window has closed"* after JEV and the LLM were already paid for. Mitigation deferred: subscribe to `message.updated`.
- **Email requires `to`.** Empty recipients return HTTP 500 `` `to` empty `` (measured). Resolved from `meta.to`, else from the conversation contact.
- **`echo_id` is secondary anti-loop defence.** Only its WebSocket delivery is guaranteed in the source; the real barrier is the intake filter (`author.type == "ai_assistant"` plus `meta.ai_assistant_id`), verified against a live webhook delivery where the hub's own message arrived as `sender_type=agent`.
- **Completion endpoint framing.** `/api/v1/ai/completion` always prepends a "rewrite the draft" instruction and HTML-escapes output, so actions are worded as rewrites. Semantic, not architectural.
- **Template-injection surface mitigated, not eliminated.** Published content passes through Go template rendering; `{{ … }}` is neutralized before sending (verified against `text/template`: `{{.Nombre}}` evaluates, `{{ call .X }}` executes). Deeper hardening pending.
- Publishing as an agent clears `waiting_since` and marks the next-response SLA met — accepted knowingly.
- Classifier parameters (`temperature`, `reasoning`, `max_tokens`) intentionally unset: the model reports `supported_parameters: []` and OpenRouter ignores them silently.
- Thresholds (`0.5` confidence / `0.45` probability) are tuning knobs, not decisions; JEV latency measured ~300 ms and cost ~$0.000027 per classification.

## [0.1.0] - 2026-11-09
### Changed
- **Release v0.1.0**: Initialize the hub-api control plane service: application scaffolding with centralized Pydantic settings and strict fail-closed validation; security enforcement via TCP origin allowlisting, API-key authentication, and HMAC-SHA256 webhook signature verification against raw request bytes; a database layer scoped to a single-UUID deletion domain with dry-run inspection before execution; a LibreDesk webhook receiver pipeline with bounded-memory deduplication, async daemon-thread dispatch, and sub-three-second acknowledgment; and diagnostic endpoints for health checks, client IP resolution, and non-sensitive config reporting. Includes operational readiness assets (restricted single-worker Dockerfile, environment templates, dependency manifests).
