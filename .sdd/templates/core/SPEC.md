# SOFTWARE DESIGN DOCUMENT (SDD) — <project-name>

> Scope: project-local only. This document describes the software project
> itself: objective, architecture, components, data, quality standards.
> It does NOT describe SDD protocols or orchestrators — those live under
> `.sdd/core/dev-cycle/` and `.sdd/protocols/`.
> Fill every section below; delete this line when done.

## 1. SYSTEM OBJECTIVE

### 1.1 Purpose Statement
- One paragraph: what the system does, for whom, and why it exists.

### 1.2 High-Level Technical Objectives
- Bullet list of the technical goals that drive the design.

## 2. ARCHITECTURE AND DESIGN RULES

- State the architectural style (stateless CLI, service, library, pipeline...).
- Describe the main layers and how they relate.
- Include a component diagram or topology sketch if it helps.

### 2.1 Dependency and Environment
- Languages, runtimes, versions.
- Environment isolation rule (virtualenv, container, ...).
- Launcher / entry point and why it must be used.
- External CLI tools the project depends on.
- File-based contracts this project relies on at runtime.

### 2.2 Project Topology and Directory Structure
- Tree of the project root, one line per entry, with the role of each folder.
- Where the project installs a workspace of its own distributed documents, classify every
  entry by **lifecycle**, not just by content: which trees are bundled tooling that an
  update replaces wholesale, and which are work the user owns that an update must never
  touch. Name both sets; a tree that belongs to neither is undocumented.
- Show nested groupings inside the replaced trees rather than flattening them — a subtree
  that ships inside another is content of it, not a sibling entry point.
- Spell out the workspace tree with its lifecycle class on each line. The shape below is the
  reference for a project that has run `init`; delete the class column only if the project
  has no bundled/owned split at all.

  ```
  .sdd/                          # the installed workspace
  ├── templates/                 # STATIC — replaced by init/update
  │   ├── core/                  #   source-of-truth maquettes: SPEC.md, CONVENTIONS.md,
  │   │                          #   dev-cycle/{PRE-FLIGHT,REVIEW,TEST_CONVENTIONS}.md,
  │   │                          #   git/COMMITS.md, skills/, specs/
  │   ├── plans/                 #   plan shapes per protocol (FEATURE.md, DEBUG.md, ...)
  │   └── instructions/
  │       ├── prompts/           #   master LLM system prompts per protocol
  │       └── maquettes/         #   master {{PLACEHOLDER}} output shapes per protocol
  ├── protocols/                 # STATIC — generic agent/tool protocols
  ├── compiled/                  # STATIC — compiled agents, tools, use-cases, models
  ├── harness/                   # STATIC — pi harness (agents, prompts, roles, extensions)
  ├── skills/                    # STATIC — skill catalogue
  ├── context-policies/          # policy catalogues resolved by the evaluator
  ├── core/                      # OWNED — this project's filled-in SPEC/CONVENTIONS/dev-cycle
  ├── inputs/                    # OWNED — REQUIREMENTS.md and friends
  ├── plans/                     # OWNED — plan sources (`workflow open` reads them)
  ├── instructions/              # OWNED — destination `generate` writes rendered docs into
  └── logs/                      # OWNED — cycle history; `init` never deletes it
  ```

  The two halves are the contract: everything under a STATIC root is regenerated from the
  bundle on every `update`, so it is authored in `infrastructure/templates/source/` and any
  hand edit in a project copy is lost on the next run. Everything under an OWNED root is
  durable work that survives `update` untouched and is never shipped as real content by the
  template — the template carries its *shape*, placeholders included, not a project's answers.
  Note that `.sdd/instructions/` is an OWNED destination while
  `.sdd/templates/instructions/{prompts,maquettes}/` are its STATIC sources: `generate` reads
  the second pair and writes the first, which is why the master templates were relocated out
  of `.sdd/instructions/` into the static tree.

