---
description: Reusable reference and setup instructions for scheduling the 5-minute orchestrator watchdog heartbeat via pi-scheduler.
category: SDD
---

# SDD Orchestrator Watchdog (5-minute Interval Heartbeat)

This document contains the prompt directive and setup instructions for configuring a recurring 5-minute heartbeat task using the `pi-scheduler` extension. It prevents orchestrator idle-hangs, forces prompt attention on context police alerts, and guarantees continuous forward progress in the SDD development cycle.

## Quick Interactive Slash Command (TUI Console)

According to the official `pi-scheduler` syntax:
```text
/schedule [action] [type] <schedule> :: <payload>
```

To schedule this 5-minute recurring prompt directly in your Pi console, run:

```text
/schedule prompt every 5m :: [ORCHESTRATOR HEARTBEAT & ADVANCE DIRECTIVE] 1. Check active sub-agent status immediately. If finished, collect result; do not wait passively. 2. Mandatory attention to context alerts: if [pi-child-context-listener] reported an alert, intervene on worker immediately. 3. Mode AUTO routing: if MODE_AUTO is true, escalate worker doubts directly to sdd-judge, do not ask user. 4. Advance workflow: if idle, consult .sdd/compiled/models.yaml and launch next pending task. 5. Keep development cycle active until user confirms closure.
```

### Management Commands from `pi-scheduler`:
- List active tasks: `/schedules`
- Include inactive tasks: `/schedules all`
- Show run history: `/schedules history`
- Cancel a task: `/schedule-cancel <id-or-prefix>`
- Disable a task: `/schedule-disable <id-or-prefix>`
- Enable a task: `/schedule-enable <id-or-prefix>`
- Remove a task: `/schedule-remove <id-or-prefix>`
---

## 1. The Watchdog Heartbeat Prompt (English)

```markdown
[ORCHESTRATOR HEARTBEAT & ADVANCE DIRECTIVE]
This is an automated periodic heartbeat from the watchdog scheduler to guarantee forward workflow momentum:

1. CHECK ACTIVE SUB-AGENTS (DO NOT IDLE):
   - Inspect the status of active or background sub-agents immediately.
   - If a sub-agent has completed or parked its output, collect its result now. Do not wait passively.

2. MANDATORY ATTENTION TO CONTEXT ALERTS:
   - Check for any pending warnings from `[pi-child-context-listener]` or `pi-child-context-police`.
   - Never ignore context police alerts: INTERVENE IMMEDIATELY on the worker following the corrective instructions provided in the alert.

3. AUTO MODE DECISION ROUTING:
   - If `MODE_AUTO == true` (or autonomous mode is active), DO NOT pause to ask the user questions or open gates for sub-agent doubts. Escalate ambiguities and blocks directly to `sdd-judge`. Ask the user ONLY if `MODE_AUTO == false`.
4. ADVANCE WORKFLOW (DISPATCH NEXT TASK):
   - If no sub-agent is in-flight and tasks remain unchecked in the current phase, resolve the model strictly via `.sdd/compiled/models.yaml` and launch the next task immediately.
   - If the current phase has concluded, advance to the subsequent phase as defined in `.sdd/compiled/agents/orchestrator/dev-orchestrator.yaml`.

5. PERSISTENCE:
   - Do NOT abort or declare the development cycle finished until the user explicitly confirms the cycle closure. Keep driving the state machine forward.
```

---

## 2. Command Payload to Schedule via `schedule_task` Tool

When in a session with the `schedule_task` tool available, invoke:

```json
{
  "name": "orchestrator-watchdog-5m",
  "description": "5-minute periodic watchdog to wake the orchestrator, process finished tasks, attend context police alerts, and advance the SDD workflow.",
  "type": "interval",
  "schedule": "5m",
  "action": "prompt",
  "prompt": "[ORCHESTRATOR HEARTBEAT & ADVANCE DIRECTIVE]\n1. Check active sub-agent status immediately. If finished, collect the result; do not wait passively.\n2. Mandatory attention to context alerts: if [pi-child-context-listener] reported an alert, intervene on the worker immediately following the alert directive.\n3. Mode AUTO routing: if MODE_AUTO is true, do NOT ask the user; escalate worker doubts/blocks directly to sdd-judge.\n4. Advance workflow: if idle, consult .sdd/compiled/models.yaml and launch the next pending task without delay.\n5. Keep the development cycle active until the user explicitly confirms closure."
}
```

---

## 3. How to Cancel After User Closure

Once the cycle is officially completed and reviewed:

```json
{
  "name": "cancel_scheduled_task",
  "arguments": {
    "id": "orchestrator-watchdog-5m"
  }
}
```
