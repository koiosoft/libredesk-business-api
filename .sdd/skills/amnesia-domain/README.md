# Amnesia domains

**This directory holds no skills.** It holds companion documents that make the skills
elsewhere actually get used.

## Why this exists

A model carries prior knowledge about most domains, and that knowledge competes with
the skill it was handed. Asked to work on configuration, it answers from training
rather than from the skill it just loaded. The result is a skill that is present,
correct, and ignored.

An amnesia-domain document removes the competition. It tells the model, for one named
skill, that its prior knowledge of that domain is unavailable — so the only remaining
source is the skill itself.

## Shape

One YAML per target skill, anywhere under this root:

```
.sdd/skills/amnesia-domain/<group>/<file>.yaml
```

```yaml
skill: <name of the SKILL.md this applies to>
domain: "<the body of prior knowledge being neutralised>"
instruction: |
  <what to forget, and what to load instead>
```

The `skill` field is the join: it must match the `name` in the target skill's
frontmatter, or the document is never applied. Folder organisation is free — the
lookup indexes by that field, not by path.

## Writing one

- **Name what is forgotten, specifically.** "You have forgotten the framework's configuration
  system" works; "ignore your training" does not.
- **List the concrete topics**, so the model recognises when it is about to answer from
  memory.
- **End with the load instruction.** The point is to route the model to the skill, not
  to leave it with a gap.
- **One document per skill.** A document spanning several skills cannot be matched by
  the `skill` field.

## What does not belong here

A `SKILL.md`. Anything that teaches rather than neutralises belongs under `agents/`,
`mcp/`, or `.sdd/core/skills/`.
