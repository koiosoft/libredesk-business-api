---
name: compiled.sdd-reviewer
description: Permission profile for compiled.sdd-reviewer (native permission key).
permission:
  tools:
    "*": allow
    ls: deny
    find: deny
    grep: deny
  bash:
    "*": allow
    # --- Discovery tools: denied (use native pi-tools instead) ---
    # Anchored to the real verb: an unanchored "*cat*" would also match
    # domain words like "clear_category" and legitimate shell uses.
    "ls*": deny
    "find *": deny
    "grep*": deny
    "cat *": deny
    "*rm*": deny
---

PERMISSION-ONLY profile. No runtime body.
