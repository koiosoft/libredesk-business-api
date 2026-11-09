---
description: Yaml Compiled orchestrator for the BOOTSTRAP SDD protocol (greenfield skeletal setup) using sub-agents and interactive menus, driving dev-orchestrator.yaml with the test phases and the pre-flight baseline DELIBERATELY SKIPPED.
category: SDD
---

We are starting a new **BOOTSTRAP** cycle.

To do so, follow the instructions on `.sdd/compiled/agents/orchestrator/dev-orchestrator.yaml` — **but with the BOOTSTRAP deviations declared below, which OVERRIDE that file's default flow.**

---

## ⚠️ PROTOCOL IS FIXED: BOOTSTRAP

`PROTOCOL = BOOTSTRAP` is **already fixed by this prompt**. Do **not** open the `resolve_protocol` gate of `dev-user-interaction` with options `[FEATURE, DEBUG, SPEC_UPDATE, BOOTSTRAP]`.

- The instruction file is `.sdd/instructions/BOOTSTRAP.md`.
- The cycle opens with `agent-instructor workflow open --bootstrap` (the `BOOTSTRAP: --bootstrap` mapping in `dev-log-preparation` is the single source of truth for that flag).
- Do **not** ask the user to choose a protocol. The user invoked the BOOTSTRAP prompt; that *is* the choice.

Everything else in `dev-user-interaction` still applies unchanged: read the instruction-file frontmatter, validate `protocol_matches` / `file_exists` / `frontmatter_required_fields_present`, then `set_state: { MODE_AUTO, RUN_INTEGRATION, RUN_UI }` from that frontmatter.

---

## ⚠️ THE BOOTSTRAP DEVIATION — READ THIS TWICE

A BOOTSTRAP cycle builds the **project skeleton** (structure, stack, base conventions, first runnable "hello world"). It does **NOT** build functionality.

**Therefore there are no unit tests to write and no test suite to baseline.** The `BOOTSTRAP.md` instruction file carries **no** `## Unit Test List` / `## Integration Test List` / `## UI Test List` sections, by design. This is not an omission to fix — it is the premise of the protocol.

To honour that premise, you MUST apply the following **two deviations** to `dev-orchestrator.yaml`. They are not optional and they are not negotiable. Do not "helpfully" run them anyway "for safety".

### Deviation 1 — SKIP the pre-flight baseline (`dev-preflight`)

`phase_3_dev_loop` begins with `apply: dev-preflight`. **Skip it.**

Reason: PF-1/PF-2 dispatch a `test-runner` in `baseline` mode to capture the **failing-test set** of the working tree before any edit. A greenfield skeleton has no test suite; the baseline would either fail to resolve a command from `SPEC.md` (which does not exist yet in a meaningful form) or capture an empty set that triages nothing. It is pure waste and, worse, it would consume a `test-runner` dispatch and a `baseline_failures.txt` artifact that the finalization regression gate (F-3) would then try to consume.

- Do **NOT** launch the `test-runner` in `baseline` mode.
- Do **NOT** create `${LOG_DIR}/baseline_failures.txt`.
- Proceed directly from `dev-log-preparation` to `dev-coder` (W-1).

### Deviation 2 — SKIP the entire test phase block (`phase_4_unit_test`, and transitively 5 & 6)

`phase_3_dev_loop` ends with `branch: phase_4_unit_test`, and `phase_4_unit_test` runs `apply: dev-testing` + `apply: dev-loop` **unconditionally** (unlike `phase_5` / `phase_6`, which are guarded by `optional: run_integration…` / `optional: ui_list_present`).

**Skip `phase_4_unit_test` entirely.** Do NOT apply `dev-testing` nor `dev-loop` with `TEST_MODE: unit`.

- `phase_5_integration_test` and `phase_6_ui_test` are already skipped by their `optional:` guards (`run_integration: false` / `run_ui: false` in the BOOTSTRAP frontmatter) — you do not need to do anything special for them, but do not resurrect them.
- Route directly from the completed dev loop (`dev-coder` returning `phase_done` / `return_to_caller`) to **`phase_7_review`**.

