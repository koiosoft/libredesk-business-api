# Tool Module: git-cai

## Alias / Command
- `git cai --print`# Tool Module: git-cai

## Rules
1. **Prefer `git cai --print` for commit generation:** When preparing a commit, prefer executing `git cai --print` to generate and inspect the commit message without applying it directly or opening an interactive editor.
2. **Review & Approval:** The generated message must be reviewed against the standards in `.sdd/core/git/COMMITS.md`. Once approved, execute standard `git commit -m "..."` using the generated message.
3. **Fallback:** If `git cai` is not available or fails, fallback to standard git commands and generate the commit message directly via LLM context.

## Alias / Command
- `git cai --print` (Dry run / preview)