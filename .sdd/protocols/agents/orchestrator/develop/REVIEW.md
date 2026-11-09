---
description: Code review protocol — read-only reviewer verdicts, review-state registration in the instruction file, and the fix-and-re-review correction loop.
category: SDD
---

> **Purpose:** Defines the **review phase** of the development orchestrator. Once the orchestration core (`develop/DEV-CODER.md`) marks a task `[x]` (implementation complete), a **read‑only reviewer** sub‑agent verifies the implementation and emits a verdict. The orchestrator registers that verdict as a review‑state section in `.sdd/instructions/${PROTOCOL}.md` (e.g. `FEATURE.md`), drives a **fix‑and‑re‑review** loop on rejection (max 3 iterations, then `ask_user`), and routes non‑fixable issues to a `## Rejected → Follow-up` section.
>
> **Reviewer role:** `sdd-reviewer` — a **read‑only** sub‑agent. It may use **inspection tools only** (`read`, `jcodemunch` `order` / `get_symbol_source` / `get_ranked_context`). It **MUST NOT** use `edit`, `write`, or `bash`. The reviewer's tool whitelist is declared in its PI extension frontmatter under `templates/source/.pi/extensions/agents/sdd-reviewer.md`; REVIEW.md is the protocol that consumes that role.

---

### R-1: Hierarchical ACK-based Reviewer List

The `## Reviewer List` section in `.sdd/instructions/${PROTOCOL}.md` is a **hierarchical ACK-based structure** that serves as the canonical source for review marks. It is parsed by `workflow review list` and mutated exclusively by `workflow review mark` / `workflow review unmark`. The **source of truth for review state** is the DOD file (`DOD-${TASK_ID}.md`), materialised during `workflow open`, which is the primary surface that tracks individual ACK marks and approval status.

- **Format** — one parent row per TASK ID with indented ACK children:
  ```markdown
  ## Reviewer List
  - TASK001 [ ]
      - ACK001 [ ] <acceptance criterion 1>
      - ACK002 [ ] <acceptance criterion 2>
  - TASK002 [ ]
      - ACK003 [ ] <acceptance criterion 3>
  ## End Reviewer List
  ```
- **ACK ids** are **globally unique across the whole cycle**, incrementing in document order under each TASK (ACK001, ACK002, …). `ACK002` is the lookup key used by `workflow review mark --ack ACK002`.
- **Parent TASK mark is derived**: `- TASK### [ ]` flips to `[x]` **only** when all its ACK children are `[x]`. This derivation is performed by the engine (`derive_review_status` / `mark_ack_review`), never by hand-editing.
- **Entry point** — a TASK ID (e.g. `TASK001`) is the unique key the orchestrator uses to launch a review. The reviewer evaluates all ACK criteria belonging to that TASK in a single pass. The orchestrator **never** uses an item's ordinal position (consistent with DEV-CODER.md W-2/W-3).
- **ACKs are materialised in the DOD file.** During `workflow open`, the engine creates `${LOG_DIR}/dod/DOD-${TASK_ID}.md` which serves as the **source of truth** for review state. The DOD file contains:
    - A `## ACK Checklist` section mirroring the hierarchical ACK structure from the Reviewer List.
    - Individual ACK checkboxes (`[ ]` / `[x]`) that track review completion per criterion.
    - A `## Review: APPROVED` section (written when all ACKs of a parent TASK are `[x]`).
