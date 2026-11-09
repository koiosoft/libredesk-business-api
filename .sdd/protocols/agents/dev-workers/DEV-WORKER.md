---
description: Protocol for development workers executing SDD tasks from task files.
category: SDD
---

### D-1: Preparation

Before executing any task, the worker MUST:
1. Read `.sdd/core/SPEC.md` and `.sdd/core/CONVENTIONS.md` for overall context and guidelines.
2. **Bootstrap MCP tools** per `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` §0: Ensure MCP tools or skills (such as `jcodemunch`) are accessible via the `mcp` gateway if needed. Never assume unlisted direct tools exist.
3. **Use the retrieval cascade** (`.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` §1): Tier 1 pi-tools → Tier 2 jcodemunch/skills → Tier 3 `read`. Protocol-first; escalate by scope. **If Tier 1 does not fully resolve the query, escalate to Tier 2 jcodemunch** (`order(action="search_symbols", args={"query":"..."})`) before Tier 3/4.
4. **Do not read other SDD protocol/instruction files** beyond: this role file and `CODE_INSPECT_TOOLS.md`. If you need context, set `status: "blocked"` with your doubt in `question`.

---

### D-2: Task Execution

The worker will receive a message containing a **task file path** (e.g., `${LOG_DIR}/tasks/TASK001.md`). This file contains the task description and a placeholder for the justification. Any `[ASSET: ...]` marker in the task resolves relative to the task artifact itself and points into `${LOG_DIR}/tasks/assets/` (e.g. `../tasks/assets/TASK001_spec.md`); follow the marker exactly as written before implementing.

**Important:** Workers (`sdd-worker`, `sdd-ui-worker`) receive **only** the task artifact (`tasks/TASK<NNN>.md`) and **never** the DOD (Definition of Done) file. The DOD lives at `${LOG_DIR}/dod/DOD-<TASK_ID>.md` and is managed exclusively by the orchestrator and reviewer. Do not expect or attempt to read a DOD file.

1. **Read the task file**:
   - Open `${LOG_DIR}/tasks/TASK<NNN>.md` and extract the task description from the "Task" section.

2. **Execute the task**:
   - **Tool priority** (follow `CODE_INSPECT_TOOLS.md` §1 cascade):
     1. `jcodemunch` (Tier 1) — artifact/symbol retrieval.
     2. `grep`/`find` (Tier 2) — surgical exact-name search.
     4. `read` (Tier 4) — full file content, last resort.
     5. `edit` (modifying) — **NEVER dump the whole file in one edit call; replace only the minimal `LINE#HASH`-anchored lines** (see `CODE_INSPECT_TOOLS.md` §2).
   - **If you need additional context** (e.g., clarification about the task, dependencies, or architecture), **DO NOT** try to locate or read any SDD instruction files.
   - Instead, follow `.sdd/protocols/agents/SUBAGENT_COMMS.md`: set `status: "blocked"` in your final result JSON and put the concrete doubt in the `question` field, so the orchestrator can resolve it and re-launch you with your context preserved. Do not read `.sdd/instructions/` or `.sdd/protocols/` yourself beyond the files mandated by your READ FIRST (this role doc and `CODE_INSPECT_TOOLS.md`).


### D-2b: Exploration Discipline (MANDATORY)

The retrieval cascade (`CODE_INSPECT_TOOLS.md` §1) tells you **which tier** to use.
This section tells you **how many times** to use it. Redundant exploration is the
single largest source of wasted context in worker runs: every re-inspection
re-injects a whole file into the context window and is paid for again on every
subsequent turn.

1. **One inspection per file — XOR rule.** For any given path, use EITHER
   `file_outline` OR `read`. NEVER both. If you already have a file's content or
   its outline, use it. Re-inspecting the same path is a protocol violation.
2. **Never re-read to verify your own edit or write.** Trust the tool response.
   A confirmation re-read re-injects the entire file and is forbidden.
3. **No directory browsing.** Keep the inspection set to the files the task names.
   Do not open neighbouring modules "for context".
4. **Declared inspection budget.** When the task names N files to inspect, your
   exploration is capped at N inspections, plus at most 2 cascade escalations.
   If you reach the cap without converging, set `status: "blocked"` — do not keep
   probing.
