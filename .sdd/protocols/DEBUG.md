## SDD Protocol (Reactive Mode)

1. Check for `.sdd/instructions/DEBUG.md` on the user's filesystem.
   - If it exists, locate the first unchecked task (marked with [ ]) in the list and designate it as the current task.
   - If no unchecked tasks remain, inform the user and stop.

2. If `.sdd/instructions/DEBUG.md` is NOT found on the filesystem, politely ask the user to provide its location or content. Do not create, edit, or log anything outside the chat without this file.

3. After completing the current task:
   - Directly update the `.sdd/instructions/DEBUG.md` file on the user's filesystem by changing the specific checkbox from [ ] to [x].
   - Use a precise editing tool (e.g., replace_in_file) to modify only the exact line of the completed task. Do not overwrite the entire file unless explicitly instructed by the user.
   - Log the update in the chat: "Task [X] completed. `.sdd/instructions/DEBUG.md` has been updated."

4. Ask the user: "Do you want to continue with the next task?" Wait for explicit confirmation (e.g., "yes", "continue", "proceed") before moving to the next task.

Additional Safety Rules (Mandatory):

* First-edit confirmation: Before performing the first file modification, the agent must explicitly ask: "I am about to modify `.sdd/instructions/DEBUG.md` on your system. Proceed?" and wait for a clear "yes". After this initial confirmation, you may proceed with subsequent edits without repeating this step.
* Never overwrite blindly: Always use targeted replacement on the exact line or block. Avoid using write_file to rewrite the whole file unless the user specifically asks you to do so.
* If the file path is unknown: Ask the user to specify the absolute or relative path to `.sdd/instructions/DEBUG.md` before making any edits.