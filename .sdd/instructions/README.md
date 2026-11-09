# SDD Instructions Directory

Este directorio (`.sdd/instructions/`) es el espacio transaccional de trabajo donde se deposita la especificación activa de tareas para el ciclo SDD en curso.

## Propósito y Ciclo de Vida

1. **Generación:**
   Al ejecutar `agent-instructor generate --<protocol>` (por ejemplo, `generate --feature`), el motor de generación compone el documento final a partir de los planes y las maquettes estáticas (`.sdd/templates/instructions/maquettes/<TYPE>.md`), escribiendo la especificación resultante directamente en este directorio (e.g. `.sdd/instructions/FEATURE.md`).

2. **Ejecución y Seguimiento:**
   Los agentes y ejecutores leen y actualizan el estado de las tareas (`[ ]` -> `[x]`) y las listas de revisión en el archivo activo dentro de esta carpeta.

3. **Ciclo y Persistencia:**
   Al abrir un ciclo (`workflow open`), el contenido activo se respalda en el log del ciclo (`INSTRUCTION_USED.md`). Al cerrar el ciclo (`workflow close`), la carpeta vuelve a su estado base para preparar el siguiente ciclo de desarrollo.
