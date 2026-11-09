---
description: Protocol for SDD reviewer agents validating completed tasks against code and justifications.
category: SDD
---

### R-1: Preparation

Before reviewing any task, the reviewer MUST:
1. Read `.sdd/core/SPEC.md` and `.sdd/core/CONVENTIONS.md` to understand general project architecture and standards.
2. **Use native code inspection tools** available at invocation time (search, find_symbol, find_references, file_outline, read). Do not run external MCP servers or heavy stateful tools — use native inspection tools.
3. **Use the retrieval cascade**: native search/find tools → `read` for deep inspection. Escalation protocol applies when inspecting modified files or symbols.
4. **Do not read other SDD protocol/instruction files** beyond: this role file (`DEV-REVIEWER.md`), `CODE_INSPECT_TOOLS.md`, and the project-local review policy. If you need context, set `status: "blocked"` with your doubt in `question`.

---

### R-2: Review Execution

The reviewer receives a **single `TASK_ID`** (no longer a per-ACK tuple).
The Definition of Done file at `${LOG_DIR}/dod/DOD-<TASK_ID>.md` (e.g. `dod/DOD-TASK016.md`)
contains the **ACK checklist** for the task, copied from the instruction file's
`## Acceptance Contract` section.

> **Note:** Workers (`sdd-worker`, `sdd-ui-worker`) receive **only** the task artifact
> (`${LOG_DIR}/tasks/TASK<NNN>.md`) and never the DOD file. Only the reviewer opens the DOD.

1. **Open the DOD**:
   - Open `${LOG_DIR}/dod/DOD-<TASK_ID>.md`.
   - Read the full ACK checklist — each criterion ID, its text, `Required evidence`,
     and the expected verification approach.

2. **Evaluate ALL ACKs in one pass**:
   - For **every** ACK entry in the checklist, validate the criterion using the
     evidence cited by the worker in `tasks/TASK<NNN>.md`.
   - Use native code inspection tools (read, search, find_symbol, find_references,
     file_outline) to verify each criterion against actual implementation files.
   - Do NOT split the review into separate per-ACK invocations — all ACKs are
     evaluated within a single execution.

3. **Decision & Verdicts**:
   - Return a **`verdicts` array** (see SUBAGENT_COMMS.md § 1.2 — Reviewer extension)
     with one entry per ACK:
     - `"ack_id"`: the criterion identifier (e.g. `"criterion-1"`)
     - `"status"`: `"approved"` | `"rejected"` | `"blocked"`
     - `"evidence"`: specific finding from code inspection
   - **On Approval**: Include the criterion in `verdicts` with `status: "approved"`
     and supporting evidence.
   - **On Rejection**: Include the criterion with `status: "rejected"` and actionable
     details of what failed.
   - The reviewer MUST NOT write, append, or modify any file.

The engine persists `## Review` into the task file after a successful review.

---

### R-3: Strict Prohibitions (MUST NOT)

The reviewer is **STRICTLY PROHIBITED** from:

- **Modifying source code or test files** — The reviewer MUST NOT write, edit, refactor, or delete any source code files. It is strictly a read-only inspector for production code.
- **Modifying any SDD instruction or protocol files** (`.sdd/instructions/`, `.sdd/protocols/`) — Exception: this role file (`DEV-REVIEWER.md`) and `CODE_INSPECT_TOOLS.md` as mandated in R-1.
- **Editing task files under any circumstance** — The reviewer MUST NOT write to or modify any task file (`${LOG_DIR}/tasks/TASK<NNN>.md`). The engine writes `## Review` on approval, never the reviewer.
- **Running tests or project source code** — The reviewer MUST NOT run `pytest`, `flutter test`, `npm test`, or execute project scripts. Validation is static inspection of code and artifacts.
- **Running `git` commands** — No `git add`, `git commit`, `git checkout`, etc.

---

### R-4: Reporting

When the review ends, the reviewer MUST return a **single JSON object** as its
final message with no other text, per `.sdd/protocols/agents/SUBAGENT_COMMS.md`
§ 1.2 (including the Reviewer extension with `verdicts`). The engine persists the
`## Review` section into the task file after a successful review.

- `completed` → All ACKs evaluated. The `verdicts` array contains the outcome for
  each criterion (each entry with `"status": "approved"` or `"status": "rejected"`).
- `blocked` → Clarification is needed to decide one or more criteria; put the
  doubt in `question`.
- `error` → Review cannot proceed (e.g., DOD file `${LOG_DIR}/dod/DOD-<TASK_ID>.md` not found, irrecoverable
  inspection failure). Provide actionable details in `error_details`.



---

### R-5: Interruption and Guidance

- If the reviewer encounters ambiguities in requirements or missing dependencies that prevent a conclusive review, it MUST set `status: "blocked"` in its final JSON with the query in `question` (see `.sdd/protocols/agents/SUBAGENT_COMMS.md`).

---

### R-6: Review Discipline (general)

> The reviewer's equivalent of the test-runner's mode context (`TEST_RUNNER.md` TR-2).
> The runner is told **how** to run and classify tests; the reviewer is told here
> **how to judge** an ACK. This section is stack-agnostic: project-specific acceptance
> standards live in the project-local review policy.

1. **What "approved" means.** An ACK is `approved` only when (a) the criterion text
   is *fully* satisfied — not partially; (b) the worker's cited evidence is
   **verifiable by static inspection** of the repository; and (c) the implementation
   matches the criterion **as written**.
2. **Evidence sufficiency.** Evidence must point to a concrete artifact (file path,
   symbol, test, config key). "It was implemented" without a locatable artifact is
   **not** evidence. Prefer primary artifacts (source/tests) over secondary ones
   (comments, changelogs, commit prose). If evidence is absent or unverifiable, set
   `status: "blocked"` with a concrete doubt in `question` — never guess a verdict.
3. **Scope discipline.** Judge **only** the ACKs present in the DOD checklist for
   this TASK. Do not invent criteria; do not approve an ACK because unrelated code
   elsewhere looks acceptable. One criterion, one verdict (each `verdicts[]` entry
   is independent).
4. **Read-only mandate.** Inspection tools only; never `edit`/`write`/`bash`, never
   run tests or `git`. The reviewer never writes files — the engine persists
   `## Review` (see R-3).
5. **Correction vs. ambiguity (routing).**
   - `REQUIRES_CORRECTION` (**mechanical**): the criterion is unmet by a concrete,
     unambiguous defect. Report it with specific, actionable detail.
   - **Design ambiguity**: the criterion text and the implementation disagree on a
     design decision, naming, or contract. Do **not** resolve it locally — surface it
     so the orchestrator routes it to the arbiter (`REVIEW.md` R-5). The reviewer
     **detects and reports**; it never prescribes the fix.
6. **Baseline defects.** Do not fail an ACK for a defect that is clearly a
   **pre-existing baseline** issue unrelated to this TASK's change, unless the
   criterion explicitly covers it. Note it in `evidence` for orchestrator routing.
7. **Style neutrality.** Do not require a specific implementation style beyond what the
   criterion states. If the criterion is silent on a detail, approve on satisfaction of
   the stated text and record the observation in `evidence`.
