#!/usr/bin/env python3
"""Busca inanición: algún objetivo (cartel/andén/señal) con ``apply_now`` y la decisión sin mando.

Uso: ``python V2/scripts/starvation_scan.py logs/v2/<sesion>.jsonl [...]``. Re-evalúa cada tick con
``evaluate_p1_tick`` (lazo abierto, ``lever`` del tick anterior), usa ``decision.starved`` (el mismo
criterio que el vigilante en vivo, ANALISIS §7.11) y agrupa las rachas de ≥ 5 ticks.
Ver ANALISIS §7.6: así se encontró el andén que esperaba a un cartel que aún no frenaba.
Las rachas cortas (3-4 s) suelen ser aplazamientos con margen (p. ej. 34,5-35,0 mph con cartel de 35).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

logging.disable(logging.CRITICAL)
_V2 = Path(__file__).resolve().parents[1]
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

# ``tests/replay_helpers.py`` por ruta (no es un paquete importable desde ``scripts/``).
_spec = importlib.util.spec_from_file_location("replay_helpers", _V2 / "tests" / "replay_helpers.py")
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
tick_to_snap = _helpers.tick_to_snap

from tsw6v2.command import BrakeReleaseState  # noqa: E402
from tsw6v2.decision import evaluate_p1_tick  # noqa: E402
from tsw6v2.learner import LearnerProfile  # noqa: E402
from tsw6v2.limits import LimitBrakeState  # noqa: E402
from tsw6v2.vehicle_package import resolve_vehicle_package  # noqa: E402


def scan(path: Path) -> tuple[int, list[tuple[float, float, tuple, int]]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ticks = [r for r in rows if r.get("type") == "tick"]
    limit_state, release_state, learner = LimitBrakeState(), BrakeReleaseState(), LearnerProfile()
    learner.apply_vehicle_brake_profile(resolve_vehicle_package(ticks[0]["vehicle"]))
    lever = None
    bad: list[tuple[float, list[str], str | None, str]] = []
    evaluated = 0
    for r in ticks:
        snap = replace(
            tick_to_snap({**r, "lever": lever if lever is not None else r["lever"]}),
            accel_ms2=r.get("accel_ms2"),
        )
        lever = r["lever"]
        stn = r.get("stn_dist_m")
        decision = evaluate_p1_tick(
            limit_state,
            release_state,
            snap,
            learner=learner,
            station_distance_m=stn if stn and stn > 0 else None,
            station_fsm=r.get("stn_fsm"),
        )
        if not decision.candidates:
            continue
        evaluated += 1
        if decision.starved:  # mismo criterio que el vigilante en vivo (decision._starved)
            due = [name for name, cand in decision.candidates.items() if cand["apply"]]
            bad.append((r["t_ms"] / 1000, due, decision.target_kind or None, decision.reason))
    runs: list[list] = []
    for t, due, picked_kind, why in bad:
        key = (tuple(due), picked_kind, why)
        if runs and t - runs[-1][1] < 1.0 and runs[-1][2] == key:
            runs[-1][1] = t
            runs[-1][3] += 1
        else:
            runs.append([t, t, key, 1])
    return evaluated, [(a, b, key, n) for a, b, key, n in runs]


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        path = Path(arg)
        evaluated, runs = scan(path)
        total = sum(n for *_, n in runs)
        print(f"{path.name}: ticks con objetivo {evaluated}, ticks sin mando con un objetivo activo {total}")
        for a, b, (due, picked_kind, why), n in runs:
            if n >= 5:
                print(f"   {a:7.1f}-{b:7.1f} s  {n:4d} ticks  pide={list(due)} elegido={picked_kind} motivo={why}")


if __name__ == "__main__":
    main()
