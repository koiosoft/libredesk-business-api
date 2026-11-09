---
description: Token-limit recovery pattern — output-token-limit terminations of sub-agents, with next-priority-model relaunch, partial-work context, and scoped reviewer relaunch.
category: SDD
---

> **Purpose:** Codifies the recovery pattern for sub-agents that terminate with an **output token limit**. When `sdd-worker`, `sdd-ui-worker`, `sdd-reviewer`, `test-writer`, or `test-runner` is cut off by its output-token ceiling, the orchestrator does **not** treat this as a `blocked` doubt (DEVELOP.md J-1..J-5) or an `error` (Universal Subagent Exit Fallback Rule). Instead it performs a **delivery recovery**: relaunch the sub-agent with the **next-priority model** from its fallback chain in `.sdd/models.yaml`, carrying a **compact directive** — partial-work context for implementation/test workers, or only the current task-evaluation prompt for reviewers. This recovery is distinct from corrective iterations and does **not** consume them (cf. `develop/testing/LOOP.md` LOOP-1, `develop/REVIEW.md` R-5).

> **Applies to:** sub-agents launched via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`) with `async: true` (DEVELOP.md § Model Selection, REVIEW.md R-2). The role's `model`/`thinking` are resolved per-model-option as in those modules; this module only defines the *recovery* relaunch.

---

## TL-1: Scope and Trigger — Detecting an Output-Token-Limit Termination

A sub-agent termination is classified **OUTPUT_TOKEN_LIMIT** when its final result (retrieved via `use_case: wait_result`) satisfies:

- **Signal (primary):** the termination message contains the token-limit signal — the substring `output token limit` (or `token limit`).
- **Evidence (secondary, confirms a forced cutoff):** a complete, canonical JSON object (SUBAGENT_COMMS.md § 1.2) could **not** be extracted from the final message using the tolerant extractor (§ 1.5(B)) — i.e. `status` is unknown/truncated/missing.

| Condition | Classification | Action (see TL-2/TL-3/TL-4) |
| :--- | :--- | :--- |
| `output token limit` signal present | OUTPUT_TOKEN_LIMIT | TL-2 (worker) / TL-3 (reviewer) / TL-4 (test workers) |
| No signal; `status: "blocked"` with `question` | DOUBT (not token-limit) | DEVELOP.md MODE_AUTO Interruption Handling J-1..J-5 (sdd-judge → resume) |
| No signal; `status: "error"` in `error_details` | IRRECOVERABLE ERROR | DEVELOP.md CRITICAL RULES — Universal Subagent Exit Fallback Rule (exit 1 / ask_user) |

> **Do not** route a clean `status: "blocked"` (doubt) or `status: "error"` through this module — those follow their own paths above. `output token limit` is a *delivery* failure (the agent was forcibly cut off), not an irrecoverable error and not a design doubt.

---

## TL-2: Recovery for Implementation Workers (sdd-worker / sdd-ui-worker)

When a **worker** terminates with OUTPUT_TOKEN_LIMIT during a task (DEV-CODER.md W-3):

| Step | Action | Detail |
| :--- | :--- | :--- |
| TL-2.1 | Resolve next-priority model | Sort the role's `model_options` in `.sdd/models.yaml` by `priority` ascending, keep entries with a non-empty `model`; advance one priority past the model just exhausted. For `sdd-worker`/`sdd-ui-worker`: p1 `openrouter/poolside/laguna-s-2.1` → p2 `openrouter/deepseek/deepseek-v4-flash-0731`. Preserve the `thinking` value from the resolved model option. |
| TL-2.2 | Gather partial-work context | (a) the task artifact `${LOG_DIR}/tasks/TASK<NNN>.md` — read text written to its **Justification** section; (b) any `affected_files` the worker reported before cutoff (if a JSON fragment was recoverable); otherwise assume edits already on disk (atomic `edit` per line per CODE_INSPECT_TOOLS.md § 2). |
| TL-2.3 | Relaunch with a compact directive | **Fresh `Agent` launch** (not `resume` — the prior context exceeded the budget, so re-sending it would re-trigger the limit). Specify the next-priority model explicitly: |

```
Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
  agent: "<sdd-worker | sdd-ui-worker>"
  task: "Protocol: ${PROTOCOL}. TASK_ID: ${TASK_ID}. Task artifact: ${LOG_DIR}/tasks/TASK<NNN>.md.\n\nYour PREVIOUS attempt was TERMINATED BY OUTPUT TOKEN LIMIT on model <prior_model>. Partial work already on disk:\n- affected_files: <recovered-from-worker, or 'see task Justification'>\n- Justification drafted: yes (see ${LOG_DIR}/tasks/TASK<NNN>.md)\n\nContinue from where you left off with a compact pass. Finish the remaining implementation, then end your turn with a SINGLE canonical JSON result (SUBAGENT_COMMS.md § 1.1/§ 1.5) — no prose after it. MANDATORY: write your technical justification to the Justification section of ${LOG_DIR}/tasks/TASK<NNN>.md."
  model: "<next-priority-model>"
  thinking: "<resolved-value from model option>"
  async: true
