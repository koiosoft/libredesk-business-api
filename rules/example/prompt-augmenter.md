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

## Environment switches that change composition (not rule files)

These live in the environment, never here; this descriptor documents their
effect so a reader of the rules knows which contract is active:

| Variable | Default | Effect on composition |
|---|---|---|
| `JEV_USE_COPILOT` | `false` | engine selector, see "Generation paths" above |
| `JEV_COMPLETION_PROMPT_KEY` | empty | key of the LibreDesk stored prompt used as system prompt by `/ai/completion`. Empty is legal but loud: startup warns and each generation falls back to the first row of `GET /api/v1/ai/prompts`, logging which one was used. Pin it in production after creating a dedicated correction prompt. |
| `JEV_MULTI_ACTION` | `false` | with `true`, secondary options join the chosen one inside ACCION when JEV's probability mass is split. See below. |
| `JEV_MULTI_PROB_CEILING` | `0.6` | running-mass ceiling for the previous row: candidates are taken from highest probability downward while the accumulated mass has NOT yet reached it -- the last addition may cross it slightly, by design. `none` never participates (it means "publish nothing" and contradicts any action). |

Multi-action ordering inside ACCION is **ascending by probability**, so the
option JEV actually chose -- normally the strongest -- reads LAST and wins by
position (same principle as G6). When multi-action fires, the pipeline logs
`multi-action conv=... choices=a->b->c probs={...}`: that log line is the
offline evidence for deciding whether production should enable the flag. With
the current thresholds (confidence 0.5 / probability 0.45), accepted decisions
usually carry p >= 0.7, already over any sane ceiling -- so the feature only
activates on genuinely divided decisions, which is its purpose, not a failure.
