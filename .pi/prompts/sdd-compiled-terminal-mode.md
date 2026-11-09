---
description: SDD compiled interaction mode — TERMINAL (default). Reads the active mode, reports the transition, and switches gates to the terminal prompt.
category: SDD
---

# SDD compiled interaction mode — TERMINAL (default)

Switch the session interaction mode to **terminal**. This is the **default**
mode: a cycle started without switching prompts begins in `terminal`.

## Steps

1. **Report the transition** in one line:
   ```
   Interaction mode: -> terminal
   ```
   
2. For the rest of this session, gates are delivered through the terminal.

## Effect

Every `gate:` is delivered through the **terminal** (native blocking prompt).
The gate contract is unchanged: it **blocks** until an explicit answer, and is
never satisfied by inference, a later unrelated message, or a timeout
(`.sdd/sdd-lang.md` §6.6). If no valid answer arrives, the run stays `blocked`
and waits. `notify:` steps are non-blocking and behave the same in both modes.

## Gate execution

Gates are delivered through the native terminal prompt. Use `ask_user` for
every `gate:`. This is the correct tool in this mode — the Telegram mode's
prohibition does not apply here.

## When to use it

Run on return to the workstation, to switch back from Telegram mode.