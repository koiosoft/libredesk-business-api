---
name: role.architect
description: Permission profile for role.architect (native permission key).
mcp:
  - jcodemunch
permission:
  tools:
    "*": allow
    edit: allow
    write: allow
    find_replace: deny
    replace_in_symbol: deny
    move_symbol: deny
  bash:
    # Default: deny. Only the read-only verbs below are re-opened.
    "*": deny

    "git log*": allow
    "git status*": allow
    "git diff*": allow
    "grep *": allow
    "find *": allow
    "ls *": allow
    "cat *": allow
    "head *": allow
    "tail *": allow
    "cp *": allow
    "agent-instructor *": allow
    "./agent-instructor *": allow
---

PERMISSION-ONLY profile. No runtime body.