```

4. After relaunch, continue with **DEV-CODER.md W-2 (Completion Handling)** as normal (mark `[x]`/`Failed` via CLI). This relaunch is a *delivery* retry — it does **not** restart or increment any correction counter.

> **Alt: `resume` (opt-in only).** Use `use_case: resume` only when (a) the canonical JSON was recoverable (cutoff was a clean tail-end overflow) **and** (b) the runtime's `resume` supports a `model` override to the next-priority model. The documented resume signature (SUBAGENT_COMMS.md § 3) omits `model`, so default to the **fresh launch** above. When supported: `use_case: resume` with `agent`, `resume: <prior_agent_id>`, `model: "<next-priority-model>"`, `task: "<compact directive + partial-work>"`.

---

## TL-3: Scoped Relaunch for Reviewers (sdd-reviewer)

When a **reviewer** terminates with OUTPUT_TOKEN_LIMIT on a review pass (REVIEW.md R-2/R-3):

| Step | Action | Detail |
| :--- | :--- | :--- |
| TL-3.1 | Resolve next-priority model | From the `sdd-reviewer` fallback chain in `.sdd/models.yaml`: p1 `openrouter/poolside/laguna-s-2.1` → p2 `openrouter/deepseek/deepseek-v4-flash-0731`. Preserve the `thinking` value from the resolved model option. |
| TL-3.2 | Scoped relaunch | **Resend ONLY the DOD-based R-2 reviewer prompt** (pointing at `${LOG_DIR}/dod/DOD-${TASK_ID}.md`). Do **not** re-send the reviewer's prior review context — that is what consumed the budget. A fresh, compact, read-only pass with a larger model is the recovery. |
| TL-3.3 | Relaunch | |

```
Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
  agent: "<models.yaml['sdd-reviewer'].name — e.g. base.sdd-reviewer>"
  task: "Protocol: ${PROTOCOL}. TASK_ID: ${TASK_ID}. The task file is at: ${LOG_DIR}/dod/DOD-${TASK_ID}.md.\n\nAct as a READ-ONLY reviewer (inspection tools only: read, jcodemunch order/get_symbol_source/get_ranked_context, read, native pi-tools, jcodemunch). You MUST NOT use edit, write, or bash.\n\n[NOTE: your PREVIOUS review was TERMINATED BY OUTPUT TOKEN LIMIT on model <prior_model>; this is a scoped relaunch — re-evaluate ONLY this task with a fresh, compact pass.] Inspect the files reported by the worker in its 'affected_files' and verify the implementation against the task description and CONVENTIONS.md / SPEC.md. End your turn with a SINGLE canonical JSON (SUBAGENT_COMMS.md § 1.1/§ 1.5) extended with the `verdicts` array per REVIEW.md R-2."
  model: "<next-priority-model>"
  thinking: "<resolved-value from model option>"
  async: true
```

4. On completion, return to **REVIEW.md R-3 (Completion Handling)** using the new `verdicts` array. This relaunch is a *delivery* retry — it does **not** increment `REVIEW_ITERATION` (R-5), so it cannot by itself trip the 3-iteration escalation.

> **Note (ACK070):** This file is maintained in `templates/source/.sdd/protocols/agents/orchestrator/develop/TOKEN_LIMITS.md` and synced to `.sdd/protocols/agents/orchestrator/develop/TOKEN_LIMITS.md`. All edits should be made in the `templates/source/.sdd/` location and then propagated to `.sdd/`.

---

## TL-4: Test Workers (test-writer / test-runner)

When a **test-worker** terminates with OUTPUT_TOKEN_LIMIT (TESTING.md T-2/T-3, LOOP.md LOOP-1):

| Step | Action | Detail |
| :--- | :--- | :--- |
| TL-4.1 | Resolve next-priority model | From the role's chain in `.sdd/models.yaml` (test-writer/test-runner: p1 `openrouter/poolside/laguna-s-2.1` → p2 `openrouter/deepseek/deepseek-v4-flash-0731`). Preserve the `thinking` value from the resolved model option. |
| TL-4.2 | Gather partial-work context | The test artifact path `${LOG_DIR}/${TEST_ID}.md`, the `TEST_ID`, and the `TEST_MODE` (unit/integration/ui); for `test-runner`, the last `log_file_path` and `TEST_ITERATION_COUNT`. |
| TL-4.3 | Relaunch with a compact directive | Fresh `Agent` launch with the next-priority model: |

```
Via `use_case: launch` (ver `.sdd/sub-agents/pi/nicobailon-pi-subagents.yaml`):
  agent: "<test-writer | test-runner>"
  task: "Mode: ${TEST_MODE}. Operation: BuildTest. Test file: ${LOG_DIR}/${TEST_ID}.md.\n\nYour PREVIOUS attempt was TERMINATED BY OUTPUT TOKEN LIMIT on model <prior_model>. Partial work already on disk:\n- affected_files: <recovered-from-test-worker, or 'see task file'>\n- test content drafted: yes (see ${LOG_DIR}/${TEST_ID}.md)\n\nContinue with a compact pass. End your turn with a SINGLE canonical JSON result (SUBAGENT_COMMS.md § 1.1/§ 1.5)."
  model: "<next-priority-model>"
  thinking: "<resolved-value from model option>"
  async: true
