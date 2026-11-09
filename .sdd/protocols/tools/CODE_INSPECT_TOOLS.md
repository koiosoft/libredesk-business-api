## Core Tooling (Read, Reason, and Write)

The agent MUST follow this cascading fallback chain for all codebase interactions. This maximizes token efficiency while guaranteeing the safety of every modification.

> **jcodemunch via the `mcp` gateway / skills**: `order`, `menu`, `route`, `set_tool_tier`, `announce_model`, `jcodemunch_guide` are exposed by the jcodemunch server and called **through the session-inherited `mcp` tool**, e.g. `mcp({server: "jcodemunch", tool: "order", args: {action: "search_symbols", args: {"query": "..."}}})` or `mcp({search: "menu"})`. Direct tools should only be used if explicitly listed; otherwise, reach them via the gateway or configured skills. **Prefer pi-tools (Tier 1) for surgical searches** — they are always available and cheaper.

### 1. Information Retrieval (Reading & Searching)

To locate code or context, the agent **MUST** apply this cascading fallback chain. **Protocol first**: follow the cascade strictly; heuristic judgment is only a fallback when the protocol does not resolve the query. Never skip the lighter levels without exhausting them first. **Escalation is by SCOPE, not a rigid tier order**: use the lighter/faster levels for targeted and precise lookups; escalate to skills or broader lookups only when the query requires cross-references or semantic discovery.

| Tier | Tool | Purpose & Trigger | Token Cost |
| :--- | :--- | :--- | :--- |
| **1** | **pi-tools** | **Structural & surgical search (cheapest).** Always available, no bootstrap needed. Replacements for classic Unix tools:
| | | - **Reemplazan a grep**: `find_replace` (text/regex search) and `find_references` (trace usages, calls, imports globally).
| | | - **Reemplazan a find**: `find_symbol` (locate files by function/class/struct).
| | | - **Reemplazan a ls**: `file_outline` (list structural content of a file).
| | | - **Reemplazan a cat**: `replace_in_symbol` (read/edit code blocks) and `clipboard` (text fragments).
| | | Cheap while scoped; escalate to Tier 2 for catalog navigation and rich cross-references. | **Low–Moderate** (only matching lines/names) |
| **2** | **`jcodemunch` (Skills/MCP)** | **Artifact & catalog retrieval via skills or `mcp` gateway.** Call `mcp({server: "jcodemunch", tool: "order", args: {action: "search_symbols", args: {"query": "..."}}})`, `mcp({..., tool: "order", args: {action: "get_symbol_source", args: {"repo": "...", "symbol_id": "..."}}})`, `mcp({..., tool: "order", args: {action: "get_ranked_context", ...}})`. Index: `mcp({..., tool: "order", args: {action: "index_folder", args: {"path": "."}}})`. Discover actions via `mcp({..., tool: "menu"})`. | **Minimal** (tens–hundreds of tokens) |
| **3** | **`read_file` (`read`)** | **Absolute last resort.** Full raw file content for holistic context when surgical tools are insufficient. | **High** (full file) |

**Rule:** to find "where `authenticate` is", try **pi-tools** (`find_symbol`, `find_references`, `find_replace`) (Tier 1) first; **if Tier 1 does not fully resolve the query, escalate to Tier 2 (jcodemunch/skills)** — it returns cross-references and signatures pi-tools cannot. Save `read_file` for last.

**Escalation triggers — Tier 1 → Tier 2 (jcodemunch/skills) when:**
- `find_references` returns empty or partial, but you know the symbol is used elsewhere.
- You need cross-references, signatures, summaries, or ranked results beyond a bare name match.
- The query is semantic (concept → code) rather than exact-name.
- `find_symbol`/`find_replace` resolve the name but not the relationships/impact.
In those cases call `mcp({server: "jcodemunch", tool: "order", args: {action: "search_symbols", args: {"query": "..."}}})` or `mcp({..., tool: "order", args: {action: "get_ranked_context", ...}})` BEFORE falling to full file reads.

**JCodeMunch Usage (via the `mcp` gateway / skills):** `mcp({server: "jcodemunch", tool: "order", args: {action: "...", args: {...}}})`, `mcp({server: "jcodemunch", tool: "menu"})`, `mcp({server: "jcodemunch", tool: "route", args: {task: "..."}})`. These are reached through the `mcp` tool or designated skills.

### 2. Safe Execution (Writing & Editing)

Once the retrieval phase identifies the target file(s):

- **DO NOT** use generic `replace` or `write` operations.
- **ALWAYS** use the `pi` agent's native `edit` tool (fully backed by `pi-hashline-edit`).
- This ensures every operation is anchored by `LINE#HASH`, guaranteeing atomic updates and preventing silent overwrites of concurrent changes.
- **CRITICAL anti-pattern — NEVER dump/near-rewrite the whole file inside a single `edit` call.** Only replace (or insert/delete) the **specific minimal set of lines** you are changing. One `edit` call = one small, targeted change anchored by its hashes. Restating large bodies of unchanged code: (1) wastes output tokens and frequently trips the model's output-token ceiling (colgados con `stopReason: "length"`), and (2) risks silently corrupting the file if a token is omitted. Prefer many small `edit` calls over one giant one, and use `replace_text` for exact single-occurrence substitutions.
- If `plan_refactoring` is needed, dispatch via `mcp({server: "jcodemunch", tool: "order", args: {action: "plan_refactoring", args: {...}}})` and apply the resulting `{old_text, new_text}` patches through the hashline-backed `edit` tool, again as minimal targeted edits.

### 3. General Workflow for a Task

1. **Explore** with pi-tools (`find_symbol`, `find_references`, `find_replace`, `file_outline`) (Tier 1) to locate the artifact/symbol.
2. **Navigate catalog & cross-references** with jcodemunch/skills (Tier 2) via the `mcp` gateway: `mcp({server: "jcodemunch", tool: "order", args: {action: "search_symbols", args: {"query": "..."}}})`, `mcp({server: "jcodemunch", tool: "menu"})`.
3. **Execute** the change using the native `edit` tool (`pi-hashline-edit`) for surgical safety.
4. **Verify** by re-querying jcodemunch via `mcp` (`mcp({server: "jcodemunch", tool: "order", args: {action: "get_symbol_source", args: {"repo": "...", "symbol_id": "..."}}})`) or running tests to confirm the change.

**Note:** `pi-hashline-edit` is the engine for Tiers 1/3 (pi-tools/`read`) and the native `edit` tool. It is not a standalone tier.
