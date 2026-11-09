---
name: jcodemunch
description: Use jcodemunch MCP tools to retrieve code. jcodemunch is Tier 2 of the project retrieval cascade and REPLACES the classic Unix tools (grep, ls, find, cat) for catalog / cross-ref / signature / semantic lookups. Prefer its direct tools; if they are not available in your tool list, reach them through the `mcp` gateway. Escalate to read (Tier 3 fallback) only as the cascade prescribes.
---

# jcodemunch (MCP retrieval — replaces grep / ls / find / cat)

## Spirit of this skill

**Do NOT reach for classic Unix tools (`grep`, `ls`, `find`, `cat`) or premature heavy reads to
locate code.** This project's retrieval cascade (`.sdd/protocols/tools/CODE_INSPECT_TOOLS.md`)
routes those lookups through pi-tools first and **jcodemunch** next. jcodemunch is what you use to
replace them:

| Classic tool | What it must become |
|---|---|
| `grep` / `grep -r` | `search_symbols`, `search_text`, `search_columns` |
| `find` | `search_symbols` / `get_file_tree` |
| `ls` | `get_repo_outline`, `get_file_tree`, `get_file_outline` |
| `cat` (to read a symbol) | `get_symbol_source`, `get_context_bundle` |

## The retrieval cascade (Tier by Tier)

| Tier | Tool | Trigger | Cost |
|---|---|---|---|
| **1** | **pi-tools** (`find_symbol`, `find_references`, `find_replace`, `file_outline`) | exact-name / structural / surgical | low–moderate |
| **2** | **jcodemunch** | catalog / cross-ref / signature / semantic | **minimal** |
| 3 | `read` (full file) | absolute last resort | high |

**Escalation is by SCOPE, not a rigid order.** Try Tier 1 for targeted lookups; **escalate to
jcodemunch (Tier 2)** whenever Tier 1 does not fully resolve the query:

- `find_references` returns empty/partial but you know the symbol is used elsewhere.
- You need cross-references, signatures, summaries, or ranked results beyond a bare name match.
- The query is semantic (concept → code) rather than exact-name.
- Tier 1 resolves the name but not the relationships/impact.

Escalate to `read` (Tier 3) as fallback only.

## How to call jcodemunch

### Option 1 — direct tools (prefer these when present)
If your tool list exposes jcodemunch tools, call them directly. Dispatch any action through `order`:
`order(action, args)`. Discover actions with `menu(query)`; get a task→action pick with `route(task)`.

### Option 2 — the `mcp` gateway (when the direct tools are NOT in your list)
If you do not have the direct tools, reach jcodemunch **through the `mcp` tool**:

```json
{"server": "jcodemunch", "tool": "order", "args": {"action": "<action-name>", "args": { ... }}}
```

## Summary of Core Actions

- `search_symbols`: Find symbol names across the repo matching a text or pattern.
- `get_symbol_source`: Get the implementation of a specific symbol by symbol ID or path.
- `get_ranked_context`: Multi-hop symbol retrieval with token budgets.
- `get_repo_outline` / `get_file_tree`: Structure of repo and folders.
