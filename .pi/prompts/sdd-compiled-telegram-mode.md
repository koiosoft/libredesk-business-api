---
description: SDD compiled interaction mode — TELEGRAM. Reads the active mode, reports the transition, and switches gates to Telegram so the user can answer while away from the workstation.
category: SDD
---

# SDD compiled interaction mode — TELEGRAM

Switch the session interaction mode to **telegram**: the user is away from the workstation and
answers through Telegram. Every decision gate must reach them there.

## Steps

1. **Probe the Telegram transport.** Use `telegram_message` to send:
   `[sdd-mode-probe]`

   If the tool is unavailable or the send fails, report
   "Telegram transport is not active. Run `/telegram-connect` in the TUI first."
   and stop. Do not touch `.sdd/.channel-mode`.

2. **Report the transition** through Telegram in one line:
   ```
   Interaction mode: -> telegram
   ```
3. For the rest of this session, gates are delivered through Telegram.

## Effect

Every `gate:` is delivered through Telegram as an assistant message, not through
the native terminal prompt. The gate contract is unchanged: it blocks until an
explicit answer arrives, and no inference counts as consent
(`.sdd/sdd-lang.md` §6.6). `notify:` steps stay non-blocking.

## Gate execution

Do not call `ask_user` in this mode. It opens a terminal overlay that is not
answerable from Telegram.

Do not call `telegram_message` for the gate. Your final assistant message IS
the gate. The `telegram_button` comments are processed by `pi-telegram` when
your output is delivered — they are not sent through a tool.

When a `gate:` opens, emit exactly this structure as your assistant message:

    ⚡ Gate — elección bloqueante
    **Decisión:** <what is being decided>

    Opciones:
    1. <option A>
    2. <option B>
    3. <option C>

    El run está pausado hasta que respondas con una opción.

    <!-- telegram_button: {"label":"<option A>","prompt":"gate: <a>"} -->
    <!-- telegram_button: {"label":"<option B>","prompt":"gate: <b>"} -->
    <!-- telegram_button: {"label":"<option C>","prompt":"gate: <c>"} -->

Then end the turn. Do not call any tool to deliver the gate.

On the next turn, treat only an explicit answer as consent. A generic
"continue", a previous message, a cancelled prompt, or a timeout is not
consent. If no explicit answer arrives, stay blocked and wait.

## Absolute rule

Never call `ask_user` in this mode. Never resolve a gate, an ambiguity, or a
design decision on your own authority while this mode is active. Detecting and
routing is the orchestrator's job; deciding is the arbiter's or the user's
(`.sdd/sdd-lang.md` §6.7). Advancing without an explicit answer can be
catastrophic.

## When to use it

Run when leaving the workstation. Run the terminal-mode prompt on return to
switch back.