# SDD Sub-agent Surface

## ¿Por qué?

Los protocolos SDD necesitan invocar sub-agentes (workers, judges, test-runners,
reviewers, doc-updaters) para delegar trabajo. Originalmente la API de invocación
estaba hardcodeada en los archivos `.md` usando la sintaxis legacy
(`Agent()`, `get_subagent_result()`, `steer_subagent()`, `subagent_type`,
`prompt`, `run_in_background`) de la extensión `@tintinweb/pi-subagents`.

Esto causaba dos problemas:

1. **Los LLMs orquestadores se confundían** — intentaban llamar `Agent()`
   (que no existe como tool), o usaban parámetros legacy en vez de los
   reales. Perdían tiempo reinterpretando.
2. **Cambiar de shell o extensión requería reescribir todos los protocolos**
   — la API quedaba acoplada a una implementación concreta.

## Solución: Surface YAML + KEYs

Cada shell/extension tiene un archivo YAML en este directorio que define la
**superficie de invocación**: las KEYs de casos de uso que los protocolos referencian.

```yaml
# Ejemplo: .sdd/sub-agents/pi/nicobailon-pi-subagents.yaml
use_cases:
  launch: subagent({ agent, task, async, model, thinking })
  resume: subagent({ agent, resume, task })
```

Cuando un protocolo necesita invocar un sub-agente, escribe:

```markdown
Via use_case: launch
  agent: "sdd-worker"
  task: "Implementar TASK001..."
  async: true
```

El LLM busca `launch` en el YAML, ve la forma `subagent({ agent, task, async, ... })`
y completa los valores. **No hay ambigüedad, no hay traducción.**

## Convención para LLMs orquestadores

1. Cuando leas `use_case: <key>` en un protocolo, busca la KEY en el YAML del shell activo.
2. El YAML te da la **forma canónica** de la invocación.
3. Completa los parámetros con los valores que el protocolo indica.
4. Si una KEY no existe en el YAML, usa tu criterio general.

## Cómo escribir un nuevo surface YAML

1. Crea el archivo en `.sdd/sub-agents/<shell>/<nombre>.yaml`.
2. Define las KEYs que el protocolo necesita. Todas son opcionales —
   define solo las que tu extensión soporta:

```yaml
use_cases:
  # Lanzar sub-agente en background
  # Params: agent, task, async, model, thinking
  launch: <invocation>

  # Reanudar un sub-agente bloqueado (status: blocked)
  # Params: agent, resume, task
  resume: <invocation>

  # Redirigir un sub-agente en plena ejecución
  # Params: id, message
  steer: <invocation>

  # Leer resultado de un sub-agente async
  # Params: id
  read_result: <invocation>

  # Esperar a que un async termine y leer resultado
  # Params: id
  wait_result: <invocation>

  # Consultar estado en vuelo
  # Params: id
  check_status: <invocation>
```

Cada KEY incluye placeholders de parámetros que el protocolo proveerá.

3. Agrega tu archivo a la tabla de la sección Archivos.

## Archivos disponibles

| Shell | Extensión | Archivo |
|---|---|---|
| Pi | nicobailon/pi-subagents | `pi/nicobailon-pi-subagents.yaml` |

## Principios de diseño

- **Determinista y finito**: El protocolo usa ~6 patrones de invocación.
  Todo lo demás el LLM lo resuelve con criterio general.
- **KEY obliga a lookup**: El LLM no puede ignorar el YAML porque
  la KEY no le dice nada sin resolverla.
- **Desacoplado**: Cambiar de shell = cambiar el YAML. Los protocolos `.md`
  nunca mencionan tools ni parámetros concretos.
- **Mínimo**: El YAML solo define lo que el protocolo necesita. No es
  un catálogo exhaustivo de la API de sub-agentes.