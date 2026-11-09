---
description: Core orchestration logic for documentation updates — reactive loop, completion handling, and task launch for sdd-doc-updater.
category: SDD
---

### SU-1: The Reactive Execution Loop (State Tracking)

**Important**: `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`) launches a sub-agent in background with `async: true`. You **cannot** read a sub‑agent's result within the same turn you launch it. When it finishes, retrieve its result with `use_case: read_result`.

**State tracking via marks:**
- `[ ]` = documentation update pending
- `[x]` = documentation update completed

#### At the start of each turn:
1. Call `use_case: read_result` for any in‑flight `agent_id`s you are tracking (wait as needed) to check whether a sub‑agent completed.
2. If a sub‑agent completed, go to **SU-2 (Completion Handling)**.
3. If no report exists, read `.sdd/instructions/SPEC_UPDATE.md` to determine the current state:
   - If there are tasks with `[ ]` (pending): Go to **SU-3 (Task Launch)**.
   - If all tasks are `[x]` (completed): **Stop SU-1** and return to `DOCS.md` to continue with Phase 3 (Finalization).

---

### SU-2: Completion Handling (when reactivated)

1. Extract the sub‑agent's result via `use_case: read_result` — a single JSON per `.sdd/protocols/agents/SUBAGENT_COMMS.md` (`status`, `success`, `summary`, `affected_files`, `error_details`, `question`).

2. **If coming from a Doc Updater sub-agent:**
   - **Never hand‑edit the `[ ]` / `[x]` marker** in `.sdd/instructions/SPEC_UPDATE.md` — mark progression is done **exclusively** by the CLI (which also rewrites the matching `INDEX.md` row). On `success: true` from the doc updater, invoke `agent-instructor workflow update --file ${DOC_ID}.md --status completed` with the explicit doc identifier (e.g., `DOC001`), **not** its ordinal position in the file.
   - **If the result is `status: "blocked"`**: do **NOT** mark it `[x]`. Ask the user via `ask_user` (docs updates may require input), then resume the `sdd-doc-updater` with `use_case: resume`.

---

### SU-3: Task Launch (Documentation Update)

1. Read `.sdd/instructions/SPEC_UPDATE.md` to find the first unchecked task (`[ ]`).
2. If none exist, return to `DOCS.md` (Phase 3 will finalize).
3. Launch the sub‑agent `sdd-doc-updater` using the `Agent` tool:

   #### 🔧 Model Selection (`.sdd/models.yaml`)
   Before launching, check if `.sdd/models.yaml` exists. If present, parse YAML, look up the matching `role`, sort items by `priority` ascending, take the first with a non‑empty `model` (trimmed), then read its `thinking` value **from that model option**. Acceptable values: `"low"`, `"high"`, or `false` (disable thinking). If undefined, omit `model`/`thinking`. Capture the returned `<agent_id>` for use with `agent-instructor workflow add --agent <agent_id> --model <model>`.

   ```
   Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
     agent: "sdd-doc-updater"
     task: "Protocol: SPEC_UPDATE. Task: <task_description>"
     model: "<resolved-model OR omit>"
     thinking: "<low|high|false from model option, omit if undefined>"
     async: true
   ```