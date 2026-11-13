---
name: libredesk-business-api-project
description: Build and maintain libredesk-business-api (hub-api), the FastAPI service that enforces JEV-classified corrections on LibreDesk AI-agent messages. Use this skill whenever working in this repository: to locate code through the retrieval cascade, to run or extend the test suite, to change the rule sets under rules/, to release a version, or to operate against the live development stack. It records the project-specific constraints that CONVENTIONS.md and SPEC.md assume you already know, plus the MCP tools this project expects you to use.
---

# Current project — hub-api operations

## Authoritative documentation — read it when the task touches its subject

This skill is operational only. The project's contracts live in `.sdd/core/`, and each
file below is the single source of truth for its area. Open the one that matches the task
before changing anything it governs; do not infer from this skill's summary.

| Document | Read it when the task involves | What it decides |
|---|---|---|
| `.sdd/core/SPEC.md` §1–2 | purpose, architecture, layer boundaries, dependency direction, directory lifecycle (STATIC vs OWNED), HTTP surface | what the system is and where a change may live |
| `.sdd/core/SPEC.md` §3 | persistence questions, why there is no table, what survives a restart, rule-set artefacts | data design and its accepted consequences |
| `.sdd/core/SPEC.md` §4 | any component edit: ingress, rule loader, classifier, composer, pipeline, LibreDesk client, post-actions | per-component purpose, trigger, process and error contract |
| `.sdd/core/CONVENTIONS.md` §1–2 | writing or reviewing code: typing policy, frozen dataclasses, naming, English-vs-Spanish boundary, import direction | how code must be written here |
| `.sdd/core/CONVENTIONS.md` §4 | logging, exception handling, "fail closed" decisions, what may never be logged | error policy and startup checks |
| `.sdd/core/CONVENTIONS.md` §5 | touching `rules/*/prompts.yaml`, `agents.yaml` or `prompt-augmenter.md` | the three-file contract and its gatekeeper |
| `.sdd/core/CONVENTIONS.md` §6 | anti-loop behaviour, intake conditions, concurrency model, generation engines, sanitisation, revive semantics | domain invariants that must not regress |
| `.sdd/core/CONVENTIONS.md` §7 | adding or changing tests, fixtures, wire-format regression tests | testing rules that keep CI meaningful |
| `.sdd/core/git/COMMITS.md` | composing any commit message | type/scope/subject format and secret scanning duty |
| `.sdd/core/git/RELEASE.md` | releasing, tagging, syncing `stable` | the ordered release procedure and its gates |
| `.sdd/inputs/FOLLOW_UP.md` | resuming work after a pause: what is open by decision, thresholds not yet calibrated, known gaps and process lessons | current state of the feature and what must not be re-litigated |
| `.sdd/inputs/REQUIREMENTS.md` | scope questions — whether something belongs in this service at all | agreed requirements and explicit exclusions (no new tables, no route renames) |

A change that contradicts one of these documents does not ship. Update the document in the
same branch, with the owner's agreement, or leave the code alone.

## 1. Retrieval: follow the cascade, do not grep blindly

Tier 1 is the pi tool surface, for exact-name and structural lookups:
`find_symbol`, `file_outline`, `find_references`, `grep` (anchored results you can edit
without re-reading), `replace_in_symbol`, `move_symbol`.

Tier 2 is **jcodemunch** (`order`, `menu`, `route`) and **codebase-memory** (`cbm_*`).
Route every "where is X defined", "who calls Y" and "context for this change" lookup
through them instead of chained reads. Call `get_ranked_context` first: it answers in one
call and costs about 4% of the tokens of reading source files. When their tools are absent
from your list, index the repo with `cbm_index_repository`, or run `cbm_connect` before
using `mcp__jcodemunch__*`.

Tier 3, full `read`, only as the cascade prescribes — for a span you intend to edit.

Do not open a second file to answer one lookup. Switch to Tier 2.

## 2. MCP surfaces

| Server | When to reach for it |
|---|---|
| `libredesk-docs` | Webhook delivery semantics, HMAC signing, AI provider config, automation-rule behaviour. Search first, then read the page path it returns; report doc problems with its feedback tool. |
| `context7` | Third-party library specifics (FastAPI lifespan, pydantic-settings validation, httpx timeouts). Resolve the library id before querying. |
| `knowledge_search` | Indexed reference material when a KB is loaded; prefer `knowledge_symbol_search` for exact symbols or config keys. |
| Kanboard (token in `.pi/mcp.json`) | Task state and coordination with the DevOps agent. Read the full comment thread before stating any status. Write decisions there; never write credentials. |

## 3. Working environment

- Run everything through the project venv: `.venv/bin/python`, `.venv/bin/pytest`. The
  system Python has no dependencies installed and will fail confusingly.
- Tests: `.venv/bin/python -m pytest` (expect ~143 passing, no network, no database).
  asyncio mode is `auto`; do not add `@pytest.mark.asyncio` decorations.
