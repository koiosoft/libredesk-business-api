---
description: Generate and review commit message following SDD conventions
category: SDD
---
Apply the rules defined in `.sdd/protocols/TOOLS.md`.

1. Read the commit conventions defined in `.sdd/core/git/COMMITS.md`.
2. Stage all active changes (`git add .`).
3. Execute `git cai --print` to obtain the proposed commit message.
4. Print the proposed message and validate it against `.sdd/core/git/COMMITS.md`.

## Execution Rule:
- **STOP HERE and ask the user for confirmation.** Show the proposed message and ask: *"¿Deseas aplicar este commit?"*
- Execute `git commit` ONLY after explicit confirmation from the user.