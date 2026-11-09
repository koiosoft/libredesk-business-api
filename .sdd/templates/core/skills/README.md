# Project skills

Skills that belong to **this project** and not to a tool or a harness.

## What belongs here

A skill whose guidance only makes sense for this repository's own architecture: a
boundary it drew, a convention it adopted, a subsystem only it has. These are the
skills an outside consumer could not reuse as written.

Each skill is one directory holding a `SKILL.md`:

```
.sdd/core/skills/<skill-name>/SKILL.md
```

The directory name is the skill's identity, and it is the exact string a task writes
inside `## SKILLS_REQUIRED: [...]`. Nesting deeper is allowed — discovery is
recursive, so a group folder may be added once the root holds several skills.

## What does not belong here

| Instead | Goes to |
|---|---|
| Guidance tied to an installed package or harness | the package's own `skills/` directory |
| Knowledge shared across projects | a transversal skills root |
| A tenant-specific correction injected into a sub-agent's prompt | `.sdd/skills/amnesia-domain/` — a companion document, not a skill |

## Declaring a skill to the generator

A skill that lives here may also be declared in `fallback_list.yaml`, beside this
file. That declaration is a plain YAML list of `name` and `summary` entries:

```yaml
skills:
  - name: <skill-name>
    summary: <what it covers, so the generator can tell when a task needs it>
```

The file is **optional**. Skills are discovered by scanning this root, so a skill
present on disk is found whether or not it is declared. The declaration exists for
two cases the scan cannot cover:

- a summary that must reach the generator for a skill whose `SKILL.md` alone is not
  self-describing enough to decide when it applies;
- a summary that marks the skill **mandatory**, in which case the generator must
  include it on every task it emits, regardless of whether the task appears related.
