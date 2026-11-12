# Planificación de la base nueva de TSW6

Esta carpeta es el punto de partida para **diseñar desde cero** la próxima base del proyecto,
sin escribir código todavía. Aquí se debate, se investiga y se decide; el código llegará cuando
el plan esté aprobado.

> Estado: **borrador para debate** (2026-11-12). Nada de lo que hay aquí está decidido salvo lo que
> figure como `Aceptada` en [decisiones/](decisiones/).

## Cómo está organizado

| Carpeta / archivo                              | Para qué sirve                                                                 | Quién lo cambia y cuándo                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------- |
| [PREGUNTAS.md](PREGUNTAS.md)                   | **Empezar aquí.** Todas las preguntas abiertas, con opciones y recomendación.  | Se responden en el PR / en el hilo; luego pasan a decisiones |
| [decisiones/](decisiones/)                     | Registro de decisiones (ADR): una decisión = un archivo numerado.              | Al cerrar una pregunta                            |
| [investigaciones/](investigaciones/)           | Preguntas técnicas que necesitan medir, leer o probar en el juego antes de decidir. | Al abrir o cerrar una investigación          |
| [ideas/](ideas/)                               | Ideas y funciones futuras, sin compromiso. Backlog vivo.                       | Cuando surja algo; se revisa en cada fase         |
| [documentacion/](documentacion/)               | Qué documentación tendrá la base nueva y qué se migra de `docs/` actual.       | Al cerrar la fase de arquitectura                 |
| [PLAN_DE_TRABAJO.md](PLAN_DE_TRABAJO.md)       | Fases, entregables, criterios de salida y hoja de ruta a largo plazo.          | Al aprobar cada fase                              |

## Principios de partida (propuestos, a debatir)

1. **Desde cero, pero con oráculo.** El V2 actual (`V2/tsw6v2/`, 660 tests, logs JSONL reales) es la
   especificación de comportamiento. El motor nuevo debe reproducir sus decisiones en los mismos
   logs antes de mejorarlas. Ver [decisiones/0001](decisiones/0001-desde-cero-con-oraculo.md).
2. **El tren es un dato, no un `if`.** Añadir un tren nuevo = un paquete de vehículo (JSON) + como
   mucho un adaptador pequeño. Nada de constantes de la Class 323 en el núcleo.
3. **Núcleo puro, bordes sucios.** La lógica de decisión no sabe de Windows, IPC, HTTP, tkinter ni
   ficheros. Todo eso vive en adaptadores en el borde. Así se prueba en cualquier SO y en CI.
4. **Cada decisión es reproducible.** Todo tick se puede grabar y volver a ejecutar (replay) con el
   mismo resultado.
5. **Un solo hogar para cada cosa.** Una fuente de verdad por concepto, una carpeta por tipo de
   documento, un único juego de instrucciones para agentes de IA.

## Cómo debatimos

1. Lee [PREGUNTAS.md](PREGUNTAS.md) y responde en el PR (comentario por pregunta, o todo de golpe en
   el hilo del proyecto). Vale contestar a medias o "no lo sé": eso abre una investigación.
2. Cada pregunta cerrada se convierte en un ADR en `decisiones/` con estado `Aceptada`.
3. Cuando las decisiones de la sección A y B estén cerradas, se escribe la arquitectura en
   `documentacion/` y se aprueba la Fase 1 del [plan de trabajo](PLAN_DE_TRABAJO.md).
