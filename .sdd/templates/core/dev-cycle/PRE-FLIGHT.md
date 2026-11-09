# <project-name> — project-local pre-flight policy

> Scope: project-local policy only. This file is NOT the generic protocol. The generic, project-agnostic pre-flight protocol lives at `.sdd/protocols/agents/orchestrator/develop/PRE-FLIGHT.md` (PF-0..PF-4) and in the test-runner role module (TR-3b baseline capture, TR-3c baseline-aware classification). This file binds that protocol to THIS repository: how the full-suite command resolves here, how to anchor the baseline, and which project-specific failure classes are pre-existing and must NOT be classified as regressions. Fill every section below for your project; delete this line when done.

### P0: Applicability — a bootstrap cycle has no suite to baseline

- **The baseline only exists when the cycle actually has a test suite.** The generic protocol PF-1 says pre-flight *always attempts* the baseline capture, because it cannot know the project. This file CAN know the project.

- **Skip the baseline capture when the active cycle's instruction file has no `## Unit Test List` section** (e.g. a `BOOTSTRAP` cycle, which builds the project skeleton — structure, stack, base conventions, first runnable skeleton — and NOT functionality). With no unit-test list there is no suite to run and nothing to snapshot.

- **When that is the case:** do NOT dispatch the `test-runner` in `baseline` mode; do NOT create `${LOG_DIR}/baseline_failures.txt`; record the baseline as *intentionally absent* and continue the cycle. This is not a failure — it is the correct behaviour for a cycle with no suite.

- **Rationale:** dispatching a baseline run against a project with no suite produces no usable artifact, wastes a full runner dispatch (environment checks, MCP bootstrap, SPEC resolution on a not-yet-populated SPEC.md) and can send the runner into its environment-fix path for an environment that cannot be fixed because it does not exist yet. The F-3 regression gate is a no-op in this case anyway, since there is no closing run to diff against.

- **Note (known gap):** this file is project-local and a greenfield bootstrap project may not have seeded it yet, and the `test-runner` does not read it via `defaultReads`. Until that link exists, the orchestrator-side prompt/protocol remains the primary mechanism for skipping pre-flight in a bootstrap. This section declares the intended policy; it does not yet force it.

### P1: How the baseline command resolves for this repo

- There is no configured `preflight.test_command`; the dispatched test-runner derives the full-suite command from `.sdd/core/SPEC.md` at run time (protocol PF-1/PF-2).
- Document here, for THIS repo, what that resolution actually produces (the interpreter + command used to run the COMPLETE suite), framed as observed behaviour, not a config field.
- Note which loops run scoped subsets vs the full suite, and why an early baseline matters for this project specifically.

### P2: Known-baseline guidance
- State whether the baseline should be captured against a clean working tree or anchored to a specific revision, and why.
- Confirm the baseline is captured before the first edit of the cycle (protocol PF-0) and that candidate regressions are confirmed by isolated re-run (protocol PF-4). A baseline diff is a triage aid, not a verdict.

### P3: Project-Specific Exemptions and Caveats
- List the failure classes known to produce PRE-EXISTING, non-regression failures in THIS repository (collection-order artifacts, seam rules, environment/root-resolution quirks, etc.), so they land in the baseline and are excluded from regression triage rather than consuming FIX iterations.
- Keep these strictly project-local; do NOT promote them into the generic protocol files.
