# Plan TSW6 producto v2

**Fecha:** 2026-08-29 (paquete tren: no buscar palanca en el tick)
**Árbol:** [../assets/esqueleto_v2.dot](../assets/esqueleto_v2.dot) ·
[../assets/esqueleto_v2.svg](../assets/esqueleto_v2.svg)
**Código actual:** foto en [../assets/esqueleto_arquitectura.svg](../assets/esqueleto_arquitectura.svg) —
referencia, no el producto v2.

**En juego:** `mods/TelemetryProbeMod/Scripts/main.lua` (contrato I/O).  
**Laboratorio Lua (diseño):** [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) — mod aparte, no mezclar con el probe.
**Python de hoy:** laboratorio. v2 puede **rediseñar el agente desde 0** (mismas pruebas de vía) sin
clonar Nexus.

Dastsc es **cómo otro proyecto creció** (capas, un mando por tick, cluster). No es plantilla ni
techo. Lo que no encaje en TSW (OCR, TSC, 2 mph de RELEASE, nunca OFF en bajada, React) no se copia.

---

## Cómo lo veo

v2 no es “el P1 actual más limpio”. Es **definir el producto** y luego implementar:

- **no buscar palancas en el tick:** `vehicle=` carga un paquete (nombres UE + mapa muesca); Lua

  solo aplica SendCommand;

- un **perfil de servicio de pasajeros** (parar, puertas, siguiente); el “a fondo vs coast” lo marca

  el **ETA**;

- **señales** como objetivo de vía desde el diseño, no un stub al final;
- **física** que se introduce solo si cambia el mando (pasajeros y/o mercancías);
- el probe **no** decide. El cálculo `v²/2a` **sí** cada tick (velocidad y distancias cambian).

El código viejo sirve para no olvidar Four Oaks / Sutton / IPC 323. No obliga a las mismas 7 capas
ni al mismo coordinador.

---

## 1. Perfil genérico de pasajeros

Casi todos los EMU/locomotoras de viajeros hacen el **mismo ciclo comercial**. Eso es el perfil
base. El FSM de puertas no cambia; **cuánto aprietas entre paradas** lo dice el horario (ETA), no
una etiqueta `express`.

```text
en vía → límite y señales → acercarse al andén → parar → puertas → despachar → repetir
```

**Horario (nombres de este doc):** **hora de llegada** y **hora de salida** = reloj HUD de la
próxima parada (no confundir con “llegar físicamente” ni con ETA cinemática). En código:
`next_stop_arrival` / `next_stop_departure`; P1 consume la llegada como `station_eta`.

| Capa | Qué es | Qué no es |
| --- | --- | --- |
| **Servicio** (genérico) | Parada comercial, dwell, puertas, siguiente estación | Muesca B2 vs B3 |
| **Ritmo (ETA)** | Holgura: hora de llegada HUD vs tiempo cinemático al andén | Layout de palanca; no hace falta `stopping` / `regional` / `airport` |
| **Líneas / paradas** | Qué servicio y qué apeaderos: ya en **`tsw_hud.db`** | Layout freight vs combined |
| **Layout** | Combined UK (323) vs split freight (SD40-2) | El número de paradas (BD). Freight: **casi nunca horario**; si un escenario lo trae, es excepción |

### Ritmo = ETA (estudiar, no inventar `pace`)

Hoy TSW6 ya tiene el mismo recorte que Dastsc (`schedule_slack_sec` → escala de reacción + metros de
coast): `station_plan.py` ≈ `nexus-agent/.../schedule.ts`.

| Pieza | TSW6 hoy | Dastsc | Qué estudiar en v2 |
| --- | --- | --- | --- |
| Fuente hora de llegada | `tsw_hud.db` + servicio HUD → `station_eta` | OCR `station.eta` | Nosotros: BD; no copiar OCR |
| Holgura | `dist/v − minutos hasta llegada` | Igual | Fórmulas casi calcadas: **no duplicar**; una función, tests |
| Reloj `now` | **PC** (`datetime.now`) | Reloj del agente (PC) | **Hueco TSW:** `TimeOfDay` escenario ([TIMEOFDAY_API.md](../reference/TIMEOFDAY_API.md)) — sin eso la holgura GUI miente |
| Flag | Holgura **OFF** por defecto | Siempre en el plan estación | ¿ON cuando el reloj sea el del mundo? |
| Coast / tarde | Mismos umbrales ~15/30/60 s | Igual | Validar in-game; ajustar **nuestros** números si Cross-City lo pide |

Con ETA basta para “muchas paradas a media vs 2 paradas a fondo”:

- **Pronto** (holgura +) → coast / frenar más tarde (no hace falta etiqueta `stopping`).
- **Tarde** (holgura −) → aplicar antes, ir al techo de vía (no hace falta etiqueta `express`).
- **Sin hora de llegada** → **no hay holgura** (no hay reloj contra el que ir pronto/tarde). Techo de vía +
  señales; no inventar horario ni un `pace`. Es lo normal en **mercancías**; también pasajero sin
  match HUD. El “margen” freight es `a` menor + ejes, no más slack de horario.

**Mejora de eficiencia (vs clonar Dastsc):** no portar otra curva; cablear `now` al escenario; un
solo `schedule_slack` en el agente v2; no calcular holgura si el flag está OFF (ya).

### Líneas: BD que ya tenemos

[HUD_TIMETABLE.md](../v1/HUD_TIMETABLE.md): `tsw_hud.db` (servicios, STOP vs GO VIA, `car_stop_signs`). No
hace falta otra base de “líneas” para saber cuántas paradas hay.

**Estudio (¿hace falta mejorar?):** match `currentServiceName` + geo; andenes de la dirección mala;
tablón en P1 (C2) vs solo planning; tamaño ~4 GB extraído vs semilla. Si el match es estable en
Cross-City, **no** rediseñar la BD.

### Layout (palancas)

Sigue siendo combined vs freight ([FREIGHT_NA.md](../v1/FREIGHT_NA.md)). Independiente de la BD de
viajeros.

**Mercancías y horario:** lo normal es **sin** hora de llegada ni de salida (no hay servicio HUD útil). Holgura ETA
**apagada**. Mandos = límites, señales, pendiente, selector de eje. Si un escenario freight trae
timetable (poco probable), se trata como pasajeros: hay hora de llegada → se puede holgura; no hace falta un
tercer perfil.

**Hueco en v2:** `PassengerService` = ciclo puertas + consumo de hora de llegada / salida **cuando existan**.
Freight = layout + física de ejes, sin FSM de puertas de viajeros.

##### Opciones (ritmo)

| | Opción | Pros | Contras |
| --- | --- | --- | --- |
| P-A | ETA + techo de vía (elegida) | Un servicio; el horario manda | Holgura inútil sin TimeOfDay |

**Sugerencia:** P-A en **pasajeros**. Freight: sin ETA salvo excepción de escenario. Sin JSON
`pace` stopping/express. Sin inferir “AV” por densidad de paradas.

### Dudas, mejoras, alternativas (§1)

##### Dudas (hay que cerrarlas con una sesión in-game, no en el md)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿El ciclo “puertas” es igual en todo EMU UK? | Perfiles Liah **no** unifican nombres UE (ver abajo). FSM 323 usa `PassengerDoor_*` + DMI | F9 + un segundo tren; adaptador de **layout** de palanca ≠ adaptador de puertas |
| ¿La hora de llegada y los metros al andén hablan del mismo sitio? | Holgura mal calculada | **Tablón = andén.** Contrastar horario HUD vs TrackData vs `car_stop_signs` (fuentes), no dos sitios |
| ¿La hora de salida entra en el perfil o solo la de llegada? | Dwell / no salir antes | Hoy P1 usa sobre todo llegada. Salida puede ser FSM, no costa |
| ¿Holgura con TimeOfDay cambia el 323 de verdad? | Si el desfase PC vs escenario es pequeño, D9 es cosmética | Medir en cabina `WorldTime` vs hora de llegada vs reloj PC |
| ¿Sin hora de llegada = más holgura (p.ej. freight)? | Confundir slack ETA con margen de vía | No: sin horario holgura **OFF**. Freight: techo + señales + `a`/ejes. Si hay llegada programada (raro), misma holgura que pasajeros |

##### Mejoras (respecto a lo que ya hay)

1. Un contrato `PassengerService` (estados: vía / approach / stopped / doors / depart) **sin**

   nombres 323 en el núcleo.

2. Holgura **una** función; `now` = escenario (D9) antes de subir umbrales 15/30/60.
3. Freight: ni intentar `tsw_hud.db` por defecto (evita match basura).
4. Si hay hora de llegada y holgura OFF, el log no debería sugerir que el horario “manda” (`p1eta=` hoy se ve

   igual).

##### Alternativas al “perfil genérico”

| | Alternativa | Cuándo tiene sentido | Coste |
| --- | --- | --- | --- |
| G-A | Un perfil pasajeros + ETA (**elegida**, ciclo) | Viajeros con HUD; ahora 323 | Otro EMU UK cuando toque; **no** un producto AV |
| G-B | Layout de palancas por familia (**elegida**) | combined / split / blended / MasterController | Un JSON por tren; no es ritmo `hs` |
| G-C | Dejar el FSM 323 y “genérico” solo en el doc | Entregar antes | v2 miente |
| G-D | Parada solo por distancia HUD, ignorar horario | Freight, sandbox | Pierdes coast/tarde en viajeros |

**Elegido:** **G-A** (ciclo comercial: ETA, andén, puertas) **y** **G-B** (a qué UObject se escribe).
No mezclar: un 375 es pasajero G-A con palanca combined y **otro nombre** (`PowerHandle`); un
SD40-2 es freight (casi sin horario HUD) con layout split. Ver
[DRIVERINPUT_API.md](../reference/DRIVERINPUT_API.md) `shared-profiles`. No hay perfil `hs` / “AV”.

### Perfiles Liah (`investigacion/.../shared-profiles`)

~90–140 `.tswprofile`: mapeo joystick → **nombre UObject**. No es el FSM de puertas.

| Familia (aprox.) | Nombres UE típicos | No es el mismo string |
| --- | --- | --- |
| Combined UK | `PowerBrakeHandle` (323), `PowerHandle` (375/387), a veces `IrregularLever_ThrottleBrake` | Cada pack inventa el hijo |
| Split NA / freight | `Throttle` + `AutomaticBrake` + `IndependentBrake` + a menudo `DynamicBrake` | Tres/cuatro ejes |
| Acela / blended | `ThrottleLever` + `AutomaticBrakeLever` (+ cruise) | Ni 323 ni SD40 |
| DE / AFB | `MasterController`, `TrainBrake_{SIDE}`, `DynamicBrake_{SIDE}` | `{SIDE}` = asiento |

Puertas en esos JSON: casi siempre **teclas** (“Open Close Left Doors”), no `PassengerDoor_FL`. El
probe 323 lee componentes; otro tren puede llamarlos distinto — **eso no está en Liah**.

### Paquete de tren — ahorro: no buscar palanca

**Idea (la que importa en el tick):** al saber el tren, **ya sabemos** a qué UObject escribir y con
qué mapa de muescas. El bucle caliente es:

```text
GetData → snapshot → v²/2a + objetivos → SendCommand (nombres del paquete)
```

**No** es: cada frame `FindAllOf` / `pairs(actor)` / F9 / heurística “¿será PowerBrakeHandle?”.

| Una vez (cambia `vehicle=`) | Cada tick (~20 Hz) |
| --- | --- |
| Cargar `data/vehicles/<id>.json` + learner | Leer GetData |
| Resolver layout + nombres UE + peldaños | Calcular metros (`a` del learner) |
| Caché en memoria | Un mando a esos nombres |

UK combined = **misma familia de palanca**, JSON distinto por tren (323 vs 375). Freight split =
otros nombres, misma idea de caché.

