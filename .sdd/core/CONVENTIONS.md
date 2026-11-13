# libredesk-business-api — project conventions

> Scope: project-local only. This document records how code is written in
> THIS project: language standards, architecture rules, dependencies,
> logging, error handling, file contracts. It does NOT describe SDD
> protocols or orchestrators — those live under `.sdd/core/dev-cycle/`
> and `.sdd/protocols/`.

## 1. LANGUAGE & TYPING STANDARDS

- Python 3.12 (pinned by `Dockerfile: python:3.12-slim`). No other runtime.
- Every module starts with `from __future__ import annotations`; parameter and
  return annotations are mandatory on public functions. Union syntax `X | None`.
- Data carriers are frozen dataclasses (`@dataclass(frozen=True)`), never dicts
  passed across a module boundary. Field order matters: `dataclass` requires
  defaulted fields last, which is why `Rules.post_actions` and the optional rule
  fields sit at the end of their declarations.
- Naming: `snake_case` for functions/variables, `PascalCase` for classes and
  dataclasses, `UPPER_SNAKE_CASE` for module constants, `log = logging.getLogger(...)`
  per module.
- **Comments, docstrings and identifiers are written in English.** Product-facing
  prompt text (the classifier `state`, action descriptions in `rules/*/prompts.yaml`)
  stays in Spanish because that is the language the business policy is authored in.
  Do not translate one into the other to "be consistent".

## 2. ARCHITECTURE & CODE STRUCTURE

- Style: single-process FastAPI service, one uvicorn worker, deliberately no
  database table owned by this service.
- Layers, and the only direction imports may cross them:
  - `app/core/` — configuration, rule loading, in-memory state, security, DB read
    access. Knows nothing about JEV.
  - `app/jev/` — the enforcement feature: intake guards, classifier, composer,
    LibreDesk client, pipeline, shared clients. May import `app.core`.
  - `app/routers/` — HTTP surface. May import both; holds no business logic beyond
    dispatch.
- Configuration lives exclusively in `app/core/config.py` as validated settings.
  Logic modules receive values through constructors (`HubClients(settings)`),
  never by calling `get_settings()` themselves, so tests can pin behaviour without
  touching the environment.
- Rule content lives in `rules/<set>/` YAML files and is loaded once at boot.
  Nothing reads disk per request.

## 3. DEPENDENCY MANAGEMENT & ENVIRONMENT

- Virtualenv at `.venv/`, created with `python3.12 -m venv`. Run everything
  through `.venv/bin/python` / `.venv/bin/pytest`; the system interpreter has no
  project dependencies installed.
- Runtime deps in `requirements.txt`, test-only deps in `requirements-dev.txt`.
  Adding one means editing the manifest in the same commit that uses it — PyYAML
  shipped inside the image but missing from `requirements.txt` once, and nobody
  noticed until a clean build.
- Critical external tools: `docker` + `docker compose` (the service runs inside the
  LibreDesk stack and its API is the only way to read assistants/publish messages),
  and `git` with the release scripts under `scripts/git/`. Their absence is a hard
  stop, not a fallback path.
- The service reaches LibreDesk only through its official REST API. Writing directly
  into LibreDesk tables is forbidden (plan risk R6: breaks on every migration).

## 4. LOGGING & ERROR HANDLING

- Use the module logger; never `print`. Format is set once in `app/main.py`.
- Startup is fail-closed and pre-flight validated: malformed config or an
  incomplete rule set raises before the app can serve. A deployment that does not
  come up beats a service running with partial policy.
- Exception policy inside the pipeline: **no exception may escape a background
  task**. Each stage returns a dict with an explicit machine-readable `reason`
  (`jev_said_none`, `low_confidence`, `no_prefix_for_channel:<x>`, `action_missing:<k>`,
  `correction_limit_reached`, `generation_empty`) instead of raising. Broad
  `except Exception` is allowed only at the task boundary, annotated
  `# noqa: BLE001`, and must log.
- Any failure means **do not publish**. Misclassification is recoverable; garbage
  sent into a customer channel is not.
- External call failures degrade to a non-action result, never to a retry: LibreDesk
  does not retry webhook delivery, so re-attempting here changes nothing for anyone.
- Never log secrets or credentials. `/meta/config` exposes booleans
  (`api_key_set`, `credentials_set`), never values. Request-payload logging is
  opt-in per environment variable and carries customer conversation text — treat
  those logs as sensitive and leave the flags off in production.

## 5. FILE-BASED CONTRACTS

