# sdd-lang.md — declarative language rules for SDD workflows & use cases

## Purpose

Defines the single declarative grammar (YAML) used to express SDD *workflows*, *use-case
dictionaries*, and *harness ports*, so that the separate artifacts stay consistent and the
engine that consumes them is deterministic. The SDD execution stack is moving from prose
(`*.md` rule books) to this compact YAML to save tokens and remove ambiguity.

Three KINDS of artifact exist; each has its own shape (below). References between them use
**stable names** resolved by these rules — never prose.

---

## 1. Artifact kinds

| Kind | Kind marker | Expresses |
| --- | --- | --- |
| Workflow | A role run | A role's run: phases, ordered steps, branches. |
| Orchestrator-mod | `kind: orchestrator_module` | A reusable phase an orchestrator `apply`s; dispatches sub-agents + CLI. |
| Use-case dict | `use_cases:` map | Reusable atomic operations (tool commands) + shared contracts. |
| Port | `use_cases:` map of invocations | Maps a role/workflow onto an external runner (harness). Provider-specific & replaceable. |

Kinds are distinguished by their content, not by a folder: the same grammar may live anywhere.

Shared use cases common to every role live in the **shared use-case dict**; per-role
extras live beside their role. Don't copy a shared case into a role file.

### Named artifacts (referenced by identity, never by path)

The grammar refers to artifacts by their **role**, not by a filesystem location. Folder layout is
free and not part of the language.

| Artifact | Identity used in this document | Owns |
| --- | --- | --- |
| Shared use-case dict | the **shared use-case dict** | The atomic use cases common to every role. |
| Role use-case dict | the **role use-case dict** | The per-role use cases. |
| Canonical result surface | the **canonical sub-agent surface** | The single `report_status` output schema (§4). |
| Channel map | the **channel configuration** | The `channels.<mode>` map a gate resolves `delivery` against (§2). |
| Model registry | the **model registry** | Per-role model options and their `thinking` level. |

---

## 2. Workflow grammar

```yaml
workflow:
  name: <kebab-name>
  entry: <phase_name>            # first phase to run; must exist under phases:
phases:
  <phase_name>:
    steps: <ordered step list>
    # each step is one of:
    #   1) apply  -> invoke a shared/role use case (atomic)
    #   2) branch -> move to another phase or terminal
  ...
```

### Step forms — NORMALIZED (one canonical shape; applied identically everywhere)

A workflow does NOT contain tool commands. It only (1) APPLIES a named use case from a
use-case dictionary, or (2) BRANCHES. The dictionary owns HOW each use case executes.

- Apply a use case (`<uc_name>` must exist in a linked use-case dict):
  ```yaml
  - apply: <uc_name>
    args:   # optional args this use case takes; omit if none
      <arg>: <value>
  ```

- Branch to a phase or a terminal:
  ```yaml
  - branch: <phase_name> | <terminal_name>
  ```
For WORKER roles step kinds are exactly two: `apply`/`branch` (a non-apply, non-branch entry is
invalid). Steps bodies are data only — no free sentences, no inline commands.

#### Orchestrator third kind — `launch` (dispatch a sub-agent)
An ORCHESTRATOR workflow (e.g. dev-orchestrator.yaml) coordinates a cycle by dispatching the
sub-agents described in the protocol. It may use a third step kind:

```yaml
- launch: <sub_agent_name>      # = models.yaml[<role>].name (resolved by the orchestrator)
  task: <task-arg-string-or-template>
  async: true
  # optional: model/thinking resolved from the model registry; wait_result is the consumer
```

An orchestrator still uses `apply` for its own lightweight tools (CLI workflows like
`agent-instructor workflow ...`) and NEVER touches source docs directly. Dispatch targets are
resolved from the **model registry** (`models.yaml[<role>].name`, single definition, §6).

#### Orchestrator module control vocabulary
Within an orchestrator (or an ``orchestrator_module``), the following declarative controls are
allowed IN ADDITION to `apply`/`branch`/`launch` — they keep cycles deterministic without prose:

