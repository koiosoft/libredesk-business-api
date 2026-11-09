# TOOL MODULE: jcodemunch

## Rules
1. **Absolute preference for symbol search:** Before using `grep` or `read_file`, use jCodeMunch's `jcodemunch_order` tool with `action: "search_symbols"` or `action: "get_symbol_source"` to locate functions, classes, methods, or variables. These are invoked directly via MCP (the `jcodemunch_order` / `jcodemunch_menu` gateway), never through a CLI wrapper.
2. **Surgical context:** To answer specific questions about a function, use `jcodemunch_order` with `action: "get_symbol_source"` instead of reading the entire file. This saves approximately 96% of tokens.
3. **Impact analysis before editing:** If you are going to modify a symbol, run `jcodemunch_order` with `action: "get_blast_radius"` or `action: "find_importers"` to determine the scope of the change.
4. **Refactoring planning:** Use `jcodemunch_order` with `action: "plan_refactoring"` to obtain an accurate change plan before applying manual edits.
5. **Automatic reindexing:** jCodeMunch automatically reindexes upon startup. If you notice desynchronization, run `jcodemunch_order` with `action: "index_folder"` (local repo, `path` argument) manually.
6. **Fallback:** If `jcodemunch_order` (with `action: "search_symbols"`) returns no results, it falls back to `grep` (which, being `pi-hashline-edit`, is safe but more resource-intensive).

## Direct MCP Access (migration to `@tintinweb/pi-subagents`)
- All jcodeMunch actions (`search_symbols`, `get_symbol_source`, `get_blast_radius`, `find_importers`, `plan_refactoring`, `get_ranked_context`, `index_folder`) are dispatched through the **session-inherited MCP gateway tools**: `jcodemunch_order` (front door, shape `{action, args?, allow_state_change?}`), `jcodemunch_menu` (discover the catalog), `jcodemunch_route` (map a task to the best action). Sub-agents launched via the `Agent` tool inherit them automatically.
- There is **no CLI wrapper** and **no `tool code-search` command**. Do not reference one, and do not launch `agent-instructor` to access these tools from a sub-agent.

## Notes
- jCodeMunch is ideal for finding "where X is" or "what Y does."
- For complex relationships (data flows, architecture), use `codebase-memory` (see `CODE_BASE_MEMORY.md`).
- Always prefer `jcodemunch_order` with `action: "get_symbol_source"` over `read_file` for extracting code.
- Remember that `grep` and `read_file` are now safe thanks to `pi-hashline-edit`, but should be the last resort due to their high token cost.