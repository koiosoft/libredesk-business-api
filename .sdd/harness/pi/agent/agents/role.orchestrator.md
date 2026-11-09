---
name: role.orchestrator
description: Permission profile for role.orchestrator (native permission key).
permission:
  tools:
    "*": allow
    edit: deny
    write: deny
    find_replace: deny
    replace_in_symbol: deny
    move_symbol: deny
  bash:
    # Default: deny. Only the read-only/CLI verbs below are re-opened.
    "*": deny

    # SDD CLI — the orchestrator's only allowed mutation path.
    "agent-instructor *": allow

    # Read-only inspection.
    "git status*": allow
    "git diff*": allow
    "git log*": allow
    "git show*": allow
    "ls *": allow
    "cat *": allow
    "head *": allow
    "tail *": allow
---

PERMISSION-ONLY profile. No runtime body.
# NOTE: `bash: "agent-instructor *"` is deliberately the ONLY non-read-only bash
# verb granted to this role. It is the orchestrator's mutation channel for SDD
# cycle state (workflow open/add/update/review/close). The orchestrator runs it
# directly and serialized; it must not be delegated to sub-agents.
