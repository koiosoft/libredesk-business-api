# Transversal and Recommended Skills

Skill material that is **not tied to this project's own architecture**.

Everything under this root could be lifted into another project unchanged: it teaches
a technique, a tool, or a domain, never a decision this repository made about itself.
The project's own vertical skills live in `.sdd/core/skills/` instead.

## What lives under this root

| Group | Content |
|---|---|
| `recommended/` | **Passive catalog** of recommended skills ready to be copied/promoted by the operator into the destination harness (`.agents/skills/`) or project core (`.sdd/core/skills/`). Holds external tool integrations such as `mcp/jcodemunch`. |
| `common/` (or `agents/`) | Skills meant for sub-agents: transversal guidelines on how to work, what to prefer, what to avoid. |
| `amnesia-domain/` | **Not skills.** Companion documents that neutralise the model's prior knowledge so a named skill gets used. See that directory's README. |

The group level organizes the tree. Discovery is recursive across `.sdd/skills/`, so a skill is found at any depth as long as it sits in its own directory as `SKILL.md`.

## The shapes a skill takes here

A skill is one directory holding a `SKILL.md`, whose frontmatter carries the identity
the rest of the system references:

```yaml
---
name: <skill-name>
description: <what it covers, so the generator can tell when a task needs it>
---
```

The `name` is the exact string a task writes inside `## SKILLS_REQUIRED: [...]`.

## Where each kind of skill belongs

| The skill is about... | It goes to |
|---|---|
| This project's own architecture, conventions or boundaries | `.sdd/core/skills/` |
| Recommended integrations ready to promote/copy to destination harness | `.sdd/skills/recommended/` |
| Transversal technique or agent guidelines reusable by any project | `.sdd/skills/common/` (or `agents/`) |
| An installed package or the harness itself | the package's own `skills/` directory |
| Correcting the model's prior knowledge for a named skill | `amnesia-domain/`, as a companion document |

## Declaring skills to the generator

Skills are discovered by scanning this root recursively, so a skill present on disk is found
whether or not it is declared. A declaration exists only to supply a summary the scan
cannot derive, and lives in `.sdd/core/skills/fallback_list.yaml`.