**This deviation is the whole point of this prompt.** The generic `sdd-compiled-orchestrate-develop` prompt does *not* skip these phases; if you follow it, the run will enter `phase_4` and attempt to run a unit suite that does not and must not exist. You are here precisely because that phase does not apply.

---

## The phase path for BOOTSTRAP (authoritative)

```
phase_1_user_interaction   → protocol FIXED to BOOTSTRAP; validate frontmatter; set_state
phase_2_prepare_logs       → workflow open --bootstrap
phase_3_dev_loop           → [SKIP dev-preflight] → dev-coder  → [SKIP phase_4]
phase_7_review             → dev-review   (Reviewer List of BOOTSTRAP.md)
phase_8_finalization       → dev-finalization (regression gate is a no-op: no baseline)
done
```

The deliverable of a BOOTSTRAP cycle is:

- `.sdd/core/SPEC.md` — project specification, created/updated by the bootstrapping tasks; and
- `.sdd/core/CONVENTIONS.md` — base conventions, created/updated likewise; and
- every task in `.sdd/instructions/BOOTSTRAP.md` marked `[x]` **via the CLI**.

Those two core files are what every later FEATURE/DEBUG cycle consumes. Getting them right is the success criterion of this cycle — not a test count.

---

## Scope — how much you may read

Before the cycle is open, and to resolve the protocol, you may read **only**:

1. The compiled orchestrator and the modules it needs to run the current phase.
2. `.sdd/instructions/BOOTSTRAP.md` — the instruction file.
3. The cycle LOG directory once `workflow open --bootstrap` has created it.
4. Strictly ignore files in .sdd/inputs.

**Do not recon the project.** The orchestrator coordinates; it does not investigate. Reading the source tree, git history, specs, or unrelated configuration is out of scope and burns the cycle's budget before any work starts.

Specifically, before the first dispatch do **not**:

- walk the repository (`find lib/`, `ls` of feature trees, `git log` / `git diff` / `git show`);
- read source files, specs, or `.sdd/config.json` to "understand the project";
- re-read this prompt, the protocol sources, or the sub-agent definitions you were already given.

The context you need for the work arrives **inside the tasks**, not from a survey of the repository. The workers inspect the code; the orchestrator dispatches and tracks.

---

## Orchestrator execution contract — READ THIS FIRST

You (the orchestrator) hold an explicit permission: `bash: "agent-instructor *" → allow`. Bash is deny-by-default EXCEPT for `agent-instructor`, and that is deliberate — it is your **only allowed mutation path** for cycle state.

**You MUST run the SDD CLI yourself, directly, via bash. Do NOT delegate these to workers.** Workers edit code and write their task Justification; they never touch cycle state.

Run these yourself, serialized (one at a time, NEVER in parallel):

- `agent-instructor workflow open --bootstrap`
- `agent-instructor workflow add --task/--test`
- `agent-instructor workflow update --file <TASK_ID>.md --status completed`
- `agent-instructor workflow review list --json`
- `agent-instructor workflow review mark --ack <ACK_ID> --status approved`
- `agent-instructor workflow summary`
- `agent-instructor workflow close`

Hard rules:

1. NEVER hand-edit `.sdd/instructions/BOOTSTRAP.md` checkboxes or INDEX rows.
2. NEVER delegate `workflow *` commands to a worker or sub-agent.
3. The INDEX moves ONLY via `workflow update`; the Reviewer List ONLY via `workflow review mark`. The CLI owns all cycle state.
4. Serialize writes: ONE `workflow *` command at a time; parallel calls corrupt the shared instruction file.
5. **The two deviations above are hard rules of this cycle.** Entering `dev-preflight` or `phase_4_unit_test` is a protocol violation for BOOTSTRAP — it runs work the protocol explicitly excludes.

## Warning:

If it asks you to use it, remember that agent-instructor is accessible in the shell since it is a CLI tool.