- The `${TASK_ID}.md` task file **keeps** a `## ACK Checklist` for the worker's convenience (to locate and validate individual criteria), but it is **not** the source of truth for review state. `workflow review mark` synchronises marks in the DOD and the Reviewer List; the task file ACK checklist mirrors the authoritative state for worker context only.
- **Mirror integrity:** whenever `## Task List` gains a new TASK ID (e.g. mid‑cycle via `agent-instructor workflow add --task`), the matching parent row **must** be appended to `## Reviewer List` (the engine adds it via `prepare_log` / `add_task_artifact`, which also materialises an empty ACK section in the task file). The orchestrator treats a mismatch between the two lists as a recoverable cycle‑binding error (see `USER_INTERACTION.md` UI‑5).
- **CLI surface** — only `workflow review` subcommands touch this list:
  - `workflow review list` — prints a grouped table of TASKs with their pending ACKs (TASK id, derived approval, list of outstanding ACK ids). Output drives reviewer launches: one launch per TASK.
  - `workflow review mark --ack ACK002 [--status approved|correction]` — flips the ACK mark in **both** the Reviewer List (`.sdd/instructions/${PROTOCOL}.md`) and the DOD file (`DOD-${TASK_ID}.md`); when all ACKs of a parent TASK are `[x]`, derives the parent as `[x]` and writes `## Review: APPROVED` in the DOD file.
  - `workflow review unmark --ack ACK002` — orthogonal inverse: flips ACK `[x]`→`[ ]` in both the Reviewer List and the DOD file; if the parent TASK no longer has all ACKs `[x]`, reverts the parent to `[ ]`.

---

### R-2: Launch Review

**Trigger:** invoked by `DEV-CODER.md` (W-2 completion handling) after a task is marked `[x]`, or as a review pass over every TASK in the Reviewer List that has any `[ ]` ACK child and whose matching Task List item is `[x]`, once the orchestration core returns to the next phase.

**Preconditions:**
1. Read `.sdd/instructions/${PROTOCOL}.md`.
2. Locate the `## Reviewer List` block.
3. Find the first TASK that has **any** `[ ]` ACK child **and** whose matching `## Task List` item is `[x]` (implemented but not yet fully reviewed). If none exist, the review phase is complete — return to `ORCHESTRATOR.md` to continue with the test phases (`TESTING.md`).
4. Extract the explicit `TASK_ID` (e.g. `TASK001`) from that parent row — **not** its ordinal position.

#### 🔧 Agent + Model Selection (`.sdd/models.yaml`)
Before launching, read `.sdd/models.yaml` and locate the entry by the **logical role** `sdd-reviewer`. From that entry obtain:
- **`name`** → the runtime name to launch (`base.sdd-reviewer`), the `agent:` of the launch.
- **`model`** → from `model_options`, sort by `priority` ascending and take the first with a non-empty `model` (trimmed).
- **`thinking`** → from that same chosen `model_options` entry.
Acceptable `thinking` values: `"low"`, `"high"`, or `false`. If the entry or role does not exist, omit `name`/`model`/`thinking` and use the default behaviour. Capture the returned `<agent_id>` for use with `agent-instructor workflow add --agent <agent_id> --model <model>`.

```
Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
  agent: "<models.yaml['sdd-reviewer'].name — e.g. base.sdd-reviewer>"
  task: "Protocol: ${PROTOCOL}. TASK_ID: ${TASK_ID}. The DOD file is at: ${LOG_DIR}/dod/DOD-${TASK_ID}.md.\n\nAct as a READ-ONLY reviewer. You may use inspection tools only (read, jcodemunch order/get_symbol_source/get_ranked_context). You MUST NOT use edit, write, or bash.\n\nInspect the codebase and verify the implementation against ALL acceptance criteria listed in the DOD file. The DOD file contains the ACK Checklist with all criteria for this task. Evaluate each criterion individually. End your turn by emitting a SINGLE canonical JSON object as your final message, with no other text. The JSON must contain:\n\n{\n  \"status\": \"completed\",\n  \"success\": true,\n  \"summary\": \"<concise review summary>\",\n  \"affected_files\": [],\n  \"verdicts\": [\n    {\n      \"ack_id\": \"ACK001\",\n      \"verdict\": \"APPROVED\" | \"REQUIRES_CORRECTION\",\n      \"error_details\": \"<reasons string — ONLY when verdict is REQUIRES_CORRECTION>\",\n      \"rejected_followup\": false\n    },\n    {\n      \"ack_id\": \"ACK002\",\n      ...\n    }\n  ]\n}"
  model: "<resolved-model OR omit if models.yaml absent/undefined>"
  thinking: "<low|high|false from model option, omit if undefined>"
  async: true
```

