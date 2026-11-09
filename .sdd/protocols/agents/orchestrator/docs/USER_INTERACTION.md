---
description: User interaction steps for documentation updates — execution mode selection and first-edit confirmation.
category: SDD
---

### UI-1: Select Execution Mode

- Use the `ask_user` tool to ask the user for the execution mode.
- Present the following options:
  1. **Automatic**: Process all pending tasks sequentially without user confirmation between tasks. You will be reactivated automatically by completion reports.
  2. **Step‑by‑step**: Execute one task, mark it, and ask for confirmation before proceeding.
- Set the variable `MODE_AUTO` to `true` for Automatic, `false` for Step‑by‑step.

---

### UI-2: First-Edit Confirmation (Mandatory)

- Before making the *first* modification to `.sdd/instructions/SPEC_UPDATE.md`, you MUST ask the user using `ask_user`:
  *"I am about to modify `.sdd/instructions/SPEC_UPDATE.md` on your system. Proceed?"*
- Wait for a clear "yes". After this initial confirmation, you may perform subsequent edits without repeating this step.