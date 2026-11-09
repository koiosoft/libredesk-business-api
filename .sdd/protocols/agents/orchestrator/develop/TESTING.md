---
description: Test writing loop — Write all pending tests for a given scope.
category: SDD
---

### T-1: The Reactive Execution Loop (Writing Tests)

**Purpose:** Write all pending tests in the corresponding test list.

**Input**: `TEST_MODE` (unit, integration, or ui) — passed by the orchestrator.

**State tracking via marks:**
- `[ ]` = test pending / not passing
- `[x]` = test written and passing

#### At the start of each turn:
1. Check whether a previously launched sub‑agent completed: call `use_case: wait_result` for any in‑flight `agent_id`s you are tracking.
2. If a report exists, go to **T-2 (Completion Handling)**.
3. If no report exists, read `.sdd/instructions/${PROTOCOL}.md` and locate the section corresponding to `TEST_MODE`.
4. Within that section, find the **first** item with `[ ]` that has NOT been processed in the current `BuildTest` pass (i.e., its artifact status is not yet recorded as `Failed` or `Completed` in the CLI log for this cycle).
   - If found, go to **T-3 (Test Launch)** with the test index `i`.
   - If all `[ ]` items have already been processed through `BuildTest` (or no `[ ]` items remain), **proceed to LOOP.md** with the current `TEST_MODE`.

---

### T-2: Completion Handling (when reactivated)

1. Extract the result from the completion report.

2. **If coming from a test-writer sub-agent in BuildTest mode:**
   - **On `success: true`:**
     - **Never hand‑edit the `[ ]` / `[x]` marker in the Test List** — mark progression is done **exclusively** by the CLI (which also rewrites the matching `INDEX.md` row).
     - Invoke the CLI with the explicit test identifier (e.g., `UNIT001`, `INT001`, `UIT001`) — **not** its ordinal position:
       ```bash
       agent-instructor workflow update --file ${TEST_ID}.md --status completed
       ```
   - **On `success: false`:**
     - Leave the line as `[ ]` (preserving the real state for resume/retry).
     - Update the test artifact status via CLI — do **not** hand‑edit the marker:
       ```bash
       agent-instructor workflow update --file ${TEST_ID}.md --status failed
       ```
   - If `MODE_AUTO == false`, ask for confirmation before proceeding.
   - **Autonomous Continuation:** Do NOT pause or request human intervention. Proceed directly to **T-1** to process the next unprocessed `[ ]` item. Once all pending items in the section have been processed through `BuildTest`, proceed **MANDATORY** to `develop/testing/LOOP.md` with the current `TEST_MODE` to run the full test battery via `test-runner`. The test phase is NOT complete until LOOP.md reports suite success (all tests passing) or the 3-iteration correction loop is exhausted. Only then return to the orchestrator main flow.

---

### T-3: Test Launch

1. Find the first item with `[ ]` in the section corresponding to `TEST_MODE` that has not been processed in the current `BuildTest` pass.
2. If all items have been processed, proceed to **LOOP.md**.
3. Determine the test's explicit identifier `TEST_ID` (e.g., `UNIT001`) from the unchecked item — **not** its ordinal position (test number `i`).
4. Launch `test-writer`:

   #### 🔧 Agent + Model Selection (`.sdd/models.yaml`)
   Before launching, read `.sdd/models.yaml` and locate the entry by the **logical role** (e.g. `test-writer`). From that entry obtain:
   - **`name`** → the runtime name to launch (`base.<rol>`), the `agent:` of the launch.
   - **`model`** → from `model_options`, sort by `priority` ascending and take the first with a non-empty `model` (trimmed).
   - **`thinking`** → from that same chosen `model_options` entry.
   Acceptable `thinking` values: `"low"`, `"high"`, or `false`. If the entry or role does not exist, omit `name`/`model`/`thinking` and use the default behaviour. Capture the returned `<subagent_id>` for use with `agent-instructor workflow add --agent <subagent_id> --model <model>`.

   ```
   Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
     agent: "<models.yaml['test-writer'].name — e.g. base.test-writer>"
     task: "Mode: ${TEST_MODE}. Operation: BuildTest. Test file: ${LOG_DIR}/${TEST_ID}.md"
     model: "<resolved-model OR omit>"
     thinking: "<low|high|false from model option, omit if undefined>"
     async: true
   ```