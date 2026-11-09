/**
 * pi-context-police — JEV intervention hook (sub-agent profile).
 *
 * WHAT THIS IS
 * ------------
 * A shipped TEMPLATE, not project content. It follows the maquette shape of the
 * SDD template tree: every path it uses is resolved against the CONSUMING
 * project's working directory at runtime, so a fresh `agent-instructor init` in
 * another project reproduces the hook without edits. Nothing here hard-codes an
 * absolute path from the repository that authored it.
 *
 * The role this hook plays is declared by the agent profile, not discovered at
 * runtime (PLAN section 10, "Decision A"): `.pi/agents/sdd/compiled/sdd-worker.md`
 * lists this file under `subagentOnlyExtensions` and names its policy directory
 * with `--policies .sdd/context-policies/subagent/`. An orchestrator-side hook
 * would point at `orchestrator/` instead; phase 1 ships that catalogue empty, so
 * its hook exists but does not invoke.
 *
 * BEHAVIOUR (plan section 14 / TASK015 spec)
 * ------------------------------------------
 *   1. Declares `name = "pi-context-police"`.
 *   2. Subscribes to `turn_end` (a core pi event) on the hook's OWN session.
 *   3. Keeps one byte offset per session in a module-level Map. Never persisted:
 *      the cursor dies with the process, which is what keeps the engine stateless.
 *   4. Decides whether to evaluate now from the policy's `trigger` block
 *      (`every_turns`, `on_milestone`, `on_loop_police`, `min_interval_minutes`)
 *      — it does NOT evaluate every turn.
 *   4a. TWO GATES, both checked BEFORE the CLI is spawned, both writing NOTHING
 *      when they skip. GATE B (interval): if `min_interval_minutes` is > 0 and a
 *      spawn happened for this session less than that many minutes ago, return —
 *      the log's contents are irrelevant to this gate. The clock counts failed
 *      spawns too, so a broken CLI is not retried every turn. GATE A (evidence):
 *      stat the session file ONCE before the spawn and return if its mtime is
 *      unchanged from the version last actually EVALUATED — polling a log that
 *      did not move cannot yield new alerts. A skipped poll is therefore only
 *      DEFERRED, never lost: the next turn offers the same work again.
 *   4b. The evidence watermark advances ONLY on a real evaluation, per exit path:
 *        exit 0 + ok/alerts_raised (classifier ran)  -> mtime YES, last-call YES, offset YES
 *        exit 0 + nothing_to_evaluate (0 evaluated)  -> mtime NO,  last-call YES, offset YES
 *        exit 1/2/3/4                                -> mtime NO,  last-call YES, offset NO
 *      So a run that read no new rows does not mark the log as current, and a
 *      failure does not either. `offsets` is deliberately NOT gated that way:
 *      it advances on every exit-0 integer `nextOffset`, because the truncation
 *      self-heal depends on the cursor following the report.
 *   5. Invokes `agent-instructor session evaluate --policies <file> --format json
 *      [--since-offset <offset>] [--previous-signal REF=VALUE]...`,
 *      omitting `--since-offset` entirely when no offset is stored for the
 *      session, so the CLI starts at byte 0. The string "undefined"/"null" is
 *      never passed: the parser takes `type=int` and would reject it.
 *   5c. Resolves the policy location to a FILE before spawning. The env var
 *      `PI_CONTEXT_POLICE_POLICIES` (or `DEFAULT_POLICIES_DIR` when unset) may
 *      name a directory — the agent profile declares one — but `--policies` is
 *      forwarded verbatim by the CLI and rejects a directory, so a directory is
 *      resolved to `<dir>/policies.yaml` and only a file path is emitted.
 *   5a. CARRIES THE ESCALATION HISTORY across stateless invocations. The CLI is a
 *      single-shot process, so the only way `kill_respawn` can be reached is for
 *      the hook to replay the session's recent `trapSignal` values into
 *      `--previous-signal <inputRef>=<value>`, one occurrence per stored value,
 *      OLDEST FIRST. They live in a module-level `signalHistory` Map keyed by
 *      inputRef, capped at 8 entries (the engine reads only the tail, and 8 is
 *      well beyond `escalation_evaluations`). Never persisted, like every other
 *      cursor here.
 *   5b. The history is appended ONLY when the entry actually evaluated:
 *      status != `nothing_to_evaluate` AND a numeric `trapSignal` AND
 *      `coverage.evaluationsRun === 1`. A poll that read no new rows must not
 *      count as a run — the same rule that governs the mtime watermark — or a
 *      static cursor would make escalation unreachable again.
 *   6. Parses the JSON, stores `nextOffset` from the entry whose `inputRef`
 *      matches this session file, and forwards EVERY alert to the parent
 *      orchestrator. No branching on `action`.
 *   6a. Forwards NOTHING when the entry carries zero alerts — an empty alert
 *      list is not actionable, so no message is sent on that turn.
 *   7. Fail-OPEN on operational failures: `console.warn` and continue.
 *   8. Fail-LOUD on configuration failures: a visible error to the orchestrator,
 *      surfaced even when there are zero alerts. A broken policy always shows.
 *   9. Never calls `steer`, `abort` or `spawn`. It reports; the orchestrator decides.
 *
 * WHY THE FAILURE SPLIT IS KEPT VISIBLY APART IN THE CODE
 * -------------------------------------------------------
 * ACK069 requires the two paths to be distinguishable at a glance, so they do not
 * share a helper. `reportOperationalFailure()` warns and returns — the child keeps
 * running, because a broken measurement is not evidence of a trapped worker.
 * `reportConfigurationFailure()` sends a message into the session and returns —
 * the orchestrator sees it, because an unreadable or invalid policy means the whole
 * governance layer is silently absent while runs still look healthy. Both are
 * reached through `classifyCliFailure()`, which maps the CLI's documented exit
 * codes onto exactly one of the two paths.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
  TurnEndEvent,
} from "@earendil-works/pi-coding-agent";

const NAME = "pi-child-context-police";

/** Set to "1" by pi-subagents in every sub-agent child process. */
const SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD";