5. **Bash is not a discovery tool.** `ls`/`find`/`grep`/`cat` are denied by policy.
   Do not attempt them, and do not attempt shell workarounds for the denial
   (e.g. `sh -c`, `python -c "import os; os.listdir(...)"`). Every denied attempt
   is a wasted turn. Use `file_outline`, `find_symbol`, `find_replace`,
   `find_references`.
6. **Stop when the deliverable is reachable.** Do not run "just one more" check.
   The cheapest successful run is: inspect each input once, produce the
   deliverable, stop.

**Editing corollary:** apply all changes to a file in ONE `edit` call with multiple
`edits` entries. Never target an anchor that also serves as the `pos` or `end` of
another entry in the same call.



3. **On success**:
   - Write the technical justification in the "Justification" section of the same task file.
   - The justification must include:
     - What was done.
     - Why specific approaches, libraries, or patterns were chosen.
     - Any trade-offs or technical debt considered.
   - This is permitted because the file is inside `.sdd/logs/`, which is an audit directory, not source code or instructions.

4. **On failure**:
   - Do not modify the task file.
   - Report the error clearly.

---

### D-3: Strict Prohibitions (MUST NOT)

The worker is **STRICTLY PROHIBITED** from:

- **Reading any SDD instruction or protocol files** (`.sdd/instructions/`, `.sdd/protocols/`) — These are managed exclusively by the orchestrator. **Exception (READ FIRST):** this does NOT apply to your own role file (`.sdd/protocols/agents/dev-workers/DEV-WORKER.md`) nor to `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` — D-1 mandates you read both before executing any task.
- **Running unit tests, integration tests, or any test suite** — This is exclusively the responsibility of the `test-runner` sub-agent. The `sdd-worker` MUST NOT execute any test commands (e.g., `pytest`, `flutter test`, `npm test`), even as a verification step.
- **Running `git` commands** — This includes `git add`, `git commit`, `git cai`, and any other Git commands. Do not create temporary files for commit messages.
- **Reading or modifying files outside the scope of the task** — Respect the working directory and file permissions.

- **D-3b: Strict Prohibition on Code/Test Execution Scope (worker-enforced)**

  - A `sdd-worker` (DEV-WORKER) is **forbidden from running ANY program, subprocess, or command that exercises compiled/interpreted source code as a "validation" or "smoke test"** — including but not limited to `python instructor.py`, `python <module>.py`, `pytest`, `dart/flutter test`, `npm test`, `npm run`, `go run`, shell scripts invoking the project entrypoint, or any REPL import that triggers runtime side-effects.
  - **The ONLY permitted `shell`/execution use is tooling strictly required by the task description** (e.g. `pip install`, `flutter pub get`, dependency resolution with no code execution). The worker MUST NOT invoke the project's own entrypoint or test runner to "prove" its edits.
  - **Pre-flight checklist before any execution:** (1) command is NOT a test runner and NOT a direct invocation of project source; (2) command purpose is dependency/tooling setup only, not behavior verification; (3) command cannot transitively execute the Feature code-paths (e.g. `main()`, `--version`, `generate`).
  - Violation → `status: "error"`, `success: false`, `error_details: "CODE_EXECUTION_SCOPE_VIOLATION"`. The orchestrator runs a `test-runner` sub-agent explicitly to validate behavior; a DEV-WORKER that skips execution to comply is never penalized.

---

### D-4: Reporting

When the task ends (success, blocked, or error), the worker MUST return a **single JSON object as its final message** with no other text, per `.sdd/protocols/agents/SUBAGENT_COMMS.md`. Follow the canonical schema and status rules there (see § 1.2/§ 1.3):

- `completed` → task finished; the orchestrator processes `affected_files` and continues.
- `blocked` → the worker needs a decision/answer; put the concrete doubt in `question`. The orchestrator will re-launch you with your context preserved.
- `error` → irrecoverable failure; explain in `error_details`.

---

### D-5: Interruption and Guidance

- If the worker encounters an obstacle requiring a decision, missing information, or clarification, it MUST set `status: "blocked"` in its final JSON and include the concrete doubt in `question` (see `.sdd/protocols/agents/SUBAGENT_COMMS.md`). The orchestrator will re-launch you with your context preserved; you then continue and return a new final JSON.

---

### Notes

- The worker's context resets on every invocation, so all necessary information must be included in the task description provided (e.g., `LOG_DIR`, task file path).
- The worker focuses on execution: write code, modify files, and deliver a working implementation for the single task it receives.