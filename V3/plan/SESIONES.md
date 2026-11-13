# Bitácora de sesiones (planificación V3)

Qué se hizo en cada sesión y por dónde seguir. Lo más reciente va arriba.

---

## 2026-11-13 (3) — A.3 y revisión de `mod-lua.md`

**Respondido:** A.3. La v1 **solo frena** el tren (carteles, andén, semáforos, señales).

**Comentario del usuario sobre el mod:** que lea todo lo posible y luego se decida qué usa cada
tren, porque cada tren lo describe de forma distinta. Si hace falta reformar Lua, se reforma.

**Clasificado:**

- Decisión → [decisiones/0004](decisiones/0004-el-mod-lee-todo-python-elige.md) (`Propuesta`):
  catálogo al cargar + suscripción en el ciclo + canal ancho lento.
- Diseño → `mod-lua.md`: principio 9, mensaje `catalog` y suscripción en `vehicle_config`.
- Dudas → [PREGUNTAS § H.9](PREGUNTAS.md#h9-el-mod-lee-todo-lo-posible) (H.9a–c) y nota de A.3 en
  H.8.

**Respondido después:** «ok» a H.9a–c → [0004](decisiones/0004-el-mod-lee-todo-python-elige.md)
`Aceptada`. Acordado también: los datos de investigación se **clasifican** (`usado` / `candidato` /
`descartado` / `desconocido`, y para qué trenes) y se **analizan a fondo** antes de usarlos. El
proceso está en [investigaciones/README](investigaciones/README.md#después-de-recoger-datos).

**Idea del usuario:** mapa de ruta por escenario (paradas, semáforos, desnivel), útil para frenar
mejor y, más adelante, para PPO/BC. Va a [ideas/](ideas/README.md) y abre la investigación
[R-11](investigaciones/README.md).

**Fuente nueva (usuario):** [tsw-controller-app](https://github.com/LiahMartens/tsw-controller-app).
Sus 140 perfiles dan el nombre real de cada palanca/eje por tren. Extracto de los mandos de freno en
[R-05](investigaciones/R-05-catalogo-de-mandos.md) (`En curso`). Sin licencia: solo se citan datos,
no se copian ficheros.

**M3A (usuario):** empezar a investigar la M3A. HTTP (RailBridge) va con retraso; probar los mismos
nombres desde Lua. El laboratorio se hace **nuevo en V3** (H.6).

- Paso 1 hecho sin juego → [R-12](investigaciones/R-12-m3a-http-vs-lua.md): cruce de los volcados
  HTTP del 2026-10-03 con el lab Lua del 2026-10-05. Hallazgos: HUD mejor por Lua; la aguja roja del
  HUD = cilindro de freno; `Simulation/*` falla en Lua pero el actor tiene **referencias** a
  Simulation (pista nueva); ACSES/ATC entero sin mirar desde Lua; `TrackData` solo HTTP.
- 0003 actualizada con `campos.json`, `catalogo/` e `investigacion/` por tren.

**Antes de escribir el laboratorio V3 falta:**

1. Aceptar 0003 (D.6a–d).
2. H.10 (nombre canónico de cada campo), H.11 (convivencia con V2 + ruta de UE4SS), H.12 (qué
   guarda una sesión de lab y dónde).
3. H.5: versión de Lua del UE4SS y si se instala `busted`.

**Siguiente:** el usuario responde esas preguntas; después se escribe `TSW6Lab` mínimo para la M3A.

---

## 2026-11-13 (2) — revisión de R-10

**Comentario del usuario:** estructurar antes de construir. Cada tren con su carpeta (perfil,
física, tests, logs, herramientas) y el código común separado por tipos de tren (muescas,
mercancías/pasajeros, cercanías/larga distancia, maniobras). Frenar en paradas, semáforos y señales.

**Clasificado:**

- Decisión → [decisiones/0003](decisiones/0003-estructura-por-tren-y-familia.md) (`Propuesta`).
- Dudas → [PREGUNTAS § D.6](PREGUNTAS.md#d6-carpeta-por-tren-y-código-común-por-familias) (D.6a–d) y
  nota en A.3 (falta confirmar si la v1 es solo frenado).
- Orden → PLAN_DE_TRABAJO, Fase 1: la estructura (`docs/estructura.md`) va antes que el contrato
  con el mod.

**Siguiente sesión — empezar por aquí:**

1. El usuario responde (vale «ok» o un cambio por número):
   - ~~**A.3:** ¿la v1 es *solo frenado*?~~ ✅ Respondida: **la v1 solo frena el tren** (carteles,
     andén, semáforos, señales). Sin tracción ni modo asistente.
   - **D.6a–d:** familias en dos ejes (mando × servicio), herramientas comunes, logs fuera de git,
     familias solo cuando haya un tren que las use.
   - **H.1–H.8:** mod Lua. En H.5 hacen falta datos: versión de Lua del UE4SS y si se instala
     `busted`.
   - ¿Algún dato de R-10 está mal?
2. Con las respuestas: ADR 0003 (y 0002 si procede) pasa a `Aceptada`, y se marcan las preguntas
   como respondidas.
3. Si 0003 se acepta, se redacta `V3/docs/estructura.md` (primer entregable de la Fase 1). Después
   vienen `mod-lua.md` y el contrato.

**Pendiente:**

- Decidir qué se hace con el PR #4.

---

## 2026-11-13

**Hecho:**

- Se creó `V3/` en este repo para la base nueva desde cero (PREGUNTAS § D.3 respondida).
- Los documentos del PR #4 (`claude/project-thread-nc3odx`, que los dejaba en `plan/` en la raíz)
  se copiaron a `V3/plan/`. El PR sigue abierto en GitHub: queda por decidir si se cierra o se
  actualiza.
- Se decidió **empezar por el mod Lua** (propuesta del usuario). Documentos nuevos:
  - [investigaciones/R-10-revision-mod-lua.md](investigaciones/R-10-revision-mod-lua.md): qué hay
    en el mod de V2, lecciones y problemas a largo plazo.
  - [documentacion/mod-lua.md](documentacion/mod-lua.md): visión del mod V3 (contrato versionado,
    `hello`/`vehicle_config`/`tick`/`cmd`, hoja de ruta M0–M7).
  - [decisiones/0002-empezar-por-el-mod-lua.md](decisiones/0002-empezar-por-el-mod-lua.md):
    `Propuesta`.
  - [PREGUNTAS § H](PREGUNTAS.md#h-mod-lua): H.1–H.8.
- Rutas actualizadas a `V3/` en el README, el PLAN_DE_TRABAJO y `documentacion/README.md`.

**Acordado: forma de trabajar.** Se revisa documento a documento. El usuario comenta (citando la
sección o en texto libre) y Claude clasifica cada cosa:

| Tipo                       | Destino              |
| -------------------------- | -------------------- |
| Decisión                   | `decisiones/`        |
| Duda u opción              | `PREGUNTAS.md`       |
| Medir o probar en el juego | `investigaciones/`   |
| Idea futura                | `ideas/`             |
| Diseño de documentación    | `documentacion/`     |
| Orden o fases              | `PLAN_DE_TRABAJO.md` |
| Corrección de un hecho     | R-10 (o el documento que corresponda) |

**Orden de lectura:**

1. R-10.
2. `mod-lua.md`.
3. PREGUNTAS § H.
4. El resto de PREGUNTAS y el PLAN_DE_TRABAJO.

**Siguiente sesión:** el usuario lee **R-10** y comenta. Se empieza por ahí.

**Pendiente:** ~~sin commit~~ (V3/ ya está en `main`, commit `3d007db`). El PR #4 sigue abierto
(ver la sesión siguiente).
