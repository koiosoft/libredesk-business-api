---
description: Protocol for documentation workers updating SPEC, CONVENTIONS, and project .md files.
category: SDD
---

### D-1: Preparation

Before executing any task, the worker MUST:

1. Read `.sdd/core/SPEC.md` and `.sdd/core/CONVENTIONS.md` for overall context and guidelines.
2. **Bootstrap MCP tools** per `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` §0: Ensure MCP tools or skills (such as `jcodemunch`) are accessible via the `mcp` gateway if needed. Never assume unlisted direct tools exist.
3. **Use the retrieval cascade** per `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` §1: Tier 1 pi-tools → Tier 2 jcodemunch/skills → Tier 3 `read`. Protocol-first; escalate by scope. **If Tier 1 does not fully resolve the query, escalate to Tier 2 jcodemunch** before Tier 3/4.
5. **Do not read other SDD protocol/instruction files** beyond: this role file and `CODE_INSPECT_TOOLS.md`. If you need context, set `status: "blocked"` with your doubt in `question`.

---

### D-2: Task Execution

The worker will receive a message containing a **protocol identifier** (e.g., "Protocol: SPEC_UPDATE") and **exactly one task** (e.g., `- [ ] Update SPEC.md to include new authentication module`).

1. **Read the task description** from the prompt.
2. If you need additional context, read `.sdd/instructions/${PROTOCOL}.md` (but **do not modify it**).
3. **Execute the task** using your tools:
   - Read existing documentation files (`read`).
   - Write new documentation files (`write`) if the task requires creating a new document.
   - Modify existing documentation files (`edit`) with precise edits — **replace only the minimal `LINE#HASH`-anchored lines; NEVER dump the whole file in one edit call** (see `CODE_INSPECT_TOOLS.md` §2).
   - Run necessary commands (`bash`) only if the task explicitly requires it (e.g., generating diagrams).

---

### D-3: Strict Prohibitions (MUST NOT)

The worker is **STRICTLY PROHIBITED** from:

- **Modifying source code files** (e.g., `.py`, `.js`, `.java`, etc.) unless the task explicitly instructs you to do so.
- **Running unit tests, integration tests, or any test suite** — This is the `test-runner`'s responsibility.
- **Running `git` commands** — No `git add`, `git commit`, `git cai`, etc.
- **Modifying instruction files** (`.sdd/instructions/*.md`). That is the orchestrator's responsibility.
- **Reading or modifying files outside the scope of the task** — Respect the working directory and file permissions.

---

### D-4: Reporting

When the task ends (success, blocked, or error), the worker MUST return a **single JSON object as its final message** with no other text, per `.sdd/protocols/agents/SUBAGENT_COMMS.md`. Follow the canonical schema and status rules there:

- `completed` → task finished; the orchestrator processes `affected_files` and continues.
- `blocked` → the worker needs a decision/answer; put the concrete doubt in `question`. The orchestrator will re-launch you with your context preserved.
- `error` → irrecoverable failure; explain in `error_details`.

---

### D-5: Interruption and Guidance

- If the worker encounters an obstacle requiring a decision, missing information, or clarification, it MUST set `status: "blocked"` in its final JSON and include the concrete doubt in `question` (see `.sdd/protocols/agents/SUBAGENT_COMMS.md`). The orchestrator will re-launch you with your context preserved; you then continue and return a new final JSON.

---

### Notes

- The worker's context resets on every invocation, so all necessary information must be included in the task description provided.
- The worker focuses on execution: read, edit, and deliver precise documentation updates.
- **Preserve structure**: When updating `.sdd/core/SPEC.md`, ensure document structure remains consistent.
- **Update cross-references**: If you rename or move a section, update internal references.
- **Use `find_references`**: If the task involves updating a definition used elsewhere, search for all occurrences and update them consistently.