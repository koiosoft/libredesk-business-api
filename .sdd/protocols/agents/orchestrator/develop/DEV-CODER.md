---
description: Development Loop logic — reactive loop, completion handling, and task launch.
category: SDD
---

### W-1: The Reactive Execution Loop (State Tracking)

**Important**: `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`) launches a sub-agent in background with `async: true`. You **cannot** read a sub‑agent's result within the same turn you launch it. When it finishes, retrieve its result with `use_case: wait_result`.


**State tracking via marks:**
- `[ ]` = task not implemented
- `[x]` = task implemented

#### At the start of each turn:
1. Call `use_case: wait_result` for any in‑flight `agent_id`s you are tracking to check whether a sub‑agent completed.
2. If a sub‑agent completed, go to **W-2 (Completion Handling)**.
3. If no report exists, read `.sdd/instructions/${PROTOCOL}.md` to determine the current state:
   - If there are tasks with `[ ]` (unimplemented): Go to **W-3 (Task Launch - Workers)**.
   - If all tasks are `[x]` (implemented): **Stop W-1** and return to `ORCHESTRATOR.md` to continue with the next phase.

---

### W-2: Completion Handling (when reactivated)

1. Extract the sub‑agent's result via `use_case: wait_result` — applies the YAML-configured timeout, then retrieves the JSON per `.sdd/protocols/agents/SUBAGENT_COMMS.md` (`status`, `success`, `summary`, `affected_files`, `error_details`, `question`).

2. **If coming from a Worker sub-agent:**
   - Extract the explicit **task identifier** (e.g., `TASK001`) from the sub‑agent's completed list item in `.sdd/instructions/${PROTOCOL}.md` — **never** its ordinal position in the file.
   - **Never hand‑edit the `[ ]` / `[x]` markers** in `.sdd/instructions/${PROTOCOL}.md` — those checkboxes are updated **exclusively** by `agent-instructor workflow update --file <TASK_ID>.md --status completed`.
   - **Update the task status via the CLI** (the CLI resolves the active cycle, rewrites the matching `INDEX.md` row, **and** flips the `[ ]`/`[x]` marker in the instruction file):
     - On `success: true`: `agent-instructor workflow update --file ${TASK_ID}.md --status completed`
     - On `success: false`: leave `[ ]` for retry — `agent-instructor workflow update --file ${TASK_ID}.md --status failed`
   - Do **not** edit `INDEX.md` or append rows by hand; the initial rows are already created by `agent-instructor workflow update` (L-1).
   - Log to the user: *"Task implemented. Marked `[x]` via CLI."* (or *"Task failed. Will retry."* if failure).
   - **Task artifact ownership**: the worker sub‑agent completes `${TASK_ID}.md` (the task artifact), writing its technical justification to the Justification section and optionally marking ACK checkboxes in its own `## ACK Checklist`. The worker **owns and edits** `${TASK_ID}.md`. The DOD (`DOD-${TASK_ID}.md`) is **never** edited by the worker — it is maintained exclusively by the CLI via `workflow review` subcommands.
   - **`workflow update --status completed` continues to update `INDEX.md`**: in addition to flipping the `[ ]`/`[x]` marker in the instruction file, the CLI also writes the matching row in `INDEX.md` as `Completed`. This existing behaviour is unchanged — the worker never edits `INDEX.md` directly.
   - If `MODE_AUTO == false`, perform HARD STOP and ask for confirmation before proceeding.
   - **If the worker result is `status: "blocked"`** (doubt in `question`): do **NOT** mark it `[x]` nor `Failed`. **Routing to `sdd-judge` is MANDATORY when `MODE_AUTO == true`** — the orchestrator MUST NOT resolve the doubt itself nor prescribe a fix. Delegate to `sdd-judge` (see `DEVELOP.md` MODE_AUTO Interruption Handling J-2); if `MODE_AUTO == false`, ask the user via a `gate` (fail-closed; see `sdd-lang.md` §6.6). Then resume the worker with `use_case: resume`, applying the judge's `DIRECTIVE_FOR_WORKER`.
   - **Engine-enforced (sdd-lang §6.7):** resolving the ambiguity locally, prescribing implementation in code, or reading source to decide is an engine-enforced violation that ends the run `blocked`. The orchestrator **detects and routes**; it never resolves.