/** Message channel used for both failure paths; distinct from the alert channel. */
const CONFIG_ERROR_TYPE = `${NAME}-configuration-error`;
const ALERT_CHANNEL = `${NAME}-alerts`;


/** Default policy directory for the sub-agent profile (relative to the project root). */
const DEFAULT_POLICIES_DIR = ".sdd/context-policies/subagent/";

/** Milestone event names recognised in `trigger.on_milestone`. */
const MILESTONE_MARKERS: Record<string, RegExp> = {
  task_end: /\bTASK\d{3}\b.*(complete|done|status\s*:\s*completed)|##\s*Status\s*\n\s*Completed/i,
  test_run: /\b(pytest|jest|vitest|npm\s+(run\s+)?test|phpunit|make\s+test)\b/i,
  file_change: /(^\s*\w+\(write|edit|replace_in_symbol|move_symbol|find_replace\))/im,
};

/** Exit codes of `session evaluate` (application/cli/commands/session.py). */
const EXIT_COMPLETED = 0;
const EXIT_USAGE_ERROR = 1;
const EXIT_POLICY_ERROR = 2;
const EXIT_INPUT_ERROR = 3;
const EXIT_CLASSIFIER_ERROR = 4;

/** Operational codes: the machinery failed, the worker is innocent. Warn and move on. */
const OPERATIONAL_EXITS = new Set<number>([EXIT_USAGE_ERROR, EXIT_INPUT_ERROR, EXIT_CLASSIFIER_ERROR]);
/** Configuration codes: the policy itself is wrong. Surface it. */
const CONFIGURATION_EXITS = new Set<number>([EXIT_POLICY_ERROR]);

/* The `turn_end` payload is the SDK's own `TurnEndEvent`, imported below. An
 * earlier revision declared a local interface here carrying `sessionFile`,
 * `sessionId` and `transcript`; none of those properties exists on the SDK type
 * (pi-coding-agent 1.3.0, dist/core/extensions/types.d.ts), so every read from
 * the event could only ever yield `undefined` and the hook leaned entirely on
 * the `ctx` fallback. Importing the real type is what makes that mismatch a
 * compile error instead of a silent dead branch.
 */

/** One byte offset per session file. In-memory only — never written to disk. */
const offsets = new Map<string, number>();

/** Turn counter per session, the clock `trigger.every_turns` divides. */
const turnCounts = new Map<string, number>();

/**
 * GATE A — mtimeMs of the last log version actually EVALUATED (not merely
 * spawned against). Advanced only when the classifier ran; never persisted, so
 * it dies with the process like every other cursor here.
 */
const evaluatedMtime = new Map<string, number>();

/**
 * GATE B — epoch ms of the last `session evaluate` SPAWN for a session, whatever
 * its outcome. Set immediately before the await so two overlapping
 * `turn_end` handlers cannot both pass the interval gate in the same turn,
 * and so a failing CLI is not retried every turn.
 */
const lastCallAt = new Map<string, number>();

/** Fallback for `trigger.min_interval_minutes` when it is absent or invalid. */
const DEFAULT_MIN_INTERVAL_MINUTES = 3;

/** Status the CLI reports when a run read no new rows and called no classifier. */
const STATUS_NOTHING_TO_EVALUATE = "nothing_to_evaluate";

/**
 * Recent `trapSignal` values per inputRef, oldest-first. Capped.
 *
 * The CLI is stateless: it cannot see that this session already scored high last
 * turn, so on its own it can never escalate `steer` to `kill_respawn`. The hook
 * replays this history into `--previous-signal REF=VALUE`. Appended only when the
 * entry actually evaluated (see the append site), never persisted, and capped at
 * `SIGNAL_HISTORY_LIMIT`: the engine reads only the tail, and the cap bounds
 * memory for a long-lived session.
 */
const signalHistory = new Map<string, number[]>();

/** Cap on `signalHistory` entries per inputRef. Far beyond `escalation_evaluations`. */
const SIGNAL_HISTORY_LIMIT = 8;

/** Sessions already reported as misconfigured, so one bad policy warns once. */
const configurationFailuresReported = new Set<string>();

// ---------------------------------------------------------------------------
// Policy reading (minimal YAML subset: scalars, inline lists, block lists)
// ---------------------------------------------------------------------------

interface TriggerConfig {
  everyTurns: number;
  onMilestone: string[];
  onLoopPolice: boolean;
  /**
   * Minimum minutes between two `session evaluate` spawns for one session.
   * 0 disables the interval gate. Hook-owned: the CLI never reads this key.
   */
  minIntervalMinutes: number;
}

