# Mod Lua de V3 — visión a largo plazo

> **Borrador para debate** (2026-11-13). Sale de la revisión
> [R-10](../investigaciones/R-10-revision-mod-lua.md). Las preguntas abiertas están en
> [PREGUNTAS § H](../PREGUNTAS.md#h-mod-lua). Cuando se cierren, este documento pasa a ser
> `V3/docs/contrato-mod.md` + `V3/docs/mod-lua.md`.

## Para qué existe el mod

El mod es **los ojos y las manos** del autopiloto dentro del juego, y nada más:

```text
 Juego (UE4) ──► MOD LUA ──► contrato versionado ──► Python V3 (decide)
               lee / aplica       (transporte)          núcleo puro
```

- **Lee** lo que el juego expone (HUD, DriverAid, mandos, Simulation cuando se pueda).
- **Aplica** mandos que le pide Python y confirma qué pasó.
- **No decide nada.** No tiene reglas de frenado, ritmo ni umbrales de conducción.
- **No sabe de trenes concretos.** Lo que cambia entre trenes (nombres de mandos, modo de escritura,
  enums de señal, puertas) llega como **dato**, desde el paquete del tren.

A largo plazo, el mod es la pieza que más tiempo vive sin cambiar. Si el contrato es bueno, el
núcleo Python puede reescribirse, añadir trenes o cambiar de UI sin tocar Lua.

## Principios

1. **Solo I/O.** Igual que en V2 (*el probe observa, Python decide, el IPC ejecuta*).
2. **El tren es un dato.** Ningún nombre de tren, tabla de muescas ni enum regional en el código Lua.
3. **Contrato versionado.** Cada mensaje lleva la versión del contrato. Si Python recibe una versión
   que no entiende, se niega a conducir y dice por qué.
4. **Capacidades declaradas.** El mod dice qué puede leer y escribir en *este* tren.
   - «No existe» (`absent`) no es lo mismo que «no lo he podido leer» (`error`).
5. **Presupuesto fijo.** El ciclo caliente cuesta ≤ 1 ms. Nada de `pairs()`, `FindAllOf`,
   introspección ni HTTP en el tick.
6. **Seguro por defecto.** Cada lectura y escritura va en `pcall`. Nunca se hace introspección sobre
   objetos con `IsValid()==false`. Nunca se usa `BeginChangingVHID` en el ciclo (bloquea el
   teclado).
7. **Producción y laboratorio separados.** Pueden compartir librería, pero no tick ni puente.
8. **Probable fuera del juego.** Toda la lógica que no toca UE (formato, parseo, cola de mandos,
   resolución de nombres) se prueba con Lua normal en CI.
9. **Leer todo, usar lo elegido** ([decisiones/0004](../decisiones/0004-el-mod-lee-todo-python-elige.md),
   aceptada). El mod descubre todo lo que expone el tren al cargarlo (`catalog`). En el ciclo solo
   lee lo que el tren pide (suscripción) y, si se activa, manda el resto despacio para investigar
   (`wide`).

## Piezas

```text
V3/mods/
  shared/              librería común (formato, util, pcall seguro, log)  ← copiada al instalar
  TSW6Bridge/          mod de producción (lee + aplica)
  TSW6Lab/             mod de laboratorio (capturas → JSON, borrador de paquete de tren)
  tests/               tests Lua sin juego (UE simulado) + fixtures compartidos con Python
```

> Los nombres son provisionales. UE4SS carga cada mod de su propia carpeta `Scripts/`, así que
> `shared/` se copia dentro de cada mod al instalar. Se acaba el «mantener en sync a mano».

## Contrato (propuesta)

### 1. Saludo al empezar sesión (`hello`)

Al cargar un tren, el mod escribe un mensaje único:

```json
{
  "type": "hello",
  "contract": "3.0",
  "mod_version": "3.0.0",
  "ue4ss": "3.x",
  "vehicle_class": "RVM_LIA_Class323_DMSO_C",
  "capabilities": {
    "read":  ["speed", "accel", "gradient", "limit", "next_limit", "odo", "brake_gauges", "signal", "doors"],
    "write": ["PowerBrakeHandle"]
  }
}
```

### 1b. Catálogo del tren (`catalog`)

Justo después del `hello`, fuera del ciclo, el mod recorre lo que expone el tren y publica cada
campo con su ruta, tipo, valor de muestra y rango si lo hay. Python lo guarda en la carpeta del
tren. Sirve para escribir el paquete del tren y para detectar cambios entre versiones del juego.

```json
{"type":"catalog","fields":[
  {"path":"Controls/PowerBrakeHandle.Input","kind":"float","sample":0.25,"range":[0,1]},
  {"path":"HUD/NextSignal.Aspect","kind":"enum","sample":3}
]}
```

### 2. Configuración que manda Python (`vehicle_config`)

Python responde con lo que sacó del paquete del tren:

- **Suscripción:** qué rutas del catálogo van en el `tick` y con qué nombre genérico (`speed`,
  `signal_stop`, `brake_cyl`…). Un campo nuevo es un cambio de datos, no de Lua.
- **Canal ancho (`wide`):** si se activa, el mod manda a ~1 Hz todos los campos baratos del
  catálogo, repartidos entre ticks, para investigar.

- Qué componente es cada eje: tracción, freno de servicio, freno independiente, dinámico…
- Cómo se escribe cada eje: `step` (un peldaño por comando, caso 323), `input` (valor analógico
  0..1, caso M3A MC) u `output`.
- Los enums de señal que significan «parada».
- Los nombres de puertas.

El mod **no** trae tablas por tren. Si no recibe configuración, solo publica lo genérico y no
acepta mandos.

### 3. Telemetría (`tick`, ~20 Hz)

```json
{"type":"tick","seq":1234,"t_game":5321.42,"t_os":17.003,
 "speed_ms":22.4,"accel_ms2":-0.61,"gradient_pct":-0.3,
 "limit_ms":26.8,"next_limit":{"ms":17.9,"dist_m":812.0},
 "odo_m":40211.5,
 "axes":{"PowerBrakeHandle":{"input":0.25,"output":-2,"step":2}},
 "brake":{"cyl_bar":1.8,"mr_bar":8.9},
 "signal":{"stop":false,"dist_m":1530.0},
 "doors":{"open":false},
 "ack":{"cmd_id":42,"ok":true}}
```

En el ciclo van los valores **crudos**. Las traducciones («muesca B2», «freno aplicado») las hace
Python con el paquete del tren. Un campo sin capacidad no aparece; uno que falló aparece en
`errors`.

### 4. Mandos (`cmd`)

Varios ejes por mensaje, cada uno con su id:

```json
{"type":"cmd","cmd_id":43,"set":[{"axis":"PowerBrakeHandle","value":0.375},{"axis":"IndependentBrake","value":0.0}]}
```

El mod aplica cada eje en el modo que dijo `vehicle_config` y confirma por eje en el siguiente
`tick`.

### 5. Transporte

El transporte va detrás de una interfaz. Para empezar se queda el de **ficheros**: ya está probado
y cuesta ~1 ms. Se cambia formato, no mecanismo. Un pipe con nombre, un socket o SHM entran solo si
R-03 demuestra que el disco es el cuello. El contrato (mensajes y versiones) no depende del
transporte.

## Laboratorio (`TSW6Lab`)

> 2026-11-13: se escribe **nuevo en V3**, no se reutiliza el ApiExplorerMod de V2 (PREGUNTAS H.6).
> Su primer trabajo es la M3A ([R-12](../investigaciones/R-12-m3a-http-vs-lua.md), paso 2).

El laboratorio hace lo mismo que el ApiExplorer de V2, pero con dos fines concretos:

1. Generar un **borrador de paquete de tren**: ejes, modo de escritura, peldaños, nombres de
   puertas, enums de señal. Con eso añadir un tren pasa a ser: lab → revisar JSON → sesión de
   validación.
2. Descubrir **campos candidatos** para el contrato. Un campo entra en `tick` solo por decisión
   explícita y con versión de contrato nueva, igual que la regla D2.

Ningún fichero pasa de 300 líneas. La introspección profunda se activa a mano (*opt-in*).

## Pruebas

| Nivel                   | Qué                                                                    | Dónde       |
| ----------------------- | ---------------------------------------------------------------------- | ----------- |
| Unit Lua                | Formato de mensajes, parseo de `cmd`, cola, resolución de nombres      | CI, sin juego |
| UE simulado             | Objetos falsos con la forma de la 323 y la M3A, incluido `IsValid=false` | CI        |
| **Contrato compartido** | Los mismos fixtures JSON los genera Lua y los lee Python               | CI          |
| Humo en juego           | Instalar, `hello`, 30 s de `tick`, un `cmd` por eje y su ACK           | Manual, por versión |

## Hoja de ruta del mod

| Paso | Entregable                                                                 | Necesita juego |
| ---- | -------------------------------------------------------------------------- | -------------- |
| M0   | Contrato escrito y aprobado (`contrato-mod.md`), versión 3.0                | No             |
| M1   | `shared/` + tests Lua en CI + formato `hello`/`tick`/`cmd`                 | No             |
| M2   | `TSW6Bridge` mínimo: `hello` + campos núcleo + un eje, puente propio       | Sí (323)       |
| M3   | `vehicle_config` desde el paquete; M3A analógica sin tocar Lua             | Sí (M3A)       |
| M4   | Marcas de tiempo + medición de latencia (cierra R-03)                      | Sí             |
| M5   | `TSW6Lab` genera borrador de paquete; probado con un tren nuevo            | Sí (lab)       |
| M6   | Ejes extra (freno independiente, dinámico), puertas, sistemas de seguridad | Sí             |
| M7   | Instalador + comprobación de versiones UE4SS/TSW6 (R-06)                    | No             |

**Convivencia con V2 durante la transición.** El mod de V3 usa **otra carpeta de puente**
(`%TEMP%\TSW6BridgeV3\`). Solo uno de los dos mods de producción va activo en `mods.txt`, porque
dos hooks del mismo `ReceiveTick` dan tirones. El oráculo no se ve afectado: los logs JSONL de V2 ya
están grabados y el arnés de replay los lee sin el mod.

## Reglas heredadas de V2 (no negociables)

- Nada de `BeginChangingVHID` en el ciclo.
- Ninguna introspección sobre objetos con `IsValid()==false`.
- En trenes `step`, un peldaño por comando, y confirmar leyendo el HUD.
- HTTP nunca dentro del mod.
- Una sola fuente para cada nombre (paquete del tren), nada de listas duplicadas entre mods.
