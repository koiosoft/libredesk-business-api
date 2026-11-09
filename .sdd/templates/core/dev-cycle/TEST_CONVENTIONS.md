# <project-name> — project-local test conventions

> Scope: project-local only. This document records how tests are written and run
> in THIS project: isolation rules, scope discipline, mock boundaries, reporting.
> It is read **only** by the test roles (`test-writer`, `test-runner`) via
> `defaultReads`. It does NOT describe SDD protocols or orchestrators — those live
> under `.sdd/protocols/`. Fill every section below; delete this line when done.

All test workers (`test-writer`, `test-runner`) MUST follow these conventions when
creating, fixing, or executing tests.

## 1. SANDBOX ISOLATION (NO REAL-PROJECT SIDE EFFECTS)

- **Tests MUST operate exclusively on disposable sandbox directories** (e.g. `tmp_path`, a runtime temp dir, or the framework's temp-fixture equivalent).
- **Never read, write, or diff files in the real project tree** unless the task explicitly targets a file in the project.
- **Never run destructive filesystem commands** (`cp`, `mv`, `rm`, `rsync`, `install`, …) on real project directories. All file operations must target paths under the sandbox.
- **Verification diffs MUST compare sandbox copies** — never diff a sandbox path against a real project path. Copy the real file into the sandbox first, then diff inside the sandbox.
- **`git restore` / `git checkout -- <file>` after the fact is NOT a valid recovery pattern** — prevent the damage by never touching real paths.

## 2. TEST SCOPE DISCIPLINE

- **`test-writer`**: when validating a test, run **only that single test file / node id** — never the whole suite, never a keyword sweep.
- **`test-runner`**: execute the full suite for the specified `mode` (unit / integration / ui). Never run tests outside the specified mode.
- <!-- ADAPT: single-test command and the canonical per-mode commands for this stack, e.g.
       Python:    pytest <file>::<test>   /   pytest tests/unit   /   pytest tests/integration
       JS/TS:     <runner> <spec> --testNamePattern "<name>"
       Angular:   ng test --include=<spec>
       Flutter:   flutter test <file.dart>
       Java:      mvn -Dtest=<Class>#<method> test -->

## 3. MOCK BOUNDARIES

- **Unit tests**: mock external I/O (filesystem, network, subprocess, time). Do **not** mock internal pure functions — test them for real.
- **Integration tests**: use real I/O but within a sandbox (e.g. a subprocess launched against a temp copy of the project skeleton).
- **Environment setup** (dependencies, config files, runtime pointers) belongs in a shared fixture / setup helper — not inlined in each test.
- <!-- ADAPT: the framework's fixture/setup mechanism (conftest.py, beforeEach, setUp, @BeforeEach, test harness, …). -->

## 4. REPORTING

- Both `test-writer` and `test-runner` MUST return a single canonical JSON per `.sdd/protocols/agents/SUBAGENT_COMMS.md`.
- `test-writer`: writes a `## Justification` section into the test artifact file. Updates to the artifact's `## Task` section are forbidden.
- `test-runner`: writes a structured summary to the `log_file_path`; never modifies test files or source code.
