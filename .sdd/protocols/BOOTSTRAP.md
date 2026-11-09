## SDD Protocol (Reactive Mode)

1. Check for `.sdd/instructions/BOOTSTRAP.md` on the user's filesystem.
   - If it exists, locate the first unchecked task (marked with [ ]) in the list and designate it as the current task.
   - If no unchecked tasks remain, inform the user and stop.

2. If `.sdd/instructions/BOOTSTRAP.md` is NOT found on the filesystem, politely ask the user to provide its location or content. Do not create, edit, or log anything outside the chat without this file.

3. After completing the current task:
   - First, update `.sdd/core/CONVENTIONS.md` and `.sdd/core/SPEC.md` based on the conventions, architecture, goals, or other relevant information extracted from the task. If a file does not exist, create it with a basic structure. If it exists, apply targeted edits (`replace_in_file`) to add or modify only the necessary sections. Log this in the chat: "Core files updated: CONVENTIONS.md and SPEC.md according to task [X]." (If no new information emerged, skip this and log that no updates were required.)
   - Then, directly update the `.sdd/instructions/BOOTSTRAP.md` file on the user's filesystem by changing the specific checkbox from [ ] to [x].
   - Use a precise editing tool (e.g., replace_in_file) to modify only the exact line of the completed task. Do not overwrite the entire file unless explicitly instructed by the user.
   - Log the update in the chat: "Task [X] completed. `.sdd/instructions/BOOTSTRAP.md` has been updated."

4. Ask the user: "Do you want to continue with the next task?" Wait for explicit confirmation (e.g., "yes", "continue", "proceed") before moving to the next task.

Additional Safety Rules (Mandatory):

* First-edit confirmation: Before performing the first file modification (whether on BOOTSTRAP.md, CONVENTIONS.md, or SPEC.md), the agent must explicitly ask: "I am about to modify files on your system (BOOTSTRAP.md, CONVENTIONS.md, and/or SPEC.md). Proceed?" and wait for a clear "yes". After this initial confirmation, you may proceed with subsequent edits without repeating this step.
* Never overwrite blindly: Always use targeted replacement on the exact line or block. Avoid using write_file to rewrite the whole file unless the user specifically asks you to do so.
* If the file path is unknown: Ask the user to specify the absolute or relative path to `.sdd/instructions/BOOTSTRAP.md` or to any of the core files (`.sdd/core/CONVENTIONS.md`, `.sdd/core/SPEC.md`) before making any edits.