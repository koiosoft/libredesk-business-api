---
description: Pre-flight protocol module — dispatch a baseline test capture before any code mutation, and diff it against the closing run to classify pure regressions.
category: SDD
---

> **Purpose:** Establish a **baseline failure set** for the current cycle so that failures observed at cycle close can be separated into *pre-existing* and *introduced-by-this-cycle*. The orchestrator **never runs the test suite itself** — it **dispatches** the `test-runner` sub-agent for that. This module is a dispatch protocol: every step below is either a read, a launch, or a record, never a shell execution.

### PF-0: Precondition — Position in the Cycle

- **Ordering contract (mandatory):**
  1. Pre-flight runs **AFTER** log preparation (`develop/LOG_PREPARATION.md`, L-1) — therefore `${LOG_DIR}` and `INDEX.md` already exist, and `ACTIVE_CYCLE` already points at this cycle.
  2. Pre-flight runs **BEFORE** the development loop (`develop/DEV-CODER.md`, W-1..W-3) and **before any code mutation** of the cycle.
- If `${LOG_DIR}` is unset or unresolvable, **do not** invent one: return to `LOG_PREPARATION.md` (L-1) first, then re-enter this module via `return_to_caller`.
- The baseline must describe the **pre-change** working tree. A baseline captured after the first edit makes every new failure indistinguishable from a pre-existing one.

### PF-1: Decide Whether to Run

- Pre-flight **always attempts** the baseline dispatch. There is **no gate**: the orchestrator reads no settings file for this step, looks up no test-command key anywhere, and does not skip the dispatch merely because no command has been declared beforehand.
- The test command is **never resolved here**. The dispatched `test-runner` derives it from `.sdd/core/SPEC.md` at run time via `read_spec_environment` — the same mechanism used by `develop/testing/RUN.md` (RUN-1). This keeps the protocol portable across stacks (Python, Flutter, Next.js/Node): the runnable full-suite command is defined in the project's `SPEC.md`, never hardcoded in this module.
- **If the project cannot run tests** — `SPEC.md` defines no runnable full-suite command, or the environment cannot execute tests — the dispatched runner returns an error. That condition is handled by PF-2's failure branch (warn + continue); it is **not** decided in advance here.
- **Do NOT fail the cycle.** Pre-flight is an optimisation, not a gate. Proceed to PF-2 whenever `${LOG_DIR}` is resolvable.

### PF-2: Dispatch the Baseline Test-Runner

- Launch the `test-runner` sub-agent in the new **`baseline`** mode. Resolve `model`/`thinking` for the role from `.sdd/models.yaml` exactly as in `develop/testing/RUN.md` (RUN-1) / `DEVELOP.md` § Model Selection.
- The launch payload mirrors the `RUN.md` (RUN-1) shape (task string `"Mode: <mode>. Log file: <path>. Run all <mode> tests."`) with `Mode: baseline` and the baseline-specific task string below. The runner writes to whatever path the caller passes via `"Log file:"`; for baseline that path is `${LOG_DIR}/baseline_failures.txt`.

```
Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
  agent: "<models.yaml['test-runner'].name — e.g. base.test-runner>"
  task: "Mode: baseline. Log file: ${LOG_DIR}/baseline_failures.txt. Run the FULL test suite once, read-only. Derive the test command from .sdd/core/SPEC.md. Capture FAILING tests only. Do NOT fix, modify, or re-run anything beyond the single capture pass.\n\nHARD CONSTRAINT: you MUST NOT modify, create, delete, or format ANY file except the single artifact ${LOG_DIR}/baseline_failures.txt. Do not edit test files, source files, configuration, or the instruction file. Do not run git commands. Do not attempt to FIX anything — this is a capture run, not a remediation run."
  model: "<resolved-model OR omit if models.yaml absent/undefined>"
  thinking: "<low|high|false from model option, omit if undefined>"
  async: true
```
- Capture the returned `<agent_id>` for CLI tracking (`agent-instructor workflow add --agent <agent_id> --model <model>`).
- **Single action per turn:** the launch is the whole turn. On reactivation, retrieve the result with `use_case: wait_result` per `develop/DEV-CODER.md` W-2.
- **On failure of the dispatch** (baseline could not be captured — e.g. `SPEC.md` has no runnable full-suite command, or the environment cannot run tests): warn, record `baseline_failures.txt` as absent, and continue the cycle without pre-flight. Do **not** escalate to `sdd-judge` and do **not** abort the cycle: pre-flight is an optimisation, not a gate.
- On success, proceed to `develop/DEV-CODER.md` (W-1) via `return_to_caller`.

### PF-2b: Baseline report format (see TEST_RUNNER.md § TR-3b)

The baseline report format is defined in the test-runner role module: `.sdd/protocols/agents/test-workers/TEST_RUNNER.md`, section **TR-3b (Baseline Mode)**. PRE-FLIGHT does not restate it; the dispatched runner writes `${LOG_DIR}/baseline_failures.txt` per TR-3b.

### PF-3: Consume the Baseline at Cycle Close

- Record, at this point in the cycle, the contract that will be honoured later: on cycle close, **pure regressions = `current_fails` − `baseline_fails`** (set difference over failing test IDs).
  - **`baseline_fails`** = the set of `FILE::TEST` identifiers parsed from the per-failure blocks of `${LOG_DIR}/baseline_failures.txt` (PF-2b). `ERROR`/`CTX` are human context and are excluded from the diff.
- **`current_fails`** = the failing test IDs reported by the closing test run (`develop/testing/LOOP.md`).
- This diff is **consumed by the finalization / review phase** (`develop/REVIEW.md`, `develop/DEV-CODER.md` W-4, `develop/FINALIZATION.md` § F-3) when classifying the cycle outcome. Failures present in **both** sets are pre-existing and are **not** regressions of this cycle.
- If `baseline_failures.txt` is absent (PF-2 dispatch failure), the diff is undefined: report *all* closing failures as un-triaged rather than silently treating them as regressions.

### PF-4: Order-Dependence and Isolation Flakiness

- Order-dependent and isolation-flaky failures **may differ** between the baseline run and the closing run even with no code change: collection order, shared fixtures, module-level state, and monkeypatch seams can shift a test between passes and fails.
- Therefore a `current_fails` ID absent from `baseline_fails` is a **regression candidate**, not a confirmed regression.
- **Confirm before classifying:** re-run each candidate **in isolation** (the single test file / node ID) and inspect the result. Only a failure that reproduces in isolation is recorded as a regression; a candidate that passes in isolation is reported as an order-dependent / isolation-flaky artifact.
- **The baseline simplifies triage, it does not eliminate it.** Never let the set difference stand in for per-failure confirmation.