/** Strip one YAML scalar's quotes and trailing comment. */
function scalar(value: string): string {
  const trimmed = value.trim();
  if (/^["'].*["']$/.test(trimmed)) return trimQuotes(trimmed);
  const hash = trimmed.indexOf(" #");
  const bare = hash === -1 ? trimmed : trimmed.slice(0, hash).trim();
  return /^["'].*["']$/.test(bare) ? trimQuotes(bare) : bare;
}

function trimQuotes(value: string): string {
  return value.replace(/^["']/, "").replace(/["']$/, "");
}

/** Parse `[a, b, c]` or a `- item` block list following a key. */
function listValue(lines: string[], index: number, inline: string): { values: string[]; next: number } {
  const bracket = inline.match(/^\[(.*)\]$/);
  if (bracket) {
    return { values: (bracket[1] ?? "").split(",").map((s) => scalar(s)).filter(Boolean), next: index + 1 };
  }
  const block: string[] = [];
  let i = index + 1;
  while (i < lines.length && /^\s*-\s+/.test(lines[i] ?? "")) {
    block.push(scalar((lines[i] ?? "").replace(/^\s*-\s+/, "")));
    i++;
  }
  return { values: block.filter(Boolean), next: i };
}

/**
 * Read the `trigger:` block from a policies.yaml.
 * Deliberately a small reader over the documented shape rather than a YAML
 * dependency: the extension ships inside the template tree and must not assume a
 * YAML library is installed in the JS runtime.
 */
function readTrigger(raw: string): TriggerConfig {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const config: TriggerConfig = {
    everyTurns: 0,
    onMilestone: [],
    onLoopPolice: false,
    minIntervalMinutes: DEFAULT_MIN_INTERVAL_MINUTES,
  };
  let inTrigger = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (/^[A-Za-z_][A-Za-z0-9_]*:/.test(line)) {
      inTrigger = /^trigger:/.test(line);
      continue;
    }
    if (!inTrigger) continue;
    const key = line.match(/^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$/);
    if (!key) continue;
    const field = key[1] ?? "";
    const value = key[2] ?? "";
    if (field === "every_turns") {
      const n = Number.parseInt(scalar(value), 10);
      config.everyTurns = Number.isFinite(n) && n > 0 ? n : 0;
    } else if (field === "on_milestone") {
      const parsed = listValue(lines, i, value.trim());
      config.onMilestone = parsed.values;
      i = parsed.next - 1;
    } else if (field === "on_loop_police") {
      config.onLoopPolice = scalar(value) === "true";
    } else if (field === "min_interval_minutes") {
      // Absent or invalid clamps to the default; an explicit 0 disables the
      // interval gate, so 0 must survive as a value and not fall through to 3.
      const minutes = Number.parseInt(scalar(value), 10);
      config.minIntervalMinutes =
        Number.isFinite(minutes) && minutes >= 0 ? minutes : DEFAULT_MIN_INTERVAL_MINUTES;
    }
  }
  return config;
}

// ---------------------------------------------------------------------------
// Cadence: does this turn warrant an evaluation?
// ---------------------------------------------------------------------------

/**
 * Decide whether to evaluate now. Three independent reasons, any one of which is
 * sufficient (plan section 17, first diamond of the flow diagram).
 */
function shouldEvaluate(trigger: TriggerConfig, turn: number, milestoneHits: string[]): boolean {
  if (trigger.onLoopPolice && milestoneHits.length > 0) return true;
  if (trigger.onMilestone.length > 0 && milestoneHits.length > 0) return true;
  if (trigger.everyTurns > 0 && turn % trigger.everyTurns === 0) return true;
  return false;
}

/**
 * Resolve the policy location to a YAML FILE path the CLI can consume.
 *
 * The env var (and the default it falls back to) names a DIRECTORY in the
 * shipped agent profile, but `session evaluate --policies` forwards its value
 * verbatim to `read_policies` and therefore rejects a directory outright. Two
 * shapes are accepted so an existing configuration keeps working:
 *
 *   - a directory that exists  -> `<dir>/policies.yaml`
 *   - anything else            -> the path verbatim (an explicit file, or a
 *                                directory that does not exist yet, whose
 *                                downstream `readFileSync` produces the loud
 *                                CONFIGURATION failure that names the path)
 *
 * A relative value is anchored on `cwd`, the project root the CLI is spawned in.
 *
 * @param cwd Project root the CLI runs in.
 * @param input Path from `PI_CONTEXT_POLICE_POLICIES` or `DEFAULT_POLICIES_DIR`.
 * @returns A path whose final segment is a `.yaml` file, never a directory.
 */
function resolvePoliciesFile(cwd: string, input: string): string {
  const candidate = join(cwd, input);
  // `existsSync` first so a missing path is not an exception, and `statSync`
  // only on a path that exists: a race that removes it between the two calls is
  // caught and falls through to the verbatim path, where the read fails loudly.
  try {
    if (existsSync(candidate) && statSync(candidate).isDirectory()) {
      return join(candidate, "policies.yaml");
    }
  } catch {
    // Unreadable path: fall through and let the caller's read fail loudly.
  }
  return candidate;
}

/** Which configured milestones the just-finished turn touched. */
function detectMilestones(names: string[], transcript: string): string[] {
  return names.filter((name) => {
    const marker = MILESTONE_MARKERS[name];
    return marker ? marker.test(transcript) : false;
  });
}

// ---------------------------------------------------------------------------
// Failure paths — deliberately two functions, never one shared helper (ACK069)
// ---------------------------------------------------------------------------

/**
 * OPERATIONAL path: fail OPEN. The CLI was down, the JEV endpoint errored, the
 * session file was unreadable. None of that says anything about whether the
 * worker is trapped, so it must not intervene and must not stop the child.
 */
function reportOperationalFailure(detail: string): void {
  console.warn(`[${NAME}] operational failure, continuing: ${detail}`);
}

/**
 * CONFIGURATION path: fail LOUD. Invalid YAML, missing policy file, empty
 * catalogue. The governance layer is absent while every run still looks healthy,
 * which is precisely the failure that must not be swallowed. Emitted both to the
 * console and into the session so the orchestrator sees it.
 */
function reportConfigurationFailure(pi: ExtensionAPI, key: string, detail: string): void {
  if (configurationFailuresReported.has(key)) return;
  configurationFailuresReported.add(key);
  console.error(`[${NAME}] configuration failure: ${detail}`);
  try {
    pi.sendMessage(
      {
        customType: CONFIG_ERROR_TYPE,
        content:
          `[${NAME}] CONFIGURATION FAILURE — the JEV policy is not usable and no ` +
          `intervention data will be produced for this session.\n${detail}\n` +
          `This is fail-loud by design: fix the policy rather than ignore it.`,
        display: true,
      },
      { triggerTurn: false }
    );
  } catch (error) {
    console.error(`[${NAME}] could not surface the configuration failure: ${String(error)}`);
  }
}

/** Route one CLI outcome to exactly one of the two paths above. */
function classifyCliFailure(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  code: number | null,
  stderr: string,
  key: string
): void {
  const detail = stderr.trim() || `exit code ${code}`;
  if (code !== null && CONFIGURATION_EXITS.has(code)) {
    reportConfigurationFailure(pi, key, detail);
    return;
  }
  if (code !== null && OPERATIONAL_EXITS.has(code)) {
    reportOperationalFailure(detail);
    return;
  }
  reportOperationalFailure(`unexpected exit code ${code}: ${detail}`);
}

// ---------------------------------------------------------------------------
// CLI invocation
// ---------------------------------------------------------------------------

/** Resolve the CLI command without hard-coding this repository's layout. */
function cliCommand(cwd: string): { file: string; baseArgs: string[] } {
  const override = process.env.PI_CONTEXT_POLICE_CLI?.trim();
  if (override) return { file: override, baseArgs: [] };
  const venv = join(cwd, ".venv", "bin", "agent-instructor");
  try {
    statSync(venv);
    return { file: venv, baseArgs: [] };
  } catch {
    return { file: "agent-instructor", baseArgs: [] };
  }
}

/** Run one `session evaluate`, resolving with stdout and the exit code. */
function runEvaluate(command: string, args: string[], cwd: string): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf-8");
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf-8");
    });
    child.on("error", (error: Error) => {
      // Spawning failed outright (CLI not installed): operational, fail open.
      resolve({ stdout: "", stderr: `spawn failed: ${error.message}`, code: null });
    });
    child.on("close", (code: number | null) => resolve({ stdout, stderr, code }));
  });
}