- The live development stack is Docker Compose owned by the sibling `LibreDesk` checkout:
  ```bash
  cd ../LibreDesk
  docker compose -f compose.yaml -f compose.dev.yaml --env-file .env.build \
    --env-file .env.local build api-hub
  docker compose -f compose.yaml -f compose.dev.yaml --env-file .env.build \
    --env-file .env.local up -d api-hub
  ```
  Pass both env files: `.env.build` supplies values interpolated into
  `compose.yaml` (encryption key, passwords); omitting it produces blank-variable
  warnings and a container that fails validation at boot.
- Service endpoints while running: `GET :8091/healthz`, `GET :8091/meta/config`
  (needs `X-Api-Key`). Logs: `docker logs koiosoft_api_hub`.
- Editing rules requires a restart: they load once at boot. Confirm what is active with
  the hash on `/meta/config`, never by reading the file and assuming.

## 4. Changing the enforcement behaviour safely

The policy lives in YAML, not code. A rule set is exactly three files
(`prompts.yaml`, `agents.yaml`, `prompt-augmenter.md`) inside `rules/example`,
`rules/dev` or `rules/prod`, selected by `PROMPT_AUGMENTER_RULE_PATH`.

- Keys in `agents.yaml` are `ai_assistants.id`, **never** the bot's `user_id`. Getting
  this wrong fails closed: nothing is evaluated, and the log says `agent_not_allowlisted`.
- Every option needs an observable condition, not an intent. "Asks two or more questions"
  is decidable and measured at confidence 0.98; "did not engage properly" was silently
  discarded at 0.26. Prefer countable wording.
- Options may take the extended form `{text, post_action}`; the only valid `post_action`
  today is `revive-assistant`, which fires **after** a successful publish and reassigns by
  team. It needs a mirror automation rule in the target workspace or it succeeds quietly
  and does nothing.
- `none` is mandatory; without it publishing becomes the default and startup aborts.
- Verify every rule-set edit by loading it:
  ```bash
  .venv/bin/python -c "from app.core.rules import load_rules; \
  r=load_rules('rules/prod'); print(r.rules_hash, sorted(r.options), r.post_actions)"
  ```
- Contract tests must not read `rules/dev` or `rules/prod`: those change live on purpose.
  Build minimal YAML in `tmp_path` (helpers in `tests/conftest.py`).

## 5. Debugging a loop that "does nothing"

Order that has found every real cause so far:

```bash
docker logs koiosoft_api_hub --since 15m | grep -E "entering pipeline|ignored reason|jev decision|pipeline result|published"
```

- No `message.created entering pipeline` at all → webhook never arrived: allowlist,
  signature, or the event list on the LibreDesk webhook record.
- `agent_not_allowlisted` → id missing from the active `agents.yaml` (check the hash).
- `jev_said_none` / `low_confidence` → correct behaviour, thresholds or option wording.
- `no_prefix_for_channel:<x>` → channel resolved but no prefix declared; note that raw
  `whatsapp`/`livechat` must normalise to `chat`.
- `generation_empty` → check whether the model spent its output budget reasoning: OpenRouter
  shows `finish_reason=length` with `completion_tokens` at the provider cap. That is a
  provider configuration issue, not a hub-api bug.
- `outcome=corrected` but nothing visible → publication is asynchronous; the response is
  `status=pending` and channel delivery happens later.
- Silent task death behind a 202 → look for tracebacks in the container log; the handler
  swallows exceptions by design because LibreDesk never retries.

Inspect payloads by setting `CLASSIFIER_LOG_REQUEST=true` and/or `COMPLETION_LOG_REQUEST=true`
in the environment, restart, then dump verbatim bodies with
`python scripts/grab-logs.py --since 30m`. These logs contain customer conversation text —
turn the flags off afterwards and never enable them in production casually.

## 6. Testing end-to-end against the widget

```bash
node scripts/livechat/serve.mjs &                    # host page on :8790
node scripts/livechat/turn.mjs send "texto como cliente"
node scripts/livechat/turn.mjs handoff               # simulate an assistant abandonment
node scripts/livechat/probe.mjs                      # scripted multi-turn run (SCRIPT=guion)
```
`turn.mjs handoff` calls `PUT .../assignee/user/remove` with the agent's own API key so
LibreDesk records the bot as actor — the same shape a real no-answer handoff produces.

## 7. Release

Follow `.sdd/core/git/COMMITS.md` for message format and `.sdd/core/git/RELEASE.md`
for the ordered workflow (`scripts/git/` implements it:
(`get_tag_logs.sh` → confirm level with the owner → `update_changelog.sh` →
`sync_stable.sh` → `create_tag.sh` → push `main stable --follow-tags`). Only `stable`
deploys. Before committing, scan the staged diff for secrets: **any hit stops the commit.**
Credentials never enter the repository or a Kanboard comment.
