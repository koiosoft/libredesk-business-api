/**
 * skill-injector — deterministic skill injection into a sub-agent's prompt.
 *
 * WHY THIS EXISTS
 * ---------------
 * The passive skill mechanism (the `<available_skills>` index: name + description + location) is weak:
 * the agent SEES the skill in its catalog but does not necessarily USE it. Empirically, agents ignored
 * the index in most runs.
 *
 * The fix: inject the skill's CONTENT (the SKILL.md body) into the sub-agent's prompt as binding
 * guidance, driven by the task itself.
 *
 * ARCHITECTURE (two phases)
 * -------------------------
 *   Phase 1 (orchestrator): the task file declares which skills it needs, e.g.
 *       ## SKILLS_REQUIRED: [python-testing, koiosoft-logging]
 *   Phase 2 (this extension): reads that declaration, resolves each skill, and injects its CONTENT.
 *
 * This file is a generic injector container: SKILLS_REQUIRED is one rule today, and future rules
 * (e.g. forbidden skills, skill hints) can live alongside it.
 *
 * HOW THE TASK IS READ
 * --------------------
 * The child's `event.prompt` contains the LAUNCHER text (e.g. "Execute the task file at `.sdd/logs/development-cycles/<cycle>/tasks/TASK001.md`"),
 * NOT the task file's contents. So this extension:
 *   1. Scans `event.prompt` for `.sdd/**.md` paths.
 *   2. Reads those files (task files first) to build a task corpus.
 *   3. Parses `SKILLS_REQUIRED: [...]` from that corpus.
 *
 * SKILL NAME SYNTAX
 * -----------------
 *   - "skill-name"                 → searched across the local roots, then across every package under
 *                                    `<cwd>/.pi/npm/node_modules/*​/skills/<name>/SKILL.md`.
 *   - "package:skill-name"         → resolved directly from that package:
 *                                    first via its `package.json` → `pi.skills`, then the conventional
 *                                    `<cwd>/.pi/npm/node_modules/<package>/skills/<skill-name>/SKILL.md`.
 *                                    Use this form when a name could be ambiguous.
 *
 * WHY `result.message` AND NOT `result.systemPrompt`
 * --------------------------------------------------
 * pi-subagents launches children with `systemPromptMode: "replace"`, which sets `forceSystemPrompt`.
 * That override DISCARDS anything the hook returns as `systemPrompt`. The `result.message` channel, by
 * contrast, is appended to the conversation history and reaches the model reliably. We use that.
 *
 * SAFETY
 * ------
 * SUB-AGENTS ONLY. Two guards (either one is enough):
 *   1. `PI_SUBAGENT_CHILD=1` in the environment (set by pi-subagents for background children).
 *   2. A literal `<active_agent name="..."/>` tag already present in the system prompt (covers
 *      in-process/foreground children).
 * If neither holds, the extension abstains (it never touches the main session).
 *
 * Everything is best-effort: any error is swallowed so the child always starts.
 */

import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD";
const ACTIVE_AGENT_TAG = /<active_agent\s+name=["'][^"']+["'][^>]*>/i;

/** Local skill roots, scanned by bare skill name. */
const LOCAL_SKILL_ROOTS = [
  [".sdd", "skills", "agents"],
  [".sdd", "core", "skills"],
  [".agents", "skills"],
];

/** Root that holds the project's installed pi packages (each may expose skills). */
const PACKAGE_ROOT = [".pi", "npm", "node_modules"];

/**
 * Build the task corpus. The launcher text only carries the task-file PATH, so we also read any
 * `.sdd/**.md` files referenced in it (task files first, since the declaration usually lives there).
 */
/**
 * Rank a referenced path by how likely it is to be a task file.
 *
 * Returns 2 for the current layout (`tasks/TASK<NNN>.md`), 1 for the historical
 * spelling (`task-<N>.md`), 0 for anything else. The current layout ranks ahead
 * of the historical one so a corpus that references both reads the declared task
 * first; every referenced `.md` is still read regardless of rank, since the rank
 * only decides which is read first.
 */
