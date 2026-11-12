# Preguntas para el debate

Cada pregunta tiene un identificador (A.1, B.2…) para poder citarla en comentarios del PR.
Formato: **pregunta** · opciones · *recomendación inicial (Claude)* · por qué importa.
Responder vale de cualquier forma: "A.1 → 3", un párrafo, o "no lo sé" (se abre una investigación).

---

## A. Visión y alcance del producto

### A.1 ¿Desde cero con oráculo?
- Opciones: (1) refactor de V2 · (2) desde cero sin mirar atrás · (3) desde cero usando V2 como
  especificación de comportamiento.
- *Recomendación:* 3. Ver [decisiones/0001](decisiones/0001-desde-cero-con-oraculo.md).

### A.2 ¿Qué es el producto en una frase?
- Ejemplos: "un copiloto que frena por mí", "un autopiloto completo que conduce el servicio entero",
  "una plataforma para experimentar con física y control de trenes en TSW".
- *Recomendación:* empezar como **autopiloto de servicio completo por fases** (frenado → tracción →
  horario), con el núcleo diseñado para todo eso desde el día 1 aunque se implemente por partes.
- Por qué importa: decide si la tracción y el horario son módulos de primera clase o añadidos.

### A.3 ¿Qué funciones entran y en qué orden?
Marca cada una como *imprescindible v1*, *más adelante* o *nunca*:
- Frenado por cartel de velocidad (límite)
- Parada en andén con precisión de metros
- Frenado por semáforo / aspecto restrictivo
- Control de tracción (acelerar hasta el límite, mantener velocidad)
- Cumplir horario (llegar a la hora, ajustar velocidad)
- Puertas, avisos, sistemas de seguridad (AWS/TPWS, PZB, ATC…)
- Modo "asistente" (solo recomienda en pantalla, no toca mandos)
- Aprendizaje automático del comportamiento de cada tren
- *Recomendación:* v1 = cartel + andén + semáforo + tracción básica + modo asistente.

### A.4 ¿Para quién es?
- Solo para ti · para ti y algunos amigos · publicable para la comunidad (instalador, documentación
  de usuario, soporte de muchas rutas).
- Por qué importa: si se publica, hacen falta instalador, configuración sin tocar código,
  compatibilidad con actualizaciones del juego y licencia.

### A.5 ¿Qué significa "sólido" para ti?
- Ejemplos medibles: "parar en andén a ±2 m el 95 % de las veces", "nunca pasar un cartel por encima
  del límite", "añadir un tren en una tarde", "una sesión de 2 h sin cuelgues".
- *Recomendación:* fijar 4–6 métricas de este tipo; serán los criterios de salida de cada fase.

---

## B. Trenes y modelo de vehículo

### B.1 ¿Qué trenes a medio plazo?
- Hoy solo hay Class 323 (UK, EMU) y M3A (MNR, palanca MC analógica).
- ¿Cuáles quieres después? Lista concreta de DLC si la tienes (ver `docs/v2/TRENES_DLC.md`).
- Por qué importa: es **la** decisión que más condiciona el modelo de vehículo.

### B.2 ¿Qué tipos de mando hay que soportar?
- Palanca combinada con escalones (323) · combinada analógica (M3A) · tracción y freno separados ·
  freno de tren + freno independiente (locos) · freno dinámico separado · selector de inversor
  / modos.
- *Recomendación:* modelar **ejes de control** genéricos (tracción, freno de servicio, freno
  independiente, dinámico) con capacidades declaradas en el paquete del tren, en lugar de "muescas
  B1–B3".

### B.3 ¿Mercancías y material europeo?
- Mercancías (SD40-2, trenes largos, freno neumático lento) · Europa (PZB/LZB, ETCS) · solo pasajeros.
- *Recomendación:* que la arquitectura lo permita, pero que no entre en v1.

### B.4 ¿Cómo se describe un tren?
- Opciones: JSON a mano (como hoy) · JSON generado por el laboratorio (ApiExplorerMod) y revisado ·
  autodetección completa en el juego.
- *Recomendación:* generado por el laboratorio y revisado, con esquema versionado y validado.

---

## C. Fuentes de datos y control del juego

### C.1 ¿Canal principal de telemetría y mandos?
- Hoy: UE4SS + `TelemetryProbeMod` (Lua) por IPC para lo rápido, HTTPAPI (`-HTTPAPI`) para planning
  y horario, OCR del HUD como apoyo.