/**
 * Extract the JSON report from a completed `session evaluate` stdout.
 *
 * stdout is not a pure document. The CLI announces the evaluation-log path
 * through `print_info`, whose default sink is stdout (`session.py`), so a
 * successful run emits a diagnostics line before the report:
 *
 *     [i] /path/to/.sdd/logs/session-evaluate/<ts>.log
 *     {"evaluations": [...]}
 *
 * Parsing the whole stream therefore failed on that line's ANSI marker with
 * `Unexpected token '\x1b', "[\x1b[96mi\x1b[0m"`. This dropped EVERY alert:
 * the hook returned before `forwardAlerts`, so the orchestrator was told
 * nothing while the engine kept evaluating correctly.
 *
 * The report is the last line that parses as a JSON object. Scanning
 * backwards is deliberate: diagnostics precede the document, never follow it,
 * so the first success from the end is the report and no earlier brace-bearing
 * line can shadow it. A genuine transport failure still throws, which the
 * caller routes to the operational path.
 *
 * @param stdout Full captured stdout of the child process.
 * @returns The parsed report document.
 * @throws {SyntaxError} When no line carries a JSON object.
 */
function parseReportFromStdout(stdout: string): EvaluationDocument {
  // The report is indented (`encode_json` uses `indent=2`), so it spans many
  // lines and cannot be recovered line by line. Diagnostics always PRECEDE the
  // document and never follow it, so the document is the trailing span that
  // starts at a line whose first non-space character is `{` and parses whole.
  // Trying every such candidate from the end keeps a genuine transport failure
  // throwing while tolerating any number of preceding diagnostics.
  const lines = stdout.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!(lines[i] ?? "").trimStart().startsWith("{")) continue;
    const candidate = lines.slice(i).join("\n").trim();
    try {
      return JSON.parse(candidate);
    } catch {
      // A brace inside a diagnostic line, not the document: keep walking back.
    }
  }
  // Report the original stream shape so the warn stays diagnosable.
  throw new SyntaxError(`no JSON document in stdout: ${JSON.stringify(stdout.slice(0, 120))}`);
}
/**
 * Build the argument vector, omitting `--since-offset` when there is no cursor
 * and omitting `--previous-signal` when no history is stored.
 *
 * `previousSignals` is the session's recent trap signals, oldest-first. One
 * `--previous-signal <inputRef>=<value>` occurrence is emitted per stored value,
 * in that order, so the CLI sees the same sequence the engine would have seen had
 * it lived across invocations. Only finite numbers are serialised: a `NaN` or a
 * non-number would be rejected by the CLI's value parser, and an empty history
 * emits nothing at all.
 */
function evaluateArgs(
  policiesFile: string,
  sinceOffset: number | undefined,
  inputRef: string,
  previousSignals: readonly number[]
): string[] {
  // No `--lookback` is emitted: the flag was removed from the CLI. How many
  // trailing turns are read is `window` in the policy, owned by the CLI side.
  //
  // `--session` takes `nargs='+'`, so its value MUST follow it immediately.
  // Interleaving another flag between the two (`--session --since-offset 5`)
  // made argparse consume the flag as the value and abort with
  //   `argument --session: expected at least one argument`
  // which the hook routed to the CONFIGURATION path -- a visible failure that
  // produced no data at all. The path is therefore bound here, not appended by
  // the caller, and every later flag follows the declared session.
  const args = ["session", "evaluate", "--policies", policiesFile, "--format", "json", "--session", inputRef];
  // Only a real number reaches the flag. `Number.isInteger` guards against ever
  // serialising undefined/null/NaN, which the int parser would reject.
  if (sinceOffset !== undefined && Number.isInteger(sinceOffset) && sinceOffset >= 0) {
    args.push("--since-offset", String(sinceOffset));
  }
  // Oldest-first, one occurrence per earlier evaluation. `REF` is the report's
  // own `inputRef` and binds to the first declared session, so the whole history
  // belongs to the session being evaluated.
  for (const signal of previousSignals) {
    if (typeof signal !== "number" || !Number.isFinite(signal)) continue;
    args.push("--previous-signal", `${inputRef}=${String(signal)}`);
  }
  return args;
}

