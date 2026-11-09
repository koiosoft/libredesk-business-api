/**
 * pi-roles → pi-permission-system bridge.
 *
 * PURPOSE
 * -------
 * Make `pi-permission-system` able to apply per-ROLE policy.
 *
 * `pi-roles` applies a session role and records it as a session entry with
 * customType `pi-roles:active-role`. `pi-permission-system` resolves per-agent
 * policy from `<agentsDir>/<name>.md`, where `name` comes from a session entry
 * with customType `active_agent` or a literal `<active_agent name="..."/>` tag
 * in the system prompt.
 *
 * Nothing connects a role to `permission_system`: roles never produce an
 * `active_agent` entry, so a role-specific `permission_system` is never found.
 * This bridge republishes the active role as an `active_agent` entry.
 *
 * SUB-AGENT SAFETY (important)
 * ----------------------------
 * `pi-subagents` ALREADY injects `<active_agent name="<childAgent>"/>` into
 * every child's system prompt, which is how per-agent policy works today for
 * sub-agents. If this bridge also published the session role inside a child, it
 * would overwrite that child identity with the parent role and silently strip
 * the agent's own `permission_system`.
 *
 * So the bridge MUST abstain whenever it is running inside a sub-agent child.
 * Two independent guards cover both launch paths:
 *   1. `PI_SUBAGENT_CHILD=1` in the environment (set by the background runner).
 *   2. A literal `<active_agent .../>` tag already present in the event's
 *      system prompt (covers any in-process/foreground child).
 *
 * LOAD ORDER
 * ----------
 * Pi loads extensions in three fixed blocks: project `<cwd>/.pi/extensions/`
 * first, then `~/.pi/agent/extensions/`, then npm packages from settings.json
 * (where `pi-permission-system` lives). This extension therefore always runs
 * its `before_agent_start` handler before `pi-permission-system` in the same
 * turn. And `session_start` (where `pi-roles` records the role) fires before
 * any `before_agent_start`, so the role entry is already present.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const ROLE_ENTRY_TYPE = "pi-roles:active-role";
const AGENT_ENTRY_TYPE = "active_agent";
const SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD";
const ACTIVE_AGENT_TAG = /<active_agent\s+name=["']([^"']+)["'][^>]*>/i;

interface SessionEntry {
  type?: string;
  customType?: string;
  data?: unknown;
}

function lastEntryName(ctx: ExtensionContext, customType: string): string | null {
  let entries: readonly SessionEntry[];
  try {
    entries = ctx.sessionManager.getEntries() as readonly SessionEntry[];
  } catch {
    return null;
  }
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry?.type !== "custom" || entry.customType !== customType) continue;
    const data = entry.data as { name?: unknown } | undefined;
    const name = typeof data?.name === "string" ? data.name.trim() : "";
    return name.length > 0 ? name : null;
  }
  return null;
}

export default function bridge(pi: ExtensionAPI): void {
  pi.on("before_agent_start", async (event, ctx) => {
    // Guard 1: never act inside a sub-agent child (its identity comes from
    // pi-subagents and must win).
    if (process.env[SUBAGENT_CHILD_ENV] === "1") return;

    // Guard 2: if the prompt already carries an active_agent tag, it is owned
    // by the host (sub-agent) — do not override it.
    const prompt = typeof event.systemPrompt === "string" ? event.systemPrompt : "";
    if (ACTIVE_AGENT_TAG.test(prompt)) return;

    const roleName = lastEntryName(ctx, ROLE_ENTRY_TYPE);
    if (!roleName) return;

    // Persist the role as an `active_agent` entry for subsequent turns.
    // NOTE: this alone is NOT enough for the CURRENT turn — pi-permission-system
    // resolves the active agent at the top of this same event, before this entry
    // exists. The returned systemPrompt below carries the identity in-turn.
    if (lastEntryName(ctx, AGENT_ENTRY_TYPE) !== roleName) {
      pi.appendEntry(AGENT_ENTRY_TYPE, { name: roleName });
    }

    // Same-turn delivery: inject the `<active_agent name="..."/>` tag into the
    // system prompt. pi-permission-system reads this tag via
    // getActiveAgentNameFromSystemPrompt during this very turn, so per-role
    // policy applies immediately instead of one turn late.
    //
    // Escaping mirrors pi-subagents' own bridge: JSON.stringify quotes the
    // attribute value and the consumer regex accepts both quote styles.
    const tag = `<active_agent name=${JSON.stringify(roleName)}/>`;
    return { systemPrompt: `${prompt}\n\n${tag}` };
  });
}
