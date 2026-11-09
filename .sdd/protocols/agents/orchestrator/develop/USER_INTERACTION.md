---
description: User interaction steps — protocol selection, execution mode, test preferences, and first-edit confirmation.
category: SDD
---

### UI-1: Identify the Protocol from Frontmatter

- The `PROTOCOL` variable is determined by the CLI `generate` command (via `--feature`, `--debug`, `--bootstrap`, or `--core-specs` flags) before the orchestrator starts.
- Construct the instruction file path: `.sdd/instructions/${PROTOCOL}.md`.
- Read the file and parse its YAML frontmatter block (the `---` delimited header at the top of the file).
- **Required frontmatter fields**: `protocol`, `mode_auto`, `run_integration`, `run_ui`.
- Validate that the `protocol` field in the frontmatter matches the `PROTOCOL` variable. If they differ, abort with an error: *"Protocol mismatch: frontmatter declares '${protocol}' but CLI selected '${PROTOCOL}'"*.
- If the instruction file does not exist, abort with an error: *"Instruction file not found: .sdd/instructions/${PROTOCOL}.md"*.
- If the file exists but lacks a valid YAML frontmatter block with all required fields, abort with an error: *"Invalid or missing YAML frontmatter in .sdd/instructions/${PROTOCOL}.md. Required fields: protocol, mode_auto, run_integration, run_ui"*.

---

### UI-1b: Load Follow-ups from Previous Cycle

- Check if `.sdd/instructions/FOLLOW_UP.md` exists and has entries beyond the placeholder.
- If it has unresolved follow-up items, present them to the user via a `gate` (UI-1b):
  *"There are unresolved follow-ups from a previous cycle. Do you want to retake them now (they will be
  added as tasks to this cycle) or leave them for a future cycle?"*
- Options: **Retake now** / **Leave for later**.
  - **Retake now** → each follow-up item becomes a task in the current `## Task List`.
  - **Leave for later** → keep the `FOLLOW_UP.md` as-is for the next cycle.
- If the user chooses to retake, clear the entries from `FOLLOW_UP.md` after they are incorporated.
- **No-answer contract (fail-closed):** the gate waits for an explicit choice from the user (delivery
  via the active channel). Consent is never inferred from an unrelated message, a cancellation, or a
  timeout. See `sdd-lang.md` §6.6.

---

### UI-2: Load Execution Mode & Test Preferences from Frontmatter

- Extract `mode_auto` from the frontmatter and set the variable `MODE_AUTO` to its boolean value (`true` or `false`).
- Extract `run_integration` from the frontmatter and set the variable `RUN_INTEGRATION` to its boolean value (`true` or `false`).
- Extract `run_ui` from the frontmatter and set the variable `RUN_UI` to its boolean value (`true` or `false`).
- **No interactive `gate` calls** are made for configuration variables. All configuration is derived from the frontmatter.
- Store `MODE_AUTO`, `RUN_INTEGRATION`, and `RUN_UI` in your state for the rest of the execution.

---

### UI-3: First-Edit Confirmation (Mandatory)

- Before making the *first* modification to `.sdd/instructions/${PROTOCOL}.md`, you MUST ask the user using a `gate` (UI-3):
  *"I am about to modify `.sdd/instructions/${PROTOCOL}.md` on your system. Proceed?"*
- Wait for a clear "yes". After this initial confirmation, you may perform subsequent edits without repeating this step.
- **No-answer contract (fail-closed):** the gate waits for an explicit "yes"; it is never satisfied by
  inference. See `sdd-lang.md` §6.6.

---

### UI-4: Instruction File Structure

- When creating or updating the instruction file (`.sdd/instructions/${PROTOCOL}.md`), ensure it contains the following sections (if applicable):
  - `## Task List` (mandatory)
  - `## Unit Test List` (mandatory)
  - `## Integration Test List` (optional, only if `RUN_INTEGRATION == true`)
  - `## UI Test List` (optional, only if `RUN_UI == true`)

- Each section must contain a list of items with `[ ]` placeholders. Example:
  ```markdown
  ## Task List
  - [ ] Implement login feature
  - [ ] Add logout button

  ## Unit Test List
  - [ ] Test login success
  - [ ] Test login failure

  ## Integration Test List
  - [ ] Test login flow with database

  ## UI Test List
  - [ ] Test login screen UI
  ```

---

### UI-5: Cycle Binding Mismatch Recovery

- Upon detecting the canonical `Cycle binding mismatch` error, perform the following steps:
  1. Notify the user using a `gate` (UI-5) with the message: *"A cycle binding mismatch has been detected. This may occur when the protocol state and cycle state are inconsistent. I will attempt to reindex the active cycle to resolve this issue. Proceed?"*
  2. Wait for user confirmation (clear "yes"). The gate waits without inferring consent if unanswered.
  3. Trigger `workflow open --reindex` on the active cycle to rebuild the cycle state.
  4. Resume the protocol from the last completed step.

- This step ensures automatic recovery from binding inconsistencies while keeping the user informed.