```

4. Continue at the same module step (TESTING.md T-2 completion handling, or back at LOOP.md LOOP-1 step 2). This relaunch does **not** increment `TEST_ITERATION_COUNT`.

---

## TL-5: Exhaustion and Escalation

- The role's fallback chain is advanced **once** per OUTPUT_TOKEN_LIMIT relaunch (track an in-cycle model pointer per `(role, task_id, token-limit)`).
- If the **last** non-empty model in the chain is exhausted (no next-priority model remains):
  1. Attempt `sdd-judge` arbitration with the partial work and `error_details = "Output token limit with all fallback models exhausted for <role>/<TASK_ID|TEST_ID>"` (DEVELOP.md J-2/J-3), to obtain a directive — typically to **split the task** into smaller sub-tasks so each fits a single model's budget.
  2. If `sdd-judge` returns `exit 1` (attempt threshold > 3 exceeded) or an unrecoverable error — or when `MODE_AUTO == false` — escalate to a `gate` (DEVELOP.md J-4/J-5, "All fallback models in `models.yaml` are exhausted"), surfacing the partial work and the reason. The gate is fail-closed: it waits for an explicit user answer and is never satisfied by inference. See `sdd-lang.md` §6.6.
- **Single-priority roles:** `sdd-judge` and `sdd-doc-updater` have only a single priority in `.sdd/models.yaml`; if they terminate with OUTPUT_TOKEN_LIMIT they skip straight to escalation (J-4/J-5).

---

## TL-6: Integration Summary (what reuses this, what does not)

| Concern | Governed by | Token-limit recovery role |
| :--- | :--- | :--- |
| Output-token-limit delivery recovery | `develop/TOKEN_LIMITS.md` (TL-1..TL-5) | **This module** |
| `model`/`thinking` resolution | `DEVELOP.md` § Model Selection, `develop/REVIEW.md` R-2 | Reuses the same resolution; this module only advances the priority pointer |
| `blocked` (doubt) arbitration | `DEVELOP.md` MODE_AUTO Interruption Handling J-1..J-5 | Not token-limit; do not route here |
| Irrecoverable errors | `DEVELOP.md` CRITICAL RULES (Universal Subagent Exit Fallback Rule) | Not token-limit |
| Reviewer verdict + fix loop / `REVIEW_ITERATION` | `develop/REVIEW.md` R-2..R-6 | TL-3 is a delivery retry → does not increment `REVIEW_ITERATION` |
| Test correction iterations / `TEST_ITERATION_COUNT` | `develop/testing/LOOP.md` LOOP-1 | TL-4 is a delivery retry → does not increment `TEST_ITERATION_COUNT` |
| Canonical JSON / `resume` contract | `protocols/agents/SUBAGENT_COMMS.md` § 1.1, § 1.2, § 1.5, § 3 | TL-2/TL-4 use `resume` only as an opt-in alternative |

---

> **Cross-references:** Defined here to avoid duplication. See `DEVELOP.md` (CRITICAL RULES — Handling Sub-agent Failures, Universal Subagent Exit Fallback Rule, MODE_AUTO Interruption Handling J-1..J-5, Model Selection §), `develop/REVIEW.md` (R-1..R-6), `develop/DEV-CODER.md` (W-1..W-4), `develop/TESTING.md` (T-1..T-3), `develop/testing/LOOP.md` (LOOP-1), `protocols/agents/SUBAGENT_COMMS.md`, and `.sdd/models.yaml` (fallback chains: sdd-worker & sdd-reviewer & test-workers p1 `openrouter/poolside/laguna-s-2.1` → p2 `openrouter/deepseek/deepseek-v4-flash-0731`; sdd-judge & sdd-doc-updater single priority).