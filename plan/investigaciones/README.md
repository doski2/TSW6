# Investigaciones

Preguntas técnicas que no se pueden decidir solo opinando: hay que medir, leer código, leer
documentación del juego o hacer una sesión. Cada una tiene un archivo `R-NN-titulo.md` cuando se
abre de verdad; hasta entonces vive en esta tabla.

Formato del archivo: **pregunta**, **por qué importa** (qué decisión desbloquea), **método**,
**resultados** (FACT / INFERENCE / UNKNOWN) y **conclusión**.

| ID   | Pregunta                                                                                           | Desbloquea   | Necesita juego | Estado     |
| ---- | -------------------------------------------------------------------------------------------------- | ------------ | -------------- | ---------- |
| R-01 | Inventario de reglas P1 de V2: qué hace cada regla, de qué sesión salió y qué test la cubre        | A.1, D.2     | No             | Pendiente  |
| R-02 | Calidad del oráculo: ¿cuántos logs JSONL reales hay, de qué trenes/rutas, y reproducen al 100 %?   | A.1, F.3     | No             | Pendiente  |
| R-03 | Latencia real del bucle: lectura IPC → decisión → mando aplicado en el juego (p50/p95)             | C.1, C.4     | Sí             | Pendiente  |
| R-04 | Qué datos físicos da el juego (pendiente, masa, presión de cilindro, adherencia) y con qué fiabilidad | E.2       | Sí             | Pendiente  |
| R-05 | Catálogo de tipos de mando en los DLC que te interesan (ejes, escalones, rangos)                   | B.1, B.2     | Sí (lab)       | Pendiente  |
| R-06 | Estabilidad de UE4SS y de la HTTPAPI entre actualizaciones de TSW6                                 | C.1, A.4     | No             | Pendiente  |
| R-07 | Otros proyectos de la comunidad (p. ej. el que se usó como referencia de paridad B1–B3): qué aprender | D.2       | No             | Pendiente  |
| R-08 | Panel web local vs tkinter: coste, latencia de refresco, uso en segunda pantalla                  | D.4          | No             | Pendiente  |
| R-09 | Señalización: qué aspectos de semáforo y sistemas de seguridad expone la API por región            | A.3, B.3     | Sí             | Pendiente  |
