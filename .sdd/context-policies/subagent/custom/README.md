# custom/ — project overlays for the sub-agent policy

This directory holds **project-owned** policy files. The shipped catalogue next
door (`../policies.yaml`) is the template's; this directory belongs to the
project and is where a project adds its own traps, overrides and suppressions
without touching the distributed artefact.

## Load order

`agent-instructor session evaluate` reads:

1. `../policies.yaml` — the base document;
2. every `custom/*.yaml` in **alphabetical order by file name**.

The files are merged into one document before validation, so what reaches the
engine is a single `PolicySet`. Name files with a date prefix
(`2026-10-18-drupal-hooks.yaml`) so alphabetical order is also chronological
order.

## How merging works

The two kinds of content compose differently, on purpose.

| Block | Merge semantics |
|---|---|
| `options`, `project_overrides`, `suppressions` | **Appended.** An overlay adds entries; it never replaces the base list, so it does not have to restate the eight shipped options. |
| `generic_message`, `classifier`, `trigger`, `lookback` | **Replaced wholesale**, last-write-wins in alphabetical order. A partial merge would splice fields out of a tuning set whose relationships are validated together (`escalation_threshold` must exceed `min_trap_signal`), so an overlay states the whole block or says nothing. |
| `instructions` | **Not overlaid at all.** The question's phrasing is the calibrated dominant parameter of the engine; silently rewriting it would invalidate the thresholds measured against it. |

Consequences to respect:

* A duplicate `option.id` — inside one file, or between the base file and an
  overlay, or between two overlays — raises `PolicyValidationError` naming both
  locations (`custom/<file>:options[j].id`). Reusing a shipped id is an error,
  not an override: give the new option a distinct id.
* `classifier.max_options` bounds the **merged** catalogue (12 with the shipped
  base of 8), so an overlay can add at most four options before validation
  fails.
* A block written as `{}` or `[]` counts as absent: emptiness means "this file
  has nothing to say about that block", and it will not erase the base values.

## What a custom file may contain

Same structure as `policies.yaml`; **every field is optional except that the
file must declare at least one of `options`, `project_overrides` or
`suppressions`** — a file that declares none of them changes nothing and should
be deleted rather than kept.

## Who writes here

The user or the orchestrator. **The engine never writes to this directory**: it
only reads it. Nothing in `domain/jev/`, `infrastructure/jev/` or the CLI will
create, amend or delete a file here, so a file you commit is a file that stays.

## Mandatory header

Every file in this directory starts with exactly these three lines:

```yaml
# custom/YYYY-MM-DD-name.yaml
# origin: <cycle>, <TASKNNN>
# NOTE: an option can only evaluate what the `state` contains. If the criteria needs absent data, it will never fire.
```

`origin` records which development cycle and task introduced the overlay, so a
policy that stops making sense can be traced back to the decision that added it.

The `NOTE` line is not decoration — it is the most common authoring failure.
The classifier only sees the trace window the engine hands it. An option whose
criteria mentions a fact the state never carries (a tool result the recorder
drops, a file path outside the window) cannot match, and no amount of threshold
tuning will make it fire. Write criteria about what appears in the trace.

## Example

```yaml
# custom/2026-10-18-migrations.yaml
# origin: FEATURE-2026-10-18-185548, TASK013
# NOTE: an option can only evaluate what the `state` contains. If the criteria needs absent data, it will never fire.

options:
  - id: "migration_regen_loop"
    action: "steer"
    signal: "semantic"
    message: "You are regenerating the migration output instead of reading it."
    criteria:
      what: "Re-runs the generation command without changing anything between runs"
      not_for: "Running it once to confirm the previous run was reproducible"
      examples:
        - "generate, then generate again, with no edit in between"
```