Dastsc: JSON del tren + `brakeStats`; **también** calcula el plan cada tick. TSW6 hoy: Liah suelto,
EMA suelta, `control_layout` heurístico. v2 = **un paquete**.

##### Qué va en el paquete / qué no

El JSON es **G-B** (palancas). **G-A** (ETA, andén, puertas) no se guarda ahí: sale del HUD en el tick.

| Va en JSON (una vez, G-B) | No va (tick) |
| --- | --- |
| `layout`: combined / split / blended / MasterController | Velocidad, gradiente, dist cartel/andén/señal |
| Nombres UE (323: `PowerBrakeHandle`; 375: `PowerHandle`) | `FindAllOf` / F9 en caliente |
| Mapa muesca → InputValue (o % si el tren no es 0–8) | Recalcular el mapa cada frame |
| Semilla física: fill_s, `a` inicial, mph/kmh | Tablas “a 47 mph → 812 m” |
| Match `rail_class` / `vehicle=` | Holgura (hora de llegada en vivo) |
| Opcional: no usar `tsw_hud.db` (freight típico) | Servicio “passenger vs freight” como ritmo |

**Demasiado / poco** (tamaño del paquete, no del tick):

- **Demasiado** = meter en JSON lo que cambia cada frame o lo que no es nuestro runtime: tablas de
  metros precalculadas (`v` y `dist` cambian); el `.tswprofile` Liah entero (USB/joystick) en el
  bucle; un archivo por muesca (el learner ya guarda `a` por muesca en `logs/profiles/`).
- **Poco** = lo de hoy: adivinar palanca por nombre en caliente (`control_layout` heurístico), sin
  JSON del tren. Eso es lo que el paquete sustituye.

##### Archivos (pocos)

| Archivo | Rol | Cuántos |
| --- | --- | --- |
| `data/vehicles/<id>.json` | Paquete estático | 1 por tren o familia |
| `logs/profiles/<vehicle>.json` | Learner (ya existe) | 1 por vehículo |
| `physics.py` + coordinador | Un `s = v²/2a` | **Uno** |
| Liah `.tswprofile` | Fuente para rellenar el paquete | No en el tick |

**Acela:** blended + nombres + % no muesca 0–8; learner calibra `a`. Sin descubrir Acela en
caliente.

##### Dos casos (servicio × layout)

```text
servicio:  freight (casi nunca ETA)  |  passenger (ETA + puertas si hay andén)
layout:    split                     |  combined | blended | MasterController
```

- Mercancías: vía + selector de ejes; holgura OFF; no puertas de viajeros.
- Pasajeros: andén + ETA + puertas. Layout **aparte** (323 combined ≠ 375 combined con otro nombre).

Mal: `if freight: … else: muescas ETA`. Bien: servicio = **objetivos**; layout = **palancas**.

**¿Dos motores de distancia?** No. Misma `s = v²/(2a)`; freight más metros porque **`a` es menor**.
Extra freight = qué eje, no otro `physics.py`.

---

## 2. Física: qué investigar e introducir

Hoy: `v²/2a`, gradiente en %, learner por muesca, `MAX_DECEL` de 323. Abajo: **qué entra en el
plan** (decidido), **qué queda en dump HTTP** y **qué no tocar** hasta evidencia in-game.

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | Gradiente probe (~20 Hz); learner (`logs/profiles/`); `s = v²/(2a)`; sin doble `g` con `using_learned` (gradiente **cerrado**) | — |
| **Elegido, sin cablear** | Masa total HTTP → `massFactor` en `physics.py` (F-B); `mass_ref` al calibrar | Código Python poll §2 F-B |
| **Validado lab · estudiar reglas** | Patinaje HUD → `is_slipping` en GetData; handler P1 **no** hasta matriz in-game | Sesiones slip §2 · ver 9b |
| **Congelado** | Cilindro / esfuerzo (`HUD_GetTractiveEffort`); longitud de formación | `brake_cyl_bar` vía HUD gauge — ver nota §2 |
| **Investigar → freight F-D** | Selector auto + dyn en bajada; ind solo maniobras | Sesión SD40; [FREIGHT_NA](../v1/FREIGHT_NA.md) |

Cierre del capítulo: ver **Criterio de cierre §2** más abajo en este apartado.

| Dato | Dónde está | ¿Pasajeros? | ¿Mercancías? | Introducir si… |
| --- | --- | --- | --- | --- |
| Gradiente | Probe DriverAid | Sí | Sí | Ya está |
| Decel aprendida | `logs/profiles/` | Sí | Sí (multi-eje) | Ya está |
| Masa consist | HTTP **peso total** (`ClampPowerInput.Mass`) | Mismo poll 5 min | Mismo poll 5 min (carga entra en el total) | F-B §2 — ruta validada lab |
| Esfuerzo / cilindro | Simulation Lua no lee; HUD gauge opcional | **Congelado** P1 | **Congelado** P1 | `HUD_GetBrakeGauge_1` validado lab; no HTTP tick |
| Longitud tren | Formación / HTTP | **No útil** | **No útil** (igual) | Se frena al andén / objetivo; da igual lo largo |
| Adherencia / patinaje | Probe **`HUD_GetIsSlipping`** (~20 Hz Lua) | Sí | Sí (más claro en bajada freight) | **Canal validado**; reglas P1 = estudio in-game (§2) |

`massFactor` Dastsc **no es otra fila:** es la misma **masa total** (F-B) pasada por una receta
(p. ej. `mass_now / mass_ref` en `physics.py`). No copiar `500 t` a ciegas; el peso ya sale del
poll HTTP. **`mass_ref`** = peso al calibrar el learner (o semilla del paquete), para no contar la
masa dos veces.

**Gradiente (una fuente, dos usos — no duplicar):** el probe Lua manda `gradient_pct` ~20 Hz
(DriverAid); **no** HTTP en el tick. Ese mismo valor sirve para:

1. **Learner / P1 con perfil:** elegir celda plano / subida / bajada (`|grad| &lt; 0,5 %` ≈ plano).
   La `a` aprendida **ya incluye** el efecto de la pendiente en esa celda.
2. **Fórmula sin perfil** (constantes UK): `effective_decel_ms2` suma gravedad en `braking_distance_m`.

En código, si `using_learned` → `gradient_pct=0` en el ctx de `s=v²/2a` (evita contar la pendiente
dos veces). No añadir tercera capa (p. ej. factor extra en bajada) sin residuo medido in-game.

#### Opciones

| | Opción | Pros | Contras |
| --- | --- | --- | --- |
| F-A | Learner-only (hoy) | Cero HTTP extra | No generaliza al cambiar masa |
| F-B | Peso **total** HTTP (arranque + cada 5 min) | Un factor en `physics.py` | Depende de `-HTTPAPI` |
| F-C | Más campos en GetData | Un archivo | Tick Lua más gordo (presupuesto §4.1) |
| F-D | Freight: **auto + dyn** (bajada → dyn) | Retención estable en pendiente | Investigar (FREIGHT_NA fase 4); **ind** solo maniobras, fuera del autopilot |

**Masa (elegida F-B):** HTTP = **peso total** de la formación (si enganchas más, el total sube; no
sumar ejes ni un Mass por vagón en el agente). Arranque + **cada 5 min**, pasajeros y mercancías
igual. Si `vehicle=` cambia, leer ya (no esperar el poll). Si acoplas vagones sin cambiar
`vehicle=`, forzar re-poll o esperar el intervalo de 5 min. F-A queda si no hay `-HTTPAPI`.

##### F-B masa — contrato (validado lab `20260830T213100Z`)

| Campo | Valor |
| --- | --- |
| **Ruta HTTP** | `GET /get/CurrentFormation/0/Simulation/ClampPowerInput.Mass` |
| **Evidencia 323** | **45 550** kg (Cross-City, build `20260830l`) — coherente con dump RailBridge ~45 480 |
| **Canal** | Python `tsw_telemetry_source` — **mismo hilo planning** que `DriverAid.TrackData` (~2 s), **no** GetData tick |
| **Poll** | Al conectar HTTPAPI + **cada 300 s** + inmediato si cambia `vehicle=` en probe |
| **Estado interno** | `mass_kg` (último OK), `mass_factor = mass_kg / mass_ref` |
| **`mass_ref`** | Peso al calibrar learner o semilla en `data/vehicles/<id>.json` — evita doble conteo con `a` aprendida |
| **`physics.py`** | Multiplicar decel efectiva por `mass_factor` solo cuando F-B activo y `mass_ref > 0` |
| **Log/GUI** | Una línea al primer poll OK: `mass_kg=… mass_factor=…` |
| **Freight** | Misma ruta en líder; confirmar si acoplar vagones exige sumar varios coches (pendiente SD40) |
| **Sin HTTP** | F-A: `mass_factor = 1.0`; no bloquear autopilot |

**No** meter `mass_kg` en GetData (~20 Hz innecesario). El agente lee el factor del estado Python.

##### Adherencia — canal HUD (validado lab `20260830T213100Z`)

| Campo | Valor |
| --- | --- |
| **Lectura Lua** | `actor:HUD_GetIsSlipping(out)` → `out["IsSlipping"]` (bool) |
| **Complemento** | `HUD_GetIsTractionLocked` — incluir en probe; correlacionar con slip en estudio |
| **GetData** | `is_slipping=0` \| `is_slipping=1` (omitir si falla); opcional `traction_locked=0\|1` |
| **Frecuencia** | Mismo tick probe ~20 Hz — **no HTTP** en P1 |
| **Evidencia 323** | F5 `hud_batch` 16/16; `IsSlipping: false` **solo parado** en `213100Z` — **sin** slip en marcha |
| **HTTP alternativo** | `Simulation/Axle_* / IsSlipping`, `CurrentTrackAdhesion` — lab/correlator; no tick |

**Problema con las reglas “fase 1” anteriores:** eran un atajo (“APPLY + slip → −1 muesca”) sin
sesiones de patinaje real. `HUD_GetIsSlipping` es un **booleano global** — no distingue:

| Escenario | Muesca típica | ¿−1 muesca ayuda? | Estado |
| --- | --- | --- | --- |
| **Freno en APPLY** (ruedas bloqueadas / ABS) | B2–B6 | **Quizá** — suelta freno | Hipótesis P1; validar 323 |
| **Tracción** (arranque, subida, power alto) | P2–P8 | **No** — hay que **bajar potencia**, no tocar freno | Regla distinta o ignorar slip |
| **Regen / dyn** (EMU o freight F-D) | dyn activo | **Incógnita** — puede ser slip de motor | Sesión aparte |
| **Parado / v≈0** | cualquiera | **Ignorar** — falso positivo o irrelevante | Umbral `speed_ms > …` |
| **COAST / RELEASE** | neutro o soltando | **No actuar** — no hay APPLY activo | Solo ventana APPLY |

**Principios de diseño (acordados, reglas numéricas pendientes):**

1. **Separar canal y acción:** cablear probe **antes** que el handler; loggear slip sin modificar mando.
2. **Contexto obligatorio:** la acción depende de `brake_command.kind`, `handle_notch`, `speed_ms` —
   no de `is_slipping` solo.
3. **No cancelar plan:** ningún escenario pasa a RELEASE ni aborta objetivo P1 por slip.
4. **Sin +metros** al plan por adherencia (igual que antes).
5. **323 combined:** tope de freno si aplica (ej. no bajar de B1) — **confirmar** si sigue siendo correcto.
6. **Freight (F-D):** −1 muesca en el **eje activo** (auto/dyn), no la misma regla que UK combined.

##### Protocolo estudio patinaje (antes de handler 9b)

Objetivo: rellenar la matriz escenario → acción con capturas **en marcha** (explorer F5 repetido o
log probe con `is_slipping`).

