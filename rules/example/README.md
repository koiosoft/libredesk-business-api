# Example rule set (documentation only)

This directory is the **reference** for how to write a rule set. It is never
loaded by a running service: development points at `../dev` and production at
`../prod`, selected by `PROMPT_AUGMENTER_RULE_PATH`.

A rule set is exactly three files:

| File | Purpose | Failure mode |
|---|---|---|
| `prompts.yaml` | The closed list of actions JEV may choose (`options`) plus the question it answers | Boot aborts if `none` is missing or any description is empty |
| `agents.yaml` | Allowlist of AI assistants this hub evaluates, their per-channel prefixes and revive team | Boot aborts on unknown channels, non-integer ids, or enabled agents without prefixes |
| `prompt-augmenter.md` | Describes how the final generation prompt is composed | Boot aborts if absent (it participates in the rules hash) |

Everything here is fail-closed: an unreadable or incomplete file means the
service does not start, rather than starting with partial policy and publishing
wrong corrections.

## What JEV actually receives

Per evaluated message, hub-api POSTs to the classifier endpoint:

```json
{
  "model": "<CLASSIFIER_MODEL>",
  "state": "<turn structure rule> + <assistant policy> + <conversation turns>",
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "<question.instructions>",
      "criteria": {"<option key>": "<option text>", "...": "..."}
    }
  }
}
```

`criteria` is `options` verbatim: keys are stable identifiers that appear in
logs and metrics; descriptions are what the classifier reads. Keep keys ASCII
and lowercase-hyphenated.

## How to write a good option description

The classifier sees only the conversation and the assistant's policy. A
description works when it states an **observable condition**, not an intent:

- Weak:  "the agent failed to engage the lead properly"   (interpretation needed)
- Strong: "the agent asks two or more questions in the same message" (countable)

Measured effect of switching one option from interpretive to countable:
confidence went from 0.26 (silently discarded) to 0.98 (correction published).

If an option needs to do more than rewrite text, declare `post_action` (see
`prompts.yaml` here). Post-actions run only after a successful publish.
