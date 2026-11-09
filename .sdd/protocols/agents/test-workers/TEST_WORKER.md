---
description: Protocol for test workers executing BuildTest and FixTest tasks for any test type (unit, integration, UI).
category: SDD
---

### TW-1: Preparation
Before executing any test task, the worker MUST:
1. Read `.sdd/core/SPEC.md` and `.sdd/core/CONVENTIONS.md` for overall context and guidelines. **CRITICAL: follow CONVENTIONS.md §8 (Test Conventions) — sandbox isolation, scope discipline, and mock boundaries.**
2. **Bootstrap MCP tools** per `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` §0: Ensure MCP tools or skills are accessible via the `mcp` gateway if needed.
3. **Use the retrieval cascade** per `CODE_INSPECT_TOOLS.md` §1: Tier 1 pi-tools → Tier 2 jcodemunch/skills → Tier 3 `read`. **If Tier 1 does not fully resolve the query, escalate to Tier 2 jcodemunch** before Tier 3/4.
3b. **Editing** (if a task requires modifying a test file): replace only the minimal `LINE#HASH`-anchored lines with the native `edit` tool — **NEVER dump the whole file in one edit call** (see `CODE_INSPECT_TOOLS.md` §2).
---

### TW-2: Task Execution

The worker will receive a **task string** containing all necessary information. The string will include:
- The `operation` (BuildTest or FixTest)
- The `mode` (unit, integration, or ui)
- The path to the test description file (e.g., `${LOG_DIR}/tests/unit/UNIT001.md`, `${LOG_DIR}/tests/integration/INT001.md` or `${LOG_DIR}/tests/ui/UIT001.md`). Test artifacts live in their own category folder under the cycle and are seeded only for the categories enabled by the frontmatter flags (`run_unit` / `run_integration` / `run_ui`) — the worker only ever sees the enabled types.

The worker MUST extract the `mode`, `operation`, and `test_file_path` from the task string.

1. **Read the test file** using the extracted `test_file_path` and extract the test description from the **"Task"** section (the CLI-generated artifact format).

2. **If operation is BuildTest**:
   - Write the test code in the appropriate test file (e.g., `test/unit/...`, `test/integration/...`, or `test/ui/...`).
   - The test artifact the worker receives is the cycle's test document (`${LOG_DIR}/tests/<type>/<PREFIX><NNN>.md`); its `mode` (`unit` / `integration` / `ui`) tells the worker which folder and naming convention the runnable test code belongs to.
   - Follow the project's conventions for the corresponding test type (framework, naming, mocking, etc.).
   - Ensure the test is appropriate for its type:
     - **Unit tests**: isolated, fast, no external dependencies.
     - **Integration tests**: may require external services, databases, or environment setup.
     - **UI tests**: may require UI automation tools, emulators, or user interaction simulation.

3. **If operation is FixTest**:
   - The task string will include the path of a failing test file.
   - Diagnose the failure by reading the test file and the relevant source code.
   - Apply fixes to the test code or the source code as necessary.
   - Ensure the test passes after the fix.

4. **On success**:
   - Write the technical justification in the **"Justification"** section of the test file (the same `test_file_path`) — the same convention as the task files. The "Status" field is managed by the orchestrator via `agent-instructor workflow update`; do not edit it yourself.
   - Provide a summary of what was done.

5. **On failure**:
   - Do **not** modify the "Status" field (managed by the orchestrator).
   - Report the error clearly so the orchestrator can update status to `Failed`.

---

### TW-3: Strict Prohibitions (MUST NOT)

The worker is **STRICTLY PROHIBITED** from:

- **Reading any SDD instruction or protocol files** (`.sdd/instructions/`, `.sdd/protocols/`) — These are managed exclusively by the orchestrator. **Exception (READ FIRST):** this does NOT apply to your own role file (`.sdd/protocols/agents/test-workers/TEST_WORKER.md`), to `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md`, nor to the mode-specific context files TW-2 mandates (`UNIT_TEST.md`/`INTEGRATION_TEST.md`/`UI_TEST.md`) — read them before executing any test task.
- **Running the full test suite** — Unless explicitly instructed by the orchestrator (this is the orchestrator's job via `test-runner`). The worker MUST NOT self-authorize a broad test run as a "validation" step.

- **TW-3b: Strict Prohibition on Test Execution Scope (worker-enforced)**

  - A `test-writer` worker is **forbidden from running any test suite, command, or subprocess that is not explicitly scoped to the single test file(s) it directly edited**. Validation commands MUST be limited to the exact path(s) of the file(s) the worker changed, optionally narrowed by `::NodeID` syntax (e.g. `pytest tests/test_instructor.py::test_version_is_defined`).
  - **No `pytest` at repo root, no `pytest tests/ --`, no `pytest -k`, no unmarked directory sweeps.** If the worker cannot form a command targeting only its own changed-file path(s), it MUST NOT run tests at all and shall report success with the validation omitted.
  - **Pre-flight checklist before any test invocation:** (1) command target path ∈ {edited files only}; (2) no bare `pytest` without an explicit path arg; (3) command does not transitively collect `tests/` wholesale.
  - Violation → `status: "error"`, `success: false`, `error_details: "TEST_EXECUTION_SCOPE_VIOLATION"`. The orchestrator does NOT penalize a worker that skipped testing to comply with scope — omitting the run is always safe; over-running is never safe.
- **Running `git` commands** — This includes `git add`, `git commit`, `git cai`, and any other Git commands.
- **Using `grep` or `find`** prematurely — Always prefer native pi-tools (`find_symbol`, `find_references`) and jcodemunch first.
- **Reading or modifying files outside the scope of the task** — Respect the working directory and file permissions.

---

### TW-4: Reporting

When the task is complete, the worker MUST return a **single JSON object as its final message** with no other text, per `.sdd/protocols/agents/SUBAGENT_COMMS.md`. Follow the canonical schema and status rules there (see § 1.2/§ 1.3):

- `completed` → test written/fixed; the orchestrator processes `affected_files` and continues.
- `blocked` → the worker needs a decision/answer; put the concrete doubt in `question`. The orchestrator will re-launch you with your context preserved.
- `error` → irrecoverable failure; explain in `error_details`.

---

### TW-5: Interruption and Guidance

- If the worker encounters an obstacle requiring a decision, missing information, or clarification, it MUST set `status: "blocked"` in its final JSON and include the concrete doubt in `question` (see `.sdd/protocols/agents/SUBAGENT_COMMS.md`). The orchestrator will re-launch you with your context preserved; you then continue and return a new final JSON.

---

### Notes

- The worker's context resets on every invocation, so all necessary information must be included in the task string provided (e.g., `mode`, `test_file_path`, `operation`).
- The worker focuses on writing or fixing a single test case as defined in the test file.