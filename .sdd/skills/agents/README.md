# Agent skills

Skills written for the sub-agents that execute this project's tasks.

## What belongs here

Guidance on *how to work*: what to reach for first, what to avoid, how to verify. A
skill here shapes an agent's behaviour on a task type rather than teaching it a
product or a domain. It should read as an instruction to an agent, not as reference
documentation for a system.

A skill whose subject is a concrete product, framework or API belongs under a group
named for that subject (`mcp/`, or a project-specific group elsewhere) — not here.

## Shape

One directory per skill, holding a `SKILL.md`:

```
.sdd/skills/agents/<skill-name>/SKILL.md
```

```yaml
---
name: <skill-name>
description: <what it covers, so the generator can tell when a task needs it>
---
```

The `name` is the exact string a task writes inside `## SKILLS_REQUIRED: [...]`.

## Writing one

- **Lead with the behaviour, not the background.** An agent loads this to act, so the
  first paragraph states what to do differently.
- **State the failure it prevents.** A skill without a named failure mode reads as
  advice and gets ignored.
- **Be concrete about alternatives.** "Prefer X over Y" beats "use X well".
- **Keep it self-contained.** The agent reads this file alone, with no surrounding
  context about why it exists.