// ---------------------------------------------------------------------------
// Report shape (translated from domain/jev/report.py, PLAN section 4.2)
// ---------------------------------------------------------------------------

/**
 * Coverage block of one evaluation entry.
 *
 * Mirrors `domain.jev.models.Coverage` as rendered by
 * `domain/jev/report.py::_coverage_to_dict`: four counters and no lookback
 * fields. `rowsSkipped` is what lets the orchestrator discount an alert built
 * on a small sample.
 */
interface Coverage {
  rowsTotal: number;
  rowsEvaluated: number;
  rowsSkipped: number;
  evaluationsRun: number;
}

/**
 * One decision emitted for one input.
 *
 * Mirrors `domain.jev.models.Alert` as rendered by
 * `domain/jev/report.py::_alert_to_dict`, key for key. `matchedRule` records
 * where the decision came from (`options[3]`, `project_overrides[0]`,
 * `escalation`), so the orchestrator can justify what it forwards.
 */
interface Alert {
  scope: string;
  option: string;
  action: string;
  message: string;
  probability: number;
  signal: string;
  matchedRule: string;
  evidence: string;
}

/**
 * Outcome of evaluating one input.
 *
 * Mirrors `domain.jev.models.EvaluationEntry` as rendered by
 * `domain/jev/report.py::_entry_to_dict`. `trapSignal` and `margin` are `null`
 * when nothing was evaluated — an infinite margin is a real measurement and
 * survives JSON encoding as `Infinity`, which `JSON.parse` reads back
 * unchanged. `nextOffset` is the byte cursor the hook stores for the next
 * invocation.
 *
 * Declared with `type` rather than `interface` so the structural value
 * `JSON.parse` returns is assignable to it without a cast.
 */
type EvaluationReport = {
  inputRef: string;
  scope: string;
  status: string;
  nextOffset: number;
  trapSignal: number | null;
  margin: number | null;
  coverage: Coverage;
  alerts: Alert[];
};

/**
 * Top-level document of one `session evaluate --format json` run.
 *
 * Mirrors `domain/jev/report.py::to_json_dict`: a single `evaluations` key
 * holding one entry per declared input, in declaration order.
 */
interface EvaluationDocument {
  evaluations: EvaluationReport[];
}

// ---------------------------------------------------------------------------
// Alert forwarding
// ---------------------------------------------------------------------------

/**
 * Forward every alert of the matching entry to the parent orchestrator.
 * NO branching on `action`: steer / kill_respawn / none are all forwarded as-is
 * and the orchestrator (the LLM) decides. The payload carries alerts, coverage,
 * sessionId and turn — the consumer contract of plan section 18.
 */

/**
 * Derive the supervisor channel directory for THIS child process.
 *
 * `pi-subagents` computes it in the parent as
 *   <tmp>/pi-subagents-<scope>/supervisor-channels/<runId>-<agent>-<childIndex>
 * and hands it to the child through runtime config, not through an env var, so
 * a hook cannot read it directly. It is, however, fully derivable from the
 * child's own session path, which always ends in `.../<runId>/run-<n>/session.jsonl`.
 *
 * Returns `undefined` when the path does not match that shape -- the hook is
 * then running outside a pi-subagents child and must not guess.
 */
/**
 * The run id encoded in a child session path (`.../<runId>/run-<n>/session.jsonl`).
 *
 * Separate from {@link resolveSupervisorChannel} because the run id is knowable
 * even when no channel directory exists -- that is exactly the case a liveness
 * check needs to disambiguate.
 */
function supervisorRunIdOf(sessionFile: string): string | undefined {
  const match = sessionFile.replace(/\\/g, "/").match(/\/([^/]+)\/run-\d+\/session\.jsonl$/);
  return match ? match[1] : undefined;
}
function resolveSupervisorChannel(sessionFile: string): { channelDir: string; runId: string; childIndex: number } | undefined {
  const normalized = sessionFile.replace(/\\/g, "/");
  const match = normalized.match(/\/([^/]+)\/run-(\d+)\/session\.jsonl$/);
  if (!match) return undefined;
  const runId = match[1] ?? "";
  const indexText = match[2] ?? "";
  const childIndex = Number.parseInt(indexText, 10);
  if (!Number.isInteger(childIndex)) return undefined;

  // The channel directory embeds the agent name. In pi-subagents 0.79.x it was
  // created at launch; in 0.81.0 it is created lazily. First look for an existing
  // directory via readdirSync, and if none exists yet, derive it deterministically
  // from status.json so we can create it ourselves on write.
  const root = join(tmpdir(), `pi-subagents-${resolveTempScopeId()}`, "supervisor-channels");
  const prefix = `${sanitizeSupervisorSegment(runId)}-`;
  const suffix = `-${childIndex}`;
  try {
    const entries = readdirSync(root);
    for (const entry of entries) {
      if (entry.startsWith(prefix) && entry.endsWith(suffix)) {
        return { channelDir: join(root, entry), runId, childIndex };
      }
    }
  } catch {
    // Root might not exist yet; we will create the full path below.
  }

  // Derive agent from the run's status.json
  const statusPath = join(
    tmpdir(),
    `pi-subagents-${resolveTempScopeId()}`,
    "async-subagent-runs",
    runId,
    "status.json"
  );
  try {
    const status = JSON.parse(readFileSync(statusPath, "utf-8")) as {
      steps?: Array<{ agent?: string }>;
    };
    const agent = status?.steps?.[childIndex]?.agent ?? status?.steps?.[0]?.agent;
    if (agent) {
      const channelDir = join(
        root,
        `${sanitizeSupervisorSegment(runId)}-${sanitizeSupervisorSegment(agent)}-${childIndex}`
      );
      return { channelDir, runId, childIndex };
    }
  } catch {
    // status.json not yet available or unreadable
  }

  return undefined;
}

