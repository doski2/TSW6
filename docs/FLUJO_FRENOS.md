# Flujo de frenos — TSW6

Mapa de conexiones desde telemetría hasta el mando en cabina.
Documentación detallada en este archivo y en [BRAKE_V2.md](BRAKE_V2.md).

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

## Secuencia por ciclo (~20 Hz)

| # | Módulo | Qué hace |
| --- | --- | --- |
| 1 | `main.lua` | Escribe velocidad, `handle_notch`, límites en `GetData.txt` |
| 2 | `autopilot_core.tick()` | Lee telemetría, construye estado, decide, ejecuta |
| 3 | `build_train_state()` | `TrainState` inmutable: speed, límites, distancia estación, ETA |
| 4 | `speed_decider.decide()` | FSM → DMI → P1 → `HOLD` (sin P2) |
| 5 | `coordinator.evaluate()` | RELEASE / emergencia / cartel / andén → `BrakeCommand` |
| 6 | `decider.brake_command` | Último comando P1 (notch objetivo + motivo) |
| 7 | `handle_controller.execute()` | **Prioridad:** si hay `brake_command`, notch absoluto por IPC |
| 8 | `tsw_ipc_bus` | `PowerBrakeHandle:0.375` → `SendCommand.txt` |
| 9 | `main.lua` | Aplica PATCH al juego, ack en `SendCommandAck.txt` |

---

## Dentro de P1 (coordinator)

```text
```

**Parada unificada** (ej. cartel 60 mph + andén cerca): frena al cartel, **RELEASE @55**, coast
hasta andén.
Ver `coordinator.py` → `_should_block_limit_release()` y `cluster.py`.

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
- `uni=Y` — parada unificada cartel+andén
- `gap=` — distancia estación − distancia cartel
- `p1eta=` — hora llegada HUD

---

## Archivos clave

| Archivo | Rol |
| --- | --- |
| `tsw6/braking/v2/coordinator.py` | Orquestación P1 |
| `tsw6/autopilot/handle_controller.py` | Ejecuta `BrakeCommand` |
| `tsw6/telemetry/tsw_ipc_bus.py` | Escritura IPC |
| `docs/BRAKE_V2.md` | Detalle frenado v2 |
