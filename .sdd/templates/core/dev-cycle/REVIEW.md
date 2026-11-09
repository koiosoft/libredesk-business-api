# <project-name> — project-local review policy

> Scope: project-local policy only. This file is NOT the generic protocol. The generic, project-agnostic review discipline lives at `.sdd/protocols/agents/dev-workers/DEV-REVIEWER.md` (R-6). This file binds that discipline to THIS repository: which project conventions an ACK is judged against, what evidence each criterion must cite here, and which criteria are affected by this project's current phase. Fill every section below for your project; delete this line when done.

### RV0: What `Completed` certifies, and what Review is for

Two orthogonal axes govern a cycle. Bind them explicitly here so a reviewer never grades
one axis against the other's vocabulary:

- **Queue state** — `Pending`, `In Progress`, `Completed`, `Failed`. Set by the worker
  through `workflow update --status`. `Completed` means the delivery was **processed**:
  the change landed where its task said it should. It is NOT business approval, NOT a
  verdict on the acceptance criteria, and NOT a green light to close.
- **Review verdict** — `approved` / `correction`. Recorded per acceptance criterion (ACK)
  through `workflow review mark`. This is the only axis that judges whether the delivered
  work satisfies the Definition of Done.

Consequences this project's reviewers must hold to:

- A row marked `Completed` with un-audited ACKs is an *unfinished* cycle, not a finished
  one. Never infer acceptance from the status column, a completion percentage, or a tick.
- The reviewer audits every DoD ACK attached to a task during the Review phase, at the
  cited location, and records the outcome as a verdict on that ACK — independently of the
  task's queue state. Task-level `Completed` neither pre-approves nor vetoes any ACK.
- `workflow close` gates on BOTH axes: every artifact `Completed` AND every ACK approved.
  State here if this project narrows either gate for a phase, and why.
- Do not introduce a fifth queue value (`superseded`, `accepted`, `rejected`) to express a
  review outcome. Obsolescence or rejection is recorded by rejecting the criterion in
  review; the queue keeps reporting delivery only.

### RV1: Applicable-conventions binding

- State which project documents the reviewer must judge code-style/structure and architecture/behaviour claims against (e.g. `.sdd/core/CONVENTIONS.md`, `.sdd/core/SPEC.md`).
- Note that a criterion naming a convention is satisfied only if the implementation follows it **at the cited location**.
- Keep these strictly project-local; do NOT promote them into the generic protocol file.
- A document that must stay byte-identical to its bundled template (a distributed source-of-truth
  artifact) is edited in the template, never in the installed copy: `init` and `update` replace
  those trees wholesale, so an edit made in the project is lost on the next run and silently
  absent for every other project. Judging "documentation updated" means judging the template.

### RV2: Evidence expectations for this repo

- State what a criterion asserting on-disk effects must cite here (the concrete path it wrote to).
- State what a "tests pass" criterion must cite here (the **specific** test file or node id — not a whole-suite claim).

### RV3: Phase-specific judging (current phase)

- If the repository is mid-migration or otherwise phase-bound, describe how a criterion referencing phase-specific routes/branches must be judged here.
- State whether coexistence of old and new paths is acceptable, and what a parity claim requires.
- Remove or replace this section when the phase ends.

### RV4: Reopened cycles

`workflow reopen` restores the active-cycle pointer and unstamps the `- **Closed**` marker
of a closed cycle so review can resume. It changes cycle *lifecycle*, not judgement:

- Every queue status and every recorded ACK verdict survives a reopen unchanged. The
  reviewer re-audits only the work added after the reopen; prior verdicts stay on record
  unless a criterion is explicitly re-marked.
- A reopened cycle is re-closed through the same both-axes gate described in RV0, so a
  previously approved criterion cannot be dropped by reopening and closing again.
- State here any project rule about what may legitimately re-open a closed cycle (late
  correction, missed criterion, regression found after closure).
