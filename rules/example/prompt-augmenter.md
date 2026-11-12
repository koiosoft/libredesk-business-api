# Prompt augmenter descriptor (example)

Describes how hub-api composes the prompt handed to the generation engine.
It is not concatenated into anything; it exists so the composition contract is
versioned next to the rules, and it participates in the rules hash.

## Generation paths (selected by JEV_USE_COPILOT)

### Contextual (default): POST /api/v1/ai/copilot

hub-api sends `{conversation_uuid, message, assistant_id}`. LibreDesk rebuilds
the full context server-side: real conversation history, the assistant's persona
(instructions + guardrails) and its tools, including knowledge-base search. Our
`message` therefore only says WHAT to fix - it must not restate the material.

Blocks produced by `app/jev/composer.py::build_correction_instruction`:

1. instruction verb ("correct the agent's reply")
2. the exact reply under review, quoted
3. the chosen action text from `prompts.yaml`
4. output contract: customer-facing text only, customer's language, no meta talk

### Legacy: POST /api/v1/ai/completion

Single flat `content` built as ROL + ACTION + PERSONA + MATERIAL, because that
endpoint carries no conversation context. Kept reachable with
`JEV_USE_COPILOT=false`.

## Inherited constraint (verified in LibreDesk source)

`internal/ai/ai.go` always prepends a fixed framing ("You are rewriting a
support agent's draft reply to a customer ... only rewrite it") and forces HTML
output. Consequences:

- Action texts are worded as rewrites, never as imperatives to do new things.
- Published content passes through Go template rendering, so `{{ ... }}` is
  neutralized before sending (see `composer.strip_dangerous_template_syntax`).

## What the classifier gets (different from the generator)

`state` = turn-structure rule extracted from guardrails + assistant policy
header + chronological conversation, newest turn last. The classifier decides
from evidence it can see; it never receives our action wording beyond `criteria`.
