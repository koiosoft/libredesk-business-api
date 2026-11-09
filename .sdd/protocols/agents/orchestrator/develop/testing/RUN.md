---
description: Execute the full test suite using test-runner for a given mode and write detailed results to a log file.
category: SDD
---

### RUN-1: Run Tests

**Purpose:** Launch the `test-runner` in the specified mode to execute the full test suite and write detailed results to the provided log file.

**Input:** 
- `mode` (unit, integration, or ui) — passed by `LOOP.md`.
- `log_file_path` — the full path where the test-runner must write the detailed results.

1. Launch the `test-runner` with the specified mode and log file path:

   #### 🔧 Model Selection (`.sdd/models.yaml`)
   Before launching, check if `.sdd/models.yaml` exists. If present, parse YAML, look up the matching `role`, sort items by `priority` ascending, take the first with a non‑empty `model` (trimmed), then read its `thinking` value **from that model option**. Acceptable values: `"low"`, `"high"`, or `false` (disable thinking). If undefined, omit `model`/`thinking`. Capture the returned `<agent_id>` for use with `agent-instructor workflow add --agent <agent_id> --model <model>`.

   ```
   Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
     agent: "<models.yaml['test-runner'].name — e.g. base.test-runner>"
     task: "Mode: ${mode}. Log file: ${log_file_path}. Run all ${mode} tests."
     model: "<resolved-model OR omit>"
     thinking: "<low|high|false from model option, omit if undefined>"
     async: true
   ```

2. Upon `use_case: wait_result`, extract the result:
   - `success`: boolean
   - `failing_test_files`: array of file paths (only if `success == false`)
   - `error_type`: string (only if `error_type == "environment"`)
   - `pre_existing_failing_files`: optional array, produced by TEST_RUNNER.md § TR-3c when a baseline exists
   - `new_failing_files`: optional array, produced by TEST_RUNNER.md § TR-3c when a baseline exists

3. **Return to `LOOP.md`** with the extracted result, via the structured return label
   `return_with` (see `sdd-lang.md` §2 — return labels) carrying `success`,
   `failing_test_files`, `error_type`, `pre_existing_failing_files`, and `new_failing_files` as
   structured keys. No prose anchors such as `<return to LOOP ...>`; the payload is data,
   not text.
   - When the runner returns the baseline-aware split, forward `pre_existing_failing_files` and `new_failing_files` unchanged so LOOP step 4 can route on them.