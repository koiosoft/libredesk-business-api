# <project-name> — project conventions

> Scope: project-local only. This document records how code is written in
> THIS project: language standards, architecture rules, dependencies,
> logging, error handling, file contracts. It does NOT describe SDD
> protocols or orchestrators — those live under `.sdd/core/dev-cycle/`
> and `.sdd/protocols/`.
> Fill every section below; delete this line when done.

## 1. LANGUAGE & TYPING STANDARDS
- Language(s) and version(s).
- Style guide (e.g. PEP 8) and any linter/formatter config.
- Typing policy (strict hints? forbidden constructs?).
- Naming conventions per symbol kind (variables, functions, classes, constants).

## 2. ARCHITECTURE & CODE STRUCTURE
- Modularity principle (single-responsibility, layer boundaries).
- Where configuration lives vs. where logic lives.
- Rules against infrastructure leaking into core logic.

## 3. DEPENDENCY MANAGEMENT & ENVIRONMENT
- Environment isolation rule and how it is enforced.
- Launcher / entry point and why it must be used.
- How new dependencies are added, reviewed, and recorded.
- Critical external tools and how their absence is handled.

## 4. LOGGING & ERROR HANDLING
- Console-output policy (helpers, formatting, no raw `print` if applicable).
- Startup / pre-flight checks.
- Exception-handling policy (specific types, no broad `except`).
- How external-process failures are handled.

## 5. FILE-BASED CONTRACTS
- Files that form the project's implicit API.
- Encoding rules for all file I/O.
- Which function is the designated gatekeeper for their presence.

## 6. <PROJECT-SPECIFIC DOMAIN>
- Add one section per project-specific domain not covered above
  (e.g. HTTP client standards, RAG pipeline, UI layer).
- Duplicate as needed; keep each topic self-contained.

## 7. JEV DOMAIN IS A LEAF MODULE
- `domain/jev/` is a leaf: it never imports from `infrastructure`, `application`, or
  `interfaces`. Its only outward dependency is the Python standard library and other
  `domain/` modules.
- JEV is consumed through the `JeveClassifier` Protocol declared in
  `domain/jev/ports.py`. The adapter in `infrastructure/jev/` implements that port
  structurally; the arrow points `infrastructure -> domain` only, so the domain never
  learns the adapter's name, nor that an HTTP provider exists.
- Consequence: anything added under `domain/jev/` must remain importable with no
  network, filesystem, console, or configuration access at module scope. Domain tests
  run against a fake object that merely exposes `ask`.

## 8. LIGHT STARTUP ON THE `session evaluate` PATH
- The `session evaluate` path keeps module-scope imports limited to the standard
  library (`re`, `sys`, `argparse`, `dataclasses`, `pathlib`, `typing`). Every JEV,
  policy, and formatter name is imported inside the function that needs it.
- Forbidden imports on that path: `infrastructure.rag`, `intelligence`, and
  `domain.generate`. Rationale: dispatching through `application/cli/dispatcher.py`
  must not pay for a YAML probe or pull in heavyweight optional dependencies
  (`requests`) that the command never uses.
- Enforce this when adding a helper to the session command: check the module-scope
  import block, not just that the code runs.
