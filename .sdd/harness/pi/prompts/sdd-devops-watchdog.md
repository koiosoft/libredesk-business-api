---
description: Prompt watchdog periódico de 5 minutos para el agente DevOps en producción vía pi-scheduler.
category: DevOps
---

# DevOps Continuous Watchdog (Heartbeat de 5 Minutos para Despliegue)

Este documento define la directiva y el comando interactivo para configurar un latido recurrente cada 5 minutos en la sesión de Pi del agente **DEV-OPS** en el servidor de producción. Evita que el agente se quede inactivo, lo obliga a avanzar de forma autónoma entre las tareas de Kanboard y canaliza las incidencias a través del tablero.

---

## 1. Comando Interactivo Slash (TUI Console de Pi en el Servidor)

En la consola de Pi donde corre el agente DevOps (`tmux`), ejecuta directamente:

```text
/schedule prompt every 5m :: [DEVOPS HEARTBEAT & ADVANCE DIRECTIVE] 1. Consulta Kanboard (Proyecto ID 3). Si hay tarea en 'Work in progress', verifica su progreso o finalízala si cumplió su DoD. 2. Si la tarea activa concluyó con éxito, muévela a 'Done' con su reporte y toma de inmediato la siguiente tarea en 'Ready' moviéndola a 'Work in progress'. 3. Modo autónomo total: ejecuta comandos sin pedir permiso. 4. Si ocurre un fallo o excepción bloqueante, documéntalo en un comentario en la tarea de Kanboard para que pi-architect te asista y no avances. 5. Mantén el ciclo vivo hasta completar todas las tajetas.
```

---

## 2. Directiva Completa del Watchdog para DEV-OPS

```markdown
[DEVOPS HEARTBEAT & ADVANCE DIRECTIVE]
Este es un latido periódico automatizado para asegurar el impulso continuo del despliegue:

1. INSPECCIÓN DE KANBOARD (PROYECTO ID: 3):
   - Conéctate al proyecto 'Koiosoft Portal - Production' vía MCP.
   - Verifica el estado de la tarea actual en 'Work in progress' ([DEPLOY-2], [DEPLOY-3], o [DEPLOY-4]).

2. CRITERIO DE AVANCE (NO DETENERSE EN ESPERA PASIVA):
   - Si la tarea en 'Work in progress' ya completó sus acciones y cumple todos los Criterios de Aceptación (DoD):
     a) Publica el reporte de ejecución en un comentario.
     b) Mueve la tarea a 'Done'.
     c) Toma inmediatamente la siguiente tarea de la columna 'Ready', muévela a 'Work in progress' y ejecuta sus instrucciones sin esperar confirmación humana.

3. AUTONOMÍA OPERATIVA:
   - Tienes autorización total para ejecutar comandos de bash, docker compose, git, curl y drush.
   - No pauses para pedir confirmaciones de rutina.

4. GESTIÓN DE ERRORES Y COMUNICACIÓN ASÍNCRONA:
   - Si un comando falla (ej. error de base de datos, colisión de puertos, código HTTP distinto de 200 en smoke test):
     a) Agrega un comentario en la tarea con el error exacto y los logs de diagnóstico.
     b) NO avances a la siguiente tarea para evitar daños en cascada.
     c) El arquitecto (pi-architect) está monitoreando el tablero y te proveerá el fix o escalará la decisión.

5. PERSISTENCIA:
   - Mantén el ciclo activo hasta que [DEPLOY-4] esté en 'Done' y el portal verificado en https://koiosoft.com.
```

---

## 3. Comandos Útiles de `pi-scheduler` para el Operador

- Ver tareas programadas activas:
  ```text
  /schedules
  ```
- Cancelar el watchdog una vez finalizado todo el despliegue:
  ```text
  /schedule-cancel <id>
  ```
- Forzar una ejecución inmediata del prompt sin esperar 5 minutos:
  Pegar el texto de la directiva directamente en la consola.
