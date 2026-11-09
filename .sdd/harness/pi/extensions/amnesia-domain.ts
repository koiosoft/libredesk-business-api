/**
 * amnesia-domain injector — Phase 2b.
 *
 * PURPOSE
 * -------
 * For every skill the sub-agent has LOADED (in its `<available_skills>` catalog),
 * find (RECURSIVELY) a .yaml under `.sdd/skills/amnesia-domain/` whose `skill:` field
 * matches, and inject that YAML's `instruction` field. Folder layout is free
 * (e.g. amnesia-domain/python/..., amnesia-domain/mcp/...).
 *
 * It is a declarative mapping:  loaded skill  ->  injected instruction.
 * It does not touch pi-subagents; it uses the proven channel (`result.message`).
 *
 * SUB-AGENTS ONLY (guard), same as skill-injector.
 */

import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD";
const ACTIVE_AGENT_TAG = /<active_agent\s+name=["'][^"']+["'][^>]*>/i;
const AMNESIA_DIR = ".sdd/skills/amnesia-domain";

function readInstruction(yamlPath: string): { skill: string | null; instruction: string | null } {
  let raw = "";
  try {
    raw = readFileSync(yamlPath, "utf-8");
  } catch {
    return { skill: null, instruction: null };
  }
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  // `skill:` field (which skill this YAML applies to)
  const skillLine = lines.find((l) => /^skill\s*:/.test(l));
  const skill = skillLine ? skillLine.replace(/^skill\s*:\s*/, "").trim().replace(/^["']|["']$/g, "") : null;
  // `instruction:` field (block or inline)
  const start = lines.findIndex((l) => /^instruction\s*:/.test(l));
  if (start === -1) return { skill, instruction: null };
  const inline = (lines[start] ?? "").replace(/^instruction\s*:\s*/, "").trim();
  if (inline && inline !== "|" && inline !== ">-" && inline !== ">") {
    return { skill, instruction: inline.replace(/^["']|["']$/g, "") };
  }
  const block: string[] = [];
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i];
    if (line === undefined) continue;
    if (line.trim() === "") { block.push(""); continue; }
    if (!/^\s/.test(line)) break;
    block.push(line.replace(/^\s{2}/, ""));
  }
  const text = block.join("\n").trim();
  return { skill, instruction: text || null };
}

/** Recursively walk a directory and return all .yaml file paths. */
function walkYaml(dir: string, acc: string[] = []): string[] {
  if (!existsSync(dir)) return acc;
  for (const entry of readdirSync(dir)) {
    if (entry.startsWith(".")) continue;
    const full = join(dir, entry);
    try {
      const st = statSync(full);
      if (st.isDirectory()) walkYaml(full, acc);
      else if (st.isFile() && /\.ya?ml$/i.test(entry)) acc.push(full);
    } catch { /* ignore */ }
  }
  return acc;
}

/** Ascend the tree to find the directory containing `.sdd` or `.git`. */
function findProjectRoot(startDir: string): string {
  let curr = startDir;
  while (curr && curr !== "/") {
    if (existsSync(join(curr, ".sdd")) || existsSync(join(curr, ".git"))) {
      return curr;
    }
    const parent = dirname(curr);
    if (parent === curr) break;
    curr = parent;
  }
  return startDir;
}

export default function amnesiaDomain(pi: ExtensionAPI): void {
  pi.on("before_agent_start", async (event: any, ctx: any) => {
    try {
      const prompt = typeof event.systemPrompt === "string" ? event.systemPrompt : "";
      const isSubagent = process.env[SUBAGENT_CHILD_ENV] === "1" || ACTIVE_AGENT_TAG.test(prompt);
      if (!isSubagent) return;

      // 1) LOADED skills: extract name and location from the systemPrompt itself (the <available_skills>
      //    block is already rendered there). systemPromptOptions.skills is empty in the child.
      const skillLocations = new Map<string, string>();
      const skillBlocks = [...prompt.matchAll(/<skill>([\s\S]*?)<\/skill>/g)];
      for (const sb of skillBlocks) {
        const block = sb[1];
        const nameMatch = block.match(/<name>([^<]+)<\/name>/);
        const locMatch = block.match(/<location>([^<]+)<\/location>/);
        if (nameMatch) {
          const name = nameMatch[1].trim();
          if (locMatch) {
            skillLocations.set(name, locMatch[1].trim());
          }
        }
      }

      const namesFromPrompt = skillLocations.size > 0
        ? [...skillLocations.keys()]
        : [...prompt.matchAll(/<name>([^<]+)<\/name>/g)].map((m) => m[1].trim());
      const loadedNames = [...new Set(namesFromPrompt)].filter(Boolean);
      if (loadedNames.length === 0) return;

      const cwd = typeof ctx?.cwd === "string" ? ctx.cwd : process.cwd();

      // 2) Index ALL .yaml under amnesia-domain by their `skill:` field (folder-independent).
      const projectRoot = findProjectRoot(cwd);
      const root = join(projectRoot, AMNESIA_DIR);
      const bySkill = new Map<string, string>();
      for (const yamlPath of walkYaml(root)) {
        const { skill, instruction } = readInstruction(yamlPath);
        if (skill && instruction) bySkill.set(skill, instruction);
      }
      if (bySkill.size === 0) return;

      // 3) For each LOADED skill, take its instruction if present.
      const blocks: string[] = [];
      const matched: string[] = [];
      for (const name of loadedNames) {
        let instruction = bySkill.get(name);
        if (!instruction) continue;

        // Path-independent resolution: compute the relative path from the worker's cwd.
        let relPath: string | null = null;
        const fullLocation = skillLocations.get(name);
        if (fullLocation) {
          relPath = relative(cwd, fullLocation);
        } else {
          // Fallback discovery if <location> was not present in the prompt
          const candidateAgents = join(projectRoot, ".agents", "skills", name, "SKILL.md");
          const candidateMcp = join(projectRoot, ".sdd", "skills", "mcp", name, "SKILL.md");
          if (existsSync(candidateAgents)) {
            relPath = relative(cwd, candidateAgents);
          } else if (existsSync(candidateMcp)) {
            relPath = relative(cwd, candidateMcp);
          }
        }

        if (relPath) {
          if (relPath.startsWith("./")) relPath = relPath.slice(2);

          // If the instruction does not yet contain the resolved relative path,
          // dynamically annotate the load directive with the exact path.
          if (!instruction.includes(relPath)) {
            const targetPattern = new RegExp("`" + name + "`(\\s+skill)?(?:\\s*\\([^)]*\\))?", "g");
            instruction = instruction.replace(targetPattern, "`" + name + "` skill (`" + relPath + "`)");
          }
        }

        blocks.push(instruction);
        matched.push(name);
      }
      if (blocks.length === 0) return;

      // 4) Inject the instructions (proven channel: result.message).
      const content = [
        "## AMNESIA-DOMAIN INSTRUCTIONS (injected by the orchestrator)",
        "",
        `Applies to the following loaded skills: [${matched.join(", ")}].`,
        "Treat the following as binding restrictions for this task.",
        "",
        blocks.join("\n\n---\n\n"),
      ].join("\n");

      return {
        message: { customType: "amnesia-domain", content, display: false },
      };
    } catch {
      // best-effort; never break startup
    }
  });
}