### 2.3 Operational Contract (CLI surface)
- List every command the project exposes, one line each: invocation and purpose.
- State which lifecycle commands exist and what each one is allowed to touch. Where a
  command replaces bundled content, name the exact set of trees it may overwrite and the
  exact set it must preserve; that split is the contract consumers rely on, not an
  implementation detail.
- Where a command reports or mutates state carried in a shared vocabulary (statuses,
  verdicts), say which axis of that vocabulary it belongs to. Two orthogonal axes that
  share a flag spelling must be told apart in the help text itself.
- Reference invocation for the workspace lifecycle and cycle surface — one line each,
  expand or delete entries to match this project:
  - `init [--force]` — install the bundled workspace into the project root. Refuses when
    `.sdd/` already exists; `--force` opts back into the destructive wholesale replace.
  - `update` — refresh the STATIC tooling roots (`templates/`, `protocols/`, `compiled/`,
    `harness/`, `skills/`) only. Non-destructive by construction: `core/`, `inputs/`,
    `plans/`, `instructions/` and `logs/` are never read, written, deleted or moved here.
  - `generate [--feature | --debug | --bootstrap | --core-specs | --docs]` — render an
    instruction document from the STATIC master prompts and maquettes under
    `.sdd/templates/instructions/` into the OWNED `.sdd/instructions/` destination.
  - `workflow open` / `add` / `update` / `summary` / `judge` / `review` / `list` / `close`
    / `reopen` — the cycle facade. `add` accepts dynamic DoD statements, per-criterion ACKs
    and required skills; `update --status` writes only the four queue states; `review mark`
    records the `approved` / `correction` verdict on an ACK; `close` gates on both axes and
    stamps `- **Closed**`; `reopen [--cycle <ID>]` restores the `ACTIVE_CYCLE` pointer and
    strips that marker without touching any status or verdict.
- `session evaluate` — Single-pass evaluator that reads session traces, queries JEV, and emits structured alerts. Exit codes: 0 completed, 1 usage error, 2 policy error, 3 input error, 4 classifier error.

## 3. DATA DESIGN AND PERSISTENCE

- What is persisted, where, and in what format.
- Configuration files and their defaults.
- Input / output artifacts and their lifecycle.
- Where the workspace separates bundled content from user data, record which half each
  artefact lives in: a file under a replaced tree is regenerated on every update and must
  be authored in the template, while a file under a preserved tree is durable work that the
  template must never carry.

Tracked artefacts:
- `.sdd/context-policies/` — declarative JEV policy catalogues (YAML), resolved by
  `session evaluate` via `--policies`, default `<root>/.sdd/context-policies/subagent/policies.yaml`.
  - `.sdd/context-policies/subagent/` — policies applied to sub-agent sessions.
  - `.sdd/context-policies/orchestrator/` — policies applied to orchestrator sessions.

## 4. CORE COMPONENTS

For each major component, one subsection:

### 4.N <Component Name>
- **Purpose:** what it does and why it exists.
- **Location:** file(s) / module(s).
- **Trigger:** how it is invoked.
- **Process:** the steps it performs.
- **Error Handling:** how failures are surfaced.
- **Lifecycle:** whether the component's data is replaced by an update or preserved
  across one, and which command owns that decision.

The three subsections below are worked examples of that contract in this project's own
tooling — replace them with the project's real components, keeping the shape.

### 4.a Workspace lifecycle commands (`init` / `update`)
- **Purpose:** install and refresh the bundled tooling of this project's workspace without
  ever destroying the work the project owns. The two commands are the only writers into the
  replaced trees, so the static/preserved split is enforced here and nowhere else.
- **Location:** the initialization support module that owns the list of replaceable tooling
  subtrees, and the domain structure module that declares the two classes of workspace path.
- **Trigger:** `init [--force]` for a fresh workspace; `update` for a refresh.
- **Process:** `init` refuses to run on a workspace that already exists — it raises with the
  exact wording "Project already initialized. Use 'update' to update tooling or 'init
  --force' to overwrite." — unless `--force` opts back into the destructive wholesale
  replace. `update` iterates the declared tooling roots only (templates, protocols,
  compiled, harness, skills), removes each destination subtree before copying so a stale
  file cannot survive a refresh, and touches nothing outside that list: the project's core
  documents, inputs, plans, generated instructions and cycle logs are preserved by
  construction. Both stamp the version marker last, so the drift gate agrees with the code
  that just landed.
