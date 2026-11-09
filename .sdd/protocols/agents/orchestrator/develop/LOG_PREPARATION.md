---
description: Prepares the log directory, index, and task/test files for the current iteration using the agent-instructor CLI.
category: SDD
---

### L-1: Prepare the log cycle with the CLI
- Run once at the start of the cycle. The `workflow open` subcommand takes a
  mode **flag**, not a bare protocol name. Use the flag that matches the current
  protocol (`${PROTOCOL}`):
  ```
  agent-instructor workflow open <FLAG>
  ```
- **Protocol → flag mapping** (pick the flag from this table; never pass the
  bare protocol name like `workflow open FEATURE` — that fails with
  `unrecognized arguments: FEATURE`):
  - `FEATURE` → `--feature`
  - `DEBUG` → `--debug`
  - `CORE-SPECS` → `--core-specs`
  - `BOOTSTRAP` → `--bootstrap`
- If no flag is supplied, `workflow open` defaults to a `FEATURE` cycle.
- Example: `agent-instructor workflow open --feature` opens the FEATURE cycle.

- Read the instruction file's YAML frontmatter before opening the cycle and derive the four
  category flags used by the seeding rule in L-1b:

  | Frontmatter key | Orchestrator variable | Category it gates | Artifacts |
  | :--- | :--- | :--- | :--- |
  | `run_unit` | `RUN_UNIT` | Unit tests | `tests/unit/UNIT<NNN>.md` |
  | `run_integration` | `RUN_INTEGRATION` | Integration tests | `tests/integration/INT<NNN>.md` |
  | `run_ui` | `RUN_UI` | UI tests | `tests/ui/UIT<NNN>.md` |
  | `run_dod` | `RUN_DOD` | Definitions of Done | `dod/DOD-TASK<NNN>.md` |

  A flag is **affirmative-only**: only a literal `true` enables its category. An absent key, `false`,
  `null` or any non-boolean spelling disables it — the same reading the engine uses
  (`domain/workflow/layout.py::_flag_enabled`), so the orchestrator and the seeder cannot disagree.
  `mode_auto` and `code_context_lines` are not category gates; they stay with
  `USER_INTERACTION.md`.

**CRITICAL — Execution rule:**
  - **When the user has explicitly requested a *new* cycle (per UI‑0), you MUST run `workflow open` without any prior state checks.** Do **not**:
  - Check whether `ACTIVE_CYCLE` exists.
  - Read the contents of any log directory.
  - Attempt to "resume" or "continue" an existing cycle.
  - The CLI itself will handle the case of an existing active cycle (e.g., by overwriting or erroring). If it errors, you follow the recovery in UI‑5 (reindex), **still without** analysing the situation. Your only responsibility is to execute the command.
  
- This command deterministically creates (all paths below are relative to `LOG_DIR`):
  - The log directory `.sdd/logs/development-cycles/${PROTOCOL}-<TIMESTAMP>` (`LOG_DIR`).
  - `INDEX.md` **at the cycle root** with the protocol, date, time, objective, and the artifact table
    (columns `#`, `Agent`, `Model`, `Task`, `Status`, `Log`). Each `Log` cell carries the
    cycle-relative path — `[tasks/TASK001.md](./tasks/TASK001.md)` — so the index itself tells every
    consumer which folder an artifact lives in.
  - One `tasks/TASK<NNN>.md` per pending `[ ]` task in the instruction file (the Task List is the one
    ungated category).
  - The task specification assets referenced by those tasks under `tasks/assets/`
    (`TASK<NNN>_spec.md`).
  - One `tests/unit/UNIT<NNN>.md` / `tests/integration/INT<NNN>.md` / `tests/ui/UIT<NNN>.md` per
    pending `[ ]` test, **only** for the categories L-1b seeds.
  - One `dod/DOD-TASK<NNN>.md` per pending task when `RUN_DOD == true`.
  - The `ACTIVE_CYCLE` pointer file that the `add` / `update` subcommands rely on.
- **Folders are created only for seeded categories.** A disabled or empty category contributes no
  folder, no artifact and no `INDEX.md` row, so an empty `tests/ui/` can never claim a category the
  instruction document does not have.
- Capture the printed relative path as `LOG_DIR`. `workflow open` also prints the realised artifact
  count and the enabled categories to **stderr**; stdout stays reserved for the cycle path.
- **Do NOT** create the directory, `INDEX.md`, or artifact files by hand. The CLI is the single source
  of truth for cycle creation.
