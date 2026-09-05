# Mantenimiento v2 — tests, depuración y cierre de entregas

**Plan maestro:** [PLAN_V2.md](PLAN_V2.md) · **Dónde codificar:** [CODIGO_V2.md](CODIGO_V2.md) ·
**Contrato:** [CANAL_CONTROL.md](../CANAL_CONTROL.md)

Checklist operativo que acompaña **cada paso** del § Orden en [PLAN_V2](PLAN_V2.md#orden-de-implementación).
Las **fases** (0–6, capacidades del producto) están en el mismo doc: [§ Fases 0–6](PLAN_V2.md#fase-0--contrato-io).

**Estado rápido (2026-09-04):** paso **3** en curso — cartel P1 en `V2/tsw6v2/` (**79** tests V2);
`physics` / `plan` / `command` / `limit_brake` en `tsw6/braking/v2/` son **shims** → V2 (sin lógica duplicada).
Autopilot v1 (`iniciar_autopilot.bat`) usa el mismo motor cartel vía esos shims.

No sustituye el plan de producto; lo hace ejecutable.

---

## Cuándo usar este documento

| Momento | Sección |
| --- | --- |
| Antes de abrir PR | [Checklist cierre](#checklist-cierre-de-paso) · [Tests](#tests) |
| Tras cambiar `main.lua` | [Probe Lua](#probe-lua) |
| Autopilot lento / mandos raros | [Depuración canal](#depuración-canal-ipc--getdata) |
| Tras sesión in-game | [Sesión juego](#sesión-in-game) |
| Antes de PR / diff inflado | [Depurar líneas y duplicados](#depurar-líneas-y-líneas-duplicadas) |
| Dudas lab vs probe | [Lab vs producción](#lab-vs-producción) |
| Idea mejora sin paso claro | [Sugerencias](#sugerencias-y-mejoras) |
| Repaso periódico | [Trimestral](#repaso-trimestral) |

---

## Checklist cierre de paso

Marcar un paso del [§ Orden](PLAN_V2.md#orden-de-implementación) como hecho solo si:

- [ ] **Código** cumple el alcance del paso (no mezcla pasos siguientes).
- [ ] **pytest** verde en el subconjunto del paso y, si tocaste contrato/probe, suite completa.
- [ ] **CANAL_CONTROL** alineado si cambió GetData o IPC.
- [ ] **Delta** en PLAN_V2 si cambió comportamiento o decisión cerrada (D3, D8, F-B, …).
- [ ] **Probe** (si Lua): `PROBE_BUILD` nuevo · `install_ue4ss_probe.bat` · smoke `test-ipc` o GUI.
- [ ] **Limpieza** en archivos tocados: diff mínimo · sin `print`/depuración temporal · sin líneas duplicadas (ver abajo).
- [ ] **Docs** tocados pasan markdownlint (ver abajo).
- [ ] **Prefacios** del paso cumplidos (P0–P4 en PLAN_V2).

**Prefacio P2 (suite):** referencia actual — `python -m pytest tests/ -q` (objetivo: 0 fallos antes
de merge).

---

## Tests

### Comandos habituales

```bat
python -m pytest V2/tests/ -q
python -m pytest tests/ -q
```

### Matriz por área tocada

| Si tocaste… | Ejecuta como mínimo |
| --- | --- |
| GetData / parser | `test_tsw_ue4ss_reader`, `test_telemetry_source`, `test_driver_aid_parser` |
| Probe / snapshot | fixture en `tests/fixtures/` + tests anteriores |
| IPC / mandos (contrato) | `test_control_channel`, `test_tsw_ipc_bus` |
| **`V2/tsw6v2/`** | **`V2/tests/`** (criterio producto) |
| Monitor CLI (v1, delega v2) | `tests/test_tsw_monitor_ipc` (solo parse args) |
| P1 coordinator (v1, shims V2) | `test_brake_coordinator`, `test_brake_release` (cartel = V2) |
| P1 policy/estación (solo v1) | `test_brake_policy`, `test_brake_station` |
| Paquete tren G-B | `test_control_layout`, `test_vehicles_json_from_lab`, `test_compare_lab_controls` |
| Lab / correlator | `test_api_correlator`, `test_lab_serialize`, `test_summarize_hud_amps` |
| Campo nuevo D2 | **mismo PR:** Lua + parser + `ProbeSnapshot` + fixture línea GetData |

### Fixtures GetData (D7)

- Líneas de ejemplo en `tests/test_tsw_ue4ss_reader.py`.
- Sesiones lab copiadas a `tests/fixtures/lab/<session>/` para pytest sin juego.
- Comparar probe vs lab: `scripts/tools/compare_lab_vs_probe.py`.

### Sin juego ≠ sin validar

pytest cubre parser, policy y canal. **In-game** sigue siendo obligatorio para: C1 señales, mandos
IPC, jitter probe, holgura ETA (D9).

---

## Probe Lua

| Acción | Comando / nota |
| --- | --- |
| Instalar mod | `install_ue4ss_probe.bat` |
| Ver línea GetData | `probe_ue4ss.bat` |
| Guardar log UE4SS | `probe_ue4ss_log.bat` → `logs/ue4ss_probe_*.txt` |
| Tras editar `main.lua` | Subir `PROBE_BUILD` · reinstalar · comprobar `seq` sube ~20 Hz |
| Rendimiento | `autopilot_perf.bat` · `lua_probe_perf.bat` — objetivo `loop_hz` ≥ 18 con GUI |
| Inventario palancas | **ApiExplorerMod** F6 — no ampliar F9 en probe |

### Síntomas probe

| Síntoma | Revisar |
| --- | --- |
| `seq` no sube | F7 probe OFF · hook UE4SS · `UE4SS.log` |
| Campos `?` o ausentes | Nombre HUD/DriverAid en lab F5/F7 · CANAL_CONTROL |
| Freeze al activar probe | DriverAid TArray — no ampliar lecturas sin medir |
| Hz &lt; 15 | `autopilot_perf.bat`; reducir trabajo en tick Lua |

---

## Depuración canal (IPC + GetData)

Ruta: `%TEMP%\TSW6Bridge\` (`GetData.txt`, `SendCommand.txt`, `SendCommandAck.txt`).

| Síntoma | Revisar |
| --- | --- |
| Mando no aplica | `last_cmd_id` / `last_ack_ok` en GetData · cola IPC · nombre control G-B |
| ACK fail | Palanca equivocada · `lever_notch` vs `handle_notch` · layout combined/freight |
| Python no lee | Ruta bridge · antivirus · probe OFF |
| Telemetría stale | `seq` congelado · comparar timestamp archivo |

Herramientas:

- GUI: `iniciar_autopilot.bat` — dashboard con `probe seq=…`
- Diagnóstico: `tsw6/telemetry/channel_diagnostics.py` (tests en `test_channel_diagnostics`)
- Log sesión: `logs/autopilot_*.log` — buscar `SESIÓN CANAL` tras pruebas de mandos

---

## Sesión in-game

Plantilla mínima tras tocar probe o P1:

1. Cross-City (o ruta habitual) · Class 323 · probe ON (F7).
2. Comprobar `seq` y campos nuevos en monitor o log.
3. Si IPC: un ciclo mando + ACK en log.
4. Anotar en bitácora [PENDIENTE_DYNAMICHUD](../v1/PENDIENTE_DYNAMICHUD.md) o delta PLAN_V2.
5. Lab opcional: export ApiExplorer si validas nuevo `HUD_Get*` (F5/F7).

Tarjetas de validación por tema (PLAN_V2):

| Tarjeta | Qué probar |
| --- | --- |
| **P3** | Carteles P1 (`--limit-brake`) — ver [checklist P3](#checklist-p3--limit-brake-in-game) |
| **C1** | Semáforo verde → ámbar → rojo; `signal_red` + distancia |
| **C2** | Aproximación andén; `station_dist` / FSM |
| **9b** | Nieve / slip; `is_slipping` en log sin cambio mando |

### Checklist P3 — `--limit-brake` in-game

Cerrar **paso 3** del [§ Orden](PLAN_V2.md#orden-de-implementación) tras esta sesión.
Alcance: solo **cartel** (`dist_limit_cm` / `next_limit_ms`); sin estación ni señal (pasos 4–7).

#### Antes de arrancar

- [ ] Probe instalado (`scripts\ue4ss\install_ue4ss_probe.bat`) y juego con UE4SS.
- [ ] Partida **Class 323** en marcha (recomendado: Cross-City, tramo con carteles 60→55 o 55→45).
- [ ] Palanca en **neutro (4)** o tracción moderada; sin freno manual al iniciar el agente.
- [ ] `pytest V2/tests/ -q` verde en la máquina (referencia actual: **79** tests).
- [ ] Opcional: copiar una línea GetData a fixture si encuentras un caso raro.

#### Comandos

```bat
REM 1) Smoke IPC (sin P1) — debe seguir PASS como en paso 2
V2\test_ipc.bat

REM 2) Agente con carteles (consola)
V2\run.bat console --limit-brake

REM 2b) Sesión debatible (recomendado) — al cerrar: JSONL + HTML + abre navegador
V2\run_p1_session.bat limit cross-city

REM Equivalente manual:
V2\run.bat console --mode limit --investigate --log --route cross-city

REM Estación / señal (trace ya; P1 cuando pasos 4-7):
V2\run_p1_session.bat signal four-oaks

REM 3) Con perfil aprendido (si existe)
V2\run.bat console --limit-brake --profile logs\profiles\class_323.json

REM 4) Visor solo lectura (comprobar seq / mph en paralelo)
V2\run_gui.bat
```

GetData vivo: `%TEMP%\TSW6Bridge\GetData.txt` — comprobar que `seq` sube ~20 Hz y existen
`dist_limit_cm` y `next_limit_ms` cuando hay cartel adelante.

#### Qué mirar en consola

Cada línea: `tick=… seq=… mph=… lever=… target=… ipc=… p1=<CMD>/<FASE>`.

| Campo | Significado |
| --- | --- |
| `p1=APPLY/B1` (o B2/B3) | Plan P1 pide freno; `target` debe ir hacia muesca 3/2/1 |
| `p1=RELEASE/NEU` | Objetivo alcanzado; `target=4` y `lever` → 4 en ticks siguientes |
| `p1=COAST_THROTTLE/…` | Soltar tracción antes de frenar (palanca > 4) |
| `ipc=True` | Un paso IPC enviado este tick (±1 muesca; normal variar 1–3 ticks hasta `lever==target`) |
| Sin `p1=…` | Lejos del cartel o dentro de banda coast — **no** debe frenar “por nada” |

#### Escenarios (marcar PASS/FAIL)

| # | Situación | Cómo provocarla | PASS si… |
| --- | --- | --- | --- |
| A | **Lejos del cartel** | 60 mph, cartel 55 a > 800 m | Sin `p1=APPLY` (o `apply` muy tarde); no B3 a kilómetros |
| B | **Ventana APPLY** | Acercarse al 55 mph; distancia ~200–400 m | `p1=APPLY/B1` (o B2); `lever` baja a 3+; `train_brake` ≥ 0.25 en B1 |
| C | **RELEASE en cartel** | Tras frenar, velocidad ≤ límite + ~0.4 mph | `p1=RELEASE/NEU`; `target=4`; palanca vuelve a 4 |
| D | **No RELEASE al arrancar** | Parado, freno puesto, cartel lejos | **No** `RELEASE` con spd ≈ 0 y cartel a cientos de m |
| E | **HOLD_DH bajada** | Cartel 60, spd ~59.5, pendiente −1%, **misma zona** (60→60) | `p1=APPLY/B1` con `Mantener bajada @59`; no soltar hasta pasar cartel |
| F | **Tracción + cartel** | Palanca > 4 acercándose a cartel | Primero `COAST_THROTTLE` o neutro, luego `APPLY` |
| G | **IPC estable** | Cualquier APPLY | ACK en log probe; sin errores `ipc_ok=False` repetidos |

**Nota:** en bajada, RELEASE puede tardar hasta `dist_limit_cm` < ~8 m (cartel “pasado”).

**Tuning distancia (P1 cartel):** `SAFETY_MARGIN` en `V2/tsw6v2/constants.py` multiplica la
distancia cinemática con margen en el plan (`apply_margin=True`). Valores: **1.40** (v1/Dastsc,
muy conservador) → **1.20** (primer paso EMU 323, 2026-09) → **1.00** si el replay HTML muestra
frenar mucho antes del cian `ds=0`. Validar con `run_p1_session.bat` y comparar APPLY vs línea cian.
Mercancías (futuro): mantener margen alto y `a` menor en learner, no el mismo 1.2.

#### Criterio global PASS (paso 3)

- [ ] A y B: planifica tarde, frena suave (B1 habitual en 60→55 plano).
- [ ] C: suelta a neutro al cumplir cartel (sin oscilar B1↔RELEASE cada tick).
- [ ] D: no suelta freno al inicio de escenario parado.
- [ ] E: HOLD_DH en misma zona (techo posted−1 mph); 60→55 usa solo BRAKE_LIMIT en horizonte.
- [ ] G: IPC responde (como paso 2); sin mandos cuando `p1` vacío lejos del cartel.
- [ ] Anotar ruta, variante y `PROBE_BUILD` en delta [PLAN_V2](PLAN_V2.md#deltas-cambios-al-codificar).

#### Si falla

| Síntoma | Revisar primero |
| --- | --- |
| `p1` siempre vacío | GetData sin `dist_limit_cm` / `next_limit_ms`; probe Lua |
| Frena muy pronto (B3 lejos) | JSONL: ¿`HOLD_DH` en 60→55? (no debe). `SAFETY_MARGIN` en `constants.py` |
| Frena muy tarde (spd > lim al cartel) | `SAFETY_MARGIN` en `V2/tsw6v2/constants.py` (hoy **1.20**; subir si hace falta) |
| No suelta (lever < 4 siempre) | RELEASE bloqueado por bajada o spd > límite + 0.4 |
| `ipc=False` con `target≠lever` | `test-ipc`; ACK timeout; juego en pausa |
| Cartel “salta” / distancia fija | C.3a odometría — anotar `odo_m` y sesión para delta |

Fixture útil tras sesión: pegar línea GetData en `tests/fixtures/` y test en `V2/tests/` si el
caso es reproducible sin juego.

#### Trazas JSONL (`--log`)

Cada tick → una línea JSON en `logs/v2/<timestamp>_<route>_limit.jsonl` (o ruta con `--log PATH`).

| Campo tick | Uso al debatir |
| --- | --- |
| `lim_mph` / `lim_dist_m` | Cartel adelante |
| `eff_mph` | Límite vigente (`speed_limit_ms`) |
| `p1.dist_start_m` | ¿Frenamos pronto/tarde? |
| `p1.apply_now` | ¿En ventana cinemática? |
| `p1.reason` | `plan`, `release`, `apply_deferred`, `coast_latch`, … |
| `p1.detail` | Texto del plan (contención bajada, latch, …) |
| `ipc` | Mandos enviados y ACK |

Valores de `p1.reason`:

| Valor | Significado |
| --- | --- |
| `plan` | APPLY/COAST desde plan cartel |
| `release` | Soltar a neutro |
| `apply_deferred` | Plan existe pero fuera de ventana |
| `coast_latch` | Anti-rebrake tras RELEASE |
| `no_plan` | Velocidad bajo cartel / coast band |
| `no_limit_sign` | GetData sin cartel |

Pegar 5–10 líneas JSON del tramo conflictivo en el chat o en delta PLAN_V2.

**Replay visual (sin juego):**

```bat
python scripts/tools/summarize_v2_limit.py logs\v2\<sesion>.jsonl --html
```

Abre el `.html`: gráfico spd/eff/lim + **franja de capas** (Vigilar, Frenar, Soltar…).
Diagrama concepto (distancia → capa): [p1_limit_capas.html](p1_limit_capas.html).

### Debate por capas (no por APPLY/COAST)

| Capa | Antes (código) | ¿Manda? |
| --- | --- | --- |
| **Vigilar** | `command_none`, apply_now=false | No |
| **Esperar ventana** | `apply_deferred` | No |
| **Quitar tracción** | `COAST_THROTTLE` | Sí → neutro |
| **Frenar** | `APPLY` | Sí → B1–B3 |
| **Soltar freno** | `RELEASE` | Sí → neutro |
| **Revisar** [GAP] | apply_now sin cmd | Debate / posible bug |

Consola `--investigate`: `capa=Vigilar [WATCH]` en lugar de solo `why=command_none`.

---

## Lab vs producción

| | ApiExplorerMod | TelemetryProbeMod |
| --- | --- | --- |
| Frecuencia | Al pulsar tecla | ~20 Hz |
| Salida | `data/lab_exports/exports/<UTC>/` | `%TEMP%\TSW6Bridge\GetData.txt` |
| HTTP en sesión | Opcional (`-HTTPAPI`) | No |
| Uso | Descubrir API, G-B, C1 enum | Producción autopilot |

Flujo: lab propone → humano aprueba → probe adopta (D2). Ver
[PLAN_API_EXPLORER § Explorar ≠ usar todo](PLAN_API_EXPLORER.md#explorar--usar-todo).

Herramientas lab post-sesión:

```bat
```

---

## Sugerencias y mejoras

Para no inflar el backlog ni duplicar PLAN_V2:

| Tipo | Dónde dejarlo |
| --- | --- |
| Decisión producto / nuevo paso | Tabla **Deltas** o § debates en [PLAN_V2](PLAN_V2.md) |
| Campo probe candidato | Sesión lab + fila en PLAN_API_EXPLORER mapa cableado |
| Bug reproducible | Issue o nota en bitácora probe con `PROBE_BUILD` y escenario |
| Refactor sin paso | **No hacer** — ver «No es mantenimiento v2» abajo |
| Líneas duplicadas / `print` olvidado | [Depurar líneas y duplicados](#depurar-líneas-y-líneas-duplicadas) |
| Doc rota / enlace | PR pequeño o `fix_markdownlint.py` |
| Herramienta CLI nueva | `scripts/tools/` + test + una fila en este doc |

**No es mantenimiento v2:** reescribir `coordinator.py` sin paso D1; refactors cosméticos sin test;
migrar todo `docs/v1/` de golpe.

---

## Depurar líneas y líneas duplicadas

Higiene de código y docs **antes de cerrar un paso o abrir PR**. El producto v2 es carpeta
nueva; copiar desde v1 o pegar bloques suele dejar restos.

### Diff mínimo (reparar o añadir)

Al **arreglar un bug** o **añadir una función**, solo las líneas imprescindibles:

| Hacer | No hacer |
| --- | --- |
| Corregir la causa en el sitio mínimo | Reformatar el archivo entero |
| Una función nueva si no cabe en la existente | Copiar bloques de v1 “por si acaso” |
| Borrar código muerto que el cambio deja huérfano | Comentar bloques viejos en lugar de eliminarlos |
| Test que demuestra el arreglo o el contrato | `print` / logs extra “para ver” que no se quitan |

Regla práctica: si el diff no explica el arreglo en &lt; 30 s de lectura, probablemente sobra.

### Plan cartel P1 (`limit_*`)

Frenada por cartel — diseño V2 desde cero: [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md).

**Fuente única de verdad:** `V2/tsw6v2/`. Los módulos homónimos en `tsw6/braking/v2/` son **shims**
(re-export) para que el autopilot v1 (`coordinator`, `speed_decider`) siga importando la ruta antigua
sin duplicar lógica.

| Módulo V2 | Responsabilidad |
| --- | --- |
| `limits.py` | Fachada: `evaluate_limit_brake` (HOLD_DH + BRAKE_LIMIT) |
| `limit_state.py` | Latch, `decel` por muesca, margen reacción + `fill_s` |
| `limit_notch.py` | Escalón B1→B2→B3, muesca mínima suficiente |
| `limit_containment.py` | HOLD_DH + horizonte BRAKE_LIMIT (sin contención legacy) |

| Shim v1 (`tsw6/braking/v2/`) | Apunta a |
| --- | --- |
| `physics.py` | `tsw6v2.physics` |
| `plan.py` | `tsw6v2.plan` |
| `command.py` | `tsw6v2.command` |
| `limit_brake.py` | `tsw6v2.limits` + `limit_*` |

Cambiar comportamiento cartel → **solo** `V2/tsw6v2/` + `V2/tests/`. No reimplementar en shims.
Coordinator/estación/señal (`policy`, `objectives`, `station_plan`) siguen en v1 hasta pasos 4–7.

### Líneas de depuración

| Quitar / revisar | Mantener |
| --- | --- |
| `print()`, `pdb`, `breakpoint()` | `logging` con nivel (`info`/`warning`/`error`) |
| Comentarios `# DEBUG`, `# TODO` sin issue | Comentarios que explican regla no obvia (IPC, G-B, tolerancias) |
| Logs verbosos en cada tick del bucle | Diagnóstico explícito (`diagnostic.py`, `test-ipc`, perf bat) |

```bat
rg "print\(|pdb\.set_trace|breakpoint\(|# DEBUG" V2/tsw6v2 mods/TelemetryProbeMod
```

Si hace falta traza puntual en juego: usar `diagnostic.run_ipc_brake_test` o flags del CLI — no
dejar `print` en `loop.py` / `ipc.py`.

### Líneas duplicadas

| Tipo | Señal | Acción |
| --- | --- | --- |
| **Consecutivas** | Misma línea dos veces seguidas (import, asignación, comentario de sección) | Borrar la copia; un solo bloque |
| **Lógica** | Misma condición o mapeo en dos módulos (`power_to_notch`, `_MS_TO_MPH`, parser GetData) | Una función en `V2/tsw6v2/` (p. ej. `bridge/getdata.py`) |
| **Docs** | Mismo párrafo en `PLAN_V2` y otro `.md` | Fuente única en PLAN; enlace desde el resto |
| **Archivos** | Dos rutas con el mismo rol (`tsw6/braking/v2/physics.py` vs `V2/tsw6v2/physics.py`) | Solo `V2/tsw6v2/` — v1 = shim de compatibilidad |

**Líneas consecutivas iguales** — PowerShell (carpeta o archivo):

```powershell
$paths = Get-ChildItem V2\tsw6v2 -Recurse -Include *.py,*.lua
foreach ($file in $paths) {
  $prev = $null; $i = 0
  Get-Content $file.FullName | ForEach-Object {
    $i++
    if ($_ -match '\S' -and $_ -eq $prev) { Write-Host "$($file.FullName):$i $_" }
    $prev = $_
  }
}
```

### Criterio de cierre

- [ ] Diff acotado al arreglo o función nueva (sin ruido colateral).
- [ ] `rg` de depuración sin coincidencias en módulos tocados.
- [ ] Sin pares de líneas consecutivas duplicadas en `.py` / `.lua` del PR.
- [ ] Diff sin bloques enteros repetidos (revisar `git diff` antes de commit).

---

## Documentación y markdown

```bat
python scripts/tools/fix_markdownlint.py --check docs/v2/
python scripts/tools/fix_markdownlint.py docs/v2/MANTENIMIENTO.md
```

| Doc | Actualizar cuando… |
| --- | --- |
| [CANAL_CONTROL](../CANAL_CONTROL.md) | Clave GetData o IPC |
| [PLAN_V2](PLAN_V2.md) | Cierre paso, delta, debate |
| [CODIGO_V2](CODIGO_V2.md) | Nueva carpeta o convención |
| [MANTENIMIENTO](MANTENIMIENTO.md) | Nuevo comando recurrente |
| [esqueleto_v2.svg](../assets/esqueleto_v2.svg) | Cambio arquitectura agent/probe |

Política v1/v2: [PLAN_V2 § Política de documentación](PLAN_V2.md#política-de-documentación).

---

## Repaso trimestral

1. §1–4 PLAN_V2 vs código — criterios de cierre de cada fase.
2. Pasada [depurar líneas y duplicados](#depurar-líneas-y-líneas-duplicadas) en `V2/tsw6v2/` y probe Lua.
3. Suite completa pytest + pyright en módulos tocados recientemente.
4. ¿Debates cerrados (D3, D8, D9) siguen reflejados en código?
5. ¿`iniciar_autopilot.bat` y `tsw_autopilot.py --console` arrancan?
6. ¿Explorer L0 checklist sigue vigente para el último `vehicle_class` documentado?

---

## Relacionados

- [README v2](README.md) — índice documentación producto
- [GUIA v1](../v1/GUIA.md) — `.bat` usuario
- [ESTADO v1](../v1/ESTADO.md) — árbol runtime actual (referencia, no backlog)
