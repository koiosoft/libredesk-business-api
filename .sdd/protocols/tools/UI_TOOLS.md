## UI Tooling Strategy

This document defines the specialized tooling strategy for UI component development from prototypes.
If the task involves implementing UI components from an HTML/Tailwind prototype (e.g., `code.html`) and the tool is available, the agent MUST follow this priority:

### Specialized UI Prototype Parsing (Tier 0)

| Tier | Tool Module | Purpose & Trigger | Token Cost |
| :--- | :--- | :--- | :--- |
| **0** | **`TAIHTO_FLAST.md`** | **UI Prototype AST Parsing.** Use `bash agent-instructor tool ui-parse --input <code.html> --out .sdd/work/ast/<basename>.ast.md` when converting HTML/Tailwind prototypes into UI code (Flutter, ReactJS, Angular, Ionic, etc.) to extract structural layout, tokens, and component hierarchies. AST persists to disk — consume via `read()` (0 rerparse tokens). | **Minimal** (disk-based) |

---

### General UI Workflow for a Task

1. **Parse UI Spec (If applicable)**: Use `TAIHTO_FLAST` (Tier 0) if converting a prototype (`code.html`) into component code.
2. **Inspect Existing UI Code**: Follow the general codebase strategy defined in `.sdd/protocols/tools/CODE_INSPECT_TOOLS.md` to locate target files and components.
3. **Execute UI Implementation**: Apply surgical edits using the native `edit` tool.
4. **Verify Alignment**: Compare the implemented component hierarchy with the extracted AST structure and project UI conventions.