---
name: role.debugger
description: Permission profile for role.debugger (native permission key).
permission:
  tools:
    "*": allow
    ls: deny
    find: deny
    grep: deny
  bash:
    "*": allow
    "ls*": deny
    "find*": deny
    "grep*": deny
    "cat*": deny
---

PERMISSION-ONLY profile. No runtime body.