```yaml
# conditional en-route (no branch_if_* invented names): use `branch` + a predicate via args
- branch: <dest>
  when: <boolean predicate>            # e.g. iterations >= 3, followups_present, binding_mismatch

# per-iteration count / bounded loop
state: { TEST_ITERATION_COUNT: 1 }
- increment: TEST_ITERATION_COUNT

# iterate over a known list (e.g. failing_test_files)
- for_each: <list_var>
  do:
    - launch: ${resolved_agent_name}
      task: ...

# optional phase / mark (only run when a feature flag is set)
phase_...:
  optional: <boolean predicate>
  steps: []

# retrieve an async child result (only legal after a launch)
- wait_result                       # => parse json; outcome branches follow

# ask the user and BLOCK until an explicit answer (only in orchestrator / module)
- gate: <name>                      # stable name, resolvable (§6.2)
  when: <boolean predicate>         # optional: only opens if predicate holds
  options: [<label>, ...]           # optional: closed choices
  delivery: <channel>               # DELEGATED: resolved in config, so the language stays pure

# notify without blocking (the run continues immediately)
- notify: <message>
  delivery: <channel>               # DELEGATED, same as gate
```

Rule: every control consumes only values the previous step produces (no hidden side effects), so
the engine can reason about it. A module ends by returning to the orchestrator via a known
`branch` label.

#### Interaction gates (the only legitimate pause)
A **gate** is a step that suspends the run until it receives an **explicit user answer**. It is
the only legitimate pause in a workflow. The language defines the SEMANTICS (what a gate is,
when it blocks); the TRANSPORT (how the question is delivered) never enters the language — it
is resolved through `delivery: <channel>` exactly like §5 resolves a port to a harness.

**Where `delivery` resolves:** in the configuration artifact that owns the active channel map
(the active mode selects a `channels.<mode>` entry). The channel changes only how the question
is delivered and how the answer arrives — never whether the gate blocks.

**Start-up mode.** Every orchestrator workflow declares the mode its run STARTS in:

```yaml
workflow:
  name: <kebab-name>
  entry: <phase_name>
  mode: terminal            # start-up channel; resolvable in the channel configuration
```

The start-up mode is `terminal` unless the workflow declares otherwise. It is the mode in effect
BEFORE any mode switch runs; a switch prompt changes it at runtime and records the transition.

- **`gate` is a first-class step kind** for orchestrator / `orchestrator_module` roles, alongside
  `apply`, `branch`, `launch`. The bare key `ask_user` is **banned** — it is local dialect.
- **A gate ALWAYS blocks.** There is no informational gate. To inform without blocking use
  `notify`.
- **`notify` never satisfies a gate.** A notification only reports; an unanswered gate stays
  open. Only an explicit answer closes it.
- **A gate is not satisfiable by inference.** Consent is never inferred from unrelated text
  (a generic "continue", a prior message, a cancellation), a timeout, or an implicit default.

A gate is *fail-closed* by default: if it does not receive an explicit answer, the run stays
`blocked` and waits. See §6 for the engine-enforced invariants.

##### Module return labels
A module ends by returning to the orchestrator via a known `branch` label. The vocab of return
labels is CLOSED and NAMED (see §2 / consensus):

| Label | Meaning |
| --- | --- |
| `return_to_caller` | Normal return to the orchestrator phase that invoked the module. |
| `return_to_loop` | Return to the module's own loop without leaving the module. |
| `return_with` | Return AND carry a structured payload to the caller. |
| `stop` | Terminate the module / line of work; no further steps in this module. |
| `done_module` | Canonical terminal label: module finished, return to caller. |

Prose anchors such as `<return to LOOP>`, `<stop>`, or `return dev-orchestrator phase complete`
are **invalid**. A return label must be one of the closed set (or a phase/terminal the caller
declares). Carried values (e.g. a module result) use structured keys, never prose inside the
label.

### Terminals

```yaml
<terminal_name>:
  - apply: report_status
    args: { status: ..., success: ..., error_details: ..., question: ... }
```
Every terminal applies the common `report_status` (see §4). Nothing else may end a run.

`output:` (optional) declares side-file targets, e.g. the task file the justification is
written back to.

### Invariants / prohibitions (parse of MUST-NOT sections)
MUST-NOT rules (e.g. D-3) are not happy-path steps. Express them declaratively:

```yaml
constraints:
  - forbidden: <action_or_tool>      # e.g. run_tests | run_git | read_other_protocols | execute_source
    unless:                          # exact carve-outs from the source .md (READ-FIRST)
      - <allowed case>
  - guard: <use_case>                # allow a use case only on a predicate (pre-flight)
    when: <boolean predicate>        # e.g. not (test_runner | entrypoint | runs_feature_code)
```
Semantics: a violated `forbidden`, or a `guard` whose `when` is false, ends the task
`blocked`/`error` (engine-enforced) — the worker does not need long prose rules.

