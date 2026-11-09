---
name: compiled.sdd-judge
description: Permission profile for compiled.sdd-judge — execute/read allowed, write denied (native permission key).
permission:
  tools:
    "*": allow
    ls: deny
    find: deny
    grep: deny
    edit: deny
    write: deny
    find_replace: deny
    replace_in_symbol: deny
    move_symbol: deny
  bash:
    # Default: allow (execution is required to evaluate builds/tests/runs).
    "*": allow

    # ---- Write prevention (the actual contract) -----------------------
    "sed -i*": deny
    "*tee *": deny
    "*patch*": deny
    "*truncate*": deny
    "*chmod *": deny
    "*chown *": deny
    "*ln *": deny
    "*install *": deny
    "*> *": deny
    "*>*": deny
    "*>>*": deny
    "rm*": deny
    "* rm *": deny
    "* rm": deny
    "*rmdir *": deny
    "*mv *": deny
    "*cp *": deny
    "*mkdir *": deny
    "*touch *": deny
    "* dd *": deny
    "*dd if=*": deny

    # ---- git: read-only (deny-all, then re-open the read verbs) -------
    "*git *": deny
    "git status*": allow
    "git diff*": allow
    "git log*": allow
    "git show*": allow
    "git branch*": allow
    "git remote*": allow
    "git describe*": allow
---

PERMISSION-ONLY profile. No runtime body.
