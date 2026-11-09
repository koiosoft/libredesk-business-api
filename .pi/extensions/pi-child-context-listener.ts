/**
 * pi-child-context-listener — PRUEBA DE CONCEPTO
 *
 * Escucha el canal de supervisor de pi-subagents desde el proceso del
 * ORQUESTADOR y avisa al modelo cuando un worker reporta una alerta JEV.
 *
 * Cadena que valida este archivo:
 *   worker (hook) → requests/<uuid>.json
 *                         ↓ fs.watch
 *   orquestador (este archivo) → pi.sendUserMessage({ deliverAs: "steer" })
 *                         ↓
 *   el modelo del orquestador lo ve en su siguiente turno
 *
 * Ningún eslabón depende del modelo del worker: un worker en sand trap deja de
 * invocar tools, así que la alerta tiene que nacer del hook y viajar por disco.
 */

import { watch, type FSWatcher } from "node:fs";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const NAME = "pi-child-context-listener";
const SUBAGENT_CHILD_ENV = "PI_SUBAGENT_CHILD";

/** Requests ya inyectados, para no repetir el aviso en cada tick del watcher. */
const seen = new Set<string>();

/** Canal raíz, idéntico al que usa pi-subagents. */
function supervisorChannelRoot(): string {
  const getuid = typeof process.getuid === "function" ? process.getuid() : undefined;
  const scope = getuid !== undefined ? `uid-${getuid}` : (process.env.USERNAME || process.env.USER || "unknown");
  return join(tmpdir(), `pi-subagents-${scope}`, "supervisor-channels");
}

/**
 * Procesa los `requests/*.json` pendientes y devuelve cuántos avisos emitió.
 *
 * Solo se miran los requests cuyo `reason` es `need_decision`: ese es el valor
 * que el hook escribe para marcar una alerta JEV. Los `progress_update` y los
 * requests de otros productores se ignoran.
 */
/** `customType` de la entry con la que pi-roles registra el rol activo. */
const ROLE_ENTRY_TYPE = "pi-roles:active-role";

/** Config del listener dentro del policy de sub-agente. */
const LISTENER_CONFIG_RELPATH = ".sdd/context-policies/subagent/policies.yaml";

/**
 * Roles autorizados a recibir alertas.
 *
 * Semántica pedida: ausente o lista vacía => **todos** los roles (cualquier
 * sesión que no sea un hijo), porque limitarlo al orquestador deja ciego a un
 * arquitecto o debugger que también despacha workers. Una lista con nombres
 * restringe la escucha a esos roles.
 *
 * Devuelve `undefined` cuando no hay restricción.
 */
function readListenerRoles(cwd: string): string[] | undefined {
  let raw: string;
  try {
    raw = readFileSync(join(cwd, LISTENER_CONFIG_RELPATH), "utf-8");
  } catch {
    return undefined;
  }
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  let inBlock = false;
  const roles: string[] = [];
  for (const line of lines) {
    if (/^contextPolice:\s*$/.test(line)) {
      inBlock = true;
      continue;
    }
    if (!inBlock) continue;
    // Otra clave de primer nivel cierra el bloque.
    if (/^[A-Za-z_]/.test(line)) break;
    const key = line.match(/^\s+listenerRoles:\s*(.*)$/);
    if (!key) continue;
    const inline = (key[1] ?? "").trim();
    const bracket = inline.match(/^\[(.*)\]$/);
    if (bracket) {
      for (const part of (bracket[1] ?? "").split(",")) {
        const v = part.trim().replace(/^["']|["']$/g, "");
        if (v) roles.push(v);
      }
    }
    return roles.length > 0 ? roles : undefined;
  }
  return undefined;
}

/** Rol activo de la sesión, según la entry que publica pi-roles. */
function activeRole(ctx: any): string | undefined {
  const entries = ctx?.sessionManager?.getEntries?.() ?? [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry?.customType !== ROLE_ENTRY_TYPE) continue;
    const name = entry?.data?.name;
    if (typeof name === "string" && name) return name;
  }
  return undefined;
}

/**
 * `sessionId` de la sesión que DESPACHÓ el run *runId*, leído de su `status.json`.
 *
 * El canal de supervisor es un directorio compartido por TODOS los proyectos de
 * la máquina. Filtrar por `cwd` NO basta: todas las sesiones de un mismo
 * proyecto comparten directorio, así que un dictamen emitido por el worker de
 * OTRA sesión del mismo proyecto pasa el filtro y se inyecta como alerta
 * fresca — el listener acaba avisando de workers que esta sesión nunca lanzó.
 *
 * `sessionId` es el log de la sesión orquestadora que hizo el spawn, y es único
 * por sesión. Medido: presente en 32/32 `status.json` de esta máquina.
 *
 * Devuelve `undefined` cuando el `status.json` no existe o no es legible. Quien
 * llama DEBE tratar ese `undefined` como "no es mío": sin dueño verificable no
 * hay atribución posible.
 */
function runSessionId(runId: string): string | undefined {
  const getuid = typeof process.getuid === "function" ? process.getuid() : undefined;
  const scope = getuid !== undefined ? `uid-${getuid}` : (process.env.USERNAME || process.env.USER || "unknown");
  const statusPath = join(tmpdir(), `pi-subagents-${scope}`, "async-subagent-runs", runId, "status.json");
  try {
    const status = JSON.parse(readFileSync(statusPath, "utf-8")) as { sessionId?: unknown };
    return typeof status.sessionId === "string" ? status.sessionId : undefined;
  } catch {
    return undefined;
  }
}

function drainChannels(pi: ExtensionAPI, ownSessionFile: string | undefined): number {
  const root = supervisorChannelRoot();
  let emitted = 0;
  let channels: string[];
  try {
    channels = readdirSync(root);
  } catch {
    return 0;
  }

  for (const channel of channels) {
    const requestsDir = join(root, channel, "requests");
    let files: string[];
    try {
      files = readdirSync(requestsDir);
    } catch {
      continue;
    }
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      const full = join(requestsDir, file);
      if (seen.has(full)) continue;
      let request: any;
      try {
        request = JSON.parse(readFileSync(full, "utf-8"));
      } catch {
        continue;
      }
      seen.add(full);

      if (request?.type !== "subagent.supervisor.request") continue;
      if (request?.reason !== "need_decision") continue;

      // Solo se atienden los runs despachados por ESTA sesión. El canal es
      // compartido por todas las sesiones de la máquina, y `cwd` no discrimina
      // entre sesiones del mismo proyecto: un worker lanzado por otra sesión
      // pasaba el filtro y su dictamen se inyectaba aquí como alerta fresca.
      //
      // Descarte estricto, sin fallbacks: sin `runId` no hay dueño, y sin
      // `status.json` no hay atribución verificable. En ambos casos el request
      // no es demostrablemente propio y se ignora.
      const requestRunId = typeof request?.runId === "string" ? request.runId : undefined;
      if (!requestRunId) continue;
      const owner = runSessionId(requestRunId);
      if (owner === undefined || owner !== ownSessionFile) continue;
      const message = typeof request.message === "string" ? request.message : "";
      if (!message) continue;

      pi.sendUserMessage(`[${NAME}] sand trap detectado en un worker:\n\n${message}`, {
        deliverAs: "steer",
      });
      emitted += 1;
    }
  }
  return emitted;
}

