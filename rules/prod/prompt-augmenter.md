# prompt-augmenter (interno de hub-api)

Descriptor de cómo se compone el prompt final que se envía a
`POST /api/v1/ai/completion`. **No es un prompt**: no se concatena tal cual,
describe la estructura.

> Estado: `prompt-augmenter` como servicio horizontal está **suspendido**
> (decisión del 2026-11-11). Este archivo vive en hub-api mientras tanto y su
> contenido es deliberadamente mínimo. Cuando el augmenter horizontal exista,
> este descriptor se traslada y aquí queda sólo la referencia.

## Composición

El prompt final se arma en `app/jev/composer.py` (motor `/ai/completion`, default
desde D3), en este orden contractual (FEATURE.md §9 / G6):

```
1. ROL            → las reglas de este archivo (qué es la corrección y cómo hablar)
2. PERSONA        → `instructions` + `guardrails` reales del asistente, obtenidos de
                    GET /api/v1/ai/assistants/{id}  (cacheado por agent_id),
                    más los snippets declarados por la opción elegida
                    (`options.<key>.snippets`, resueltos por GET /api/v1/ai/snippets)
3. HISTORIAL      → conversación cronológica (no llega al corrector ciego)
4. MATERIAL       → mensaje del cliente + respuesta del agente a corregir
5. ACCIÓN         → el bloque elegido por JEV en rules/prompts.yaml (`options.<key`);
                    SIEMPRE al final: la precedencia se expresa por posición
```

`none` nunca llega aquí: si JEV responde `none`, o si la clave no existe en el YAML,
no se compone ni se publica nada.

## Reglas de redacción del resultado

- La salida reescribe la respuesta del agente; **no** la comenta ni la analiza.
- Un solo mensaje, en el idioma del cliente.
- No inventar datos: precios, plazos, capacidades o enlaces que no estén en el
  material o en la persona del asistente.
- Conservar lo correcto del agente y añadir sólo lo que la acción pide.
- Extensión comparable a la respuesta original; la corrección no es un informe.

## Restricción heredada de LibreDesk (verificada en el fuente)

`internal/ai/ai.go` antepone al contenido un framing fijo — *"You are rewriting a
support agent's draft reply to a customer… only rewrite it"* — y al final fuerza la
salida a fragmento HTML (`ensureHTMLFragment`). Por eso:

- Las acciones de `prompts.yaml` se redactan como **reescrituras**, no como mandatos.
- El texto compuesto debe leerse como una instrucción de reescritura continua, para
  no contradecir el prefijo del servidor.
- Mitigación pendiente (acordada post-MVP): el contenido publicado pasa por
  `RenderStaffTemplate()`, que interpreta `{{ ... }}` de plantilla Go.
