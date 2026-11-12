#!/usr/bin/env python3
"""Captura los payloads reales de hub-api (JEV + Nemotron) y los escribe en el escritorio.

Uso:
    scripts/grab-logs.py                     # ultimos 60 minutos, todas las conversaciones
    scripts/grab-logs.py --since 2h          # ventana explicita (formato docker --since)
    scripts/grab-logs.py --conv 0cfc8689     # filtra por prefijo de conversation uuid
    scripts/grab-logs.py --out DIR           # destino (por defecto ~/Desktop/test-webhooks)

Por cada conversacion encontrada escribe:
    {conv}.md                    payload literal enviado a JEV + su decision
    prompt-ai-{conv}.md          body literal enviado a /api/v1/ai/completion (Nemotron)

Requiere CLASSIFIER_LOG_REQUEST=true y COMPLETION_LOG_REQUEST=true en el entorno
del contenedor (sin eso no hay payload que capturar; solo se ven las decisiones).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CONTAINER = "koiosoft_api_hub"
JEV_MARK = "jev request payload "
COMP_MARK = "completion request payload "
COPILOT_MARK = "copilot request payload "
DEC_RE = re.compile(r"jev decision choice=(\S+) confidence=([\d.]+) probability=([\d.]+) act=(\S+) reason=(\S+)")
RES_RE = re.compile(r"pipeline result (\{.*\})")


def docker_logs(since: str) -> list[str]:
    r = subprocess.run(
        ["docker", "logs", CONTAINER, "--since", since],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit("no pude leer logs de %s: %s" % (CONTAINER, r.stderr[:200]))
    return (r.stdout + r.stderr).splitlines()


def payload_after(line: str, mark: str) -> dict | None:
    i = line.find(mark)
    if i < 0:
        return None
    try:
        return json.loads(line[i + len(mark):].strip())
    except json.JSONDecodeError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="60m")
    ap.add_argument("--conv", default="", help="prefijo del uuid de conversacion")
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "test-webhooks"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = docker_logs(args.since)

    # Agrupar por conversacion usando el state/payload y los mensajes vecinos.
    jev_events: list[tuple[int, dict, str]] = []   # (idx, payload, conv_guess)
    gen_events: list[tuple[int, dict, str]] = []  # (idx, body, "completion"|"copilot")
    decisions: list[tuple[int, str]] = []
    results: list[tuple[int, str]] = []

    last_conv = ""
    for idx, l in enumerate(lines):
        m = re.search(r"conv=([0-9a-f-]{8,})", l)
        if m:
            last_conv = m.group(1)
        jev_payload = payload_after(l, JEV_MARK)
        if jev_payload:
            jev_events.append((idx, jev_payload, last_conv))
        else:
            for mark, kind in ((COMP_MARK, "completion"), (COPILOT_MARK, "copilot")):
                gp = payload_after(l, mark)
                if gp:
                    gen_events.append((idx, gp, kind))
                    break
        if d := DEC_RE.search(l):
            decisions.append((idx, d.group(0)))
        if r := RES_RE.search(l):
            results.append((idx, r.group(1)))

    if not jev_events and not gen_events:
        print("No hay payloads en la ventana %s. ¿Flags de log prendidos? ¿Ocurrio algun ciclo?" % args.since)
        return

    # Agrupar por conversacion: un archivo {conv}.md con TODOS los eventos JEV y
    # un prompt-ai-{conv}.md con TODAS las llamadas de generacion del ciclo.
    by_conv_jev: dict[str, list[tuple[int, dict]]] = {}
    for idx, payload, conv in jev_events:
        if args.conv and args.conv not in conv:
            continue
        dec = next((d for i, d in decisions if i > idx), "(sin decision)")
        res = next((r for i, r in results if i > idx), "")
        by_conv_jev.setdefault(conv, []).append((idx, payload, dec, res))

    written = []
    for conv, evts in by_conv_jev.items():
        md = "# Conversación `%s` — payloads enviados a JEV\n\n" % conv
        for n, (idx, payload, dec, res) in enumerate(evts, 1):
            md += "## Evaluación %d\n\n```json\n%s\n```\n\n**Decisión:** `%s`\n" % (
                n, json.dumps(payload, indent=2, ensure_ascii=False), dec)
            if res:
                md += "**Resultado:** `%s`\n" % res[:200]
            md += "\n---\n\n"
        f = out_dir / ("%s.md" % conv)
        f.write_text(md, encoding="utf-8")
        written.append(f)

    by_conv_gen: dict[str, list[dict]] = {}
    for idx, body, kind in gen_events:
        prior = [c for i, _, c in jev_events if i < idx]
        conv = prior[-1] if prior else "desconocido"
        if args.conv and args.conv not in conv:
            continue
        by_conv_gen.setdefault(conv, []).append({"kind": kind, "body": body})

    for conv, calls in by_conv_gen.items():
        md = "# Llamadas de generación — conversación `%s`\n\n" % conv
        md += ("Cada bloque es el body literal que hub-api envio al motor de generacion.\n"
               "`copilot` = POST /api/v1/ai/copilot (historial + persona + KB del lado LibreDesk).\n"
               "`completion` = POST /api/v1/ai/completion (prompt plano legacy).\n\n")
        for n, c in enumerate(calls, 1):
            md += "## Generación %d (%s)\n\n```json\n%s\n```\n\n" % (
                n, c["kind"], json.dumps(c["body"], indent=2, ensure_ascii=False))
        target = out_dir / ("prompt-ai-%s.md" % conv if conv != "desconocido"
                            else "prompt-ai-desconocido.md")
        target.write_text(md, encoding="utf-8")
        written.append(target)

    for f in written:
        print(f)


if __name__ == "__main__":
    main()
