# SOFTWARE DESIGN DOCUMENT (SDD) — libredesk-business-api

> Scope: project-local only. This document describes the software project
> itself: objective, architecture, components, data, quality standards.
> It does NOT describe SDD protocols or orchestrators — those live under
> `.sdd/core/dev-cycle/` and `.sdd/protocols/`.

## 1. SYSTEM OBJECTIVE

### 1.1 Purpose Statement

A control-plane service that keeps an AI sales agent honest. It watches the public
messages an AI assistant publishes inside LibreDesk, asks a JEV (TypeSafe) choice
model whether each reply deviates from the business policy the operator wrote for
that assistant, and when it does, generates a corrected answer through LibreDesk's
own configured LLM provider and appends it to the conversation as an extra, clearly
labelled message. It exists because an agent that drifts from its commercial
protocol damages deals silently, and nobody was watching. Nothing is deleted,
nothing is reassigned by default, and no customer data is stored.

### 1.2 High-Level Technical Objectives

- Fail closed everywhere: unreadable config, incomplete rules, classifier outage or
  ambiguous verdict all mean "publish nothing", never "publish anyway".
- Never let the customer channel see machine-generated noise: corrections are additive
  and labelled, and the loop cannot consume its own output.
- Reuse the platform instead of duplicating it: generation goes through LibreDesk so
  base URL, model, credentials and knowledge-base search stay in one place.
- Bound every cost: concurrency semaphore, per-conversation correction cap, clipped
  prompt blocks, dual thresholds on classification confidence.
- Keep deployment state auditable without a database: content hash of the loaded rule
  set exposed on `GET /meta/config`, structured reason on every rejection.

## 2. ARCHITECTURE AND DESIGN RULES

Style: single-worker FastAPI service, stateless with respect to persistence, running
as a sibling container inside the LibreDesk compose stack.

```
   LibreDesk (app)                         OpenRouter
  ┌────────────────┐                    ┌──────────────────┐
  │ ai_providers   │  HTTP Basic        │ jev-1.14         │ ← classifier (direct)
  │ ai_prompts     │◀──completion/copilot│ TypeSafe        │
  │ ai_assistants  │                    ├──────────────────┤
  │ conv_messages  │──webhook HMAC─────▶│ nemotron-3.5     │ ← generator (via LibreDesk)
  └───────▲────────┘                    └──────────────────┘
          │ official REST API                    ▲
  ┌───────┴──────────────────────────────────────┴─────────┐
  │ hub-api                                                │
  │ routers/hooks.py → intake guards → run_guarded(sem)    │
  │      → pipeline: history → state → classify → generate │
  │        → sanitise → publish → optional post_action     │
  │ core/rules.py (boot) · core/state.py (RAM) · deps.py   │
  └────────────────────────────────────────────────────────┘
```

Dependency direction: `routers → jev → core`. `core` imports nothing from `jev`. The
service owns no table; durable audit is out of scope by decision (§3).

### 2.1 Dependency and Environment

- Python 3.12 (`python:3.12-slim`), FastAPI + uvicorn, httpx, pydantic-settings, PyYAML,
  psycopg 3 (read-only inspection endpoint only).
- Isolation: `.venv/` locally, non-root user inside the image, **one** uvicorn worker —
  dedupe, channel cache and correction counters live in process memory.
- Entry point: `uvicorn app.main:app --host 0.0.0.0 --port 8091 --workers 1`. Locally,
  always through `.venv/bin/python`; the system interpreter has no project dependencies.
- External tools relied upon: `docker` / `docker compose` (the service runs in the
  LibreDesk stack and its API is the only supported way to read assistants and publish
  messages), `git` plus `scripts/git/*` for release. Absence is a hard stop.
- Runtime file contracts: the three files of a rule set (§5 of CONVENTIONS, §3 here).
  Missing or malformed → `RulesError` before the app can serve.

### 2.2 Project Topology and Directory Structure

