# Flujo de frenos — TSW6

Mapa de conexiones desde telemetría hasta el mando en cabina.
Documentación detallada en este archivo y en [BRAKE_V2.md](BRAKE_V2.md).

**Comparativa con Nexus V4 (Dastsc):** [COMPARATIVA_DASTSC_FLUJO.md](COMPARATIVA_DASTSC_FLUJO.md)
— misma numeración de pasos que el SVG cuando sea posible. Espejo en
`C:\Users\doski\Dastsc\docs\FLUJO_FRENOS_V4.md` y `flujo_frenos_v4.svg` (15 pasos).

**Diagramas (imagen):**

| Tipo | Archivo | Para que sirve |
| --- | --- | --- |
| **Mapa por modulos** (como boceto) | [assets/esqueleto_arquitectura.svg](assets/esqueleto_arquitectura.svg) | Cajas: Telemetria, Autopilot, Gestion, Freno v2… |
| Arbol cronologico | [assets/esqueleto_flujo_cronologico.svg](assets/esqueleto_flujo_cronologico.svg) | Pasos 1→14 en orden temporal |
| Por capas | [assets/esqueleto_flujo_capas.svg](assets/esqueleto_flujo_capas.svg) | Vista horizontal de capas |

Navegador: [assets/esqueleto_arquitectura.html](assets/esqueleto_arquitectura.html)

---

## Diagrama general

```mermaid
```

---

## Secuencia por ciclo (~20 Hz) — numeración SVG

Alineada con [esqueleto_flujo_cronologico.svg](assets/esqueleto_flujo_cronologico.svg). Para el
equivalente Dastsc por paso, ver [COMPARATIVA_DASTSC_FLUJO.md](COMPARATIVA_DASTSC_FLUJO.md).

| Paso | Bloque | Módulo | Qué hace |
| --- | --- | --- | --- |
| **1** | LECTURA | `main.lua` | HUD + DriverAid → `GetData.txt` (~20 Hz) |
| **2** | LECTURA | `tsw_ue4ss_reader.py` | `parse_probe_line()` → `ProbeSnapshot` |
| **3** | LECTURA | `tsw_telemetry_source.py` | Merge probe + HTTP + HUD DB → `_telem` |
| **4** | CICLO | `autopilot_core.tick()` | Bucle principal |
| **5** | CICLO | `build_train_state()` | `TrainState` inmutable |
| **6** | DECISIÓN | `speed_decider.decide()` | FSM → DMI → P1 o `HOLD` (sin P2) |
| **7–11** | P1 | `BrakeCoordinatorV2` | limit / station / planner → `BrakeCommand` |
| **12** | EJECUCIÓN | `handle_controller.execute()` | Notch absoluto por IPC |
| **13** | EJECUCIÓN | `tsw_ipc_bus` | `SendCommand.txt` |
| **14** | JUEGO | `main.lua` | Aplica `PowerBrakeHandle`, ack |

Detalle pasos 1–3: [ESTADO.md](ESTADO.md#árbol-cronológico--pasos-1-2-3-lectura). Pasos 4–6:
[ESTADO.md](ESTADO.md#árbol-cronológico--pasos-4-5-6-ciclo--decisión).

---

## Dentro de P1 (coordinator)

```text
```

**Parada unificada** (cartel 55 + andén ≤350 m y no cabe 55→soltar→0):

- El **cartel marca cuándo** APPLY (mientras dist al cartel > 8 m).
- El **andén marca v→0**; no se suelta en el cartel.
- Tras pasar el cartel, sí RELEASE si sobra distancia al andén (evita B1 eterno).

Código: `cluster.py`, `priority.py`, `coordinator.py`. Detalle:
[BRAKE_V2.md](BRAKE_V2.md#parada-unificada-2026-08-27).

**Ventana APPLY (2026-08-26):** metros dinámicos vía `physics.apply_zone_margin_m` — sustituye
60 m fijo, histeresis 80/30 m y contención 150 m. RELEASE bloqueado si estación en ventana
(`release_blocked:station`). Detalle:
[BRAKE_V2.md](BRAKE_V2.md#ventana-de-aplicación-2026-08-26) ·
[FISICA_Y_APRENDIZAJE.md](FISICA_Y_APRENDIZAJE.md#ventana-apply--de-metros-fijos-a-física-2026-08-26).

---

## Capas de decisión (sin P2)

| Capa | Cuándo | Salida |
| --- | --- | --- |
| **FSM** | Parada comercial (APPROACHING/STOPPED/DEPARTING) | `HOLD` / `COAST` / perfil `effective_limit` |
| **Marcador DMI** | `brake_marker_m` en vía | `BRAKE` / `BRAKE_FAST` advisory |
| **P1** | Hay cartel/estación/señal adelante | `BrakeCommand` IPC (B1–B3, RELEASE, COAST_THROTTLE) |
| **Sin plan P1** | Lejos de objetivos | `HOLD` |
| **Watchdog** | +5 mph sobre límite durante ≥3 s | `BRAKE_FAST` (teclado) |

Eliminado 2026-08-25: capa P2 reactiva (`_decide_p2`, `p2_overspeed_brake_command`).
Ver [ESTADO § Sin P2](ESTADO.md#sin-p2-2026-08-25).

---

## Campos de log útiles

En `logs/autopilot_*.log`:

- `p1=B1→N3` — plan activo, notch objetivo
- `p1cmd=APPLY` / `RELEASE` — tipo de comando
- `p1ds=` — `dist_start` (m): negativo = tarde; APPLY cuando &#124;`p1ds`&#124; ≤ zona

  (~`speed×2.5`, min 25 m)

- `uni=Y` — parada unificada cartel+andén
- `gap=` — distancia estación − distancia cartel
- `p1eta=` — hora llegada HUD
- `lua=` / `dmi=` — puertas probe / DMI (`1` abierto). GUI: `cerradas lua=0 dmi=—` si el Class 323 no publica `PassengerDoor_*` en el coche de cabina
- `next_lim=55@0.0m` — cartel ya pasado; DriverAid no ha dado el siguiente (probe `dist_limit_cm` a menudo congelado ~2496 m)
- `release_blocked:station` — RELEASE bloqueado (estación en ventana física)

---

## Archivos clave

| Archivo | Rol |
| --- | --- |
| `tsw6/braking/v2/coordinator.py` | Orquestación P1 |
| `tsw6/autopilot/handle_controller.py` | Ejecuta `BrakeCommand` |
| `tsw6/telemetry/tsw_ipc_bus.py` | Escritura IPC |
| `docs/BRAKE_V2.md` | Detalle frenado v2 |
