# Código v2 — dónde va cada pieza

**Plan:** [PLAN_V2.md](PLAN_V2.md) · **Mantenimiento:** [MANTENIMIENTO.md](MANTENIMIENTO.md)

## Regla principal

| Qué | Dónde |
| --- | --- |
| **Proyecto V2 (todo)** | **`V2/`** en la raíz del repo |
| Python producto | `V2/tsw6v2/` |
| Tests producto | `V2/tests/` |
| Legacy (solo referencia) | `tsw6/autopilot/`, `tsw6/braking/` — **no ampliar**; cartel = shims → `V2/tsw6v2/` |
| Cableado D2 (GetData + IPC) | `V2/tsw6v2/bridge/` — implementación propia, contrato [CANAL_CONTROL](../CANAL_CONTROL.md) |

## Estructura `V2/`

```text
V2/
  README.txt
  run.bat              python -m tsw6v2 …
  run_p1_session.bat   P1 + JSONL + investigate (limit | station | signal | p1)
  test_ipc.bat
  tsw6v2/
    bridge/            GetData parser + IPC (contrato D2, sin importar tsw6)
    physics.py         v²/2a (paso 3)
    plan.py / limits.py / planning.py / learner.py / brake_air.py
    limit_state.py     latch cartel (decel, reacción)
    limit_notch.py     escalón B1→B3, muesca mínima
    limit_containment.py  HOLD_DH + horizonte BRAKE_LIMIT
    command.py         APPLY / RELEASE / COAST (paso 3)
    decision.py        limit_brake tick → BrakeCommand (paso 3)
  tsw6/braking/v2/     shims v1 (physics, plan, command, limit_brake → tsw6v2)
    trace.py           JSONL + investigate (afinado paso 3)
    gui.py           visor tkinter (paso 2)
    constants.py
    ipc.py
    loop.py
    probe.py
    diagnostic.py
    cli.py
  tests/
    test_channel.py
    test_gui.py
    test_bridge.py
    test_ipc.py
    test_loop.py
    test_probe.py
    test_physics.py
    test_command.py
    test_release.py
    test_decision.py
    test_learner.py
    test_trace.py
```

## Comandos

```bat
python -m pytest V2/tests/ -q
V2\test_pytest.bat
V2\run.bat console
V2\run_gui.bat
V2\test_ipc.bat
```

`PYTHONPATH` debe incluir la raíz del repo **y** `V2/` (los `.bat` lo configuran).

## v1 vs V2

| Situación | Qué hacer |
| --- | --- |
| Feature nueva | Solo `V2/tsw6v2/` |
| Bug en v1 producción | Arreglo mínimo en v1 **o** ya en V2 si sustituye el flujo |
| Import desde v1 | **Prohibido** en `V2/tsw6v2/` — contrato D2 en `bridge/` |
| Cambios de código | Diff mínimo — ver [MANTENIMIENTO § Depurar](MANTENIMIENTO.md#diff-mínimo-reparar-o-añadir) |
| Tests producto | Solo `V2/tests/` |

## Estado (pasos PLAN_V2)

| Paso | Qué | Estado |
| --- | --- | --- |
| 1 | Contrato GetData | Casi cerrado |
| 2 | Esqueleto `V2/tsw6v2/` | **Cerrado** (pytest + `test-ipc` in-game) |
| **3** | Física / learner / carteles en V2 | **pytest verde** (`command`, `release`, `decision`) · validar in-game `--limit-brake` |

Módulos cartel: `limit_state` · `limit_notch` · `limit_containment` · `limits` (fachada) — ver [MANTENIMIENTO § Plan cartel](MANTENIMIENTO.md#plan-cartel-p1-limit_).

**Reglas de frenado (diseño V2 desde cero):** [REGLAS_FRENOS_P1.md](REGLAS_FRENOS_P1.md) — ideas de v1 sí; comportamiento legacy no. H1 (`HOLD_DH`) = primer bloque.

Fases de producto (0–6): [PLAN_V2 § Fases](PLAN_V2.md#fase-0--contrato-io) · orden de código: [§ Orden](PLAN_V2.md#orden-de-implementación).

## Relacionados

- [README v2](README.md) · [PLAN_V2](PLAN_V2.md)
