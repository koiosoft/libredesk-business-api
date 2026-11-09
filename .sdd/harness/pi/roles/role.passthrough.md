---
name: role.passthrough
description: Empty passthrough role — intentionally declares no tools, model, thinking, or body so the host extension (pi-subagents) keeps ownership of the system prompt and tool set. Used to stop pi-roles from clobbering sub-agent prompts.
---

<!--
═══════════════════════════════════════════════════════════════════════════════
  ⛔ DO NOT ADD `model:` OR `thinking:` TO THIS FRONTMATTER. EVER.
═══════════════════════════════════════════════════════════════════════════════

WHY THIS WARNING EXISTS
-----------------------
This role is configured as `pi-roles.defaultRole` in `.pi/settings.json`, which
makes it the role applied to EVERY new session in this project — including the
sessions that pi-subagents creates for sub-agents.

Any `model` declared here is applied by pi-roles via `pi.setModel()` AFTER
pi-subagents has already resolved the launch model from the call. pi-roles
does not participate in pi-subagents' precedence table, so it silently
overrides the highest-priority source (the per-run override).

The overriding is invisible in the sub-agent's prompt — the child's preamble
shows `<active_agent>` but no role — which makes it very hard to diagnose from
the transcript alone.

HOW IT SURFACES (misleadingly)
------------------------------
The sub-agent runs fine and completes its task, but pi-subagents reports:

    model_verification_failed: native Pi child reported a different model
    than the launch candidate. Expected '<requested-model>' but observed
    '<role-model>'.

The error blames the "observed model" and suggests configuring
`modelResponseAliases`. DO NOT DO THAT — it would permanently mask this bug by
asserting that the role's model IS the requested model, so every sub-agent
would keep running on the wrong model while you believe otherwise.

Note the self-contradiction: pi-subagents records `requestedModel` and
`modelOrigin: "explicit"` correctly (what was ASKED), while the child's
transcript records the role's model (what actually RAN). Both fields are
honest; they describe different moments — before and after the override.

REGRESSION HISTORY
------------------
Introduced in commit bc9f779 (2026-10-03): `model: deepseek/deepseek-flash`
was added to this role, contradicting the role's own description one line
above. First failing runs appeared 2026-10-04. Prior to that, this role
declared no model and everything worked.

The mismatch was invisible while the role's model happened to match the model
requested by the call (deepseek == deepseek). It only became visible once
`.sdd/compiled/models.yaml` began requesting a different model (qwen) as
priority 1.

VERIFIED EVIDENCE
-----------------
Same payload (agent `compiled.sdd-worker` + `alibaba-token-intl/qwen3.8-flash`),
differing only in whether this role declared a model:

  with    `model: deepseek/deepseek-flash` → exitCode 1, model_verification_failed,
                                             transcript provider='deepseek'
  without the model                       → exitCode 0, no error,
                                             transcript provider='alibaba-token-intl'

IF YOU NEED A MODEL FOR A SPECIFIC ROLE
---------------------------------------
Declare it on that role, not here. But be aware that ANY role carrying a
`model` will override sub-agent model resolution for sessions where it is
active. For the session default, leave this role empty.

See also: `.pi/roles/role.orchestrator.md` declares a model and carries the
same risk if ever used as `defaultRole` or activated via `/role orchestrator`.
-->
