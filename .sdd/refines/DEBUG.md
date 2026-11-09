**STEP 1 (SOURCE OF TRUTH):**
Read the file `.sdd/inputs/DEBUG.md` completely. This file contains the original, immutable requirements of the project.

**STEP 2 (THE EXISTING PLAN):**
Read `.sdd/instructions/DEBUG.md`. 
**CRITICAL:** This file already contains a full list of artifacts, tasks, and paths derived from `.sdd/inputs/DEBUG.md`. Your job is NOT to rebuild this list from the codebase. Your job is to verify its accuracy (unless that is necessary).

**STEP 3 (VALIDATION AGAINST REQUIREMENTS - vs `.sdd/inputs/DEBUG.md`):**
Compare the tasks and artifacts listed in `.sdd/instructions/DEBUG.md` against the functional requirements written in ./`.sdd/inputs/DEBUG.md`. Ask yourself:
- Is there any explicit requirement in `.sdd/inputs/DEBUG.md` that lacks a corresponding task or artifact in `.sdd/instructions/DEBUG.md`? (If missing, you must add it).
- Is there any task or artifact in `.sdd/instructions/DEBUG.md` that does not stem from `.sdd/inputs/DEBUG.md` or contradicts it? (If redundant or incorrect, you must correct/remove it).

**STEP 4 (VALIDATION AGAINST THE ACTUAL CODE - FOCUSED & SCOPED):**
Take ONLY the specific paths, file names, and artifacts explicitly mentioned in `.sdd/instructions/DEBUG.md`.
- Check the indexed project to verify whether those exact paths exist and whether the file names are up-to-date.
- Check if any tasks marked as "pending" in `.sdd/instructions/DEBUG.md` have actually been implemented in those specific files.
- **CRITICAL:** DO NOT analyze files that are not mentioned in `.sdd/instructions/DEBUG.md`. DO NOT generate new artifacts from scratch. Strictly limit yourself to cross-checking the items already written in the file.

**UPDATE CRITERIA:**
If you find ANY discrepancy in Steps 3 or 4 (orphaned requirements, fabricated tasks, outdated paths, or incorrect statuses), you MUST update `.sdd/instructions/DEBUG.md` to fix it.

**STRICT RULES:**
- ONLY modify the `.sdd/instructions/DEBUG.md` file.
- Preserve its EXACT formatting (headings, bullets, indentation, structure). Do not alter the layout.
- If everything matches perfectly (both against `.sdd/inputs/DEBUG.md` and against the actual files mentioned), make NO changes.

**FINAL REPORT:**
When finished, respond ONLY with: "✅ Updated: [concrete reason for