> **Verdict contract (extends SUBAGENT_COMMS § 1.2):** the reviewer always returns `status: "completed"` and `success: true` (the *review* completed). Instead of a single `verdict` field, the output carries a `verdicts` array where each entry corresponds to one ACK criterion. Every entry includes `ack_id`, `verdict` (`APPROVED` or `REQUIRES_CORRECTION`), `error_details` (populated only when the verdict is `REQUIRES_CORRECTION`), and `rejected_followup` (`false` by default). This is a documented, backward‑compatible extension: consumers that only read `status`/`success` still see a completed review; consumers that need per‑ACK gate outcomes read the `verdicts` array.
---

### R-3: Completion Handling (Verdicts)

1. On reactivation, retrieve the reviewer result via `use_case: wait_result`.
2. Extract the JSON and iterate over the `verdicts[]` array. For each verdict entry:
   - **`APPROVED`** → go to **R‑4** (Register Approved).
   - **`REQUIRES_CORRECTION`** → inspect `rejected_followup`: 
     - If `rejected_followup == true` → go to **R‑6** (Non‑Fixable / Rejected → Follow‑up).
     - Otherwise → go to **R‑5** (Fix‑and‑Re‑Review loop).
   - If `status == "blocked"`: do **not** register a review state. Read `question`, resolve it (or route to `sdd-judge` when `MODE_AUTO == true`), and resume the reviewer with `use_case: resume` per SUBAGENT_COMMS.md § 3. A blocked review consumes **no** correction iteration.
   - If the reviewer was **terminated by an output token limit** (signal "output token limit" with no complete canonical JSON) — a *delivery* failure, not a `blocked` doubt: apply `develop/TOKEN_LIMITS.md` TL-3 — scoped relaunch resending **only** the current `TASK_ID` task-evaluation prompt with the next-priority model (`sdd-reviewer`: p1 `openrouter/poolside/laguna-s-2.1` → p2 `openrouter/deepseek/deepseek-v4-flash-0731`, `thinking: medium`). This does **not** increment `REVIEW_ITERATION` (R-5).
3. If `MODE_AUTO == false`, perform a HARD STOP and ask for user confirmation before proceeding to R‑4 / R‑5 / R‑6.

---

### R-4: Register Review State (Approved)

When a per-ACK verdict is `APPROVED`, the orchestrator does **not** manually write review state or flip markers. Instead, it delegates to the CLI:

1. **CLI command**: `workflow review mark --ack ${ACK_ID} --status approved`
   This single command atomically:
   - Flips the ACK `[ ]`→`[x]` in **both** the Reviewer List (FEATURE.md) **and the DOD file (`DOD-${TASK_ID}.md`)**.
   - When **all** ACKs of the parent TASK become `[x]`, derives the parent `- TASK### [ ]`→`[x]` in the Reviewer List.
   - Writes a `## Review: APPROVED` section in the DOD file (`DOD-${TASK_ID}.md`).

2. **Per-TASK review, per-ACK marking**: the reviewer is launched once per TASK (R-2) and returns verdicts for all ACKs of that TASK. The orchestrator then calls `workflow review mark --ack ${ACK_ID} --status approved` for each approved ACK individually. The marking is per-ACK for atomicity; the evaluation is per-TASK for efficiency.

3. **Per-task completion**: when all ACKs of a TASK are marked `[x]`, the task is considered fully approved. The orchestrator then proceeds to the next unreviewed TASK (return to **R-2**), or — when all TASKs in the Reviewer List have all their ACKs `[x]` — return to `ORCHESTRATOR.md` to continue with the test phases (`TESTING.md`).

4. **Logging**: the orchestrator logs to the user: "ACK ${ACK_ID} approved. Task: ${TASK_ID}." No manual review‑state block editing is required — the engine handles it.

