---
description: Finalization protocol — CLI-driven summary, close, and user notification.
category: SDD
---

> **Principle**: finalization is done **via the CLI** (`agent-instructor workflow summary` + `workflow close`). The CLI is the single source of truth for the cycle state. **Do not** read `.sdd/instructions/${PROTOCOL}.md` to count marks or edit `INDEX.md` by hand.

### F-1: Generate Final Summary (CLI)

1. Review the cycle state via the CLI:
   - `agent-instructor workflow summary`
   - (Optional, machine-readable) `agent-instructor workflow summary --json`

2. Confirm every artifact is `Completed`. If any `Incomplete`/`Pending`/`Failed` item remains, fix it (re-run its `workflow update`) **before** continuing.

3. Derive the `finalization-summary.md` artifact (optional) in `${LOG_DIR}` using `write`, **based on the output of `workflow summary`** — do not re-read the instructions file or re-count marks by hand.

4. If `RUN_INTEGRATION == false`, mention that integration was skipped.

#### Implementation (IMPORTANT — avoid role confusion)
- F-1 and F-2 are **lightweight** steps executed directly (CLI + notification). **No sub-agents required**.
- F-1: use `write` (artifact `finalization-summary.md`, derived from `workflow summary`). F-2: use a notification (`notify`) to the user — **not** a blocking `gate`, since no answer is required.
- **Prohibited**: launching `sdd-worker`, `test-writer`, or `planner` for F-1/F-2 — violates the scope of these roles (TW-3b: test-worker focuses on a single test case; F-1/F-2 are not testing).
  - **Exception:** `sdd-judge` MAY optionally be consulted at close as an **advisory** reviewer (severity summary only, under F-3 below); it never decides and never blocks closure, and it does not produce work. All other sub-agents remain prohibited for finalization.
- If tools are used, prefer `harness: pi` with a lightweight configured model (no providers without an API key).

---

### F-2: Close the Cycle and Notify User

1. **Close the cycle with the CLI** — the single point of control. It verifies all artifacts are `Completed`, stamps a closure date in the `INDEX.md` header, and clears the `ACTIVE_CYCLE` pointer. Before running workflow close, evaluate the F-3 regression gate. Regardless of its outcome the cycle still closes: F-3 may either reactivate correction loops (bounded) or record open regressions as a FOLLOW_UPS report, but it must never leave the cycle unclosed. Then run:
   - `agent-instructor workflow close`

   - If `workflow close` aborts (any artifact not `Completed`), fix the incomplete item(s), re-run their `workflow update`, then re-run `workflow close`. Never bypass it by editing `INDEX.md` or deleting `ACTIVE_CYCLE` manually.

2. **Notify** the user of the final summary via `notify` (non-blocking — the run continues and stops; no answer is awaited):
   - *"✅ FEATURE Protocol — Complete"*
   - Show the summary table with task status (from `workflow summary`).
   - If tests passed: *"✅ All tests passed."*
   - If tests failed: *"❌ Some tests failed. Check the logs."*

---

### F-3: Regression Gate (conditional)

- **Evaluation order note:** F-3 is evaluated before F-2's workflow close even though it is documented after it.
- **Purpose:** handle **UNRESOLVED NEW regressions** at close by asking the human for a free decision **WITHOUT ever preventing eventual closure**. A development cycle MUST **eventually** close, because an unclosed cycle keeps `ACTIVE_CYCLE` occupied and blocks starting another cycle. Pre-existing failures (present in `baseline_failures.txt`) never activate this step.
- **Condition to ACTIVATE this step:** across all executed test modes there remains **>=1 unresolved `new_failing_files` entry** (i.e., still failing after the loop's bounded retries, or `Skip` was chosen on new failures). If every remaining failure is pre-existing (present in `baseline_failures.txt`) or there are none, **SKIP F-3 entirely** — inform and close directly (the common case, stays lightweight).
- **When activated:** the orchestrator builds the per-mode consolidation from the data it already observed during the loops, e.g.:
  ```
  unit:        X new / Y pre-existing
  integration: X new / Y pre-existing
  ui:          X new / Y pre-existing
  ```
  It **PRESENTS** this consolidation as context, then opens an **OPEN GATE** (fail-closed — an explicit written human answer is required; consent is **never** inferred — §6.7). The gate does **NOT** offer a fixed menu; the human replies with a **free directive** and the orchestrator acts on that explicit answer (it never branches by inference — §6.7).
- **Examples of valid human directives** (illustrative, **NOT** exhaustive, **NOT** selectable options): continue the correction loop for one/all modes; continue with only a subset of the incidents; re-run tests applying a criterion not previously used; accept the open regressions and close with a `FOLLOW_UPS` report; abort. These illustrate what the human **may** ask for — they are not a closed option list.
- **Handling:** the orchestrator executes the explicit directive (e.g., re-enter testing/`LOOP.md` fix cycles — iterations still capped at 3 by `LOOP.md` — or run a requested re-test), then **RETURNS TO THIS SAME GATE** so the human sees the updated state. This repeats until the human issues a **closing directive**.
- **Closing directives:** any directive that ends the cycle proceeds to write `${LOG_DIR}/followups.md` recording each unresolved new regression (`FILE::TEST` + `ERROR` line + mode) when debt is being accepted, then runs `workflow close`. There is **NO** path that leaves the cycle permanently open: if the human gives no explicit answer the gate stays **blocked (fail-closed)** rather than silently continuing or silently closing.
- **Optional advisory:** the orchestrator MAY dispatch `sdd-judge` to summarise severity **before** opening the gate; the judge **informs** the human but **never decides** closure and never blocks it.
- **Rationale note:** `LOOP-1` asks retry/skip/abort mid-loop; F-3 is the final **OPEN HUMAN decision** on how to handle leftover new regressions. It is intentionally **unbounded in choices** but **bounded in outcome** (the cycle always reaches closure).