### Role attributes (parse of Notes/metadata)
```yaml
role:
  context_resets: true          # each invocation starts clean
  single_task_per_run: true
  resume_across_runs: true      # orchestrator may re-launch preserving context
  reader_only: true             # (reviewer/judge) never writes source/test/task
```

### Role-specific outputs (reader / arbiter roles)
Not every role ends with `report_status`. Reader/arbiter roles (reviewer → `verdicts`,
judge → `judge_result`) yield a role-specific result object. Model it as a TERMINAL that
`apply`s a role use case whose schema the role-use-case dict declares:

```yaml
# in the role use-case dict
verdict_report:
  emits: <role schema>        # e.g. common_schema_verdicts / judge_result_schema
# in the workflow terminal
final_review:
  - apply: verdict_report
```
Invariant: a role uses EXACTLY ONE terminal — `report_status` OR its single declared
role-output schema — never prose.



---

## 3. Use-case dictionary grammar

```yaml
common_schema_*:            # optional shared JSON-schema constants (top-level)
use_cases:
  <uc_name>:
    # either a list of tool/command steps:
    steps:
      - command: <tool_name>
        args: { <k>: <v> }
        # - tool metadata/limits may follow
    # OR a pure contract (e.g. report_status) declaring what it returns:
    emits: <schema>         # reference a common_schema_* defined above it
```
Rules:
- Body is a pure atomic command surface: no prose, no governance (no project-rule references here).
- A use case may carry `emits:` when its output is a defined value/schema (vs a side effect).
- Names are global; a workflow step referencing `<uc_name>` resolves to exactly this entry.

### Shared canonical schema (used by every role's exit)

The canonical result object every sub-agent returns:

```yaml
report_status:                  # = same as the canonical sub-agent surface
  output_schema:
    type: object
    additionalProperties: false
    required: [status, success, summary, affected_files, error_details, question]
    properties:
      status:         { enum: [completed, blocked, error] }
      success:        { type: boolean }
      summary:        { type: string }
      affected_files: { type: array, items: { type: string } }
      error_details:  { type: [string, null] }
      question:       { type: [string, null] }
```
Declared once (in the **canonical sub-agent surface** → `report_status.output_schema`).
Every terminal and every port that must force a canonical result validates against it.

---

## 4. `report_status` (the one way a run ends)

- Defined once in the **canonical sub-agent surface** (`report_status`).
- Every workflow terminal calls it with the fixed shape `{status, success, error_details,
  question}`; the engine validates output against `report_status.output_schema`.
- Semantics:
  - `completed` → success true, error_details & question null.
  - `blocked`    → success false, question carries the concrete doubt.
  - `error`      → success false, error_details carries the failure.
- Contract: the run's final emission is exactly that JSON object (structured when the port
  enables it; else as JSON-in-text). No prose precedes/follows it.

**Extension by role (observed: test-runner).** A role may declare its OWN report schema that
ADDS fields on top of the base rather than replacing it (e.g. test-runner adds
`failing_test_files`, `error_type` to `report_status`). Do it in the role dict:

```yaml
# role dict (e.g. test-runner-use-cases.yaml)
schema_runner_report:
  output_schema:
    # ...same base required fields...
    additionalProperties: false
    properties:
      status: { enum: [completed, error, blocked] }
      # ...                  base fields ...
      failing_test_files: { type: array, items: { type: string } }
      error_type:         { type: [string, "null"] }
use_cases:
  runner_report:
    emits: schema_runner_report.output_schema
```
Rule: the base required fields stay (status/success/summary/affected_files/error_details/
question); a role adds its own OPTIONAL extra keys only. Emitters validate against the role
schema, not just the base.

**Side-file/log outputs.** When a role writes a summary/byproduct to its own path (e.g.
test-runner: structured test log → `log_file_path`), declare it under the workflow `output:`
with an explicit side path — it is ADDITIONAL to the JSON exit, not a substitute for it.



---

## 5. Port grammar

A port is REPLACEABLE. It holds the *least* logic: it maps the named use cases of the SDD
surface onto an external runner call. It MUST NOT define SDD contracts or schemas.