function rankTaskPath(path: string): number {
  const basename = path.split("/").pop() ?? "";
  if (/^TASK\d{3}\.md$/.test(basename)) return 2;
  if (/^task-\d+\.md$/.test(basename)) return 1;
  return 0;
}

function taskCorpusOf(event: { prompt?: string }, cwd: string): string {
  let corpus = typeof event.prompt === "string" ? event.prompt : "";
  const paths = [...corpus.matchAll(/(\.sdd\/[^\s`"')]+\.md)/g)]
    .map((m) => m[1])
    .filter((p): p is string => p !== undefined);
  // Prefer task files over other referenced .md files, and the current layout
  // (`tasks/TASK<NNN>.md`) over the historical spelling (`task-<N>.md`). The
  // historical form is still accepted so a cycle opened before the layout change
  // keeps resolving.
  paths.sort((a, b) => rankTaskPath(b) - rankTaskPath(a));
  for (const p of paths) {
    try {
      corpus += "\n" + readFileSync(join(cwd, p), "utf-8");
    } catch {
      /* ignore unreadable paths */
    }
  }
  return corpus;
}

/** Parse `SKILLS_REQUIRED: [a, b]` (case-insensitive) into a list of skill names. */
function parseRequiredSkills(task: string): string[] {
  const m = task.match(/SKILLS_REQUIRED\s*:\s*\[([^\]]*)\]/i);
  const body = m?.[1];
  if (body === undefined) return [];
  return body
    .split(",")
    .map((s) => s.trim().replace(/^['"`]+|['"`]+$/g, ""))
    .filter(Boolean);
}

/** Return the SKILL.md path for a local skill directory name, or null. */
function resolveInRoots(name: string, roots: string[][]): string | null {
  for (const parts of roots) {
    const root = join(...parts);
    const dirForm = join(root, name, "SKILL.md");
    const fileForm = join(root, `${name}.md`);
    if (existsSync(dirForm)) return dirForm;
    if (existsSync(fileForm)) return fileForm;
  }
  return null;
}

/** Locate `skills/<name>/SKILL.md` inside one installed package directory. */
function skillInsidePackage(packageDir: string, name: string): string | null {
  const dirForm = join(packageDir, "skills", name, "SKILL.md");
  if (existsSync(dirForm)) return dirForm;
  const fileForm = join(packageDir, "skills", `${name}.md`);
  return existsSync(fileForm) ? fileForm : null;
}

/** Read an array of skill names declared by a package's `package.json` (`pi.skills`). */
function packageDeclaredSkills(packageDir: string): string[] {
  try {
    const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf-8"));
    const skills = manifest?.pi?.skills;
    return Array.isArray(skills) ? skills.map((s: unknown) => String(s)) : [];
  } catch {
    return [];
  }
}

/** Resolve `package:skill` directly from that package (package.json first, then convention). */
function resolveQualifiedSkill(pkg: string, name: string, cwd: string): string | null {
  const packageDir = join(cwd, ...PACKAGE_ROOT, pkg);
  if (!existsSync(packageDir)) return null;

  // 1. Trust the package manifest when it points at concrete SKILL.md paths.
  for (const declared of packageDeclaredSkills(packageDir)) {
    const candidate = join(packageDir, declared.replace(/^\.\//, ""));
    if (existsSync(candidate) && /(^|\/)SKILL\.md$/.test(candidate)) {
      // Only accept the declared entry that matches the requested skill name.
      if (candidate.includes(`${name}/SKILL.md`) || candidate.endsWith(`${name}.md`)) return candidate;
    }
  }

  // 2. Convention: <pkg>/skills/<name>/SKILL.md
  return skillInsidePackage(packageDir, name);
}

/** Resolve a bare skill name across every installed package under the package root. */
function resolveBareSkillInPackages(name: string, cwd: string): string | null {
  const root = join(cwd, ...PACKAGE_ROOT);
  let entries: string[];
  try {
    entries = readdirSync(root);
  } catch {
    return null;
  }
  for (const pkg of entries) {
    if (pkg.startsWith(".")) continue;
    const dir = join(root, pkg);
    // Support scoped packages: @scope/name
    const candidates = pkg.startsWith("@")
      ? (() => {
          try {
            return readdirSync(dir).map((sub) => join(dir, sub));
          } catch {
            return [];
          }
        })()
      : [dir];
    for (const packageDir of candidates) {
      const found = skillInsidePackage(packageDir, name);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Resolve a skill reference to its SKILL.md path.
 * Accepts both `skill-name` and `package:skill-name` forms. Pure and local to this extension —
 * it does not affect the native pi-subagents resolution path.
 */
function resolveSkillFile(name: string, cwd: string): string | null {
  const [pkg, skill] = name.includes(":")
    ? [name.slice(0, name.indexOf(":")).trim(), name.slice(name.indexOf(":") + 1).trim()]
    : [null, name.trim()];

  if (!skill) return null;

  // Qualified form: package:skill → go straight to that package.
  if (pkg) return resolveQualifiedSkill(pkg, skill, cwd);

  // Bare form: local roots first, then any installed package.
  return resolveInRoots(skill, LOCAL_SKILL_ROOTS.map((p) => [cwd, ...p])) ?? resolveBareSkillInPackages(skill, cwd);
}

/** Read a SKILL.md and return its body (frontmatter stripped). */
function skillBody(filePath: string): string {
  let raw = "";
  try {
    raw = readFileSync(filePath, "utf-8");
  } catch {
    return "";
  }
  const norm = raw.replace(/\r\n/g, "\n");
  if (!norm.startsWith("---")) return norm.trim();
  const end = norm.indexOf("\n---", 3);
  if (end === -1) return norm.trim();
  return norm.slice(end + 4).trim();
}

export default function skillInjector(pi: ExtensionAPI): void {
  pi.on("before_agent_start", async (event: any, ctx: any) => {
    try {
      const systemPrompt = typeof event.systemPrompt === "string" ? event.systemPrompt : "";

      // Guard: sub-agents only.
      const isSubagent =
        process.env[SUBAGENT_CHILD_ENV] === "1" || ACTIVE_AGENT_TAG.test(systemPrompt);
      if (!isSubagent) return;

      const cwd = typeof ctx?.cwd === "string" ? ctx.cwd : process.cwd();

      // Phase 1 declaration, read from the task file (not the launcher text).
      const required = parseRequiredSkills(taskCorpusOf(event, cwd));
      if (required.length === 0) return;

      // Resolve each required skill and collect its body. A name that resolves to
      // nothing is reported rather than skipped in silence: a declaration the runtime
      // cannot honour leaves the sub-agent under-equipped while the run still looks
      // healthy.
      const blocks: string[] = [];
      const injected: string[] = [];
      const unresolved: string[] = [];
      for (const name of required) {
        const file = resolveSkillFile(name, cwd);
        if (!file) {
          unresolved.push(name);
          continue;
        }
        const body = skillBody(file);
        if (!body) {
          unresolved.push(name);
          continue;
        }
        blocks.push(`### SKILL: ${name}\n${body}`);
        injected.push(name);
      }
      if (blocks.length === 0 && unresolved.length === 0) return;

      // Inject the content as binding guidance (via the history channel; see header note).
      // An unresolved name is reported in the same message, so a mis-declared skill is
      // visible instead of buried behind a run that appears to have worked.
      const lines = [
        "## MANDATORY SKILLS (injected by the orchestrator for THIS task — apply them)",
        "",
      ];
      if (injected.length > 0) {
        lines.push(`The task declares these required skills: [${injected.join(", ")}].`);
        lines.push("Treat the following content as binding guidance for this task.");
        lines.push("");
        lines.push(blocks.join("\n\n"));
      }
      if (unresolved.length > 0) {
        lines.push("");
        lines.push(
          `WARNING — these declared skills resolved to no file and were NOT injected: [${unresolved.join(", ")}].`
        );
        lines.push(
          "The task will run without them. Check the spelling and that the skill exists under a discoverable root."
        );
      }
      const content = lines.join("\n");

      return {
        message: { customType: "skill-injector", content, display: false },
      };
    } catch {
      // Best-effort: never break the child's startup.
    }
  });
}
