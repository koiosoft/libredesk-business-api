---
description: Fix failed test files using test-writer in FixTest mode for a given mode.
category: SDD
---

### FIX-1: Correct Failed Test Files

**Purpose:** Given a list of failed test file paths and a mode, use `test-writer` in FixTest mode to diagnose and fix each failure.

**Input:** 
- `mode`: unit, integration, or ui — passed by `TESTING.md` (T-5).
- `failing_test_files`: array of file paths.

1. Extract the list of failed test file paths from the input.

2. For **each** failed test file:
   - Launch `test-writer` in FixTest mode:

     #### 🔧 Model Selection (`.sdd/models.yaml`)
     Before launching, check if `.sdd/models.yaml` exists. If present, parse YAML, look up the matching `role`, sort items by `priority` ascending, take the first with a non‑empty `model` (trimmed), then read its `thinking` value **from that model option**. Acceptable values: `"low"`, `"high"`, or `false` (disable thinking). If undefined, omit `model`/`thinking`. Capture the returned `<agent_id>` for use with `agent-instructor workflow add --agent <agent_id> --model <model>`.

     ```
     Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
       agent: "<models.yaml['test-writer'].name — e.g. base.test-writer>"
       task: "Mode: ${mode}. Operation: FixTest. Test file: <failed_test_file_path>"
       model: "<resolved-model OR omit>"
       thinking: "<low|high|false from model option, omit if undefined>"
       async: true
     ```

3. After all failing files are processed, return to `LOOP.md` via the `return_to_caller` label
   (see `sdd-lang.md` §2 — return labels). No prose anchors such as `<return to LOOP>`.