```yaml
use_cases:
  <sdd_key>: "<runner-({ args })>"     # the concrete invocation for this provider
```
- Every key here is an operation of the SDD surface (`launch`, `steer`, `read_result`,
  `resume`, `wait_result`, ...). Their contract is fixed in the protocol; only the invocation
  string is provider-specific.
- Structured-result ports (when the provider supports a schema) reference the *shared*
  schema by identity (the **canonical sub-agent surface** → `report_status.output_schema`)

---

## 6. Cross-artifact consistency rules

1. **Single definition, no duplication**: the shared atomic use cases live in
   the **shared use-case dict**; the canonical result schema lives once in
   the **canonical sub-agent surface**. Others reference, never copy.
2. **Name = identity**: a workflow step, a branch target (phase / terminal / return label), and
   a port key resolve by exact name. Unknown name ⇒ invalid document (fail closed).
3. **A run ends on exactly one terminal schema**: default = `report_status`; a role may
   declare one alternative/extension schema (reviewer `verdicts`, judge `judge_result`,
   test-runner fields) and use it as its single terminal — never prose.
4. **Instructions, not prose**: a step body is data (apply → use case + `args`, or branch).
   sentences; forbid emotional words / guidance in bodies. Longer rationale belongs to the
   canonical protocol documentation (`.md`), not the executable YAML.
5. **Port is thin & swappable**: never put domain logic or result schemas in a port. Swap the
   harness by editing only the port.
6. **Gate = explicit consent (fail-closed, engine-enforced)**: a `gate` whose `when` was not
   satisfied by an **explicit answer** leaves the run `blocked`. Inferring consent from
   unrelated text (a generic "continue", a prior message, a cancellation), from a timeout,
   or from an implicit default is **invalid**. The engine verifies and blocks this; it is not
   a matter of agent conduct.
7. **Ambiguity resolution is delegated, never local**: an orchestrator **cannot resolve** a
   technical/design ambiguity itself — it must **route** it (`launch` to the arbiter) or
   **pause** it (`gate` to the human). Resolving it, prescribing implementation in code, or
   reading source to decide is an **engine-enforced violation** that ends the run `blocked`.
8. **One kind per step, one terminal per run**: a bare step (e.g. `- ask_user_review_ready`)
   is an invalid document. A step is exactly one of the declared kinds; a run ends on exactly
   one terminal.

**Engine-enforced semantics (§6.6–6.8):** these are ENGINE constraints, not conduct rules. A
violated `forbidden`, a `guard` whose `when` is false, an inferred gate consent, or a local
resolution of an ambiguity ends the run `blocked`/`error`. The agent does not need long prose
rules — the engine enforces them. See §7 for why the grammar stays compact.

---

## 7. Token discipline (why the grammar is compact)

- YAML here is meant to be smaller than the prose it encodes: prefer short keys, drop filler
  (`description:` optional), single-line leaf values where unambiguous, and no repeating
  comments/notes that restate a body.
- Keep a rule ONCE (in the document that owns it). Consumers who need it reference that owner
  by name.

### 7.1 Comment policy (executable YAML carries NO semantics)

A comment is NOT documentation. The YAML must be readable and correct **with every comment
removed**. Comments are frequently wrong, silently stale after a rule changes, and they are
re-read on every turn while the engine never validates them.

Allowed — and nothing else:
1. **Trace anchor**: a bare pointer to the owning `.md` section (e.g. `# W-2`, `# R-5`).
2. **Non-obvious tool reason**: a one-phrase why for a line whose purpose cannot be derived
   from the code (e.g. `# reviewer: scoped relaunch, not prior context`).

Forbidden:
1. **Restating a rule that lives in this document or in the protocol** (e.g.
   `# fail-closed: never inferred`, `# delegate ambiguity to sdd-judge`). The rule lives in its
   owner; repeating it here creates a SECOND owner that will drift.
2. **Explaining what a step does** when the step already says it (`# run suite module` next to
   `apply: module_test_run`).
3. **Hiding behaviour the grammar cannot express.** If something can only be understood from a
   comment, the model is wrong: encode it as a step, a key, or a `constraint:` — never as prose.
   This is the root cause of invented dialects such as `branch_if_*`, whose meaning lived in a
   comment instead of in the grammar (§2).

Rule of thumb: if deleting the comment loses information, the information belongs in a `.md`
owner (or in the grammar). If deleting it loses nothing, it was noise.