- On success, return to the orchestrator phase that invoked this module via the `return_to_caller`
  label (see `sdd-lang.md` §2 — return labels). On a cycle binding mismatch, follow L-4
  (`workflow open --reindex`) and then return via the same label.
- Seeding itself follows **L-1b**: read it before assuming which artifacts must exist after the
  command returns.

**Version drift (precondition):**
  - `workflow open` compares the **executable's version** (read from
    `agent-instructor`'s own `CHANGELOG.md`) against the target project's
    `.sdd/.init-version` before creating the cycle.
  - If they match, the cycle opens normally with no prompt.
  - If they differ, the CLI warns and asks whether to continue, e.g.:
    ```
    .sdd/ initialized with v0.29.1, executable is v0.30.0. You may continue
    under your own risk and responsibility, or exit now to upgrade
    agent-instructor and the project, then re-run this command.
    ```
    - To resolve it cleanly: exit, upgrade `agent-instructor`, run
      `agent-instructor init` in the target project (which rewrites
      `.sdd/.init-version`), and re-run `workflow open`.
    - To proceed anyway: confirm the prompt. Most upgrades are safe
      improvements, but some can break the in-flight process — continuing is
      the user's conscious responsibility.
  - **Do not** bypass the prompt by editing `.sdd/.init-version` by hand;
    that file is written only by `agent-instructor init`.
  - **Re-verification guard:** after the user confirms, the CLI re-reads the
    executable version from disk. If `agent-instructor` was upgraded *while
    the prompt was on screen*, the in-memory code is obsolete; the CLI aborts
    and instructs the user to re-run the command. Re-running is safe and
    expected: the fresh process loads the upgraded code, and if `.init-version`
    still differs it will simply warn again (continue if you accept the risk).

### L-1b: Optional-category seeding rule (what `workflow open` actually creates)

Every artifact category except **Task** is optional, and all four optionals follow one rule:

> A category is seeded **only** when its frontmatter flag is `true` **and** its section exists in the
> instruction file **and** that section is populated. The flag wins over content.

| Section | Flag | Artifact folder / name | Seeded when |
| :--- | :--- | :--- | :--- |
| `## Task List` | — (ungated) | `tasks/TASK<NNN>.md` | always, one per `[ ]` task |
| `[ASSET: ...]` targets of a task | — | `tasks/assets/TASK<NNN>_spec.md` | copied whenever the task carries a marker |
| `## Unit Test List` | `run_unit` | `tests/unit/UNIT<NNN>.md` | flag true **and** section populated |
| `## Integration Test List` | `run_integration` | `tests/integration/INT<NNN>.md` | flag true **and** section populated |
| `## UI Test List` | `run_ui` | `tests/ui/UIT<NNN>.md` | flag true **and** section populated |
| `## DOD List` (else derived from the Task List) | `run_dod` | `dod/DOD-TASK<NNN>.md` | flag true **and** at least one task |
| `## Reviewer List` (`ACK###`) | — (never gated) | **no folder of its own** | never an artifact |

Consequences the orchestrator must accept as normal:

- **Present-but-empty is a valid answer.** A `## UI Test List` containing only `(empty)` seeds zero
  artifacts, exactly like an absent section.
- **A disabled flag suppresses populated content.** `run_ui: false` with ten listed UI tests still
  seeds zero; the flag wins.
- **The reported count equals the files on disk.** No row is invented for a category that was not
  seeded, so `workflow summary` and `workflow close` can never be blocked by an artifact that does
  not exist.
- **`ACK` is never a test artifact.** An acceptance criterion is nested inside its parent task's DOD
  document (`dod/DOD-TASK<NNN>.md`) and mirrored in the `## Reviewer List`; no combination of
  `run_*` flags promotes it into `tests/unit`, `tests/integration` or `tests/ui`.
- **`TASK` is never gated**: there is no `run_task` flag and none may be inferred.

### L-2: Dynamic artifacts (recovery option)

- If a task or test needs to be added mid-cycle (e.g., discovered during execution), use the CLI against the active cycle:
  ```
  agent-instructor workflow add --task "<task>" [--agent <Agent>] [--model <Model>]
  agent-instructor workflow add --test --<unit|int|ui> "<test>" [--agent <Agent>] [--model <Model>]
  ```
- Each command appends the artifact file **into its category folder** (`tasks/TASK<NNN>.md`,
  `tests/unit/UNIT<NNN>.md`, `tests/integration/INT<NNN>.md`, `tests/ui/UIT<NNN>.md`) and an
  `INDEX.md` row whose `Log` cell carries that cycle-relative path, with status `Pending`.
