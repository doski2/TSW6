# 0002 — Empezar V3 por el mod Lua y su contrato

- **Estado:** Propuesta
- **Fecha:** 2026-11-13
- **Pregunta de origen:** PREGUNTAS.md § H.1 (propuesta del usuario, 2026-11-13)
- **Investigaciones relacionadas:** R-10, R-03, R-05, R-06

## Contexto

Todo lo que el autopiloto puede hacer está limitado por lo que el juego deja leer y escribir. Esa
frontera es el mod Lua. La revisión [R-10](../investigaciones/R-10-revision-mod-lua.md) concluye
cuatro cosas:

- El principio «el mod solo hace I/O» y la separación producción/laboratorio funcionan.
- El mod de V2 lleva **conocimiento de la 323 y la M3A dentro**: tablas de muescas, marcadores MC,
  enum de rojo UK, nombres de puertas.
- El contrato **no tiene versión** en el cable y solo acepta **un mando** (la palanca combinada).
- No hay tests de Lua fuera del juego.

Además, el núcleo nuevo (D.2) se diseña alrededor de tipos como `WorldState` y `Command`. Si esos
tipos se diseñan antes que el contrato con el juego, se corre el riesgo de copiar otra vez la forma
de la 323.

## Opciones consideradas

1. **Reutilizar el probe de V2 tal cual y empezar por el núcleo Python.** Es lo más rápido, pero
   el núcleo nacería atado a `lever_notch` y `PowerBrakeHandle`, justo lo que V3 quiere evitar.
2. **Empezar por el contrato y el mod V3 (propuesta).** Primero se escribe el contrato versionado,
   con saludo, capacidades, varios ejes y valores crudos. Después se hace un mod mínimo con tests
   fuera del juego, en un puente separado de V2. El núcleo se diseña después, a partir de ese
   contrato.
3. **Adaptador Python encima del probe de V2 y aplazar el mod.** Permite empezar el núcleo con un
   contrato limpio en Python, pero la deuda queda en Lua (tren dentro del mod, sin versión) y habría
   que tocarlo igual en cuanto llegue un tercer tren.

## Decisión

Pendiente de debate. Recomendación: **opción 2, por etapas**:

1. **Sin código:** contrato escrito (`contrato-mod.md`, paso M0 de
   [mod-lua.md](../documentacion/mod-lua.md)) y respuestas a PREGUNTAS § H.
2. **Código que no necesita juego:** `shared/`, formato de mensajes y tests Lua en CI (M1).
3. **Primer contacto con el juego:** mod mínimo con la 323 en puente propio (M2).

## Consecuencias

- El orden de fases cambia: el contrato con el mod es el primer entregable de la Fase 1, y el mod
  mínimo entra en la Fase 2 junto con el CI y el arnés de replay. Ver
  [PLAN_DE_TRABAJO](../PLAN_DE_TRABAJO.md).
- V2 sigue funcionando sin cambios: su probe y su puente (`%TEMP%\TSW6Bridge\`) no se tocan. Los
  logs del oráculo ya grabados no dependen del mod nuevo.
- Hace falta un entorno Lua fuera del juego, con la misma versión que UE4SS, para los tests. Hay que
  confirmar cuál es (pregunta H.5).
- Mientras dure la transición hay dos mods de producción, pero solo uno activo a la vez.