| # | Situación in-game | Qué capturar | Pregunta |
| --- | --- | --- | --- |
| S1 | Freno fuerte en cartel, hojas/mojado | F5 o GetData + nota muesca | ¿`IsSlipping` true en APPLY? ¿cuántos frames? |
| S2 | Arranque power alto en pendiente | idem | ¿slip true con power>0? ¿`TractionLocked`? |
| S3 | Regen activo bajando | idem | ¿slip ligado a dyn? |
| S4 | Seco, frenada normal B2 | línea base | ¿slip siempre false? |
| S5 | Freight SD40 bajada (futuro) | F-D | ¿slip en eje dyn vs auto? |

**Salida del estudio:** tabla **escenario × señales × acción** aprobada; entonces sí cablear handler.

**Borrador handler (solo tras S1–S4 en 323):**

```text
SI speed_ms < 0.5 → no actuar
SI brake_command.kind != "APPLY" → no actuar
SI is_slipping == 0 → no actuar
SI handle_notch <= 4 (zona tracción) → no bajar freno; opcional: cap tracción (futuro)
SI handle_notch > 4 (zona freno) Y APPLY → soltar 1 muesca; debounce; tope B1
```

**Fase 2 (aplazada):** learner + `CurrentTrackAdhesion` HTTP — solo si fase 1 insuficiente.

**Cableado en dos entregas:**

| Entrega | Qué | Validación |
| --- | --- | --- |
| **9b-a** | Probe: `is_slipping` (+ opcional `traction_locked`) en GetData | Log en partida; sin cambio de mando |
| **9b-b** | Handler P1 tras matriz estudio | pytest + sesión S1–S4 |

**Nota cilindro (independiente):** `Simulation` no lee presión en Lua 323; **`HUD_GetBrakeGauge_1`**
(`RedNeedle (Pa)` ÷ 100 000 ≈ bar) coincide con HTTP cilindro en `213100Z`. Candidato probe para
`brake_cyl_bar` — ver [PLAN_API_EXPLORER](PLAN_API_EXPLORER.md) L0.6; P1 esfuerzo sigue congelado.

**F-D (mercancías):** investigar con el SD40. Selector **automático + dinámico** en línea (tren
enganchado). Hipótesis: **bajada** → dyn; **límite / parada / emergencia** → automático (dyn + auto
si hace falta). Umbral de bajada (~0,5 %) y reglas auto vs dyn: validar in-game. El 323 combined no
aplica. Distancia = `v²/2a`; learner por eje.

**Congelado:** esfuerzo tractivo (`HUD_GetTractiveEffort`); longitud de formación (tablón = andén;
enganchar vagones no mueve el punto de parada).

**Fase 2 adherencia (aplazada):** learner en celdas mojado / umbral `CurrentTrackAdhesion` HTTP —
solo si fase 1 no basta tras sesiones de calibración. **No** EMA mientras patina.

**Calibrar ≠ tabla de situaciones → metros.** El learner ya es EMA por muesca × banda de velocidad
× gradiente. El tick hace `s = v²/(2a)` con esa `a`. Más fino (SQLite por situación) solo si F-A
falla in-game (residuo sistemático tras masa y fill).

##### Dudas (cerrar con dump Lua, sesión SD40 o medición de residuo)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿`massFactor` + learner a otra masa? | Doble conteo de peso | `mass_ref` fijo al calibrar; factor solo para desvío respecto a esa base |
| ¿Enganche mid-session sin cambiar `vehicle=`? | Peso sube y el plan no lo ve | Re-poll HTTP al detectar cambio de formación, o acotar el riesgo con poll 5 min |
| ¿Adherencia → qué hace P1? | Regla única demasiado simple | **Matriz estudio** §2 (S1–S4); handler solo tras 9b-b |
| ¿Umbral bajada para dyn (F-D)? | 0,5 % es hipótesis | SD40 en pendiente; documentar en [FREIGHT_NA](../v1/FREIGHT_NA.md) |
| ¿Gradiente en probe y en learner? | Parece “dos rutas” al mismo dato | **Cerrado:** probe = única fuente; learner **elige celda**; fórmula solo si no hay perfil. Ya evita doble g con `using_learned` |

##### Criterio de cierre §2

- **323:** F-B cableado con ruta `ClampPowerInput.Mass` (evidencia `213100Z`); adherencia: probe
  `is_slipping` (9b-a) + sesiones S1–S4 antes de handler (9b-b).
- **Freight:** una sesión SD40 con reglas auto/dyn anotadas (F-D); learner por eje sin mezclar con
  combined UK.
- **No reabrir:** segundo `physics.py`, tablas precalculadas de metros, cilindro HTTP en el tick.

Investigación complementaria: [CURRENTFORMATION_API.md](../reference/CURRENTFORMATION_API.md),
[FISICA_Y_APRENDIZAJE.md](../v1/FISICA_Y_APRENDIZAJE.md) L3–L4,
[TSW_HTTPAPI_INDEX.md](../reference/TSW_HTTPAPI_INDEX.md),
[PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) (sesión `20260830T213100Z`).

---

## 3. Semáforos (diseño v2, no apéndice)

**Alcance autopilot: solo rojo.** Ámbar, doble amarillo y verde **no** entran en P1 v2 — el
conductor los vigila. Si más adelante hace falta, será decisión explícita fuera de este contrato.

**Escenario y permisos:** en algunos modos TSW el **controlador / escenario** puede **autorizar pasar
en rojo** (SPAD permitido, tutorial, variante de ruta, etc.). v2 **asume por defecto** que rojo =
parar (mismo criterio que un maquinista sin autorización). Cómo detectar “rojo pero legal pasar” y
si el autopilot debe obedecer al juego o siempre frenar: **aplazado** — documentar en sesión C1 cuando
aparezca un escenario concreto; no bloquea el contrato `signal_red` + distancia.

**Canal elegido: solo Lua** (mismo `GetDriverAidData` que cartel y gradiente). **No HTTP** para
señales (lento; el tick ya va por GetData).

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **Elegido** | S-Lua: `signal_red=1` + `signal_dist_cm` solo con aspecto rojo adelante | F9 + `extract_signal_red` en probe |
| **Python parcial** | `is_red_signal_aspect`, `policy.py` (señal vs cartel/andén), emergencia SIGNAL en coordinator | `evaluate_signal_brake` stub; sin telemetría en GetData |
| **Fuera de alcance** | Ámbar / verde / cola `nextSignals[]` | Conductor; no D8 en autopilot |
| **Aplazado** | Rojo con **permiso de escenario** (pasar en rojo) | Ver en juego si hay flag/API; política autopilot vs conductor |

Contrato mínimo en GetData — **solo cuando hay rojo adelante**:

```text
signal_red=1
signal_dist_cm=<metros en cm, como dist_limit_cm>
```

Si no hay rojo, **no** mandar esas claves (Python no inventa señal).

```text
GetDriverAidData (main.lua, pendiente)
  → escalares distanceToSignal + signalAspectClass (evitar TArray nextSignals[] si lim2)
  → si Stop / DANGER / RED → signal_red=1 + signal_dist_cm
  → TrainState → policy (tercer objetivo de vía) → P1 como cartel/andén
```

**Investigación Lua** (tarjeta **C1**, antes de cablear Python):

1. F9 / `dump_driver_aid` frente a señal **roja**: nombres exactos y unidades (cm).
2. UK: ¿`Stop` o `DANGER`? (`is_red_signal_aspect` acepta ambos.)
3. `extract_signal_red(driverAid)` — `pick_float` + pcall; sin `pairs` del struct entero.
4. Escribir claves solo si `dist_cm > 0` y aspecto rojo.

| | Opción | Estado |
| --- | --- | --- |
| S-Lua | 2 claves GetData (rojo + dist) | **Elegida** |
| S-A HTTP | DriverAid por HTTP | Descartada (lento) |
| S-D | Ignorar señales | No es v2 |

##### Dudas (cerrar con sesión C1 / tests D7)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿Escalares legibles al tick? | `nextSignals[]` puede ser TArray como lim2 | F9; preferir `distanceToSignal` + `signalAspectClass` |
| ¿Stop vs DANGER en UK? | Mapeo a `signal_red=1` | Cabina Cross-City; lista en `is_red_signal_aspect` |
| ¿Rojo vs cartel 55? | Prioridad de objetivo | Validar con `policy.should_prefer_signal_over_limit` |
| ¿Señal detrás del andén? | Frenar señal ya pasada | `signal_behind_station` (~50 m); sesión andén+señal |
| ¿Escenario permite pasar en rojo? | Autopilot podría frenar de más | C1: anotar escenario; más adelante flag o override manual |

##### Criterio de cierre §3

- Rojo a distancia conocida → P1 frena (plan o emergencia) en Cross-City 323.
- GetData estable ~20 Hz con C1 documentado.
- Tests fixture GetData con `signal_red=1` (D7) sin juego.
- Ámbar/verde: **sin** objetivo autopilot (conductor).

Validación: tarjeta **C1** · [DRIVERAID_API.md](../reference/DRIVERAID_API.md) señales.

---

## 4. Restricciones: alternativas y mejoras

Esto **no** es “no se puede”. Es el coste de cada camino. v2 elige; no hereda el “no hacer” del
laboratorio.

### 4.1 Tick Lua (UE4SS)

Referencia código: `mods/TelemetryProbeMod/Scripts/main.lua` (`WRITE_INTERVAL_S = 0.05` ≈ **17–20 Hz**;
`PROBE_BUILD`). Estabilidad: [PENDIENTE_DYNAMICHUD.md](../v1/PENDIENTE_DYNAMICHUD.md).

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | ~20 Hz GetData; `pcall` en lecturas HUD/DriverAid; probe = **solo I/O** | — |
| **Regla `pairs`** | No recorrer `driverAid` / `actor` entero en `ReceiveTick` | F9/dump sí puede usar `pairs` |
| **Añadir campo** | Mismo patrón escalar (`extract_*`, `pick_float`) | F9 + medición de tiempo antes de merge |
| **Descartado** | 10 Hz; reglas P1 en Lua; `pairs` del struct cada frame | — |

**Sin `pairs` (aclaración):** no significa cero `pairs` en el mod. Significa **no** hacer
`pairs(driverAid)` ni `pairs(actor)` en el tick caliente (congela el juego). Descubrimiento de
palancas, F9 y dump DriverAid van **fuera** del presupuesto de 50 ms.

**Campos en tick hoy (inventario):** velocidad, power/muescas, frenos HUD, `accel`, `gradient_pct`,
un cartel (`dist_limit_cm` / `next_limit_ms`), puertas (componentes + Facts, sin TArray `Messages`),
`odo_m`, `brake_cyl_bar` (candidato HUD gauge §2), `is_slipping` (* §2 adherencia),
mandos IPC ack. Presupuesto **C1:**
`signal_red` + `signal_dist_cm` = dos escalares más, mismo patrón que el cartel.

| Alternativa | Mejora | Coste |
| --- | --- | --- |
| **Seguir ~20 Hz, pcall, sin `pairs` en hot path (elegida)** | Estable (ya) | Lógica de vía en Python |
| Más DriverAid en Lua | Señales al mismo Hz | Riesgo freeze; medir antes (p. ej. `signal_red` + `signal_dist_cm`) |
| Bajar a 10 Hz GetData | Lua más holgado | Palanca más torpe |

**Elegido:** probe solo I/O; no bajar Hz; no meter reglas en Lua. Nuevos campos GetData solo tras
F9/medición.

##### Criterio de cierre §4.1

- Sesión 10+ min Cross-City 323 sin freeze tras añadir campos nuevos.
- Ningún `extract_*` del tick usa `pairs` del struct DriverAid completo.
- Agente Python sigue leyendo snapshot a ~20 Hz (§4.7); el cuello no es bajar Lua a 10 Hz sin medir.

### 4.2 IPC archivo