- The next sequence number is computed from the files already present in that folder, so a manual
  addition cannot collide with what L-1 seeded.
- Adding a test of a category the cycle did not seed (e.g. `--test --ui` while `RUN_UI == false`) is
  an explicit operator decision: it creates the folder and the row for that one artifact. Do not use
  it to work around a disabled flag — enable the flag in the frontmatter and re-open instead.
- This is an optional recovery mechanism, not the normal path (initial tasks/tests are already generated by L-1).

### L-3: DOD creation (gated by `run_dod`)

In addition to the artifacts created by L-1, `workflow open` materialises a **Definition of Done
(DOD)** document for every pending task **when `RUN_DOD == true`** (frontmatter `run_dod`, see L-1):

- One `dod/DOD-TASK<NNN>.md` per pending `[ ]` task — i.e. `${LOG_DIR}/dod/DOD-TASK001.md`, named
  after the task it describes but filed in its **own** `dod/` folder, never beside it in `tasks/`.
- The DOD contains the **ACK checklist** (acceptance criteria) for the task, copied from the
  instruction file's `## Acceptance Contract` / `## Reviewer List`. ACK ids stay **nested inside this
  document**: they are never promoted to top-level `TASK`/`UNIT`/`INT`/`UIT` artifacts.
- The reviewer uses this file during review (see `dev-workers/DEV-REVIEWER.md` R-2); verdicts written
  by `workflow review mark --ack` / `--task` mirror onto it, including the `## Review: APPROVED`
  section.
- Workers (`sdd-worker`, `sdd-ui-worker`) receive **only** `tasks/TASK<NNN>.md` and never the DOD file
  (see ACK068).
- When `run_dod` is `false` (or absent) **no DOD artifact exists**. The review then records its
  outcome directly in `tasks/TASK<NNN>.md`, which is the documented fallback surface — the
  orchestrator must not fail looking for a `dod/` folder the cycle never seeded.

This ensures every task has its acceptance criteria captured at cycle-creation time, decoupling the
review contract from the worker's implementation artifacts.

### L-4: Reindex and layout resolution

- On a `Cycle binding mismatch`, run `agent-instructor workflow open --reindex` (see
  `USER_INTERACTION.md` UI-5). `reindex_log` rebuilds `INDEX.md` **from the folders on disk**, so the
  regenerated rows carry the same cycle-relative paths (`tasks/TASK001.md`,
  `tests/unit/UNIT001.md`, …) that `workflow open` wrote originally — a healthy cycle reindexes
  byte-for-byte.
- Every CLI writer resolves an artifact by basename **or** cycle-relative path: the layout folder is
  tried first and the historical flat location at the cycle root last. That is why a cycle opened
  before this layout keeps working without being migrated.


### L-5: Worker launch paths (what the orchestrator hands out)

- Task work: `${LOG_DIR}/tasks/TASK<NNN>.md`. Its `[ASSET: ...]` markers were rewritten by the
  engine to `../tasks/assets/TASK<NNN>_spec.md` — relative to the task artifact, not to the cycle
  root — because a relative reference resolves against the file carrying it. Always tell the worker
  to follow the marker exactly as written in its own task file.
- Test work: `${LOG_DIR}/tests/<type>/<PREFIX><NNN>.md` (`unit`/`UNIT`, `integration`/`INT`,
  `ui`/`UIT`) for the enabled types only.
- Review work: `${LOG_DIR}/dod/DOD-TASK<NNN>.md`, reviewer-facing only; workers never receive it.
  (see L-3).

### Notes

- The orchestrator never reads the `tasks/*.md` / `tests/**/*.md` / `dod/*.md` files directly; it manages them only through the CLI.
- The `INDEX.md` Status column uses the canonical values `Pending` / `In Progress` / `Completed` / `Failed` (`CANONICAL_STATUSES` in `domain/workflow/status.py`), managed exclusively via `update-status`. Reads are case-insensitive and writes always store the canonical form, so a hand-decorated cell (`✅ Completed`) still matches a completion check but is rewritten as `Completed`.
- Retries reuse the same `tasks/TASK<NNN>.md` (or `tests/<type>/<PREFIX><NNN>.md`). The responsible sub-agent writes its justification only on success.
- `workflow close` moves the plan the cycle consumed out of the live slot: `.sdd/plans/<PROTOCOL>.md` → `.sdd/plans/done/<protocol>/<CYCLE_ID>.md`. Never copy it by hand.