> **Note:** The `workflow review mark` engine call is the **only** path that flips Reviewer List markers. The orchestrator **never** hand-edits `[ ]`/`[x]` markers (consistent with DEV‑CODER.md W‑2).
---

### R-5: Fix-and-Re-Review Loop

When the verdict is `REQUIRES_CORRECTION` (and `rejected_followup` is `false`):

1. Initialize `REVIEW_ITERATION = 1`.
2. **Disambiguate the verdict before fixing.** A `REQUIRES_CORRECTION` may be either (a) a
   mechanical fix in the implementation or (b) a genuine design ambiguity (is the ACK wording
   wrong, or is the implementation wrong?). The orchestrator must **classify** it:
   - If the reason is a **mechanical correction** (a concrete, unambiguous defect in the
     implementation): proceed to fix (step 3).
   - If the reason signals a **design ambiguity** (e.g. the acceptance criterion text and the
     implementation disagree on a design decision, naming, or contract): **do NOT decide it
     locally and do NOT prescribe a fix.** Route it to `sdd-judge` arbitration (see
     `DEVELOP.md` MODE_AUTO Interruption Handling), then apply the judge's
     `DIRECTIVE_FOR_WORKER`. The orchestrator **detects and routes**; it never resolves.
     This is engine-enforced — see `sdd-lang.md` §6.7.
3. **Register the rejection state** in `.sdd/instructions/${PROTOCOL}.md`:
   ```markdown
   ## Review: REQUIRES_CORRECTION
   ### ${TASK_ID}
   - <reason bullet 1>
   - <reason bullet 2>
   ```
   Reason bullets come verbatim from the reviewer's `error_details`.
4. **Launch a fix worker** for the rejected task — the same worker that originally implemented it (role selected by semantic intent per DEV‑CODER.md W‑3), scoped to the reviewer's reasons:
   ```js
   Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
     agent: "<sdd-worker | sdd-ui-worker>"
     task: "Protocol: ${PROTOCOL}. TASK_ID: ${TASK_ID}. The task artifact is at ${LOG_DIR}/tasks/TASK<NNN>.md.\n\nThe reviewer found the following issues (REQUIRES_CORRECTION):\n<reasons>\n\nFix the implementation to address each reason. Re-read CONVENTIONS.md and SPEC.md. End your turn with a single canonical JSON result (SUBAGENT_COMMS.md). Write your technical justification to the Justification section of ${LOG_DIR}/tasks/TASK<NNN>.md."
     model: "<resolved-model OR omit>"
     thinking: "<low|high|false from model option, omit if undefined>"
     async: true
   ```
> **Context note:** the fix worker receives `${LOG_DIR}/tasks/TASK<NNN>.md` (the task artifact) for implementation context. It does **not** receive the DOD (`${LOG_DIR}/dod/DOD-${TASK_ID}.md`) — the DOD is the reviewer's artifact and is not needed for correction work.
5. When the fix worker completes (`status: "completed"`):
   - Mark the task re‑completed via CLI: `agent-instructor workflow update --file ${TASK_ID}.md --status completed`.
   - **Re‑review** — return to **R‑2** to launch `sdd-reviewer` again on the same `${TASK_ID}`. The reviewer again receives the DOD file (`DOD-${TASK_ID}.md`) as its primary artifact, exactly as in the initial review (see R‑2 launch template).
   - Increment `REVIEW_ITERATION`.
6. **Iteration cap:** if `REVIEW_ITERATION` reaches **3** and the verdict is still `REQUIRES_CORRECTION`:
   - Append the final iteration's reasons under the existing `## Review: REQUIRES_CORRECTION` block (do not overwrite prior iterations — keep the history).
   - Invoke a `gate` with options **Retry / Skip / Abort** (mirrors `testing/LOOP.md` LOOP‑1):
     - **Retry** → reset `REVIEW_ITERATION` to 1 and return to R‑2.
     - **Skip** → leave the task `REQUIRES_CORRECTION`; mark it `Failed` via `agent-instructor workflow update --file ${TASK_ID}.md --status failed`; return to `ORCHESTRATOR.md`.
     - **Abort** → stop the cycle (escalate to a `gate` with full reviewer history).
     - **No-answer contract (fail-closed):** if the gate does not receive an explicit answer,
       the run stays `blocked` and waits. Consent is never inferred. See `sdd-lang.md` §6.6.
   - In `MODE_AUTO == true`, the orchestrator first attempts automated recovery via the next model priority in `.sdd/models.yaml` and `sdd-judge` arbitration (see `DEVELOP.md` safety rules) before escalating to the user.