/** Mirrors pi-subagents' own segment sanitiser for channel names. */
function sanitizeSupervisorSegment(value: string): string {
  return value.trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
}

/** Mirrors pi-subagents' temp scope: the uid on POSIX, the user name on Windows. */
function resolveTempScopeId(): string {
  if (typeof process.getuid === "function") return `uid-${process.getuid()}`;
  for (const key of ["USERNAME", "USER", "LOGNAME"]) {
    const value = process.env[key]?.trim();
    if (value) return value.replace(/[^A-Za-z0-9._-]+/g, "-");
  }
  return "unknown";
}

/**
 * Whether the run owning *runId* is still executing.
 *
 * `pi-subagents` writes `status.json` per run: a live run carries
 * `state: "running"` and no `endedAt`, a finished one carries a terminal state
 * plus `endedAt`. A missing file is treated as NOT live -- the alert then falls
 * back silently, which is the safe direction for an unknown run.
 */
function isRunLive(runId: string): boolean {
  const statusPath = join(
    tmpdir(),
    `pi-subagents-${resolveTempScopeId()}`,
    "async-subagent-runs",
    runId,
    "status.json"
  );
  try {
    const status = JSON.parse(readFileSync(statusPath, "utf-8")) as { state?: string; endedAt?: number };
    return status.endedAt === undefined && status.state !== "complete" && status.state !== "failed";
  } catch {
    return false;
  }
}

/**
 * Deliver one composed alert to the parent orchestrator.
 *
 * This extension runs inside the CHILD process, so `pi.sendMessage` writes into
 * the child's own session: persisted, but nothing wakes the parent to read it,
 * and `pi-subagents` only wakes a parent for lifecycle completions. An alert
 * about a worker stuck in a sand trap must reach the orchestrator WHILE the
 * worker is stuck, so it cannot wait for the run to end -- and it cannot depend
 * on the child model invoking `contact_supervisor`, because a trapped model
 * stops issuing new tool calls. The write therefore happens here, in the
 * handler, driven by the JEV verdict alone.
 *
 * COUPLING -- read before upgrading:
 * `requests/<id>.json` under the supervisor channel is pi-subagents' internal
 * transport, not a published API. The format is pinned to pi-subagents 0.79.x
 * (`native-supervisor-channel.js`: REQUESTS_DIR, the `subagent.supervisor.request`
 * document and the `expectsReply: false` progress-update variant). If the
 * package changes that layout, this write silently reaches nobody, which is why
 * a missing channel is reported loudly instead of degrading to sendMessage.
 */
function deliverToOrchestrator(
  pi: ExtensionAPI,
  content: string,
  sessionFile: string,
  entry: EvaluationReport
): boolean {
  const channel = resolveSupervisorChannel(sessionFile);
  if (!channel) {
    // No channel, two very different situations:
    //  * the worker already finished -- there is nothing left to correct, so the
    //    alert is dropped without a trace (reporting it would reach nobody);
    //  * the worker is STILL RUNNING but has no supervisor channel (the bridge
    //    was off when the run started, or `pi-subagents` changed the layout).
    //    Dropping the alert here would leave exactly the case this hook exists
    //    for -- a worker stuck in a sand trap -- invisible to the orchestrator.
    //    Fall back to the child's own session so the transcript keeps the
    //    evidence and the orchestrator can read it from the run artifacts.
    const runId = supervisorRunIdOf(sessionFile);
    if (runId !== undefined && isRunLive(runId)) {
      reportOperationalFailure(
        `no supervisor channel for a LIVE run ${runId}; alert parked in the child session`
      );
      pi.sendMessage(
        { customType: ALERT_CHANNEL, content, display: false, details: { sessionFile, entry } },
        { triggerTurn: false }
      );
      return false;
    }
    return false;
  }

  const requestsDir = join(channel.channelDir, "requests");
  const requestId = randomUUID();
  const request = {
    type: "subagent.supervisor.request",
    id: requestId,
    createdAt: Date.now(),
    // BLOCKING by design. `progress_update` would be non-blocking, but the
    // parent only receives a pushed notice (`needs_attention`) for a request it
    // must answer -- a progress update is invisible until someone polls the
    // channel, and an orchestrator model is free to ignore a message it merely
    // reads. `need_decision` forces the exchange: the parent is woken, and the
    // worker stays blocked until it answers. A worker in a sand trap has nothing
    // left to lose by blocking, and the alternative is an alert nobody acts on.
    reason: "need_decision",
    message: content,
    expectsReply: true,
    runId: channel.runId,
    childIndex: channel.childIndex,
  };

  try {
    mkdirSync(requestsDir, { recursive: true });
    writeFileSync(join(requestsDir, `${requestId}.json`), JSON.stringify(request, null, "\t"), "utf-8");
  } catch (error) {
    reportOperationalFailure(`cannot write supervisor request: ${String(error)}`);
    return false;
  }

  // Mirror into the child's own session so the alert is also visible in its
  // transcript; the orchestrator's copy is the supervisor request above.
  pi.sendMessage(
    { customType: ALERT_CHANNEL, content, display: false, details: { sessionFile, entry } },
    { triggerTurn: false }
  );
  return true;
}