- **Error Handling:** an aborted `init` leaves the workspace exactly as it found it, because
  the guard runs before any deletion. A tooling root the bundle does not carry is reported
  as a skipped step, not an error, so a partial bundle still refreshes what it ships.

### 4.b Cycle workflow commands (`workflow open` / `add` / `update` / `review` / `close` / `reopen`)
- **Purpose:** drive one development cycle from plan to reviewed closure, keeping queue
  state and review verdicts on separate axes (see §5).
- **Trigger:** `workflow <subcommand>` against the active cycle, resolved through the
  cycle pointer under the logs tree.
- **Process:** `open` links the plan and seeds the artifacts; `add` registers a task, test
  or DoD artifact and can attach acceptance criteria and required skills to it dynamically;
  `update --status` moves a row through the four queue states only; `review mark` records
  the per-criterion verdict; `close` gates on both axes, stamps `- **Closed**` in the index
  header and clears the pointer; `reopen [--cycle <ID>]` is the mirror image — it restores
  the pointer and strips the `- **Closed**` line so review can resume, leaving every status
  and verdict it finds untouched. Reopening while a cycle is active raises with the exact
  wording "A cycle is already active. Close it before reopening another."; reopening with no
  prior cycle raises "No closed cycle found to reopen.".
- **Error Handling:** a failed gate aborts with the offending rows listed and keeps the
  pointer intact so the cycle is resumable; neither route may be bypassed by editing the
  index by hand.

### 4.c JEV Intervention Engine
- **Purpose:** decide whether a session trace warrants an intervention and express that
  decision as data, so no consumer has to re-interpret prose.
- **Location:** the JEV engine module and its classifier adapter; reached through the
  `session evaluate` command listed in §2.3.
- **Scope:** sub-agents only in phase 1. Orchestrator evaluation is deferred; the engine
  reaches it through the same interface when that phase opens.
- **Process:** the eight-option catalogue. Each evaluated window yields exactly one option
  from the closed set (`continue`, `clarify`, `correct`, `constrain`, `pause`, `escalate`,
  `abort`, `nothing_to_evaluate`). The escalation rule promotes the selected option when the
  same signal recurs across consecutive evaluations, so a repeat finding is answered more
  forcefully than its first occurrence.
- **Output contract:** a JSON report emitted on stdout — status, the selected option, alert
  records, and coverage fields (`inputRef`, `sinceOffset`/`nextOffset`, `evaluationsRun`) —
  followed by the exit-code ladder listed on the `session evaluate` entry in §2.3. Failures are reported by exit code,
  never by free text, so the caller can branch on the shape rather than the wording.
- **Error Handling:** contained classifier outages degrade to `nothing_to_evaluate` with
  exit 0; uncontained ones exit non-zero per the ladder.

## 5. CODING AND QUALITY STANDARDS

- Language-level standards — or point to `.sdd/core/CONVENTIONS.md`.
- Error-handling policy for this project.
- Pre-flight / startup checks this project performs.
- Canonical status vocabulary: `Pending` / `In Progress` / `Completed` / `Failed`. These are
  **queue states** set by the worker; `Completed` certifies that the delivery was processed,
  nothing more. Acceptance is the second, orthogonal axis — recorded per acceptance criterion
  (ACK) as a review verdict (`approved` / `correction`) during the Review phase, never
  inferred from a row's status. Closure gates on both axes. There is no fifth queue value:
  rejecting or superseding a criterion is a verdict on that criterion, not a task state.
  Keep this wording aligned with the CLI help and `.sdd/core/dev-cycle/REVIEW.md`.

## 6. CYCLE OUTCOMES (optional)

- Optional: one short section per significant completed cycle.
