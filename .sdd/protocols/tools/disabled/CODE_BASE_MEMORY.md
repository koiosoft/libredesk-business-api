# TOOL MODULE: codebase-memory

## Rules
1. **Reindex at session start:** Before any codebase-memory query, call `cbm_index_repository`. If the tool is not available, skip this module silently.
2. **Search priority:**
- For **specific symbols** (functions, classes, methods) → use **jCodeMunch** via its gateway: `jcodemunch_order` with `action: "search_symbols"` / `action: "get_symbol_source"`.
- For **semantic relationships** (call flows, service dependencies, multi-repo architecture) → use **codebase-memory** (`cbm_search_graph`, `cbm_trace_path`).
- For **free text or difficult patterns** (log messages, literal strings) → use **`grep`** (which, with `pi-hashline-edit`, is safe but more expensive).
3. **Consult `codebase-memory` only when you need relationships:** Don't use `cbm_search_graph` to find a simple function if `jCodeMunch` can return it in a single call.
4. **Fallback:** If both systems fail, resort to `grep`/`read_file`.
4. **Direct MCP:** All `cbm_*` tools are session-inherited MCP tools exposed to sub-agents launched via the `Agent` tool. There is **no CLI wrapper** and **no `tool code-search` command**. Do not reference or add one.
## Note
- `auto_watch` is disabled (v0.9.0 buffer-overflow bug with long git branch names). Reindex is required at session start until fixed.
- Remember that `grep` and `read_file` are now safe thanks to `pi-hashline-edit`, but should be the last resort due to their high token cost.