- A rule set is exactly three files, all required:
  - `prompts.yaml` — `question.instructions` plus `options:` (closed action list;
    `none` is mandatory; options may use the extended `{text, post_action}` form).
  - `agents.yaml` — allowlist keyed by `ai_assistants.id` (**not** `user_id`), each
    with `enabled`, `name`, `prefixes` per channel, optional `revive_team_id` and
    `bot_user_id`.
  - `prompt-augmenter.md` — describes how the generation prompt is composed; it
    participates in the rules hash even though it is never concatenated.
- Encoding: UTF-8 explicitly on every read/write (`encoding="utf-8"`). No implicit
  locale dependence.
- Designated gatekeeper: `app/core/rules.load_rules()` is the only function that
  decides whether a rule set is valid. It raises `RulesError` for any missing file,
  empty description, unknown channel, non-integer id, or unrecognised `post_action`.
  Nothing else may soften that verdict.
- Rules load once at boot; editing any of the three files requires a restart. The
  loaded content hash is exposed on `GET /meta/config` so "which rules are active"
  is answerable without reading disk.
- Environment sets: `rules/example` (committed reference, and the default),
  `rules/dev` (this workstation's live policy, gitignored), `rules/prod` (reviewed
  production policy, pinned by `compose.prod.yaml`). The default must resolve to a
  committed directory — pointing it at a gitignored one made a fresh clone fail at boot.

## 6. ENFORCEMENT LOOP DOMAIN

- Anti-loop invariant: hub-api publishes as a normal `agent` user, so its own
  messages carry `author.type='agent'` and no `meta.ai_assistant_id`, and the intake
  filter rejects them. `echo_id` (`jev-retry:<uuid>`) is a secondary marker and a
  human-visible trace, not the barrier.
- Intake requires all four conditions together: `type == outgoing`,
  `private is False`, `meta.ai_assistant_id > 0`, `author.type == 'ai_assistant'`,
  plus the agent being enabled in `agents.yaml`. Two independent AI signals are
  demanded on purpose: one is written in memory by `postReply()`, the other comes
  from a JOIN — agreement between them is a cheap integrity check before spending
  money on classification.
- Concurrency: `asyncio.Semaphore(JEV_CONCURRENCY)` wraps the **whole** pipeline,
  not just the slow step, and work runs as event-loop tasks. One thread per event is
  forbidden; there is a regression test that fails if `threading.Thread` reappears in
  the webhook path.
- Generation has two engines behind `JEV_USE_COPILOT`: copilot (default) sends only
  an instruction and lets LibreDesk rebuild history, persona and knowledge-base
  search server-side; completion sends a flat self-contained prompt. Both inherit
  LibreDesk's fixed rewrite framing, which is why action texts are worded as rewrites.
- Published content is sanitised before leaving the service: HTML tag allowlist,
  nested entities decoded first, and Go template braces neutralised
  (`{{ … }}` → broken pair) because LibreDesk renders staff content through
  `text/template`.
- Post-actions (`revive-assistant`) run **only after a successful publish**, and
  reassign by TEAM, never by bare user id: assigning a user directly bypasses the
  operator's automation rules.

## 7. TESTING CONVENTIONS

- Framework: pytest + pytest-asyncio (`asyncio_mode = auto`). No network, no
  database, no LibreDesk instance in any test.
- Contract tests must not read `rules/dev` or `rules/prod`: those files are edited
  live on purpose, and asserting against them breaks CI with no bug involved. They
  build minimal fixture YAML in `tmp_path`. The single exception is
  `test_repo_rules_load`, which checks parseability and shape invariants only.
- Feed wire-format regression tests (`tests/test_libredesk_contract.py`) verbatim
  captured API responses. Never hand-shape a response fixture: a double built from an
  assumption proves only that the code matches that assumption.
- In-memory state is reset by an autouse fixture; without it, the second test
  sending the same payload inherits the first one's dedupe hit.

## 8. GIT LIFECYCLE (reference only)

Commit message rules and the release/tagging workflow are owned by
`.sdd/core/git/COMMITS.md` and the scripts under `scripts/git/`. They are not
restated here; read those before committing or releasing.

Two project-local constraints that the git docs cannot know:

- Secret scanning is a hard stop here, not advice: any line the scan returns means
  do not commit. The env templates in this workspace have carried real credentials,
  which is why they are gitignored.
- Credentials never enter the repository or the Kanboard thread. They are generated
  in the LibreDesk admin UI and written directly into `.env.production` on the host.