---

### W-3: Task Launch (Phase 1: Implementation / Bug Fixing)

1. Read `.sdd/instructions/${PROTOCOL}.md` to find the first unchecked task (`[ ]`).
2. If none exist, return to `ORCHESTRATOR.md`.
3. Determine the task's explicit identifier `TASK_ID` (e.g., `TASK001`) from the unchecked list item — **not** its ordinal position (task number `i`) in the instructions file.
4. **Select the worker role by semantic intent** — analyze the task description's intent and context, then dispatch the specialized worker:
   - **Dispatch `sdd-ui-worker`** if the task's core focus involves UI layout/components,
     screen creation or refactoring, HTML/Tailwind prototype translation, or visual
     token integration.
   - **Dispatch `sdd-worker`** for core domain logic, backend, non-UI state management
     code, data models, repositories, or general utilities.
5. Launch the selected sub‑agent (`sdd-ui-worker` or `sdd-worker`) using the `Agent` tool:

   #### 🔧 Agent + Model Selection (`.sdd/models.yaml`)
   Before launching, read `.sdd/models.yaml` and locate the entry by the **logical role** (e.g. `sdd-worker`, `sdd-ui-worker`). From that entry obtain:
   - **`name`** → the runtime name to launch (`base.<rol>`), which is the `agent:` of the launch. This is `models.yaml[rol].name`.
   - **`model`** → from `model_options`, sort by `priority` ascending and take the first with a non-empty `model` (trimmed).
   - **`thinking`** → from that same chosen `model_options` entry.
   Acceptable `thinking` values: `"low"`, `"high"`, or `false` (disable thinking). If the entry or role does not exist, omit `name`/`model`/`thinking` and use the default behaviour. Capture the returned `<agent_id>` for use with `agent-instructor workflow add --agent <agent_id> --model <model>`.

   ```
   Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
     agent: "<models.yaml[rol].name — e.g. base.sdd-ui-worker | base.sdd-worker>"
     task: "Task artifact: `${LOG_DIR}/tasks/TASK<NNN>.md`. Execute the task defined in that file. MANDATORY: Read the ASSET file referenced by `[ASSET: ...]` markers in the task artifact BEFORE starting implementation and follow its instructions. The ASSET is part of the task spec — its instructions are as binding as the ACK checklist. Do NOT treat asset instructions as scope-widening; they are the implementation details of this task. MANDATORY: return your technical justification (for the Justification section of `${LOG_DIR}/tasks/TASK<NNN>.md`) as part of your final result message."
     model: "<resolved-model OR omit if models.yaml absent/undefined>"
     thinking: "<low|high|false from model option, omit if undefined>"
     async: true
   ```

---

### W-4: Finalization (Phase 7)

When every task and test in `.sdd/instructions/${PROTOCOL}.md` is marked `[x]` and all `workflow update` calls report success, finalize the cycle **through the CLI** — never by editing `INDEX.md` or writing the summary by hand.

1. **Review the cycle state**:
   - `agent-instructor workflow summary`
   - (Optional, machine-readable) `agent-instructor workflow summary --json`
   - Confirm every artifact is `Completed`. If any `Incomplete`/`Pending`/`Failed` item remains, fix it (re-run its `workflow update`) **before** continuing.

2. **Close the cycle with the CLI** (this verifies all artifacts are `Completed`, stamps a closure date in the `INDEX.md` header, and clears the `ACTIVE_CYCLE` pointer):
   - `agent-instructor workflow close`

3. **Write the final summary as a derived artifact** (optional, NOT the source of truth — the CLI already recorded the state):
   - Create `finalization-summary.md` in `${LOG_DIR}` using `write`.
   - Base it on the output of `workflow summary` — do **not** re-read `.sdd/instructions/${PROTOCOL}.md` or re-count marks by hand.

4. **Notify the user (F-2)** via `ask_user`.

> **MANDATORY**: `workflow close` is the single point of control for finalization. It **aborts** if any artifact is not `Completed` and leaves the `ACTIVE_CYCLE` pointer intact, so a partially-closed cycle can be resumed. Never bypass it by editing `INDEX.md` or deleting `ACTIVE_CYCLE` manually.
