# Common / Transversal Skills

Skills contained in this directory are **transversal agent skills** that apply across multiple sub-agents and workflows.

## Purpose

Guidance on *how to work*: what to reach for first, what to avoid, how to verify. A skill here shapes an agent's behaviour on a task type rather than teaching it a product or a domain. It reads as an instruction to an agent, not as reference documentation for a system.

## Shape

One directory per skill, holding a `SKILL.md`:

```text
common/<skill-name>/SKILL.md
```

```yaml
---
name: <skill-name>
description: <what it covers, so the generator can tell when a task needs it>
---
```

The `name` is the exact string a task writes inside `## SKILLS_REQUIRED: [...]`.
