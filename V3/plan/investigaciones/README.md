# Investigaciones

Preguntas técnicas que no se pueden decidir solo opinando: hay que medir, leer código, leer
documentación del juego o hacer una sesión. Cada una tiene un archivo `R-NN-titulo.md` cuando se
abre de verdad; hasta entonces vive en esta tabla.

Formato del archivo: **pregunta**, **por qué importa** (qué decisión desbloquea), **método**,
**resultados** (FACT / INFERENCE / UNKNOWN) y **conclusión**.

## Después de recoger datos

Acordado el 2026-11-13. Los datos de una investigación (catálogos, canal ancho, sesiones) **no se
usan en bruto**. Antes pasan por dos pasos:

1. **Clasificar.** Cada campo o hallazgo queda en un estado:

   | Estado        | Significa                                                        |
   | ------------- | ---------------------------------------------------------------- |
   | `usado`       | Entra en la suscripción o en el paquete de algún tren            |
   | `candidato`   | Parece útil; falta analizarlo a fondo                            |
   | `descartado`  | No sirve, con el motivo (ruido, constante, duplica otro campo…)  |
   | `desconocido` | No se sabe qué es; hay que investigarlo                          |

   También se anota **para qué trenes vale**: uno, una familia ([0003](../decisiones/0003-estructura-por-tren-y-familia.md))
   o todos.
2. **Analizar a fondo** los `candidato` y `desconocido`: qué mide, unidades, rango, si cambia
   entre trenes o versiones del juego, y si es fiable (FACT / INFERENCE / UNKNOWN). El análisis
   se escribe en el `R-NN` correspondiente y, si cambia algo, sale una decisión (ADR).

Solo después de esos dos pasos se decide si un campo se usa y en qué trenes.

## Tabla

| ID   | Pregunta                                                                                           | Desbloquea   | Necesita juego | Estado     |
| ---- | -------------------------------------------------------------------------------------------------- | ------------ | -------------- | ---------- |
| R-01 | Inventario de reglas P1 de V2: qué hace cada regla, de qué sesión salió y qué test la cubre        | A.1, D.2     | No             | Pendiente  |
| R-02 | Calidad del oráculo: ¿cuántos logs JSONL reales hay, de qué trenes/rutas, y reproducen al 100 %?   | A.1, F.3     | No             | Pendiente  |
| R-03 | Latencia real del bucle: lectura IPC → decisión → mando aplicado en el juego (p50/p95)             | C.1, C.4     | Sí             | Pendiente  |
| R-04 | Qué datos físicos da el juego (pendiente, masa, presión de cilindro, adherencia) y con qué fiabilidad | E.2       | Sí             | Pendiente  |
| R-05 | [Catálogo de tipos de mando](R-05-catalogo-de-mandos.md) en los DLC que te interesan (ejes, escalones, rangos) | B.1, B.2, H.8 | Sí (lab)  | En curso (fuente: tsw-controller-app) |
| R-06 | Estabilidad de UE4SS y de la HTTPAPI entre actualizaciones de TSW6                                 | C.1, A.4     | No             | Pendiente  |
| R-07 | Otros proyectos de la comunidad (p. ej. el que se usó como referencia de paridad B1–B3): qué aprender | D.2       | No             | Pendiente  |
| R-08 | Panel web local vs tkinter: coste, latencia de refresco, uso en segunda pantalla                  | D.4          | No             | Pendiente  |
| R-09 | Señalización: qué aspectos de semáforo y sistemas de seguridad expone la API por región            | A.3, B.3     | Sí             | Pendiente  |
| R-10 | [Revisión del mod Lua de V2](R-10-revision-mod-lua.md): qué hay, lecciones, qué no sirve a largo plazo | C.3, H, 0002 | No        | ✅ Hecha 2026-11-13 |
| R-11 | Mapa de ruta: ¿el juego expone posición de paradas, señales y pendiente por delante? ¿Cuánto deriva el odómetro entre pasadas? | Idea «mapa de ruta», E.1 | Sí | Pendiente  |
| R-12 | [M3A: qué expone HTTP y qué alcanza Lua](R-12-m3a-http-vs-lua.md) | 0004, paquete M3A, lab V3 | Paso 1 no; 2–3 sí | Paso 1 ✅ 2026-11-13 |