- *Recomendación:* IPC con el mod como canal principal; HTTPAPI como segunda fuente; **ambos detrás
  de una misma interfaz** para poder simular y grabar.

### C.2 ¿Seguimos con el OCR del HUD?
- Opciones: mantener · dejarlo como herramienta aparte · eliminar.
- *Recomendación:* fuera del núcleo; solo como herramienta de diagnóstico si sigue aportando datos
  que no da la API.

### C.3 ¿Cuánto vive en Lua y cuánto en Python?
- Principio actual: "el probe observa, Python decide, IPC ejecuta".
- *Recomendación:* mantenerlo. El mod Lua debe ser fino, versionado y con contrato explícito.
  Detalle en la sección [H](#h-mod-lua).

### C.4 ¿Frecuencia objetivo del bucle?
- ¿Cuántos ticks por segundo necesitamos y qué latencia máxima aceptamos entre leer y actuar?
- Abre investigación R-03.

---

## D. Arquitectura del software

### D.1 Lenguaje del núcleo
- Python (como hoy) · Rust · C# · mixto.
- *Recomendación:* **Python 3.12+ con tipado estricto** (pyright/mypy). El cuello de botella es el
  juego, no Python; y el oráculo y las herramientas ya están en Python.

### D.2 Estilo del núcleo
- Propuesta: **bucle de etapas puras** `leer → normalizar → modelo del mundo → planificar →
  decidir → actuar → trazar`, donde cada etapa recibe un estado inmutable y devuelve uno nuevo.
- Las reglas de frenado como **políticas independientes** (cartel, andén, semáforo, emergencia)
  que proponen objetivos, y un **árbitro** único que elige.
- Sin estado global (nada de `set_active_physics`): el contexto (tren, física, configuración) se pasa
  explícitamente.

### D.3 Estructura del repositorio
- Propuesta: un único paquete instalable (`pyproject.toml`, layout `src/`), sin hacks de
  `PYTHONPATH`, con subpaquetes `core/`, `vehicles/`, `adapters/` (ipc, http, archivos), `apps/`
  (cli, gui), `tools/`. Mods Lua en `mods/` con su propia versión.
- ¿Repo nuevo o carpeta nueva en este repo? *Recomendación:* **este mismo repo**, carpeta nueva;
  el V2 y el legacy pasan a `archive/` cuando la base nueva alcance paridad. Así no se pierde el
  historial.
- **Respondida (2026-11-13):** carpeta **`V3/`** en este repo. El paquete Python, los mods, la
  documentación y el plan viven dentro de `V3/` (`V3/src/`, `V3/mods/`, `V3/docs/`, `V3/plan/`).
  Queda abierto si al final (Fase 6) `V3/` sube a la raíz o se queda como está.

### D.4 Interfaz de usuario
- tkinter (como hoy) · panel web local (navegador) · solo consola + informes HTML.
- *Recomendación:* panel web local servido por el propio proceso: funciona en segunda pantalla, se
  puede ver desde el móvil y separa la UI del núcleo.

### D.5 Configuración
- ¿Ficheros TOML/JSON por usuario, por ruta y por tren? ¿Perfiles?
- *Recomendación:* TOML para configuración de usuario, JSON con esquema para paquetes de tren.

---

## E. Física y aprendizaje

### E.1 ¿El learner es central o un extra?
- Hoy aprende perfiles de deceleración por tren (`logs/profiles/<vehicle>.json`).
- *Recomendación:* central pero **opcional en ejecución**: el motor funciona con valores del paquete y
  el learner los refina; nunca decide por su cuenta.

### E.2 ¿Modelo físico propio?
- Hoy: deceleración por escalón + margen. ¿Queremos pendiente, masa, adherencia, retardo del aire?
- Abre investigación R-04.

---

## F. Calidad, pruebas y mantenimiento

### F.1 ¿Qué pruebas son obligatorias?
- Propuesta: unitarias del núcleo, **replay de sesiones reales** (paridad con V2), simulador de bucle
  cerrado por tren, y pruebas de contrato del mod Lua.

### F.2 ¿CI en GitHub Actions?
- *Recomendación:* sí, en cada PR: lint (ruff), tipos (pyright), tests en Linux y Windows.

### F.3 ¿Dónde guardamos los logs de sesiones reales?
- Son grandes. Opciones: Git LFS · release assets · carpeta local + subconjunto recortado en el repo.
- *Recomendación:* fixtures recortados en el repo; logs completos fuera (LFS o almacenamiento aparte).

### F.4 Instrucciones para agentes de IA
- Hoy hay tres juegos (`.cursor/`, `.codex/`, `.github/agents`).
- *Recomendación:* una sola fuente (`AGENTS.md` + `docs/`) y, si hace falta, ficheros mínimos que
  apunten a ella.

### F.5 Idioma
- Código, commits y documentación: ¿español, inglés o mixto (código en inglés, docs en español)?
- *Recomendación:* identificadores en inglés, documentación y commits en español.

---

## G. Forma de trabajar

### G.1 ¿Cuánto tiempo puedes dedicar y cuándo puedes probar en el juego?
- Por qué importa: las fases que necesitan sesión de juego deben estar agrupadas.

### G.2 ¿Cómo prefieres revisar?
- PRs pequeños y frecuentes · PRs grandes por fase.
- *Recomendación:* PRs pequeños, cada uno con su criterio de salida.

---

## H. Mod Lua

Sale de la revisión [R-10](investigaciones/R-10-revision-mod-lua.md). La propuesta completa está en
[documentacion/mod-lua.md](documentacion/mod-lua.md).

### H.1 ¿Empezamos V3 por el mod y su contrato?
- Propuesta del usuario (2026-11-13). Ver [decisiones/0002](decisiones/0002-empezar-por-el-mod-lua.md).
- *Recomendación:* sí, por etapas. Primero el contrato escrito, después el formato y los tests sin
  juego, y al final el mod mínimo con la 323.

### H.2 ¿El tren sale del mod?
- Hoy el mod lleva dentro tablas de la 323, marcadores MC de la M3A, el enum de rojo UK y los nombres
  de puertas.
- Opciones: (1) se queda como está · (2) Python manda la configuración del tren al empezar sesión
  (`vehicle_config`) · (3) el mod lee el paquete del tren directamente desde disco.
- *Recomendación:* 2. Una sola fuente (el paquete) y el mod no necesita saber dónde está el repo.

### H.3 ¿Valores crudos o traducidos en el ciclo?
- Hoy viajan cosas ya interpretadas (`lever_notch`, `power_neg`).
- *Recomendación:* crudos (`input`/`output`/`step` de cada eje). Python traduce con el paquete. Así
  un tren nuevo no cambia el mod.

### H.4 ¿Formato y transporte?
- Formato: `clave=valor` en una línea (como hoy) · JSON por línea · binario.
- Transporte: ficheros (como hoy) · pipe con nombre · socket · SHM.
- *Recomendación:* JSON por línea sobre **ficheros**, detrás de una interfaz. Solo se cambia de
  transporte si R-03 demuestra que el disco frena. Hay que medir que JSON no pase de ~1 ms por
  ciclo.

### H.5 ¿Tests de Lua sin juego?
- ¿Qué versión de Lua lleva el UE4SS que usas (5.4)? ¿Te vale instalar Lua y un framework de tests
  (p. ej. `busted`) en Windows y en CI?
- *Recomendación:* sí. Tests de formato y parseo con objetos UE simulados, más fixtures compartidos
  que genera Lua y lee Python.

### H.6 ¿Uno o dos mods?
- Opciones: (1) producción y laboratorio separados, como en V2 · (2) un solo mod con modo lab
  activable.
- *Recomendación:* 1, con una librería `shared/` que se copia al instalar. La separación fue un
  acierto en V2: el probe pasó de ~2 040 a ~950 líneas.

### H.7 ¿Qué hace el mod si Python se cae?
- Hoy no hace nada: el último mando se queda aplicado.
- Opciones: (a) nada, solo avisarlo en `tick` · (b) *watchdog*: si no hay latido de Python en N
  segundos, soltar mandos a neutro · (c) aplicar freno.
- *Recomendación:* empezar con (a) y medir. (b) y (c) son decisiones de seguridad que conviene
  probar en el juego antes de activarlas.

### H.8 ¿Qué ejes y sistemas tiene que soportar el contrato desde la versión 3.0?
- Palanca combinada (323), MC analógica (M3A), freno independiente, dinámico separado, puertas,
  avisos AWS/TPWS…
- *Recomendación:* el **formato** admite cualquier eje desde 3.0. La **implementación** empieza con
  los dos que ya conocemos (323 y M3A) y crece con R-05.