```
app/
├── main.py               # lifespan: settings validation, rule load, shared clients, ordered shutdown
├── core/                 # config.py · rules.py · state.py · security.py · db.py
├── jev/                  # intake.py · classifier.py · composer.py · libredesk.py · pipeline.py · deps.py
└── routers/              # hooks.py (webhook) · meta.py (introspection) · cleanup.py (separate deletion domain)
rules/
├── example/              # STATIC reference: README + the three contract files; also the boot default
├── dev/                  # OWNED, gitignored: this workstation's live policy (.gitkeep only in git)
└── prod/                 # OWNED, versioned: reviewed production policy, pinned by compose.prod.yaml
tests/                    # pytest suite; contract tests build fixture YAML, never read dev/prod
scripts/
├── git/                  # release tooling (see .sdd/core/git/)
├── livechat/             # Playwright harnesses: turn.mjs (single turn), probe.mjs (scripted run)
└── grab-logs.py          # dumps the exact JEV and generation payloads from container logs
.sdd/                     # SDD workspace (its own static/owned split, documented below)
Dockerfile                # copies rules/ wholesale; single worker
requirements*.txt         # runtime vs test-only manifests
.env.example              # documented variable surface, no secrets
```

Lifecycle classes for the SDD workspace under `.sdd/`:

```
.sdd/
├── templates/            # STATIC — replaced by init/update
├── protocols/            # STATIC — generic agent/tool protocols
├── compiled/             # STATIC — compiled agents, tools, use-cases, models
├── harness/              # STATIC — pi harness (agents, prompts, roles, extensions)
├── skills/               # STATIC — skill catalogue
├── context-policies/     # policy catalogues resolved by the evaluator
├── core/                 # OWNED — this SPEC.md, CONVENTIONS.md, git/COMMITS.md
├── inputs/               # OWNED — REQUIREMENTS.md, FOLLOW_UP.md
├── plans/                # OWNED — plan sources
├── instructions/         # OWNED — destination `generate` writes into
└── logs/                 # OWNED — cycle history; never deleted by init
```

Everything under a STATIC root is regenerated from the bundle on `update`, so hand
edits there are lost. Everything under an OWNED root survives untouched and is never
shipped as real content by the template.

### 2.3 Operational Contract (HTTP surface)

This project exposes no CLI; its operational surface is HTTP plus release scripts.

- `POST /hooks/libredesk` — webhook receiver. Origin allowlist on the TCP peer, HMAC-SHA256
  over raw body bytes, answers `202 Accepted` before any slow call. Events consumed:
  `message.created`, `message.updated`, `conversation.created`, `conversation.assigned`,
  `conversation.unassigned`, `conversation.status_changed`.
- `GET /healthz` — liveness. No configuration, no data.
- `GET /meta/config` — requires `X-Api-Key`. Exposes rule hash and action list, thresholds,
  credential booleans and in-memory state volumes. Never values, never prompt text.
- `GET /meta/whoami` — reports the IP the service actually sees, used to fix the allowlist.
- `GET|POST /conversations/{uuid}` — separate single-UUID deletion domain (dry-run unless
  `execute=true`); unrelated to the enforcement loop.
- Release lifecycle: `scripts/git/get_tag_logs.sh` → `update_changelog.sh <TAG> "<summary>"`
  → `sync_stable.sh` → `create_tag.sh <patch|minor|major>` → push `main stable --follow-tags`.
  Only `stable` is deployed. Rules for commit messages and tagging are owned by
  `.sdd/core/git/COMMITS.md`; they are not restated here.

## 3. DATA DESIGN AND PERSISTENCE

- **Nothing is persisted by this service.** No table, no migration, no schema of its own.
  State lives in `app/core/state.py`: bounded dedupe keys (LRU), per-conversation channel
  cache, per-conversation correction counter, handoff flags. Restart clears all of it.
- Accepted consequences, recorded rather than hidden: restart resets the correction cap;
  the service is single-process by construction; "why wasn't this corrected?" is answered
  from structured logs, not SQL. If it ever scales horizontally, that state moves to Redis
  or a table with a UNIQUE constraint.
- Configuration: every knob is an environment variable validated at import in
  `app/core/config.py` (see `.env.example`). Defaults are safe: rules resolve to a committed
  directory, logging flags off, copilot engine on, thresholds conservative.
- Rule sets are the project's input artefacts, selected by `PROMPT_AUGMENTER_RULE_PATH`:
  `rules/example` (STATIC reference and boot default), `rules/dev` (OWNED local, gitignored),
  `rules/prod` (OWNED, versioned, reviewed like code). Editing any rule file requires a
  restart; the loaded hash on `/meta/config` is the proof of what is active.
