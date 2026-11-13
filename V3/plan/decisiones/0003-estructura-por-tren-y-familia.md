# 0003 — Estructurar antes de construir: carpeta por tren y código común por familias

- **Estado:** Propuesta
- **Fecha:** 2026-11-13
- **Pregunta de origen:** PREGUNTAS.md § D.3, D.6 (comentario del usuario al revisar R-10, 2026-11-13)
- **Investigaciones relacionadas:** R-10, R-05

## Contexto

Comentario del usuario (2026-11-13), tras leer R-10:

> Deberíamos estructurar primero antes de construir. […] Cada tren su perfil, física, incluso
> carpeta con sus herramientas, test, logs, así cada tren será por separado. Y el código conjunto
> habrá que separarlo por tipos de trenes: muescas, mercancías o pasajeros, cercanías o larga
> distancia, incluso maniobras.

Datos que lo apoyan:

- FACT (R-10): en V2 el conocimiento de cada tren está repartido entre `config.lua`, `ipc.lua`,
  `data/vehicles/*.json`, `logs/profiles/` y `if` sueltos en Python. Para saber «qué hay de la 323»
  hay que mirar en muchos sitios.
- FACT (memoria del proyecto): una corrección para un tren suele romper el otro, y hay que pasar
  `regression_check.py` para darse cuenta.
- INFERENCE: lo que cambia entre trenes se explica con **dos ejes independientes**:
  1. **Cómo se manda** (tipo de mando): palanca combinada por muescas (323), analógica (M3A),
     tracción y freno separados, freno independiente o dinámico.
  2. **Qué servicio hace** (tipo de servicio): cercanías (muchas paradas cortas, precisión en
     andén), larga distancia (velocidades altas, pocas paradas), mercancías (tren largo y pesado,
     freno lento), maniobras (velocidad baja, enganches, sin horario).

  Un tren es una **combinación** de los dos. Por ejemplo, la 323 es «muescas + cercanías» y una
  SD40-2 es «tracción/freno separados con freno independiente + mercancías».

## Opciones consideradas

1. **Organizar por capas, sin carpeta por tren** (lo propuesto en D.3: `core/`, `vehicles/`,
   `adapters/`…). Es limpio para el código, pero lo de cada tren sigue repartido.
2. **Una carpeta por tren con todo dentro, código incluido.** Cada tren es independiente, pero el
   código se duplica y cada arreglo hay que hacerlo N veces. Es lo contrario de «el tren es un dato».
3. **Carpeta por tren solo con datos, pruebas y logs, y código común separado por familias
   (propuesta).** El tren declara a qué familia de mando y de servicio pertenece. El código vive
   una sola vez, en su familia.

## Decisión

Pendiente de debate. Recomendación: **opción 3**, y escribir la estructura **antes** de escribir
código (entregable de la Fase 1).

Esquema provisional (los nombres se cierran en Fase 1). Actualizado el 2026-11-13 con
[0004](0004-el-mod-lee-todo-python-elige.md): `campos.json`, `catalogo/` e `investigacion/`.

```text
V3/
  src/tsw6/
    core/          bucle, árbitro, tipos (no sabe nada de trenes concretos)
    politicas/     cartel, andén, semáforo/señal, emergencia
    mando/         cómo se convierte «quiero −0,8 m/s²» en mandos:
                   muescas/, analogico/, separado/, independiente/
    servicio/      perfiles de servicio: cercanias/, larga_distancia/,
                   mercancias/, maniobras/ (márgenes, precisión, curvas)
    adaptadores/   ipc (mod Lua), http, ficheros
    herramientas/  log_info, regression_check… parametrizadas por tren
  trenes/
    class_323/
      tren.json      identidad, mandos, capacidades, familia (mando + servicio)
      fisica.json    deceleraciones, retardos, lo que aprende el learner
      campos.json    suscripción: nombre genérico → campo del catálogo (0004, H.10)
      catalogo/      lo que expone el tren, uno por versión del juego (0004)
      investigacion/ sesiones de laboratorio (fuera de git; resúmenes sí)
      tests/         replay de sus logs y casos propios
      logs/          sesiones reales (fuera de git; recortes como fixtures)
      herramientas/  solo si algo es exclusivo de este tren (excepción, con motivo)
      NOTAS.md       qué se sabe del tren, problemas conocidos
    m3a_mnr/
      …
  mods/            mod Lua (no sabe de trenes: recibe tren.json por vehicle_config)
```

Reglas:

1. En `trenes/<id>/` **no hay lógica de conducción**: solo datos, pruebas, logs y notas.
2. Si un tren necesita un comportamiento nuevo, se añade a su **familia** (`mando/` o `servicio/`)
   y vale para todos los trenes de esa familia. Si no encaja en ninguna, se discute la abstracción
   (regla 3 del plan: un tren nuevo no cambia `core/`).
3. Arreglar un tren no puede romper otro: los tests de **todos** los trenes corren en cada PR.
4. Las herramientas son comunes y reciben el tren como parámetro. La carpeta `herramientas/` de un
   tren es la excepción.

## Consecuencias

- Más fácil: añadir un tren (copiar la carpeta, rellenar datos, pasar sus tests), saber todo lo de
  un tren en un único sitio y ver qué trenes afecta un cambio (los de esa familia).
- Más difícil: hay que acertar con las familias. Si se separan demasiado pronto (p. ej. cercanías y
  larga distancia por separado sin necesitarlo) habrá carpetas vacías o casi iguales.
- A revisar: qué familias existen de verdad se decide con trenes reales (B.1, R-05), no en abstracto.
  Al principio solo habrá `muescas` + `analogico` y `cercanias`.
- Afecta al mod Lua: refuerza H.2 (el tren sale del mod y llega como `vehicle_config`).