export function forwardAlerts(pi: ExtensionAPI, entry: EvaluationReport, ctx: ExtensionContext | undefined, sessionId: string, turn: number, sessionFile: string): void {
  const alerts = entry.alerts;
  if (alerts.length === 0) return;
  const lines = [
    `[${NAME}] session=${sessionId} turn=${turn} inputRef=${entry.inputRef}`,
    `status=${entry.status} trapSignal=${entry.trapSignal ?? "null"} ` +
      `margin=${entry.margin ?? "null"} nextOffset=${entry.nextOffset}`,
    `coverage=${JSON.stringify(entry.coverage)}`,
    `alerts (${alerts.length}):`,
  ];
  for (const alert of alerts) {
    lines.push(
      `  - option=${alert.option} action=${alert.action} ` +
        `probability=${alert.probability} signal=${alert.signal} ` +
        `matchedRule=${alert.matchedRule} message=${alert.message}`
    );
  }
  lines.push("The orchestrator decides among these; the hook does not act on them.");
  deliverToOrchestrator(pi, lines.join("\n"), sessionFile, entry);
}

// ---------------------------------------------------------------------------
// Hook registration
// ---------------------------------------------------------------------------

export default function contextPolice(pi: ExtensionAPI): void {
  // CHILD ONLY. This half evaluates a sub-agent's own transcript, so it must
  // never run in a parent/orchestrator session: there the "worker" would be the
  // orchestrator itself, and `review_trap` fires on ordinary coordinating work.
  // pi auto-loads every file under `.pi/extensions/` in every process, so the
  // guard lives here rather than in a per-agent `subagentOnlyExtensions` list --
  // no fragile `../../../../` paths, and it cannot be forgotten by a profile.
  // The parent half is pi-child-context-listener.
  if (process.env[SUBAGENT_CHILD_ENV] !== "1") return;

  // `turn_end` is the core pi event that fires when a turn completes. It is
  // emitted in the sub-agent's own process (verified: 3 fires per 3-turn run),
  // and `ctx.sessionManager.getSessionFile()` there points at the sub-agent's
  // log — which is exactly the file this hook evaluates.
  pi.on("turn_end", async (event: TurnEndEvent, ctx: ExtensionContext) => {
    try {
      const cwd = typeof ctx?.cwd === "string" ? ctx.cwd : process.cwd();
      const sessionManager = ctx?.sessionManager;
      // SESSION IDENTITY COMES FROM `ctx`, NOT FROM THE EVENT. The SDK's
      // `TurnEndEvent` carries `type`, `turnIndex`, `message`, `toolResults`,
      // `messageEntryId` and `toolResultEntryIds` -- no `sessionFile`, no
      // `sessionId`. `ctx.sessionManager` is the only source.
      const sessionFile =
        typeof sessionManager?.getSessionFile === "function"
          ? sessionManager.getSessionFile()
          : undefined;
      if (!sessionFile) {
        reportOperationalFailure("no session file available for this event");
        return;
      }
      const sessionId =
        typeof sessionManager?.getSessionId === "function"
          ? String(sessionManager.getSessionId())
          : String(sessionFile);

      // Cadence bookkeeping happens before the policy read: the counter advances
      // even on turns that decide not to evaluate.
      const turn = (turnCounts.get(sessionFile) ?? 0) + 1;
      turnCounts.set(sessionFile, turn);

      // Policies come from the location the agent profile declares, so the hook
      // stays parameterised rather than tied to one scope. `DEFAULT_POLICIES_DIR`
      // is the fallback only when the env var is unset or blank.
      //
      // The env var is accepted in either shape so an existing configuration
      // keeps working — a DIRECTORY (the profile's declaration) or an explicit
      // FILE path — but only a file ever leaves this function.
      const policiesInput =
        process.env.PI_CONTEXT_POLICE_POLICIES?.trim() || DEFAULT_POLICIES_DIR;
      // `--policies` is forwarded verbatim by the CLI
      // (application/cli/commands/session.py::_resolve_policies_path passes
      // `Path(explicit)` straight to `read_policies`), so a directory argument
      // fails with IsADirectoryError. Resolving a directory to its
      // `policies.yaml` here is therefore mandatory, not cosmetic: it is the
      // only place that knows the env var may denote a directory.
      const policiesPath = resolvePoliciesFile(cwd, policiesInput);
      let trigger: TriggerConfig;
      try {
        trigger = readTrigger(readFileSync(policiesPath, "utf-8"));
      } catch (error) {
        // Missing/unreadable policy file is a CONFIGURATION failure, not an
        // operational one: nothing is being governed until it is fixed.
        reportConfigurationFailure(pi, `config:${policiesPath}`, `${policiesPath}: ${String(error)}`);
        return;
      }

      // MILESTONE MARKERS ARE NOT REACHABLE FROM THIS EVENT. `TurnEndEvent`
      // carries `message`, `toolResults` and the `BoundaryState` fields -- none
      // of them is a transcript string, and an earlier revision read a
      // `event.transcript` that does not exist, so `detectMilestones` was always
      // handed "" and no milestone ever fired. Passing "" keeps that behaviour
      // explicit (cadence is carried by `every_turns` and `on_loop_police`)
      // rather than leaving a dead read that looks alive. Wiring milestones to
      // real content is a separate change with its own tests.
      const milestones = detectMilestones(trigger.onMilestone, "");
      if (!shouldEvaluate(trigger, turn, milestones)) return;

      // GATE B — interval. Checked before stat and before spawn, so a deferred
      // poll costs one policy read and writes nothing: no mtime, no last-call,
      // no offset. The milestone it might have caught is re-offered next turn.
      const now = Date.now();
      const intervalMs = trigger.minIntervalMinutes * 60_000;
      const sinceCall = lastCallAt.get(sessionFile);
      if (intervalMs > 0 && sinceCall !== undefined && now - sinceCall < intervalMs) return;

      // GATE A — evidence. The mtime is captured BEFORE the spawn, never after:
      // a version read after the run may already be a later write, which would
      // mark the wrong log as evaluated. An unchanged mtime means the CLI would
      // read no new rows, so there is nothing to learn.
      let preRunMtimeMs: number;
      try {
        preRunMtimeMs = statSync(sessionFile).mtimeMs;
      } catch (error) {
        reportOperationalFailure(`cannot stat session file ${sessionFile}: ${String(error)}`);
        return;
      }
      const evaluatedAt = evaluatedMtime.get(sessionFile);
      if (evaluatedAt !== undefined && evaluatedAt === preRunMtimeMs) return;

      const stored = offsets.get(sessionFile);
      const { file, baseArgs } = cliCommand(cwd);
      // The escalation history is keyed by the report's `inputRef`, which for a
      // session log is the session file path. Passing it here keeps the REF the
      // hook sends identical to the REF the CLI reports back.
      const history = signalHistory.get(sessionFile) ?? [];
      // The session path travels INSIDE `evaluateArgs`, immediately after
      // `--session`; see the `nargs='+'` note there. Appending it here would
      // place it after `--since-offset`/`--previous-signal` and argparse would
      // reject the whole invocation.
      const args = [...baseArgs, ...evaluateArgs(policiesPath, stored, sessionFile, history)];
      // Recorded BEFORE the await, for two reasons: a failed attempt must count
      // (otherwise a broken CLI is retried every turn), and setting it first
      // means two overlapping `turn_end` handlers cannot both pass GATE B in
      // the same JS turn.
      lastCallAt.set(sessionFile, Date.now());
      const result = await runEvaluate(file, args, cwd);

      if (result.code !== EXIT_COMPLETED) {
        classifyCliFailure(pi, ctx, result.code, result.stderr, `cli:${sessionId}`);
        return;
      }

      // stdout is NOT pure JSON: the CLI announces the evaluation-log path with
      // `print_info`, whose default sink is stdout, so a completed run emits
      //   [i] /path/to/<ts>.log
      //   {"evaluations": [...]}
      // before the document. Parsing the whole stream failed on the `\x1b[96mi`
      // marker of that line. The report is the last line that parses as a JSON
      // object, so search backwards and tolerate any number of diagnostic lines.
      let document: EvaluationDocument;
      try {
        document = parseReportFromStdout(result.stdout);
      } catch (error) {
        // Malformed JSON from a completed run is operational: the run succeeded,
        // only its transport broke.
        reportOperationalFailure(`unparseable JSON report: ${String(error)}`);
        return;
      }

      // `evaluations` is required by the type; `Array.isArray` guards the
      // untrusted payload, where a malformed document could carry anything.
      const entries: EvaluationReport[] = Array.isArray(document.evaluations) ? document.evaluations : [];
      const entry = entries.find((candidate) => candidate.inputRef === sessionFile) ?? entries[0];
      if (!entry) {
        reportOperationalFailure("report carried no evaluations");
        return;
      }

      // The evidence watermark advances ONLY on a real evaluation. A run that
      // read no new rows (`nothing_to_evaluate`) did not look at this version of
      // the log, so recording its mtime would silence the next turn for work
      // that was never done. Failures already returned above, so they leave the
      // watermark untouched as well.
      if (entry.status !== STATUS_NOTHING_TO_EVALUATE) {
        evaluatedMtime.set(sessionFile, preRunMtimeMs);
      }

      // Escalation history. Appended ONLY when this run actually evaluated: a
      // poll that read no new rows returned `nothing_to_evaluate` with
      // `evaluationsRun == 0`, and counting it as a run would let a static
      // cursor make `kill_respawn` unreachable — the same rule that governs the
      // mtime watermark above. Capped at SIGNAL_HISTORY_LIMIT so a long session
      // cannot grow it without bound.
      if (
        entry.status !== STATUS_NOTHING_TO_EVALUATE &&
        entry.trapSignal !== null &&
        entry.coverage.evaluationsRun === 1
      ) {
        const h = signalHistory.get(entry.inputRef) ?? [];
        h.push(entry.trapSignal);
        if (h.length > SIGNAL_HISTORY_LIMIT) h.shift();
        signalHistory.set(entry.inputRef, h);
      }

      // The offset store is deliberately NOT gated on `evaluated`: the cursor
      // follows every exit-0 integer nextOffset (including the truncation
      // self-heal where the log shrank), so the self-heal keeps working.
      const next = Number.isInteger(entry.nextOffset) ? entry.nextOffset : undefined;
      if (next !== undefined) {
        // If nextOffset did not advance, do not retry: store it and wait for the
        // next cadence hit rather than re-reading the same bytes.
        offsets.set(sessionFile, next);
      }

      forwardAlerts(pi, entry, ctx, sessionId, turn, sessionFile);
    } catch (error) {
      // Last-resort containment. An exception escaping here would abort the child's
      // turn for a measurement failure — the definition of an operational fault.
      reportOperationalFailure(String(error));
    }
  });
}
