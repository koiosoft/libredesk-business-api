# Seguimiento — hub-api (JEV enforcement loop)

Documento de cierre de sesión. Único archivo en español del workspace `.sdd/inputs/`.
Lo que sigue es el estado real al 2026-11-13, qué quedó abierto y por qué, y qué decisión
le toca a quién. La documentación técnica vive en `.sdd/core/SPEC.md` y
`.sdd/core/CONVENTIONS.md`; las reglas de trabajo operativo en
`.agents/skills/current-project/SKILL.md`.

## Estado: desplegado y funcionando en producción

Versión `v0.3.0` corriendo en el servidor. El ciclo completo fue observado en vivo:
webhook recibido → JEV clasificó con confianza 0.90 → generó vía copilot → publicó un
mensaje adicional etiquetado, con el marcador anti-bucle presente y cero trazas de error.
El resto del stack no fue reiniciado durante el despliegue.

Kanboard: HUB-12 (deploy) y HUB-13 (rule de revive) cerradas. Ready y WIP vacíos.

## Abierto por decisión consciente (no es deuda oculta)

1. **Calibración de umbrales.** Siguen los valores de desarrollo (`0.5` confianza / `0.45`
   probabilidad). Con tráfico real se va a ver una tasa de `none` alta; antes de bajarlos
   conviene acumular casos y revisar si el problema es el umbral o la redacción de la opción.
   Motivo de mantener ambos ejes: midieron divergencia real (probabilidad 0.37 contra
   confianza 0.16 en la misma decisión).

2. **Ninguna corrección observada todavía sobre un lead verdadero.** La primera publicada
   en producción salió de una conversación de prueba del propio agente. El camino técnico es
   idéntico, pero la validación de negocio falta. Llega sola con uso normal.

3. **Cobertura de snippets hacia el clasificador.** JEV no ve la base de conocimiento porque
   LibreDesk no expone API pública para leerla. El generador sí llega, por tools internas.
   Hoy el state incluye la cláusula de estructura de turno + política del asistente, que es lo
   que hace decidible una desviación. Si algún día se quiere más, hace falta una lectura
   directa de la BD (prohibida por diseño) o una herramienta nueva en LibreDesk.

4. **Entrega asíncrona sin confirmación.** Publicar devuelve `status=pending`; un rechazo del
   canal (ventana de 24 h cerrada en WhatsApp, por ejemplo) llega después por `message.updated`
   y hoy solo se loguea. Mitigación posible: suscribirse ya a ese evento y marcar el resultado
   final. Queda pendiente desde el MVP.

5. **Sin persistencia propia.** Dedupe, caché de canal, tope de correcciones y bandera de
   handoff viven en memoria; el servicio es de un solo worker a propósito. Si se escala
   horizontalmente, eso migra a Redis o a una tabla con UNIQUE. Decidido así para evitar
   migraciones en el MVP; la consecuencia es que el contador de correcciones se reinicia.

## Defectos encontrados durante el ciclo (todos corregidos y con regresión)

Vale la pena conservarlos porque explican decisiones de diseño que hoy parecen arbitrarias:

| Defecto | Efecto real | Qué se hizo |
|---|---|---|
| Respuesta paginada leída como lista | historial vacío silencioso → JEV respondía `none` en todo, parecía decisión válida | unwrap de `data.results` + test con respuesta capturada literal |
| Canal crudo sin normalizar | `whatsapp` no tenía prefijo → corrección descartada después de pagar clasificación y generación | normalización en todas las rutas de entrada |
| Credenciales con carácter no-ASCII | `UnicodeEncodeError` dentro de httpx en cada evento, con 202 respondido igual | validador en arranque que rechaza no-ASCII |
| Timeout fijo de 20 s | cortaba generaciones sanas (copilot mide 15–34 s) | variable configurable, default 90 |
| `has_post_action()` inexistente | `AttributeError` dentro de la tarea de fondo en cada handoff ajeno al bot; invisible porque el webhook ya había contestado 202 | método agregado por hotfix |
| Default apuntando a directorio ignorado por git | clon limpio abortaba en arranque; producción sobrevivía solo porque compose fija su valor | default movido a `rules/example`, que sí está versionado |
| Instrucciones contradictorias en la política del asistente | Nemotron agotaba los tokens de salida razonando y devolvía texto vacío → handoff | orden único declarado en la regla A; también subir el límite de salida del proveedor |

## Lecciones de proceso (aplicables fuera de este feature)

- **Traer datos del remoto antes de afirmar sobre él.** Dos veces en una sesión se sacaron
  conclusiones falsas sobre ramas y estado desplegado por leer una vista local vieja.
- **Validar contra el código autoritativo, no contra una fórmula reimplementada.** Un snippet
  manual de hash difería del loader real en un byte separador; usado como criterio de parada
  habría hecho fallar un despliegue correcto.
- **Un doble diseñado por uno mismo solo prueba que el código coincide con esa creencia.** Los
  bugs de formato de alambre sobrevivieron más de cien pruebas verdes hasta que los fixtures se
  alimentaron con respuestas capturadas literales.
- **Cualquier coincidencia en el escaneo de secretos detiene el commit.** Ocurrió: dos líneas
  reportadas fueron ignoradas y llegaron a un commit local con la llave de cifrado y una
  contraseña SMTP. Se revirtió antes de empujar nada, pero el riesgo no debió existir.
- **Los nombres de variables son contrato.** Que compose declarara un nombre y el código leyera
  otro produjo días de "no funciona" con todo correctamente versionado.

## Qué haría falta para dar esto por terminado del todo

1. Observar una corrección disparada por un lead real y revisarla con el equipo comercial.
2. Decidir umbrales con esa muestra encima, no antes.
3. Suscribir el loop a `message.updated` para confirmar entrega final del canal.
4. Rotar la contraseña SMTP si se quiere cerrar por completo el episodio del commit revertido
   (la llave de cifrado nunca salió de la máquina; no requiere rotación).
