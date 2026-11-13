# Prompt augmenter descriptor (example)

Describes how hub-api composes the prompt handed to the generation engine.
It is not concatenated into anything; it exists so the composition contract is
versioned next to the rules, and it participates in the rules hash.

## Generation paths (selected by JEV_USE_COPILOT)

### Active (default): POST /api/v1/ai/completion

Single flat `content` composed here (`composer.compose_prompt`) so the corrector
sees exactly what the generator saw plus JEV's instruction. Block order is
contractual (FEATURE.md section 9 / G6):

1. ROL
2. PERSONA: assistant instructions + limits it may never cross + the snippets
   declared by the chosen option (`options.<key>.snippets`, resolved through
   `GET /api/v1/ai/snippets`)
3. HISTORIAL de la conversacion
4. MENSAJE DEL CLIENTE
5. RESPUESTA DEL ASISTENTE A MEJORAR
6. ACCION APLICAR -- always LAST: precedence is positional, not declarative

### Escape hatch: POST /api/v1/ai/copilot (JEV_USE_COPILOT=true)

hub-api sends `{conversation_uuid, message, assistant_id}` and LibreDesk rebuilds
context server-side. Measured limitation (V15): BuildCopilotPersona omits the
assistant's guardrails, so this engine cannot enforce what it never sees; kept
reachable but no longer the default.

## Inherited constraint (verified in LibreDesk source)

`internal/ai/ai.go` always prepends a fixed framing ("You are rewriting a
support agent's draft reply to a customer ... only rewrite it") and forces HTML
output. Consequences:

- Action texts are worded as rewrites, never as imperatives to do new things.
- Published content passes through Go template rendering, so `{{ ... }}` is
  neutralized before sending (see `composer.strip_dangerous_template_syntax`).

## What the classifier gets (different from the generator)

`state` = turn-structure clause + assistant policy header (instructions and
guardrails, unclipped -- D1/G2) + the mandatory-snippets block (union of every
id declared across options) + chronological conversation, newest turn last. The
classifier decides from evidence it can see; it never receives our action
wording beyond `criteria`.