> **Scope note:** the fix‑and‑re‑review loop is scoped **per TASK ID**. Each task carries its own `REVIEW_ITERATION` counter. A task that is re‑approved (`APPROVED`) resets its own counter; it never inherits another task's correction iterations.

---

### R-6: Non-Fixable / Rejected → Follow-up

When the reviewer sets `rejected_followup == true` (a reason that **cannot** be corrected by a developer — e.g. an environment/dependency blocker, an architectural decision needing user input, or a spec gap):

1. Create or append to a dedicated section in the DOD file (`DOD-${TASK_ID}.md`):
   ```markdown
   ## Rejected → Follow-up
   ### ${TASK_ID}
   - [ ] <non-fixable reason bullet 1>
   - [ ] <non-fixable reason bullet 2>
   ```
   Each bullet is an open follow‑up item (carries its own `[ ]` mark) to be resolved outside the current cycle.
2. Leave the Reviewer List mark for `${TASK_ID}` as `[ ]` (the derivation remains not-approved since its ACKs are not all `[x]`), and record the artifact as `Failed` via the CLI:
   ```bash
   agent-instructor workflow update --file ${TASK_ID}.md --status failed
   ```
3. If `MODE_AUTO == false`, notify the user immediately via `ask_user` with the non‑fixable reason.
4. Proceed to the next unreviewed item (return to **R‑2**), or — when all items are processed — return to `ORCHESTRATOR.md`. Non‑fixable items are carried as follow‑ups into the next cycle; they do **not** block finalization of approved tasks (all ACKs `[x]`).

---

### R-7: User Override — Register Follow-up in FOLLOW_UP.md

When the user explicitly decides to override a reviewer rejection and close the cycle
despite unresolved observations:

1. Append each unresolved observation to `.sdd/instructions/FOLLOW_UP.md` under a
   section for the current cycle:
   ```markdown
   ## <TAG_NAME or PROTOCOL> (YYYY-MM-DD)
   
   ### <TASK_ID> — <task title>
   - [ ] <observation 1>
   - [ ] <observation 2>
   - **Override por:** usuario
   - **Contexto:** <brief reason why the cycle was closed anyway>
   ```
2. The `## Reviewer List` mark for `${TASK_ID}` remains as `[ ]` (not approved).
3. Record the artifact as `Failed` via the CLI:
   ```bash
   agent-instructor workflow update --file ${TASK_ID}.md --status failed
   ```
4. These items will be surfaced at the start of the next cycle via **UI-1b**
   (see `USER_INTERACTION.md`).

> **Cross-references:** This module is invoked by `develop/DEV-CODER.md` (W‑2 completion handling). The `## Review: APPROVED` / `## Review: REQUIRES_CORRECTION` / `## Rejected → Follow-up` state sections and the mirrored `## Reviewer List` are written into / read from `.sdd/instructions/${PROTOCOL}.md` (resolved to `FEATURE.md` for the FEATURE protocol, `DEBUG.md` for DEBUG). Verdicts obey the canonical sub‑agent JSON contract in `protocols/agents/SUBAGENT_COMMS.md` (§ 1.2) with the `verdict` extension documented in R‑2. The read‑only reviewer role `sdd-reviewer` (inspection tools only) has its tool whitelist declared in its PI extension frontmatter at `templates/source/.pi/extensions/agents/sdd-reviewer.md`. Termination by output-token-limit is handled by the dedicated recovery pattern in `develop/TOKEN_LIMITS.md` (TL-3).