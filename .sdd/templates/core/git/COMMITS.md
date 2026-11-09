# Git Commit Style & Conventions

This document defines how git commit messages must be constructed across the project. 

Tools like `git cai` or LLM commit generators **must** inspect the staged `git diff` and evaluate changes in `.sdd/instructions/` to determine the type, scope, subject, and body of the commit.

---

## 1. Safety & Secret Detection

Before formatting any commit message:
* **Sensitive Data Warning:** If you detect sensitive information in the staged diff (such as API keys, secrets, tokens, passwords, or credentials), write a clear warning line at the VERY top of the output before the commit subject line.

---

## 2. Instruction-Driven Logic & Precedence

When changes to files in `.sdd/instructions/` are included in the staged diff, they dictate the core "spirit" and type of the commit. 

If multiple instruction files are modified simultaneously in the diff, evaluate them following this **strict hierarchy of precedence**:

1. **`.sdd/instructions/FEATURE.md`**  
   * **Type**: `feat`
   * **Focus**: New features, functional enhancements, or business capability additions.
2. **`.sdd/instructions/DEBUG.md`**  
   * **Type**: `fix`
   * **Focus**: Bug fixes, error resolutions, or unexpected behavior corrections.
3. **`.sdd/instructions/BOOTSTRAP.md`**  
   * **Type**: `chore` / `init`
   * **Focus**: Project initialization, tool setup, or infrastructure configuration.
4. **`.sdd/instructions/SPEC_UPDATE.md`**  
   * **Type**: `docs` / `refactor`
   * **Focus**: Architectural changes, documentation updates, or specification refactoring.

---

## 3. Fallback: Natural Commits

If **no files in `.sdd/instructions/` are modified** in the changes:
* Generate a standard Conventional Commit purely based on the staged code diff provided by the tool context.
* Automatically derive `<type>`, `<scope>`, and `<subject>` from the modified source files, functions, or assets.
* **Documentation-Only Changes:** If every changed file in the diff is a documentation file (e.g., `*.md` outside `.sdd/instructions/` or files under `docs/`), treat the commit as `docs` and describe the changes accordingly without classifying them as features or fixes.

---

## 4. Commit Structure & Task Correlation

Commit messages must strictly adhere to Conventional Commits:

```text
[OPTIONAL: WARNING: Sensitive data detected in diff!]

<type>(<scope>): <short summary>

[task-to-code correlation / context body]