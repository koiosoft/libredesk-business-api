# Changelog

## [Unreleased]
### Added
- Snippet coverage for the JEV decision and the correction: per-option `snippets:` ids in `rules/*/prompts.yaml`, resolved through `GET /api/v1/ai/snippets` (cached by `max(updated_at)`), injected as a dedicated block into both prompts.

### Added
- Multi-action correction (opt-in): when JEV's probability mass is genuinely split, secondary options join the chosen one inside ACCION ordered ascending by probability (chosen last, strongest position); `none` never participates. Controlled by `JEV_MULTI_ACTION` (default false) and `JEV_MULTI_PROB_CEILING` (default 0.6).

### Changed
- Assistant policy (`instructions` + `guardrails`) reaches the classifier unclipped: the 2400-character limit dropped normative clauses and its only justification (cost) measured to fractions of a cent.
- Corrected false documentation claims: LibreDesk DOES expose an authenticated snippets read API; direct SQL reads of `ai_knowledge_base` are now explicitly forbidden in SPEC.md §3.

## [0.3.1] - 2026-11-13
### Changed
- **Release v0.3.1**: chore: update PI agent configuration and documentation infrastructure## [Unreleased]
### Fixed
- **Default rule set no longer points at a gitignored directory.** `PROMPT_AUGMENTER_RULE_PATH` defaulted to `rules/dev`, but `.gitignore` excludes `rules/dev/*` on purpose, so a fresh clone only has `.gitkeep` there and `load_rules()` aborts with `RulesError: prompts.yaml not found` before the app can start. Any deployment that did not set the variable explicitly failed at boot (or, worse, kept running an older image while looking healthy). The default is now `rules/example`, which is committed and complete; `rules/dev` stays local-only by design and production keeps reading `rules/prod` from `compose.prod.yaml`.
- **`Rules.has_post_action()` was missing.** `hooks.handle_unassigned` calls it as the guard for its note-reading fallback, so every `conversation.unassigned` event whose actor was not the bot raised `AttributeError` inside the background task. The webhook still answered 202, so LibreDesk considered the delivery successful while hub-api silently dropped the event. In production this path is frequent: automation rules 4/6/7/8 and the autoassigner reassign conversations constantly.
## [0.2.0] - 2026-11-12
### Changed
- **Release v0.2.0**: ## [0.2.0] - 2026-11-12
### Added
- JEV enforcement loop: public outgoing AI-agent messages are classified with JEV Choice and, when a correction applies, a rewritten reply is generated through LibreDesk's own LLM provider and published as an additional message. Nothing is deleted or reassigned by default.
- Contextual generation via POST /api/v1/ai/copilot (JEV_USE_COPILOT), giving the model real conversation history, the assistant persona and knowledge-base search; the flat completion path remains available behind the flag.
- Handoff detection from conversation.unassigned plus assistant-authored private notes, and declarative post_action revive-assistant that reassigns by team after a successful publish.
- Environment rule sets rules/{example,dev,prod} selected by PROMPT_AUGMENTER_RULE_PATH, loaded once at boot and validated fail-closed; active hash exposed on GET /meta/config.

### Changed
- Classifier state now carries the mandatory turn-structure clause and the assistant policy so actions are judged against a stated contract.
- Concurrency moved from one thread per event to asyncio tasks bounded by a semaphore; the 202 acknowledgment still precedes every slow call.
- LibreDesk API credentials must be ASCII (they travel in an HTTP header); non-ASCII aborts startup instead of failing per event.
- Generation timeout is configurable (copilot measured 15-34 s).

### Fixed
- Paginated message responses were read as a list, silently returning no history so JEV answered none on every message.
- Raw inbox channel (whatsapp) bypassed prefix normalization, discarding valid corrections after paying for classification and generation.## [0.2.0] - 2026-11-11
### Added
- **JEV enforcement loop (MVP)**: every public outgoing message authored by an AI agent is classified with JEV Choice (`typesafe/jev-1.14` via OpenRouter `/api/alpha/decisions`) and, when a correction applies, a rewritten reply is generated through LibreDesk's own completion provider and published as an additional message. Nothing is deleted, nothing is reassigned; the agent keeps the conversation.
- `rules/prompts.yaml`, `rules/agents.yaml`, `rules/prompt-augmenter.md`: closed allowlist of actions (with mandatory `none`) and per-assistant/channel prefixes. Loaded once at startup and validated fail-closed — a malformed or incomplete YAML aborts boot. Active version/hash exposed on `GET /meta/config`; `/healthz` stays data-free.
- `app/core/rules.py` (rule loading + hash), `app/core/state.py` (in-memory dedupe, channel cache, per-conversation correction counter), `app/jev/` (`intake`, `classifier`, `composer`, `libredesk`, `pipeline`, `deps`).
- New settings: `CLASSIFIER_URL`, `CLASSIFIER_API_KEY`, `CLASSIFIER_MODEL`, `JEV_MIN_CONFIDENCE`, `JEV_MIN_PROBABILITY`, `JEV_MAX_CORRECTIONS`, `JEV_CONCURRENCY`, `JEV_COMPLETION_PROMPT_KEY`, `PROMPT_AUGMENTER_RULE_PATH`.
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