export default function childContextListener(pi: ExtensionAPI): void {
  // En un worker no hacemos nada: la mitad hija es pi-child-context-police.
  if (process.env[SUBAGENT_CHILD_ENV] === "1") return;

  const root = supervisorChannelRoot();

  const cwd = process.cwd();
  const allowedRoles = readListenerRoles(cwd);

  // The runtime is NOT ready while the extension factory runs: calling
  // `pi.sendUserMessage` here fails with "Extension runtime not initialized.
  // Action methods cannot be called during extension loading." Every drain is
  // therefore deferred until a turn actually starts. `active` gates both the
  // watcher and the safety timer so nothing fires during load.
  let active = false;
  let watcher: FSWatcher | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;

  const safeDrain = (ctx?: any): void => {
    if (!active) return;
    // Una lista de roles no vacía restringe la escucha a esos roles. Ausente o
    // vacía => todos, para no dejar ciego a un arquitecto o debugger que
    // también despacha workers.
    if (allowedRoles) {
      const role = activeRole(ctx);
      if (!role || !allowedRoles.includes(role)) return;
    }
    // La sesión propia es el discriminante de propiedad. Medido en ejecución:
    // `getSessionFile()` ya devuelve la ruta absoluta completa al entrar en
    // `session_start`, así que se lee aquí y no se cachea (una sesión por
    // proceso, pero el runtime es quien manda sobre cuándo está lista).
    let ownSessionFile: string | undefined;
    try {
      const sessionManager = ctx?.sessionManager;
      ownSessionFile =
        typeof sessionManager?.getSessionFile === "function"
          ? sessionManager.getSessionFile()
          : undefined;
    } catch {
      ownSessionFile = undefined;
    }
    if (!ownSessionFile) return;

    try {
      const n = drainChannels(pi, ownSessionFile);
      // Silencioso a propósito: el aviso llega al modelo por sendUserMessage y
      // repetirlo en stderr solo ensucia la terminal del usuario.
      void n;
    } catch (error) {
      console.error(`[${NAME}] drain error: ${String(error)}`);
    }
  };

  pi.on("session_start", (_event: any, ctx: any) => {
    if (active) return;
    active = true;

    // Barrido inicial: requests escritos antes de que el watcher existiera.
    safeDrain(ctx);

    try {
      // `recursive` permite ver requests/ dentro de cada canal; en plataformas
      // sin soporte el barrido periódico de abajo cubre el hueco.
      watcher = watch(root, { recursive: true }, () => safeDrain(ctx));
      watcher.on("error", (error) => {
        console.error(`[${NAME}] watcher error: ${String(error)}`);
      });
    } catch (error) {
      console.error(`[${NAME}] no se pudo vigilar ${root}: ${String(error)}`);
    }

    // Red de seguridad: el watcher puede perder eventos (creación de directorios,
    // plataformas sin recursive). Un barrido lento garantiza la entrega.
    timer = setInterval(() => safeDrain(ctx), 5_000);
    timer.unref?.();
  });

  // Si la sesión ya arrancó antes de registrarnos, `session_start` no vuelve a
  // dispararse: el primer turno sirve de arranque alternativo.
  pi.on("turn_end", (_event: any, ctx: any) => {
    const start = (): void => {
      try {
        watcher = watch(root, { recursive: true }, () => safeDrain(ctx));
        watcher.on("error", (error) => {
          console.error(`[${NAME}] watcher error: ${String(error)}`);
        });
      } catch (error) {
        console.error(`[${NAME}] no se pudo vigilar ${root}: ${String(error)}`);
      }
      timer = setInterval(() => safeDrain(ctx), 5_000);
      timer.unref?.();
    };

    if (!active) {
      active = true;
      start();
    }
    // Drena en CADA turno, no solo en el de arranque: el watcher puede perder
    // eventos y, si `session_start` ya activó la escucha, este es el único
    // punto que vuelve a mirar el canal.
    safeDrain(ctx);
  });
  pi.on("session_shutdown", () => {
    watcher?.close();
    clearInterval(timer);
  });
}
