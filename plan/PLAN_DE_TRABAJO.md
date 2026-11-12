# Plan de trabajo

Borrador. Las fases se aprueban una a una; cada fase tiene **entregables** y **criterios de salida**
medibles. Ninguna fase empieza sin que la anterior cumpla sus criterios.

```text
Fase 0  Debate y decisiones           ← estamos aquí
Fase 1  Arquitectura escrita
Fase 2  Cimientos (repo, CI, arnés de replay)
Fase 3  Núcleo + Class 323 en paridad con V2
Fase 4  Segundo tren (M3A) sin tocar el núcleo
Fase 5  Juego real: bucle cerrado y panel
Fase 6  Retirada de V2 y legacy
Fase 7+ Ampliaciones (hoja de ruta)
```

## Fase 0 — Debate y decisiones

- **Entregables:** respuestas a [PREGUNTAS.md](PREGUNTAS.md); ADR `Aceptada` para A.1–A.5, B.1–B.2,
  C.1, D.1–D.3; investigaciones R-01 y R-02 cerradas.
- **Salida:** sabemos qué producto hacemos, para qué trenes y con qué métricas de "sólido".

## Fase 1 — Arquitectura escrita

- **Entregables:** `documentacion/arquitectura.md` con capas, flujo de un tick, tipos principales
  (`WorldState`, `VehicleProfile`, `Target`, `Command`), contrato con el mod Lua y esquema del paquete
  de tren v2. Diagramas.
- **Salida:** se puede explicar cómo entraría un tren con freno independiente y una regla PZB sin
  modificar el núcleo (ejercicio en papel).

## Fase 2 — Cimientos

- **Entregables:** paquete instalable (`pyproject.toml`, `src/`), ruff + pyright + pytest en CI
  (Linux y Windows), **arnés de replay** que lee logs JSONL de V2 y compara decisiones de cualquier
  motor, conjunto de fixtures recortados.
- **Salida:** CI verde; el arnés reproduce V2 contra sí mismo al 100 %.

## Fase 3 — Núcleo + Class 323

- **Entregables:** bucle de etapas, políticas cartel / andén / semáforo / emergencia, árbitro,
  modelo de vehículo genérico, paquete 323.
- **Salida:** paridad con V2 en los logs de la 323 (diferencias clasificadas y justificadas con ADR);
  cobertura del núcleo ≥ 90 %.

## Fase 4 — Segundo tren sin tocar el núcleo

- **Entregables:** paquete M3A + adaptador si hace falta.
- **Salida:** paridad en logs M3A con **cero cambios** en `core/`. Si hay que cambiar el núcleo, se
  vuelve a la Fase 1 para corregir la abstracción.

## Fase 5 — Juego real

- **Entregables:** adaptadores IPC/HTTP, mod Lua versionado, panel (según D.4), modo asistente.
- **Salida:** métricas de A.5 cumplidas en sesiones reales (p. ej. 10 sesiones, parada ±2 m ≥ 95 %).

## Fase 6 — Retirada

- **Entregables:** V2 y legacy movidos a `archive/`, documentación migrada según
  [documentacion/](documentacion/README.md), `.bat` de la raíz sustituidos por un único lanzador.
- **Salida:** la raíz del repo contiene solo la base nueva.

## Fase 7+ — Hoja de ruta (ampliaciones)

Orden tentativo; se reordena con las respuestas de A.3 y B.1. Cada punto tendrá su ADR antes de
empezar.

| Ampliación                         | Depende de     | Notas                                                   |
| ---------------------------------- | -------------- | ------------------------------------------------------- |
| Control de tracción completo       | Fase 5         | Acelerar hasta límite, mantener velocidad               |
| Conducción por horario             | Tracción       | Usa horario HUD/HTTPAPI                                 |
| Learner integrado                  | Fase 5         | Refina física del paquete; nunca decide solo (E.1)      |
| Trenes con freno independiente     | Fase 4         | Primer caso fuera de "palanca combinada"                |
| Mercancías (SD40-2)                | Freno indep.   | Freno neumático lento, trenes largos                    |
| Sistemas de seguridad por región   | R-09           | AWS/TPWS, PZB… como políticas enchufables               |
| Asistente para añadir trenes       | Fase 4         | Lab Lua → paquete → validación                          |
| Publicación para la comunidad      | A.4            | Instalador, documentación de usuario, catálogo de trenes |

## Mantenimiento a largo plazo (reglas permanentes, a aprobar)

1. Todo PR pasa CI (lint, tipos, tests, replay).
2. Toda regla de conducción tiene test y, si cambia comportamiento, ADR.
3. Un tren nuevo no puede cambiar `core/`; si lo necesita, se discute la abstracción.
4. El contrato con el mod Lua tiene versión; Python rechaza versiones incompatibles con mensaje claro.
5. Revisión trimestral: ideas, deuda técnica, dependencias, compatibilidad con el juego.