- Output artefacts: the published correction message (lives in LibreDesk, not here) and the
  payload dumps produced by `scripts/grab-logs.py` for review, which contain customer text
  and must be treated as sensitive.

## 4. CORE COMPONENTS

### 4.1 Webhook ingress (`app/routers/hooks.py`)
- **Purpose:** authenticate, acknowledge fast, dispatch, and record why anything was refused.
- **Location:** `app/routers/hooks.py`, guards in `app/jev/intake.py`.
- **Trigger:** LibreDesk delivery to `POST /hooks/libredesk`.
- **Process:** TCP-origin allowlist → HMAC over raw bytes → dedupe key (event + message UUID,
  falling back to a body hash so repeated "Send test" clicks do not collide) → pure intake
  guards → background task under the semaphore. `conversation.unassigned` additionally flags
  an abandonment when the actor is the bot's own user, with a fallback that reads recent
  private notes for an assistant-authored handoff message.
- **Error Handling:** the 202 precedes every slow call; task failures are logged and swallowed
  so a crash cannot look like a delivery failure to LibreDesk (which never retries).
- **Lifecycle:** code only, no data. Preserved across updates.

### 4.2 Rule loader (`app/core/rules.py`)
- **Purpose:** turn operator-authored YAML into an immutable, validated policy object and
  prove which version is running.
- **Location:** `app/core/rules.py`; consumed once in `app/main.py` lifespan.
- **Trigger:** process start.
- **Process:** read the three files of the selected set, enforce the contract (`none` present,
  non-empty descriptions, known channels, integer ids, known `post_action` values, extended
  `{text, post_action}` shape), compute a SHA-256 over name+bytes of all three, expose
  `action_text()`, `post_action()`, `has_post_action()`, `agent()`, `is_evaluable()`.
- **Error Handling:** any violation raises `RulesError` before the app can serve. There is no
  partial-policy mode.
- **Lifecycle:** `rules/prod` is versioned and reviewed; `rules/dev` is local and gitignored.
  The boot default must resolve to a committed directory — pointing it at an ignored one made
  a fresh clone fail at startup.

### 4.3 Classifier client (`app/jev/classifier.py`)
- **Purpose:** ask the JEV choice model whether a reply deviates, and translate its answer into
  a go/no-go decision expressed as data.
- **Location:** `app/jev/classifier.py`.
- **Trigger:** one call per accepted message, direct to OpenRouter's decisions endpoint.
- **Process:** build `{model, state, questions.action:{type:"choice",instructions,criteria}}`;
  criteria are the YAML options verbatim, minus `handoff-too-early` when no abandonment was
  observed (presenting it always biases the model toward deriving instead of rewriting).
  Parse `answers.action` and require **both** axes above threshold: `confidence` measures how
  peaked the distribution is, `probability` how likely the chosen option — measured divergence
  0.37 probability against 0.16 confidence, so one threshold alone is not enough.
- **Error Handling:** network error, non-200, missing decision or unparsable body all return
  `should_act=False` with an explicit reason. Never raises to the caller.
- **Lifecycle:** stateless. Tuning knobs (`temperature`, `max_tokens`) are deliberately not sent:
  the model advertises `supported_parameters: []` and the gateway ignores them silently.

### 4.4 Prompt composer (`app/jev/composer.py`)
- **Purpose:** assemble what the classifier sees and what the generator is told, and make the
  published text safe.
- **Location:** `app/jev/composer.py`.
- **Trigger:** called by the pipeline between fetch and publish.
- **Process:** classifier `state` = mandatory turn-structure clause quoted from the assistant's
  guardrails + policy header (clipped ~2400 chars each) + chronological non-private turns with
  the reply under review last and never duplicated. Generator instruction states only what to
  fix, because the copilot engine rebuilds context server-side. Output sanitising: HTML tag
  allowlist after decoding nested entities, event handlers stripped, and Go template braces
  neutralised because staff content is rendered through `text/template`.
- **Error Handling:** empty or unusable results return falsy values the pipeline aborts on.
- **Lifecycle:** product-facing prompt text stays in Spanish (business language); code comments
  and identifiers stay in English.

### 4.5 Enforcement pipeline (`app/jev/pipeline.py`)
- **Purpose:** order the stages so money is spent as late as possible and nothing publishes on
  any doubt.