Hoy: `%TEMP%\TSW6Bridge\`:

| Archivo | Dirección | Rol |
| --- | --- | --- |
| `GetData.txt` | Lua → Python | Telemetría; **sobrescritura** cada ~50 ms |
| `SendCommand.txt` | Python → Lua | Línea de mando (`PowerBrakeHandle:…:cmd_id`) |
| `TSW6ApplyCommands.flag` | Python → Lua | “Hay mandos armados” |
| `SendCommandAck.txt` | Lua → Python | `ok` / `fail` tras aplicar |

**Sin HTTP** como canal de mandos en producción (323 validado por IPC). Detalle e incidentes:
[CANAL_CONTROL.md](../CANAL_CONTROL.md).

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | Ficheros + `write_send_command_with_ack`; cola `CommandChannel` | — |
| **Parcial** | Reassert: hasta 3 intentos, backoff 25 ms, `ack_timeout` ~120 ms adaptable | Documentar valores **nuestros** v2 |
| **Aplazado** | SHM (telemetría o mandos) | Medición tarjeta V2 CANAL_CONTROL |
| **Fuera de v2 agente** | HTTP PATCH como fallback si IPC falla | Mantener solo emergencia o quitar en `agent/` |

**Semántica:** GetData = snapshot fresco cada tick. Mandos = cola Python → un writer async → Lua
lee ~20 Hz y aplica; correlación `cmd_id` en GetData y ack. Vigilar `drops` si la cola se llena.

Código: `tsw_ipc_bus.py`, `control_channel.py` (no reimplementar en agente v2; mismo contrato §4.7).

| Alternativa | Pros | Contras |
| --- | --- | --- |
| **Ficheros (elegida)** | Simple, debuggable, ya funciona con UE4SS | Disco + ~ms; un mando por línea; cola (`drops`) |
| **Reassert hasta ack** | Reintentos si no `ok` | Ya en `CommandChannel`; mal calibrado satura el puente |
| **Shared memory (SHM)** | Menos lag que disco | Otro proyecto; no fase 0 |

**Elegido:** seguir con **ficheros** + reassert **ya cableado** (calibrar ms/reintentos v2, no copiar
Dastsc). SHM solo si medición dice que el disco es el cuello; no ahora.

##### Criterio de cierre §4.2

- Sesión 10+ min: mandos con `ack=ok`, `drops` bajo control, sin palanca “saltada”.
- Timeouts/reintentos documentados en agente v2 o § [Orden de implementación](#orden-de-implementación).
- Agente nuevo (`agent/`) usa el **mismo** puente; no segundo canal sin decisión explícita.

### 4.3 Un cartel en el probe

Referencia código: `mods/TelemetryProbeMod/Scripts/main.lua` (`extract_speed_limits`),
`tsw6/braking/v2/limit_brake.py`, `tsw6/telemetry/tsw_telemetry_source.py` (C.3a odometría),
`driver_aid_parser.build_speed_limits_queue`.

**Hoy (probado 2026-08-28):** solo **un** cambio de límite adelante en GetData — escalares
`DistanceToNextSpeedLimit` + `NextSpeedLimit` → `dist_limit_cm` / `next_limit_ms`. Al pasar un cartel
el juego actualiza el par. **No** hay `dist_limit2_*` en el probe (Python tiene campos y
`_merge_probe_second_limit` preparados; **inactivos** hasta que Lua escriba lim2).

**Tres magnitudes (no confundir):**

| Campo probe | Qué es | Quién lo usa |
| --- | --- | --- |
| `speed_limit_ms` | Límite **vigente** ahora | `effective_limit`; contención bajada (`posted_limit_mph`) |
| `dist_limit_cm` + `next_limit_ms` | **Próximo cambio** adelante | Objetivo principal `limit_brake` / P1 |
| `speed_limits_ahead[]` | Cola (hoy 0–1 entradas desde probe) | `coordinator._resolve_limit_objective`; fase 5 si hace falta cola |

**Intento `NextSpeedLimits[]` en Lua:** el array existe (`foreach_n=2`), pero cada ítem es
`UScriptStruct` → `d=nil`, `ms=nil` en el tick. No salió nada útil; **revertido** a 1 escalar.
Ver [DRIVERAID_API.md — lim2](../reference/DRIVERAID_API.md#investigar-2º-límite-lim2).

**Cola HTTP `nextSpeedLimits[]`:** sí hay muchos carteles en el JSON, pero el **2.º elemento no es
“el siguiente mph”** — suele ser **otro cartel al mismo mph** (55 a ~50 m). El primer **cambio de
cifra** (p. ej. 45) puede ir **kilómetros** más adelante. No confundir “dos filas en el array” con
90→75 juntos. Con **F7 ON**, `tsw_telemetry_source` hace `skip_limit_keys` al merge HTTP: la cola
**no** alimenta P1; solo el escalar del probe (+ odometría C.3a si el cm va plano).

**Odometría C.3a:** si `dist_limit_cm` no baja pero el tren avanza (`_probe_limit_flat`), Python
resta metros con velocidad entre refrescos del juego — mismo patrón que estaciones HTTP (§4.4).

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | 1 escalar probe → P1 @ ~20 Hz | — |
| **Parcial** | C.3a si cm plano; `speed_limit_ms` para límite vigente | — |
| **Aplazado** | `lim2` Lua; cola HTTP como fuente P1 | F9 o tramo que demuestre hueco |
| **Fuera v2** | HTTP `nextSpeedLimits[]` en tick de frenado | Lento; cola ≠ cadena mph |

| Alternativa | Pros | Contras |
| --- | --- | --- |
| **Un cartel en probe (elegida)** | Estable ~20 Hz; P1 ya frena con `v²/2a` + ese par | No ves la cola completa |
| Cola HTTP | Floats legibles; fallback **sin** F7 | Lento; cola ≠ cadena mph; no en P1 con probe ON |
| `lim2` en GetData | Mismo Hz que lim1 | Lua no lee el TArray; aparcado hasta F9/HTTP puntual |

**v2:** seguir con **un cartel** + señal roja (§3) + techo si vas tarde (ETA, fase 5). Reabrir lim2
solo si in-game un tramo demuestra que el escalar no basta — no por teoría 90→75.

##### Dudas (cerrar con sesión in-game, no con dump HTTP)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿Cuándo falla **un** cartel? | 90→75 si el 2.º cambio es visible antes de pasar el 1.º | Tramo Cross-City + log `next_lim` / `lim2=—` |
| ¿`next_limit` siempre es reducción? | Subida o repetidor → P1 podría frenar de más | Anotar si `next_limit_ms` ≥ `speed_limit_ms` |
| ¿Cartel vs andén vs rojo? | Tres objetivos de vía compiten | §3 / §4.4; cartel = `LIMIT`, no sustituye estación/señal |
| ¿Reabrir lim2 vía F9 en ítem TArray? | Única vía Lua sin HTTP | Ticket aparte; no bloquea v2 |

##### Criterio de cierre §4.3

- **Tests:** `test_telemetry_source.py` — odometría cartel, probe congelado en pausa, resync por
  `seq` (`test_planning_distance_dead_reckoning`, `test_stale_probe_holds_distance`,
  `test_frozen_probe_seq_holds_distance`, `test_probe_planning_interpolates_between_game_updates`).
- **In-game (E1 / Cross-City 323, F7 ON):** sesión 10+ min; `lim2=—` estable;
  `p1tgt=SPEED_LIMIT` en carteles conocidos (p. ej. 55) con `p1d` coherente (baja; no fija
  @2496 m).
- **C.3a:** en marcha, `next_lim`/`dist` bajan o `probe_stale=Y` con dist interpolada; en
  **pausa**, distancia no avanza (`probe_motion_frozen` / `frozen`); `gap` no absurdo vs andén
  (ver [CANAL_CONTROL.md § C.3a](../CANAL_CONTROL.md#odometría-cartel-c3a)).
- **Sin cola HTTP en P1** con F7 ON — solo escalar probe (+ C.3a).

**Reapertura lim2 (no es cierre §4.3):** sesión documentada donde un cartel no basta (tramo
90→75 u otro); no por dump HTTP.

Validación: tarjeta **E1** · [CANAL_CONTROL.md § C.3a](../CANAL_CONTROL.md#odometría-cartel-c3a).

### 4.4 Estaciones / andén (tablón)

Referencia código: `tsw6/telemetry/tsw_telemetry_source.py` (`_poll_driver_aid_planning`,
`_tick_station_distances`, `PLANNING_MIN_INTERVAL_S` ≈ 2 s), `driver_aid_parser.py`
(`parse_track_data_stations`, `resolve_display_next_stop`), `tsw6/braking/v2/station_plan.py`,
`speed_decider.py` (`_p1_station_target`, `_p1_station_distance`), `hud_timetable.py`
(`tsw_hud.db`, `car_stop_signs`).

**Tablón vs fin de andén:** en la API, `markers[].distanceToStationCM` es distancia al **fin de
plataforma** (marker `Platform`), no al **tablón** `car_stop` del HUD. Hoy P1 frena con esa distancia
HTTP + odometría Python. El tablón fino (`car_stop_signs` en `tsw_hud.db`) es mejora **C2** — ver
[DRIVERAID_API.md](../reference/DRIVERAID_API.md) TrackData · [HUD_TIMETABLE.md](../v1/HUD_TIMETABLE.md).

**Hoy:** la distancia al andén **no va por Lua** — va por **HTTP** (~2 s, hilo en background):

1. `DriverAid.TrackData` → `markers[].distanceToStationCM` (paradas programadas).
2. Filtro `tsw_hud.db` (`filter_stations_by_stop_names`, `hud_geo` / `car_stop_signs` si el marker
   es de la dirección mala — detalle §4.6).
3. Entre polls HTTP, Python **resta** metros con `v×dt` (`_tick_station_distances`) — no es GPS ni
   `odo_m` del probe (aún).

El probe **sí** manda `odo_m` (~20 Hz) y puertas (`doors_telem` / `doors_dmi`); **no**
`station_dist_cm`. **Sin OCR** (Dastsc).

**Tres capas (no confundir):**

| Capa | Qué es | Quién lo usa |
| --- | --- | --- |
| `stations[].distance_m` (HTTP) | Lista de paradas; refresco ~2 s + `v×dt` entre medias | `resolve_display_next_stop`, GUI |
| FSM + `_p1_station_*` | Andén **activo** en APPROACHING (no el `next_stop` ya saltado) | P1 `station_plan` / coordinator |
| `car_stop_signs` (HUD DB) | Coordenadas tablón | Match horario; **P1 fino pendiente C2** |

**Intento `markers[]` en Lua cada tick:** mismo riesgo que lim2 (TArray / `UScriptStruct`). No en
v2 salvo F9 con escalar legible.

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | HTTP markers + `v×dt` + filtro HUD + FSM puertas (Lua/DMI) | — |
| **Parcial** | P1 usa fin de plataforma, no tablón; `odo_m` no ancla estaciones | C2 |
| **Aplazado** | `station_dist_cm` en GetData (Lua) | F9 frente a andén; después de C1 |
| **Investigar (C2)** | Ancla HTTP + Δ`odo_m` probe (como C.3a en carteles) | Medir si ~2 s + `v×dt` no basta |
| **Fuera v2** | HTTP cada tick; OCR tablón; `markers[]` TArray en Lua sin F9 | Lento / TSC / hitch |

| Alternativa | Pros | Contras |
| --- | --- | --- |
| **HTTP markers + odometría Python (elegida)** | Ya funciona; no carga probe | ~2 s refresco; fin de plataforma ≠ tablón |
| `station_dist_cm` en GetData (Lua) | Mismo Hz que límites | ¿Existe escalar en `GetDriverAidData`? F9 |
| Híbrido `odo_m` + ancla HTTP | Más precisión entre polls HTTP | Hoy solo `v×dt`; Δ`odo_m` = C2 |
| GPS / coordenadas mundo | `distanceToStation` {x,y} en HTTP | Actor pos en Lua incierto |
| OCR (Dastsc) | Tablón visual | No — TSC |

**v2:** seguir HTTP + resta. **C2** después de **C1** (señales): F9 en andén — ¿existe
`distanceToNextStation` / `distanceToStationCM` como **número** en el struct que ya lee Lua? Si sí →
`station_dist_cm` en GetData. Si no → ancla HTTP + Δ`odo_m`. Sentido / HUD invertido: §4.6 (no
duplicar reglas aquí).

##### Dudas (cerrar con sesión C2 / Cross-City, no solo dump HTTP)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿Fin de plataforma basta para P1? | Parada corta vs tablón desplazado | Sesión andén conocido; comparar con `car_stop_signs` |
| ¿`v×dt` vs Δ`odo_m`? | Deriva en pendiente / velocidad errática | Log dist estación vs `odo_m` en tramo largo |
| ¿Marker de la vía contraria? | Sutton / Four Oaks | `hud_geo` + `stop_names` (§4.6); no “más cercano” |
| ¿Escalar andén en Lua al tick? | Misma pregunta que lim2 | F9 en APPROACHING; no TArray a ciegas |

##### Criterio de cierre §4.4

- **Tests:** `test_station_odom_skips_when_probe_age_stale`; `test_speed_decider` (FSM no salta
  `next_stop`); `test_brake_station` / `test_station_fsm`.
- **In-game (Cross-City 323):** FSM llega a STOPPED en paradas del horario; P1 `p1tgt=STATION` con
  distancia coherente en APPROACHING; puertas vía Lua/DMI (sin OCR).
- **HTTP:** refresh ~2 s sin bloquear tick; entre polls `stations[].distance_m` baja con marcha;
  en pausa / probe stale no avanza (`probe_motion_frozen` / `telemetry_age_ms`).
- **Sin regresión** filtro HUD (parada correcta del servicio, no vía contraria — §4.6).

**Reapertura C2 (no es cierre §4.4):** sesión donde fin de plataforma + `v×dt` falla el tablón;
entonces F9 Lua o ancla `odo_m`.

Validación: tarjeta **C2** (tras C1) · [DRIVERAID_API.md](../reference/DRIVERAID_API.md) TrackData ·
[HUD_TIMETABLE.md](../v1/HUD_TIMETABLE.md).

### 4.5 Semáforos

**Diseño completo:** [§3](#3-semáforos-diseño-v2-no-apéndice) (solo rojo, S-Lua, D3/D8 cerrados).
Aquí: **restricción de canal** y **hueco en código** — el plan ya está; falta cablear C1.

Referencia código: `mods/TelemetryProbeMod/Scripts/main.lua` (pendiente `extract_signal_red`),
`tsw6/braking/v2/objectives.py` (`evaluate_signal_brake` stub, `is_red_signal_aspect`),
`policy.py`, `coordinator.py` (emergencia `SIGNAL`).

**Dos capas (no confundir):**

| Capa | Estado | Notas |
| --- | --- | --- |
| Probe GetData | ❌ | Sin `signal_red` / `signal_dist_cm` (presupuesto §4.1: +2 escalares) |
| Parser / `TrainState` / decider | ❌ | No cableado desde GetData |
| P1 emergencia | ✅ | Dist + aspecto rojo → `check_p1_emergency` (`test_signal_emergency_red_aspect`) |
| P1 plan gradual | ❌ | `evaluate_signal_brake` stub — sin candidato `SIGNAL` en cola normal |
| Policy prioridad | ✅ | `should_prefer_signal_over_limit`, `signal_behind_station` (~50 m) |

La API HTTP (`distanceToSignal`, `signalAspectClass`) **existe** pero **no** es canal de tick (D3).
El hueco operativo no es “falta de diseño” sino **probe → P1**.

**Restricción v2:** no HTTP en tick; no `nextSignals[]` en Lua (mismo riesgo TArray que lim2, §4.3);
ámbar/verde fuera del autopilot (conductor, D8). SPAD permitido por escenario: aplazado (§3).

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **Elegido** | S-Lua: `signal_red=1` + `signal_dist_cm` solo con rojo adelante | F9 + `extract_signal_red` |
| **Parcial** | Emergencia + policy en coordinator | `evaluate_signal_brake` + telemetría |
| **Fuera v2** | HTTP tick; ámbar/verde; cola `nextSignals[]` | §3, D3, D8 |
| **Aplazado** | Rojo con permiso de escenario (pasar en rojo) | Sesión C1 si aparece caso |

| Alternativa | Estado |
| --- | --- |
| **S-Lua — 2 claves GetData (elegida)** | §3 |
| S-A HTTP DriverAid en tick | Descartada (D3) |
| S-D Ignorar señales | No es v2 |

Dudas de producto y mapeo Stop/DANGER: ver **§3** (no duplicar aquí).

##### Criterio de cierre §4.5

Igual que **§3**, más checklist de cableado:

- `extract_signal_red` en probe; claves solo si rojo y `dist_cm > 0`.
- Parser GetData → `TrainState` → `speed_decider` → coordinator.
- `evaluate_signal_brake` deja de ser stub; tests fixture `signal_red=1` (D7).
- Cross-City 323: rojo a distancia conocida → P1 frena (plan o emergencia); GetData ~20 Hz sin freeze.

Validación: tarjeta **C1** · §3 · [DRIVERAID_API.md](../reference/DRIVERAID_API.md) señales.

### 4.6 HUD invertido (pasajeros, p. ej. 323)

**Ámbito:** solo **pasajeros** con `tsw_hud.db` / servicio HUD (323 Cross-City). **Freight:** N/A
(sin horario de paradas; ver [FREIGHT_NA.md](../v1/FREIGHT_NA.md)).

**Postura v2:** en Cross-City **funciona bien con lo que hay** — reglas P1 + filtro planning. No
abrir rediseño ni `pace` nuevo; **documentar** casos y sesiones. Si un tramo futuro no encaja, se
aborda entonces (sesión + patrón claro), no por teoría.

Referencia código: `tsw6/braking/v2/policy.py` (`station_waits_for_approach_limit`,
`next_sign_is_reduction_beyond_station`, `should_defer_station_brake`, `skip_defer`),
`hud_timetable.py` (`merge_schedule_stations`, `source: hud_geo`),
`driver_aid_parser.py` (`filter_stations_by_stop_names`), `governor_station.py` / FSM.
Detalle casos Four Oaks / Sutton: [BRAKE_V2.md](../v1/BRAKE_V2.md) · [HUD_TIMETABLE.md](../v1/HUD_TIMETABLE.md).

**Dos fenómenos (no uno solo):**

| Fenómeno | Síntoma (ejemplo) | Capa que responde hoy |
| --- | --- | --- |
| **Distancias invertidas** | Andén HUD más cerca que cartel 55 (Four Oaks) | P1: `station_waits`, `skip_defer`, `next_sign_is_reduction_beyond_station` |
| **Lista de paradas mala** | Sutton antes que Four Oaks en `markers[]` | Planning: `stop_names` del horario, `hud_geo`, `filter_stations_by_stop_names` |

**Planning (sentido del servicio):**

- **`tsw_hud.db`** → orden de paradas (`2R17`, `stop_names`) = hacia dónde vamos.
- **`PlayerInfo.geoLocation`** (HTTP) + `car_stop_signs` → `hud_geo` si TrackData trae marker de la
  dirección mala.
- **`filter_stations_by_stop_names`** → solo andenes del horario, no la vía contraria.
- Entre polls HTTP, `_tick_station_distances` resta `v×dt` (§4.4). **`odo_m` no valida sentido**
  hoy — solo documentar si en sesión hace falta más adelante.

**Cabina / reversa en Lua:** no cablear en v2 inmediato; F9 en segundo plano.

**No hacer:** “ganar el más cercano” sin reglas (Sutton/Four Oaks otra vez); sustituir
`station_waits` por un `pace` genérico.

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | `station_waits` / `skip_defer` + filtro HUD/geo | — |
| **Suficiente por ahora** | Cross-City 323 con reglas actuales | Ninguno — no ticket activo |
| **Solo documentar** | Sesiones donde TrackData miente; orden vs horario | Cuando aparezca caso nuevo |
| **Aplazado** | `odo_m` vs orden horario; cabina explícita en Lua | Sin patrón que lo exija aún |
| **Fuera v2** | “Más cercano” sin filtro; `pace` nuevo | — |

| Alternativa | Estado |
| --- | --- |
| **Reglas TSW actuales + HUD DB (elegida)** | ✅ |
| Refinar con Δ`odo_m` o cabina Lua | Documentar; abordar si falla in-game |
| Ignorar horario y usar distancia cruda | No |

##### Dudas (anotar en sesión; no bloquean v2)

| Duda | Por qué importa | Cuándo mirarla |
| --- | --- | --- |
| ¿`hud_geo` basta sin marker TrackData? | Solo haversine al tablón | Si próxima parada sale mal en log |
| ¿Caso no cubierto por `station_waits`? | Nueva regla P1 | Tramo documentado que falle con policy actual |
| ¿Orden `markers[]` vs horario? | Filtro insuficiente | Sutton/Four Oaks u otra ruta |
| ¿Cabina / reversa? | Sentido explícito | F9; no prioridad v2 |

##### Criterio de cierre §4.6

- **Hoy:** comportamiento Cross-City 323 **aceptable** con stack actual — no hay deuda de código
  obligatoria en esta sección.
- **Tests:** `test_brake_policy` (waits/defer); C.2 Four Oaks en `test_speed_decider` /
  `test_station_fsm` verdes.
- **Documentación:** casos Four Oaks / Sutton en [BRAKE_V2.md](../v1/BRAKE_V2.md); esta sección + §4.4
  como referencia de sentido.
- **Reapertura:** solo tras sesión donde falle algo **no** explicado por las reglas de arriba; entonces
  decidir planning vs P1 vs cabina — no anticipar.

Validación: fase 3 (servicio pasajeros) · sin tarjeta C dedicada hasta incidente documentado.

### 4.7 Proceso Python + GUI

**Postura v2:** para 323 **funciona hoy** (hilo de control + snapshot). El refactor `agent/` (D1) es
**cuando toque la ejecución**, no urgencia in-game — misma API mental (`tick` / `step` → snapshot).
Sidecar (dos procesos) solo si medición lo pide; no por defecto.

Referencia código: `tsw6/autopilot/autopilot_gui.py` (`_control_loop`, `_UI_MS=50`),
`autopilot_core.py` (`AutopilotEngine.tick`, `AutopilotSnapshot`),
`tsw6/telemetry/control_channel.py` (`TelemetryReader`, `AsyncCommandWriter`),
`tsw_autopilot.py` (`--console`). Debates: **D1** (agente nuevo), **D4** (frontera sin tkinter).

**Tres capas (hoy vs objetivo):**

| Capa | Hoy | Objetivo v2 (D1) |
| --- | --- | --- |
| Lectura GetData | `TelemetryReader` ~20 Hz (hilo aparte) | Igual |
| Bucle decisión | `AutopilotEngine.tick()` ~20 Hz | `agent.step()` — mismo contrato |
| GUI tkinter | Hilo control + pintado ~20 Hz (`_UI_MS=50`) | Visor + toggles → **config**; sin P1/policy |

**Hoy:** `autopilot_gui.py` lanza un **hilo** que llama `engine.tick()` (`_LOOP_HZ = 20`) y la ventana
refresca el último `AutopilotSnapshot` cada **~50 ms** (~20 Hz). Motor, FSM y P1 siguen en
`autopilot_core`; la GUI también cambia flags (learn, holgura, pausa) vía métodos del engine — en v2
eso pasa a ser solo **config del agente**, sin importar `policy` ni coordinator.

**v2 (elegido):** dos roles en **un proceso**:

```text
  Agente (bucle ~20 Hz)              GUI (visor, ~20 Hz pintado)
  ─────────────────────              ───────────────────────────
  Leer GetData (TelemetryReader)     Leer snapshot (copia bajo lock)
  TrainState → P1 → IPC              Mostrar: vel, lim, andén, llegada, P1, ack
  Learner (EMA)                      Toggles: ON/OFF, holgura, pausa → config
  NO tkinter                         NO decide freno ni escribe SendCommand
