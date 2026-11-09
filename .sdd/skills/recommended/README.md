# Recommended Skills

Skills contained in this directory are **recommended, reusable skill packages** designed to be adopted by target projects or copied directly into their harness infrastructure.

## Purpose

When a project integrates SDD tooling, it can benefit from ready-to-use skills that:
1. Teach sub-agents how to interact with external developer tools and servers (e.g., Model Context Protocol servers like `jcodemunch`).
2. Provide pre-packaged best practices for specific stacks, workflows, and integrations.
3. Serve as a curated library ready to be promoted into the destination harness (e.g., copied into `.agents/skills/<skill-name>/` in a `pi.dev` environment).

## Layout

```text
recommended/
├── mcp/
│   └── jcodemunch/
│       └── SKILL.md      # Guidance on using jcodemunch MCP tools for codebase inspection
└── README.md
```

## How to Promote a Skill to Destination Project Harness

To adopt any skill from `recommended/`, the operator copies it to the desired destination:

1. **Option A: Copy to destination project harness (e.g. `.agents/skills/` in `pi.dev`):**
   ```bash
   cp -R .sdd/skills/recommended/mcp/jcodemunch .agents/skills/
   ```
   The skill is immediately active under `.agents/skills/jcodemunch/SKILL.md` and recognized by the harness.

2. **Option B: Copy to project core skills (`.sdd/core/skills/`):**
   ```bash
   cp -R .sdd/skills/recommended/mcp/jcodemunch .sdd/core/skills/
   ```
   The skill becomes a project-specific skill under `.sdd/core/skills/jcodemunch/SKILL.md`.

Once copied to either location, the skill is discoverable and active for tasks and sub-agents.