- **Location:** `app/jev/pipeline.py`, bounded by `app/jev/deps.run_guarded`.
- **Trigger:** one accepted `message.created`.
- **Process:** assistant persona → history → state → classify → correction-cap reservation
  (**before** generating) → generate → sanitise → resolve channel and prefix → publish →
  optional post-action. Channel comes from `conversation.created` or, after a restart, from
  reading the conversation header; it is normalised because `whatsapp` and `livechat` both map
  to the `chat` prefix key.
- **Error Handling:** every early exit returns a machine-readable reason; no exception escapes.
- **Lifecycle:** in-memory only.

### 4.6 LibreDesk client (`app/jev/libredesk.py`)
- **Purpose:** the only door to the platform — read assistant, read history, read conversation
  header, generate, publish, reassign team.
- **Location:** `app/jev/libredesk.py`.
- **Trigger:** pipeline stages and the test harness.
- **Process:** HTTP Basic with token form credentials; assistant config cached by id; paginated
  responses unwrapped from `data.results`; publication as the hub's own `agent` user carrying
  `echo_id=jev-retry:<origin uuid>`.
- **Error Handling:** unexpected payload shapes log a warning instead of returning a silent empty
  list — that silence previously made the classifier answer `none` on every message while looking
  legitimate. Generation timeout is configurable because copilot measures 15–34 s.
- **Lifecycle:** stateless besides the assistant cache.

### 4.7 Post-actions (`revive-assistant`)
- **Purpose:** restore an agent that gave up, when the operator's policy says so.
- **Location:** declared in `prompts.yaml`, executed in `pipeline.py`, implemented as
  `LibreDeskClient.assign_team`.
- **Trigger:** only after a successful publish, and only for options declaring the effect.
- **Process:** `PUT /api/v1/conversations/{uuid}/assignee/team {assignee_id: revive_team_id}`.
  Assignment targets the **team**, never a bare user id: assigning a user bypasses the
  automation engine, while a team change fires `conversation.team.assigned` and lets the
  operator's rule assign the bot. On success the handoff flag is cleared.
- **Error Handling:** missing `revive_team_id` logs a warning and skips; the correction already
  published stands on its own. Requires the mirror automation rule to exist in the target
  workspace, otherwise the PUT succeeds and nothing returns — verified in production with
  rule `Revive AI Agent on team assignment`.
- **Lifecycle:** depends only on in-memory flags.

## 5. CODING AND QUALITY STANDARDS

- Language-level rules, logging, error handling and file contracts: see
  `.sdd/core/CONVENTIONS.md`.
- Pre-flight checks performed at startup: settings validators (credential lengths, ASCII-only
  LibreDesk credentials because they travel in an HTTP header, https-only classifier URL,
  thresholds in range, allowlist refusing `0.0.0.0/0`) then rule-set validation. Any failure
  aborts the boot.
- Tests: pytest + pytest-asyncio (`asyncio_mode = auto`), no network, no database, no LibreDesk
  instance. Contract tests build minimal YAML in `tmp_path` and never read `rules/dev` or
  `rules/prod`; wire-format regressions are fed verbatim captured responses. Run with
  `.venv/bin/python -m pytest`.
- Canonical status vocabulary for pipeline outcomes — these are **results**, not queue states:
  `corrected` (published), `skipped` (classifier declined or threshold missed), `ignored`
  (guard rejected before spending), `failed` (generation or publication error). Acceptance of a
  feature is a review verdict, decided outside this service.

## 6. OPERATIONAL STATE AND OPEN ITEMS

Deployed: production runs the enforcement loop end to end — classification, contextual
generation, additive labelled publication, anti-loop echo marker.

Open by decision, not oversight:

- Thresholds (`JEV_MIN_CONFIDENCE=0.5`, `JEV_MIN_PROBABILITY=0.45`) are calibrated on
  development traffic. Recalibrate only against a sample of real cases.
- No correction has yet been observed on a genuine lead message; the published case came
  from a synthetic test conversation. The code path is identical.
- Channel delivery is unconfirmed: publication returns `status=pending` and rejection
  arrives later through `message.updated`, which is logged but not reconciled.
- Knowledge-base snippets reach the generator (through its tools) but not the classifier:
  LibreDesk exposes no public read API for them.
- In-memory state forces a single worker. Horizontal scaling requires moving dedupe,
  channel cache, correction counters and handoff flags to Redis or a UNIQUE-backed table.
