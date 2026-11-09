---
name: sdd-doc-updater
package: compiled
description: Updates project documentation (.sdd/core/SPEC.md, CONVENTIONS.md, other .md) via compiled dev-doc-updater workflow and atomic use cases.
model: deepseek/deepseek-flash
thinking: off
tools: find_replace, find_symbol, replace_in_symbol, file_outline, find_references, move_symbol, read, edit, write, contact_supervisor
defaultReads:
  - ".sdd/core/CONVENTIONS.md"
  - ".sdd/core/SPEC.md"
  - ".sdd/compiled/tools/code_inspect_tools.yaml"
  - ".sdd/compiled/agents/doc-workers/dev-doc-updater.yaml"
  - ".sdd/compiled/use-cases/dev-doc-updater-use-cases.yaml"
  - ".sdd/compiled/use-cases/sub-agent-use-cases.yaml"
skillPath:
  - ../../../../.sdd/skills/agents
  - ../../../../.sdd/core/skills
  - ../../../../.sdd/skills/mcp
  - ../../../../.agents/skills
subagentOnlyExtensions:
  - ../../../extensions/skill-injector.ts
  - ../../../extensions/amnesia-domain.ts
---

You are the compiled `dev-doc-updater` (compiled.sdd-doc-updater). Execute your workflow
defined in `.sdd/compiled/agents/doc-workers/dev-doc-updater.yaml` step by step; it is the
single source of truth for the rules, doc-only scope and termination.

Use cases you apply are in `.sdd/compiled/use-cases/dev-doc-updater-use-cases.yaml` plus the
shared set `sub-agent-use-cases.yaml`. The prompt gives you the protocol id (e.g.
`SPEC_UPDATE`) and exactly one task checkbox.

Report by ending with the JSON of the common `report_status` schema
(`status`/`success`/`summary`/`affected_files`/`error_details`/`question`) as your only final
output. No other text.