```

| Pieza | Hace | No hace |
| --- | --- | --- |
| **Agente** | Telemetría, física, objetivos, mandos | Pintar ventanas |
| **GUI** | Datos útiles para el conductor / depurar | `v²/2a`, policy, cluster |

**Por qué:** el tick no depende del pintado normal (hilo aparte). Un `messagebox` de error **para**
el bucle de control — aceptable. Misma filosofía que Lua = solo I/O en el probe.

`--console` (`tsw_autopilot.py`) usa el **mismo** `tick()` que la GUI (tests, logs sin ventana).

##### Perfil conductor (GUI) — documentado, sin ticket de código aún

Uso real: **comprobar telemetría** (velocidad, límite vía) y **qué hace o dice el autopilot**; el
detalle fino sigue en `logs/autopilot_*.log`, no en pantalla.

| Zona GUI | Mantener / cambiar (cuando toque GUI) |
| --- | --- |
| **Siempre visible** | Velocidad, límite vía, probe F7, Hz/`age`, barra **Acción** (mando + fase) |
| **Acción** (abajo) | Añadir **plan P1 real** (`p1tgt`, distancia, objetivo LIMIT/STATION/SIGNAL) desde snapshot — hoy solo en log |
| **Estado** | Próx. cartel, FSM, puertas; **quitar** fila «Límite efectivo» (ver abajo) |
| **Planning** | 2–3 **siguientes** paradas del horario (dist + llegada/salida); cartel ya cubierto en Estado |
| **Depuración** | **Quitar** pestaña — log en archivo basta |
| **Aprendizaje** | Dejar si se usa el toggle learn; no es núcleo de vigilancia |

**`effective_limit` (límite efectivo):**

- En **motor P1** sigue siendo necesario: techo interno (`min` vía, crucero, APPROACHING, marcador
  DMI, etc.) — ver §4.3 (`speed_limit_ms` → `effective_limit`).
- En **GUI no aporta** al conductor habitual; posible resto de crucero/aceleración temprana. **No**
  mostrar en visor (o solo en modo depuración si algún día hiciera falta). **Quitar de pestaña Estado**
  cuando se retoque la GUI — **sin** tocar `speed_decider` / coordinator.

**Modo ligero:** `--console` (cero tkinter) o, más adelante, pintado GUI a 10 Hz con control a 20 Hz.

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | Hilo control + `AutopilotSnapshot` + telem/mandos async | — |
| **Suficiente por ahora** | 323 Cross-City con GUI abierta | Ninguno — no ticket activo |
| **Aplazado (D1)** | Carpeta `agent/` + GUI solo visor | § [Orden](#orden-de-implementación) pasos 2–3 |
| **Fuera v2** | Sidecar sin medición; GUI que llama P1 directo | — |

| Alternativa | Cuándo |
| --- | --- |
| **Un proceso, agente + GUI visor (elegida)** | D1 — `agent/` con `step()` → snapshot |
| **`--console` / headless** | Sesión ligera; mismo `tick()`, sin ventana |
| GUI pintado 10 Hz (control 20 Hz) | Menos CPU UI; opcional |
| Sidecar (dos procesos) | Solo si `work_ms` / `loop_hz` empeoran con ventana abierta |

##### Dudas (no bloquean v2 in-game)

| Duda | Por qué importa | Cuándo mirarla |
| --- | --- | --- |
| ¿`agent/` o endurecer `autopilot_core`? | D1 **elegido** — carpeta nueva | Solo si ejecución paso 2 demuestra bloqueo |
| ¿Umbral para sidecar? | Evitar over-engineering | Tras medir con GUI + `autopilot_perf.bat` |
| ¿Learner en hilo de control? | CPU del tick | Solo si `work_ms` sube |

##### Criterio de cierre §4.7

- **Hoy:** `loop_hz` ≥ 18 con GUI abierta (ver [CANAL_CONTROL.md](../CANAL_CONTROL.md)); mismo
  comportamiento `--console` y GUI.
- **D1 implementado:** `agent/` con API mínima `step()` → snapshot; GUI sin imports de `braking/v2`
  (solo snapshot + config).
- **Sidecar:** solo tras sesión documentada donde tkinter sea el cuello — no anticipar.

Validación: tarjeta **D1** · § [Orden](#orden-de-implementación) pasos 2–3.

### 4.8 Layout 323 vs freight

**Diseño del paquete (G-B):** §2 (JSON, qué va / qué no). Aquí: **restricción** — no mezclar
objetivos de servicio (G-A) con rutas de escritura IPC (G-B).

Referencia código: `tsw6/learning/control_layout.py` (`detect_control_layout`: `combined` /
`freight_na`), `control_schema.py`, `freight_learner.py`, `handle_controller.py` (hoy combined UK),
plantilla `data/control_schemas/freight_na_railbridge_v3.json`. Freight operativo:
[FREIGHT_NA.md](../v1/FREIGHT_NA.md).

**Glosario:** en el plan **split** = en código **`freight_na`** (tracción + auto + dyn + ind). Unificar
vocabulario al crear `data/vehicles/<id>.json`.

**No es** “pasajero vs mercancías” como único eje. Son **dos ejes** que se combinan:

| Eje | Qué es | Ejemplo |
| --- | --- | --- |
| **Servicio** (G-A) | Objetivos: ETA, andén, puertas vs vía sin horario | 323 Cross-City vs SD40-2 |
| **Layout** (G-B) | **Cómo** se escribe el mando en UE | combined vs split (`freight_na`) |

```text
servicio (G-A) × layout (G-B) → JSON (nombres UE) + objetivos en el tick
```

| Tren | Servicio | Layout | Escritura IPC |
| --- | --- | --- | --- |
| Class **323** | Pasajeros (G-A) | **Combined** — una palanca 0–8 | `PowerBrakeHandle` |
| **SD40-2** | Freight (sin ETA) | **Split** (`freight_na`) | `Throttle`, `AutomaticBrake`, `DynamicBrake` |
| 375 / 387 | Pasajeros | Combined pero **otro nombre** | `PowerHandle` (no el string del 323) |

**Postura v2:** **323 combined basta hoy** en producción. Freight / multi-eje cuando haya **sesión
SD40 documentada** (F-D) — no cablear P1 multi-mando por teoría.

**v2:** un **paquete JSON por tren** (`layout` + nombres UE + semilla física). El agente elige
**objetivos** por servicio y **palancas** por layout. Mal: `if freight: … else: muescas 323` en un
solo sitio. Hoy: heurística `detect_control_layout` + esquema freight; **no** existe aún
`data/vehicles/<id>.json` (§2).

Probe GetData: mismos campos (`train_brake`, `loco_brake`, `dyn_brake`, …); el paquete solo decide
**qué** líneas `SendCommand` usar.

##### Estado v2

| Estado | Qué | Bloqueo |
| --- | --- | --- |
| **En producción** | 323 combined → `PowerBrakeHandle` vía `handle_controller` | — |
| **Parcial** | `freight_na` schema + `FreightLearner`; probe lee ejes split | P1 autopilot SD40 no cerrado |
| **Aplazado** | `data/vehicles/<id>.json` por `vehicle=` | Sustituye heurística layout |
| **Investigar (F-D)** | Auto + dyn en bajada; ind solo maniobras | Sesión SD40 — [FREIGHT_NA](../v1/FREIGHT_NA.md) |
| **Fuera v2** | Escritor genérico / SAFE_LEVER para todos los trenes | Crashes UE |

| Alternativa | Pros | Contras |
| --- | --- | --- |
| **`layout` + `service` separados (elegida)** | 323 y SD40 sin mezclar write paths | Dos pipelines de mandos |
| Un escritor genérico / SAFE_LEVER | Menos JSON | Mandos al UObject equivocado |

Misma física `v²/2a` (§2); learner por eje/peso en freight.

##### Dudas (cerrar con sesión o JSON, no con suposiciones)

| Duda | Por qué importa | Cómo salir |
| --- | --- | --- |
| ¿`split` vs `freight_na` en JSON? | Un solo vocabulario plan/código | Al crear primer `vehicles/*.json` |
| ¿Pasajero + layout split (raro)? | G-A y G-B independientes | Matriz 2×2; no asumir freight=split siempre |
| ¿375 `PowerHandle` en P1? | Combined con otro string IPC | Prueba EMU antes de generalizar |
| ¿Cuándo quitar `detect_control_layout` heurístico? | Paquete por `vehicle=` | Cuando JSON cubra trenes objetivo |

##### Criterio de cierre §4.8

- **323:** sin regresión combined; mandos solo por nombres del paquete/heurística actual.
- **JSON:** al menos un `data/vehicles/<id>.json` validado (323 o SD40) con tests de escritura IPC.
- **Freight:** sesión SD40 con F-D anotada antes de marcar P1 multi-eje en producción.
- **blended** / **MasterController** (Acela, DE): documentar en JSON cuando haya tren; no bloquean 323.

Validación: fase 6 (freight) · [FREIGHT_NA.md](../v1/FREIGHT_NA.md) · §2 G-B.

---

## Árbol v2

Diagrama: [esqueleto_v2.svg](../assets/esqueleto_v2.svg) · fuente [esqueleto_v2.dot](../assets/esqueleto_v2.dot) ·
HTML: [esqueleto_v2.html](../assets/esqueleto_v2.html).

**Leyenda:** `*` = pendiente cablear (C1 señal, F-B masa, `is_slipping`). Tachado mental = no entra en v2.

```text
TSW6 producto v2 — dos bandas + canales laterales
══════════════════════════════════════════════════════════════════════════════

┌─ UNA VEZ (vehicle= / arranque / cambio de tren) ────────────────────────────┐
│  vehicle= en GetData                                                         │
│    → Paquete G-B (objetivo: data/vehicles/<id>.json)                         │
│        layout: combined | freight_na (split) | blended* | MasterController*  │
│        nombres UE (323 PowerBrakeHandle · 375 PowerHandle · SD40 Throttle…) │
│        mapa muesca→eje · semilla fill_s / a inicial                          │
│    → Hoy: detect_control_layout + freight_na_railbridge_v3.json              │
│    → Learner EMA → logs/profiles/<veh>.json (a viva, no en JSON del tren)    │
│  Pasajeros G-A: match tsw_hud.db (servicio, stop_names, car_stop_signs)      │
│  Freight G-A: sin HUD por defecto · holgura OFF                              │
└──────────────────────────────────────────────────────────────────────────────┘
         │ layout/palancas (G-B)              │ horario/paradas (G-A)
         ▼                                    ▼

┌─ PROBE Lua ~20 Hz (§4.1) — SOLO I/O, sin P1, sin pairs en hot path ─────────┐
│  TelemetryProbeMod · ReceiveTick · pcall · WRITE_INTERVAL ~50 ms             │
│  ESCRIBE GetData.txt (overwrite):                                            │
│    seq speed_ms power handle_notch lever_notch                               │
│    train_brake loco_brake dyn_brake accel_ms2 gradient_pct                   │
│    speed_limit_ms dist_limit_cm next_limit_ms  (1 cartel — §4.3)             │
│    odo_m doors_telem doors_dmi brake_cyl_bar is_slipping vehicle=              │
│    signal_red signal_dist_cm  (* C1 — solo si rojo adelante)                  │
│  LEE SendCommand.txt + TSW6ApplyCommands.flag → aplica HUD → SendCommandAck  │
│  NO: nextSignals[] TArray · lim2 · markers[] · reglas de frenado              │
└──────────────────────────────────────────────────────────────────────────────┘
         │ GetData.txt                              ▲ SendCommand.txt + ack
         ▼                                            │
┌─ IPC %TEMP%\TSW6Bridge\ (§4.2) ─────────────────────────────────────────────┐
│  TelemetryReader ~20 Hz (hilo) · AsyncCommandWriter + reassert ack           │
│  Sin HTTP para mandos (D3 señales tick = Lua, no HTTP)                       │
│  SHM · sidecar: aplazado                                                     │
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ HTTP DriverAid ~2 s (hilo planning — §4.4) ────────────────────────────────┐
│  TrackData.markers → estaciones + dist (v×dt entre polls)                    │
│  PlayerInfo.geoLocation + hud_geo si marker mal                              │
│  Formación → masa total F-B (* poll 5 min — §2, ruta ClampPowerInput.Mass)    │
│  NO alimenta P1 límites si F7 ON (skip_limit_keys)                          │
└──────────────────────────────────────────────────────────────────────────────┘
         │ merge planning
         ▼
┌─ AGENTE Python ~20 Hz (D1: agent/ — hoy AutopilotEngine.tick) ────────────────┐
│  ProbeSnapshot → TrainState                                                  │
│  G-A objetivos: LIMIT | STATION | SIGNAL* (solo rojo §3)                     │
│  G-B escritura: nombres del paquete (combined vs freight_na)                 │
│  physics.py: s = v²/(2a) · gradiente probe · learner a · massFactor* HTTP      │
│  P1 coordinator:                                                             │
│    limit_brake (1 cartel + C.3a odo si cm plano)                             │
│    station_plan + FSM puertas (pasajeros)                                    │
│    evaluate_signal_brake* (stub → C1) · policy station_waits skip_defer       │
│  RELEASE/APPLY: un mando/tick · política TSW (D5)                            │
│  Holgura ETA: schedule_slack (* D9 TimeOfDay — OFF por defecto)              │
└──────────────────────────────────────────────────────────────────────────────┘
         │ AutopilotSnapshot
         ▼
┌─ GUI / --console (§4.7) — visor, no decide ─────────────────────────────────┐
│  Núcleo: velocidad · límite vía · acción/muesca · plan P1* · probe seq/Hz    │
│  Planning: 2–3 paradas (dist + arr/dep) · sin pestaña Depuración (log file)  │
│  Sin límite efectivo en pantalla (sigue en motor)                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ FUERA v2 / horizonte (no bloquean 323) ────────────────────────────────────┐
│  SHM · lim2/cola HTTP · ámbar/verde (D8) · SPAD escenario · OCR tablón       │
│  sidecar 2 procesos · tick Rust/C++ · Dynamic HUD in-game                    │
│  blended/Acela · MasterController DE · adherencia learner fase 2             │
│  ApiExplorerMod (L0) — ver PLAN_API_EXPLORER.md · laboratorio, no tick P1    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Flujo resumido (cada tick):**

```text
UE → Probe → GetData → TrainState → [G-A objetivos + G-B nombres] → physics → P1 → IPC → Probe → UE
                              ↑
                    HTTP ~2s (estaciones, masa*)
```

**Ahorro v2:** no `FindAllOf` / `pairs(driverAid)` en caliente; nombres UE en caché (paquete).

**No ahorro:** `v²/2a` cada tick (velocidad y distancias cambian).

**Añadir campo nuevo** (señal, lim2, slip): contrato GetData (D2) + F9 + tests (D7) — no un `if` suelto en Lua.

**Mapa plan → árbol:**

| § PLAN_V2 | Nodo en árbol |
| --- | --- |
| §1 G-A pasajeros | Servicio, FSM, holgura, `tsw_hud.db` |
| §1 G-B paquete | JSON layout + nombres UE |
| §2 física | `physics.py`, learner, F-B, F-D freight |
| §3 señales | `signal_red*` en probe + P1 SIGNAL |
| §4.1 probe | Lua GetData / mandos |
| §4.2 IPC | Bridge ficheros |
| §4.3 cartel | 1 escalar `dist_limit` |
| §4.4 andén | HTTP markers + `v×dt` |
| §4.5–§3 | Cableado señal (mismo nodo) |
| §4.6 HUD invertido | policy `station_waits` (dentro P1) |
| §4.7 GUI | Snapshot visor |
| §4.8 layout | G-B combined vs `freight_na` |

---

## Debates (v2 elige, no hereda)

**Estados:** `Cerrado` = no reabrir salvo evidencia nueva · `Elegido` = decisión de producto, código
pendiente · `Abierto` = falta medición o proceso · `Aplazado` = fuera del camino 323.

| ID | Tema | Estado | Detalle |
| --- | --- | --- | --- |
| **D1** | Agente nuevo `agent/` + migración por pruebas | **Elegido** | Debates, §4.7, ejecución pasos 2–3 |
| **D2** | Schema GetData versionado (señal, lim2, …) | **En curso** — contrato en [CANAL_CONTROL](../CANAL_CONTROL.md); falta C1 en probe + checklist Fase 0 | [CANAL_CONTROL](../CANAL_CONTROL.md#contrato-getdata-v2) |
| **D3** | Señales en tick: Lua vs HTTP | **Cerrado** S-Lua | §3 |
| **D4** | Agente sin GUI en el rewrite | **Elegido** | §4.7, `--console` |
| **D5** | Política RELEASE (TSW, no V4) | **Elegido** | §2, Fase 2, tests `brake_release` |
| **D6** | Layout G-B: palancas del paquete | **Elegido** | §4.8, paquete JSON |
| **D7** | Tests sin juego (fixtures GetData) | **Elegido** | Fase 0/4, `tests/` |
| **D8** | Ámbar / verde en autopilot | **Cerrado** fuera | §3 |
| **D9** | Reloj holgura: PC vs `TimeOfDay` | **Abierto** (medición) | §1, Fase 3 — holgura **OFF** hasta cerrar |

**No son debates D** (aplazados o ya cubiertos en fases): sidecar dos procesos (§4.7), SHM
(§4.2), lim2/cola HTTP (Fase 5), `detect_control_layout` → JSON (transición G-B en §4.8).

### D1 — ¿Desde 0 el agente?

| Opción | Pros | Contras |
| --- | --- | --- |
| A. Agente **nuevo** (módulo/carpeta), probe igual | Producto v2 claro; sin arrastrar `uni`/capas viejas | Hay que **reconectar** comportamiento |
| B. Refactor in-place del coordinador | Menos archivos nuevos | Sigue el lío; cada fix enreda más |
| C. Todo nuevo incluido Lua | Limpio en papel | Tiras el canal que ya funciona |

**Elegido: A con migración por pruebas** — no es “copiar pegando” ni “borrar y olvidar”:

1. **Nuevo esqueleto** (`agent/` o similar): snapshot → objetivos → un mando → IPC. GUI solo visor
   (§4.7). Probe **no** se toca salvo claves nuevas (señal, etc.).
2. **Portar por rebanadas** lo que **ya funciona** y tiene test: `physics.py`, learner, parser
   GetData, reglas TSW que validasteis (hold bajada, Four Oaks, `station_waits`) — como **módulos**
   llamados desde el agente nuevo, no copiando el coordinador entero.
3. **Reimplementar** donde el plan dice v2 distinto: un RELEASE, paquete tren, `PassengerService`,
   señales desde el diseño.
4. **Criterio de hecho:** mismo escenario pytest / Cross-City que antes; si falla, o se porta la
   regla o se documenta por qué v2 cambia.

Mal: refactor infinito del `coordinator.py` actual. Mal: wipe sin pytest ni sesión 323.

**Implementación:** pendiente — § [Orden](#orden-de-implementación) pasos 2–3.

### D2 — Schema GetData

**Problema:** añadir `signal_red`, `lim2`, etc. sin romper parser, probe ni tests en distintos
momentos.

**Elegido:** cambio **atómico** por campo — misma entrega actualiza contrato documentado, probe (si
aplica), parser Python y fixture pytest (D7). No “primero Lua y el parser otro día”.

**Criterio de cierre:** Fase 0 checklist; claves canónicas en [CANAL_CONTROL § Contrato GetData](../CANAL_CONTROL.md#contrato-getdata-v2);
proceso [D2 — añadir campo](../CANAL_CONTROL.md#d2--añadir-campo); C1 cableado + fixture.

**Detalle:** §4.1, §4.3, Fase 0.

### D3 — HTTP vs Lua para señales en tick

**Cerrado: S-Lua** (§3). El tick P1 no usa `distanceToSignal` / HTTP DriverAid. HTTP queda para
planning (~2 s): estaciones, geo, masa.

### D4 — Agente sin GUI como frontera del rewrite

**Problema:** mezclar tkinter con P1 complica tests y el tick.

**Elegido:** un proceso, dos roles — **agente** (`step()` → IPC) y **GUI visor** (snapshot + config).
`--console` usa el mismo bucle sin ventana. La GUI no importa `braking/v2` ni escribe mandos.

**Criterio de cierre:** §4.7 — GUI sin policy/coordinator; `loop_hz` ≥ 18 con ventana abierta.

**Detalle:** §4.7, ejecución paso 2.

### D5 — Política RELEASE

**Problema:** importar RELEASE de Dastsc V4 sin validar en TSW.

**Elegido:** política **TSW** — hold en bajada, banda ~0,4 m/s (o lo que validen tests/sesión 323),
un APPLY/RELEASE por tick. Reglas ya cubiertas por pytest (`test_brake_release`, coordinator).

**Criterio de cierre:** Fase 2 — misma conducción en carteles y bajada que hoy; sin copiar V4.

**Detalle:** §2, Fase 2.

### D6 — Layout G-B (palancas)

**Problema:** escribir palancas equivocadas según tren (323 combined vs SD40 split).

**Elegido:** rutas IPC salen del **paquete G-B** (`layout` + nombres UE). Lua solo aplica claves que
el contrato SendCommand permite para ese layout. Sin `pace` ni ritmo en Lua.

**Criterio de cierre:** un JSON validado (323 o SD40) + test de escritura IPC; §4.8.

**Nota:** holgura ETA es G-A (servicio), no layout — ver D9.

### D7 — Tests sin juego

**Problema:** cablear señal o lim2 solo in-game retrasa el diseño y rompe CI.

**Elegido:** fixtures GetData en `tests/` **antes** o **en el mismo PR** que el parser/probe. Escenarios
sintéticos de señal (`signal_red=1`, distancia) aunque C1 aún no esté en Lua.

**Criterio de cierre:** pytest verde sin TSW abierto; Fase 4 ítem tests; tarjeta C1 no bloqueada por
falta de fixture.

**Detalle:** Fase 0/4, § [Orden](#orden-de-implementación) pasos 4–5.

### D8 — Ámbar / verde

**Cerrado: fuera del autopilot** (§3). Solo **rojo** entra en P1. Ámbar, verde y cola
`nextSignals[]`: conductor; no debate D8 en código v2.

### D9 — Reloj de holgura ETA

**Problema:** `now` del PC vs `WorldTime` del escenario invalida holgura 15/30/60 s.

**Abierto hasta medición** en cabina (`WorldTime` vs hora llegada vs reloj PC — §1).

**Elegido por defecto:** holgura **OFF** en producción hasta cerrar D9. Si se activa sin medir, solo
como experimento documentado.

**Criterio de cierre:** Fase 3 — `schedule_slack` con `now` = escenario, o holgura sigue OFF con nota
en GUI.

**Detalle:** §1, [TIMEOFDAY_API](../reference/TIMEOFDAY_API.md), ejecución paso 8.

---

## Plan de trabajo

**Tres capas (no duplicar):**

| Capa | Qué responde | Dónde |
| --- | --- | --- |
| **Fases 0–6** | Qué capacidades debe tener el producto (comportamiento) | Abajo |
| **Transversal** | Tests, revisiones y mantenimiento **en cada entrega** | [§ Transversal](#transversal--revisión-tests-y-mantenimiento) |
| **Orden de implementación** | En qué secuencia codificar (PRs, prefijos, deltas) | [§ Orden](#orden-de-implementación) |

Las fases **no** son cronológicas 1→2→3. El orden real al codificar es la tabla numerada
(agente antes que paquete JSON; C1 en paralelo o tras esqueleto `agent/`).

Criterio de fase = comportamiento validado (pytest o sesión in-game), no solo archivos nuevos.
**Cada paso** del § Orden incluye el checklist transversal (como mínimo pytest + delta si aplica).

### Transversal — revisión, tests y mantenimiento

Corre **en paralelo** a las fases 0–6; no es una fase “al final”.

#### Tests (sin juego — D7)

| Cuándo | Qué | Comando / referencia |
| --- | --- | --- |
| Antes de cada paso | Suite relevante verde | `pytest tests/` o subconjunto del paso |
| Tras tocar GetData / probe | Parser + fixtures | `test_tsw_ue4ss_reader`, `test_telemetry_source`, fixture `tests/` (D7) |
| Tras tocar IPC / mandos | Canal async | `test_control_channel`, `test_tsw_ipc_bus`, `test_tsw_monitor_ipc` |
| Tras tocar P1 / policy | Frenado v2 | `test_brake_*`, `test_speed_decider`, `test_station_fsm` |
| Tras `agent/` | Regresión 323 | Mismos tests que hoy en Four Oaks / carteles (paso 3) |
| Campo nuevo en contrato | Atómico con código | Fixture GetData + parser + probe en **mismo PR** (D2) |

**Prefacio P2:** `pytest` verde en `braking/v2/` + telemetría antes de marcar un paso hecho.

#### Revisiones (documentación y diseño)

| Cuándo | Qué |
| --- | --- |
| Cierre de paso | ¿El código contradice algún debate **cerrado** (D3, D8)? → delta o corregir código |
| Cierre de paso | ¿[CANAL_CONTROL](../CANAL_CONTROL.md) sigue al probe/parser? |
| Cambio de comportamiento | Fila en tabla **Deltas** (§ Orden); no reescribir debates sin motivo |
| Repaso trimestral / tras fase | §1–4 vs código: criterios de cierre de cada § |
| Docs tocados | Markdown coherente (`scripts/tools/fix_markdownlint.py` si hace falta) |
| Árbol v2 | `esqueleto_v2.dot` / `.svg` si cambia arquitectura |

#### Mantenimiento (repo y canal)

| Cuándo | Qué |
| --- | --- |
| Cambio en `main.lua` | `install_ue4ss_probe.bat` · anotar `PROBE_BUILD` · sesión corta `test-ipc` |
| Sospecha de jitter | `autopilot_perf.bat`, `lua_probe_perf.bat` — `loop_hz` ≥ 18 con GUI |
| Tras sesión in-game | Revisar `logs/autopilot_*.log` + `SESIÓN CANAL` si tocó mandos |
| Entrada del proyecto | `.bat` raíz y `tsw_autopilot.py --console` siguen arrancando |
| Dependencias | `requirements-dev.txt` / pyright sin warnings nuevos en módulos tocados |
| Histórico | Docs sustituidos → `archive/docs/` (no editar allí) |

**No es mantenimiento v2:** reescribir `coordinator.py` sin paso D1; refactors cosméticos sin test.

### Fase 0 — Contrato I/O

Contrato canónico: [CANAL_CONTROL.md § GetData v2](../CANAL_CONTROL.md#contrato-getdata-v2).

- [x] Claves GetData canónicas (tabla en CANAL_CONTROL).
- [x] Huecos documentados: `signal_red` / `signal_dist_cm` (C1), lim2 (parser sí, Lua no).
- [ ] C1 implementado en probe + fixture pytest (D7).
- [ ] Auditoría: Lua sin ritmo/cluster en hot path.

**Validación:** `test_tsw_ue4ss_reader`, `test_control_schema`; fixture GetData con campos C1;
`test-ipc` PASS tras cambio Lua.

### Fase 1 — Contratos de producto

- [ ] Contrato **paquete de tren** G-B (layout + nombres UE + semilla; learner aparte).
- [ ] `PassengerService` G-A (sin enum stopping/express).
- [ ] Holgura ETA (D9: OFF hasta medición, o `now` = escenario).
- [ ] Auditoría corta `tsw_hud.db`: match servicio OK o lista de fallos.

**Validación:** `test_control_layout`, `test_hud_timetable`; test escritura IPC por layout;
revisión JSON vs `detect_control_layout` hoy.

### Fase 2 — Agente + límites + RELEASE

**Hoy en `autopilot_core` (323):** bajada y carteles con una política de soltar — lecciones 323 sí;
estructura Dastsc no obligatoria.

**Pendiente D1:** carpeta `agent/` + GUI visor; portar módulos con test (physics, learner, parser);
mismo comportamiento Cross-City / Four Oaks.

**Validación:** `test_physics`, `test_online_learner`, `test_brake_release`, `test_brake_coordinator`,
`test_brake_v2`; `--console` y GUI mismo snapshot; `loop_hz` ≥ 18 (§4.7).

### Fase 3 — Servicio pasajeros

- [ ] Un horizonte de andén.
- [ ] FSM puertas como implementación del perfil genérico (no 323 en núcleo).
- [ ] HUD invertido donde el HUD mienta — `station_waits` en policy (§4.6), no `pace`.

**Validación:** `test_station_fsm`, `test_brake_station`, `test_speed_decider`; sesión Cross-City
andén conocido; revisar §4.6 vs log.

### Fase 4 — Señales rojas (mínimo viable)

Diseño hecho (§3, policy, coordinator). Cableado pendiente tarjeta **C1**.

- [ ] `extract_signal_red` en probe → `signal_red` + `signal_dist_cm` (S-Lua).
- [ ] Quitar stub `evaluate_signal_brake`; rojo → plan a 0 o emergencia.
- [ ] Fixtures GetData + dumps DRIVERAID (D7).

**Validación:** `test_signal_emergency_red_aspect` (o equivalente); fixture `signal_red=1`;
sesión **C1** in-game; §3 criterios de cierre.

### Fase 5 — Techo de vía + cola de límites

Solo si ETA/holgura no basta sin inventar tipo de tren.

- [ ] Tarde → techo + señales (sale del slack).
- [ ] `lim2` / cola solo si un cartel no cubre el tramo (evidencia in-game).

**Validación:** `test_telemetry_source` (cartel, odo C.3a); log con tramo que **demuestre** hueco;
no activar lim2 por dump HTTP solo.

### Fase 6 — Física selectiva + freight

- [x] Masa F-B — ruta validada lab `213100Z` (§2); pendiente cablear Python poll + `physics.py` (paso **9**).
- [ ] Patinaje **9b-a** — probe `is_slipping` (+ opcional `traction_locked`); log sin handler.
- [ ] Patinaje **9b-b** — matriz S1–S4 en 323; luego handler P1.
- [ ] Freight: selector de eje ([FREIGHT_NA](../v1/FREIGHT_NA.md), sesión F-D); no un 323 con tres palancas.

**Validación:** `test_freight_learner`, `test_learn_monitor_freight`; sesión SD40 documentada;
revisión [FREIGHT_NA](../v1/FREIGHT_NA.md) vs comportamiento.

---

## Orden de implementación

Al codificar: **un paso** por entrega; prefacio cumplido; checklist [transversal](#transversal--revisión-tests-y-mantenimiento);
matiz → tabla **Deltas** (no reescribir debates salvo cambio de producto).

### Prefacios globales

| # | Requisito | Estado |
| --- | --- | --- |
| P0 | **D1** decidido; implementación `agent/` | ✅ decisión · ⬜ código |
| P1 | Probe estable ~20 Hz (§4.1) | ✅ |
| P2 | pytest verde en ámbito del paso (+ suite completa antes de merge) | ⬜ verificar |
| P3 | Plan repasado (§1–4, debates, árbol) | ✅ |
| P4 | Revisión doc: CANAL_CONTROL / delta si el paso tocó contrato | ⬜ por paso |

### Pasos (orden canónico)

Cada fila: código + **tests** + **revisión** (P2, P4) + fila Deltas si hubo matiz.

| # | Entrega | Prefacio | Fase | Validación mínima |
| --- | --- | --- | --- | --- |
| 1 | Contrato GetData en [CANAL_CONTROL](../CANAL_CONTROL.md) | P1, P3 | 0 | ✅ doc · ⬜ C1 probe + fixture |
| 2 | Esqueleto `agent/` (snapshot → un mando → IPC), GUI visor | D1, P0 | 2 | `test_control_channel`; `--console` |
| 3 | Portar `physics.py`, learner, parser GetData al agente | P2 | 2 | Four Oaks / carteles pytest |
| 4 | `extract_signal_red` + fixture pytest | Sesión **C1**, P2 | 4 | `signal_red=1` fixture |
| 5 | Quitar stub `evaluate_signal_brake`; rojo en P1 | Paso 4, P2 | 4 | emergencia rojo + C1 in-game |
| 6 | Paquete JSON `data/vehicles/` + caché palancas G-B | 323 validado, P2 | 1 | `test_control_layout` + IPC |
| 7 | `PassengerService` genérico + FSM puertas | Paso 6, P2 | 3 | `test_station_fsm` + andén |
| 8 | TimeOfDay → holgura (o OFF documentado) | D9 medición, P4 | 1, 3 | nota en GUI + §1 |
| 9 | Masa F-B (HTTP `ClampPowerInput.Mass`) | Evidencia `213100Z`, P2 | 6 | log `mass_kg` + `mass_factor` |
| 9b-a | Probe `is_slipping` (+ `traction_locked` opc.) | Evidencia `213100Z`, P2 | 6 | GetData en partida; **sin** cambio mando |
| 9b-b | Handler slip P1 (matriz estudio) | Sesiones S1–S4 323 | 6 | pytest + in-game mojado/hojas |
| 10 | Freight `brake_selector` + SD40 | Sesión **F-D**, P2 | 6 | [FREIGHT_NA](../v1/FREIGHT_NA.md) |

**Paralelo (laboratorio):** tarjeta **L0** — [PLAN_API_EXPLORER.md](PLAN_API_EXPLORER.md) (`ApiExplorerMod`);
desbloquea C1/G-B sin hinchar el probe. No sustituye pasos 1–10.

**Sesión actual:** objetivo = arrancar v2 · **siguiente** = paso 2 (`agent/`) o terminar paso 1 (C1
probe) · bloqueos = ninguno de producto.

### Deltas (cambios al codificar)

| Fecha | Paso | Plan decía | Hicimos / nota |
| --- | --- | --- | --- |
| 2026-08-31 | doc | 9 / 9b-a cablear | Contrato + stubs parser/constants; sin comportamiento en partida |

---

## Prioridad (resumen)

1. **Pasos 2–3** — `agent/` + portar lo que ya tiene test (D1); P2 verde.
2. **Pasos 4–5 / C1** — señal roja; fixture + sesión in-game.
3. **Pasos 6–7** — paquete tren + servicio pasajeros; revisión `tsw_hud.db` si falla match.
4. **Pasos 8–10** — holgura, masa, freight solo con evidencia.
5. **Siempre** — checklist transversal al cerrar cada paso (pytest, delta, probe si Lua).

---

## Qué no es este plan

- No es “hacer TSW = Dastsc V4”.
- No obliga a no tocar `tsw6/braking`.
- Sí obliga a **no** meter P1 en Lua.

**Siguiente código:** paso 2 (`agent/`) o cerrar paso 1 (C1 en probe). Tarjetas in-game: **C1**
señales · **C2** andén. Canal: [CANAL_CONTROL](../CANAL_CONTROL.md) · probe:
[PENDIENTE_DYNAMICHUD](../v1/PENDIENTE_DYNAMICHUD.md).
