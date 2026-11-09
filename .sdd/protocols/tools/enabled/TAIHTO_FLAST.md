# TOOL MODULE: taihto-flast

## Rules
1. **Absolute preference for AST parsing over manual layout reading:** Before writing UI components from a prototype (`code.html`), always invoke `bash agent-instructor tool ui-parse --input <code.html> --out .sdd/work/ast/<basename>.ast.md` to obtain the precise widget/component AST structure and layout breakdown. The AST is persisted to disk — consume it via `read()` (0 reparse tokens).
2. **Framework-agnostic UI Mapping:** Use the generated AST tree to map structural tokens (colors, paddings, flex gaps, borders, typography) to the target project's framework (Flutter, ReactJS, Angular, Ionic, Vue, etc.).
3. **Design-Token Consistency (Conditional):** If a design spec file exists (e.g., `.sdd/core/DESIGN.md`, design system tokens, or local UI conventions), compare the extracted AST properties against it before implementing the component to prevent style drift or missing tokens. If no design spec is available, use the extracted AST properties directly along with the project's existing UI codebase conventions.
4. **Surgical UI Scope:** Only parse the HTML/Tailwind screens or fragments relevant to the current task. Do not re-parse unmodified prototypes unnecessarily.
5. **Single Source of Truth:** Treat the prototype AST as the authoritative structural reference for layout geometry and responsive rules.

## Notes
- `taihto-flast` transforms raw HTML/Tailwind layout specifications into a deterministic Abstract Syntax Tree (AST).
- Ideal for extracting exact component hierarchies, spacing, flex behaviors, and visual properties without manual manual visual guessing.
- Works in tandem with `sdd-ui-worker` to ensure high-fidelity translation from prototype to code.
- If the tool is not available in the active session or the task is non-UI, proceed using standard codebase inspection tools.