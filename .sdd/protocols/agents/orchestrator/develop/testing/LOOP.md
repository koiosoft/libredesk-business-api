---
description: Test execution and correction loop — Run tests, fix failures, and retry up to 3 times.
category: SDD
---

### LOOP-1: Run Tests

**Purpose:** Execute the full test suite for the current `TEST_MODE` and handle failures with retries.

**Input**: `TEST_MODE` (unit, integration, or ui) — passed by `TESTING.md`.

1. Initialize `TEST_ITERATION_COUNT = 1`.

2. **Start the loop:**
   - Construct the log file path:
        log_file_path = ${LOG_DIR}/test_results_${TEST_MODE}_iter${TEST_ITERATION_COUNT}.txt
   - Invoke **`testing/RUN.md`** with the current `TEST_MODE` and `log_file_path`.

3. Upon `use_case: wait_result`, extract the result (`success`, `failing_test_files`, `error_type`, `pre_existing_failing_files`, `new_failing_files`).

4. **Process the result:**
   - **If `success: true`**:
     - The suite result is already recorded in `log_file_path` (`test_results_${TEST_MODE}_iter${N}.txt`) by the `test-runner`; the orchestrator does **not** insert a row or status into `INDEX.md` for the whole-suite result (suite passes are not per-artifact rows).
     - **Sync Marks:** Do **not** hand‑edit the `[ ]` / `[x]` markers in `.sdd/instructions/${PROTOCOL}.md` — mark remaining `TEST_MODE` items as `[x]` **exclusively** via `agent-instructor workflow update --file <TEST_ID>.md --status completed` for each (using the explicit identifier, e.g. `UNIT001`).
     - **Sync CLI Log:** Ensure all test artifacts for `TEST_MODE` in `INDEX.md` are set to `Completed` via the CLI (covered by the per‑artifact updates above).
     - **Return to `ORCHESTRATOR.md`** (phase complete).
   - **If `error_type == "environment"`**:
     - Stop and ask the user to fix the environment.
   - **If `success: false` (test failures)**:
     - **Baseline-aware routing (primary branch):** when the runner returned `new_failing_files` (i.e. the baseline-aware split is present), that set is the ONLY actionable one. `failing_test_files` is NOT passed to `FIX.md` in this branch.
       - If `new_failing_files` is **empty** (all failures are pre-existing): the cycle introduced no regression — record the pre-existing set as known/context (**do NOT** send anything to `FIX.md`, **do NOT** increment `TEST_ITERATION_COUNT`), and proceed as phase-complete (same terminal handling as `success: true` marks sync, but keep the pre-existing list for the finalization summary).
       - If `new_failing_files` is **non-empty**: continue with the retry/FIX logic below, passing ONLY `new_failing_files` to `testing/FIX.md` (never pre-existing ones).
     - **Backward-compat fallback branch (ONLY when the split fields are absent):** if the runner did NOT return the split fields (no baseline captured, so `new_failing_files` is undefined), fall back to the legacy behaviour and pass `failing_test_files` as the actionable set to `testing/FIX.md`. The two branches are mutually exclusive: the fallback fires ONLY when `new_failing_files` is absent.
     - If `TEST_ITERATION_COUNT >= 3`:
       - Ask the user how to proceed (Retry/Skip/Abort) via a `gate`.
       - **No-answer contract (fail-closed):** if the gate does NOT receive an explicit
         answer, the run stays `blocked` and waits. It is **never** satisfied by inference
         (a generic "continue", a prior message, a cancellation) nor by a timeout. "Skip"
         is chosen **only** when the user explicitly chooses it — never as an implicit
         default after no response. See `sdd-lang.md` §6.6.
       - If "Retry": reset counter and go to step 2.
       - If "Skip": log warning and return to `ORCHESTRATOR.md`.
       - If "Abort": stop the cycle.
     - Else:
       - Invoke **`testing/FIX.md`** with the current `TEST_MODE` and the actionable set resolved by the routing above — `new_failing_files` when the split is present, otherwise `failing_test_files`.
       - Upon completion, **increment `TEST_ITERATION_COUNT`** and go back to step 2.