#!/usr/bin/env python3
"""Paridad de decisiones P1 entre dos versiones del código, sobre sesiones JSONL.

Uso (antes y después de un refactor, mismos logs)::

    python V2/scripts/parity_jsonl.py antes.jsonl logs/v2/2026*_station.jsonl
    # ...cambiar el código...
    python V2/scripts/parity_jsonl.py despues.jsonl logs/v2/2026*_station.jsonl
    cmp antes.jsonl despues.jsonl && echo PARIDAD_OK

Vuelca una línea por tick con la decisión de ``evaluate_p1_tick`` (comando, motivo, objetivo,
fase, ``apply_now``, distancia de andén, ``station_stop_m``). Es lazo abierto: demuestra que el
código decide lo mismo con esas entradas, no que el tren se comporte igual. Solo vale para los
vehículos de los logs que le pases (hoy no hay sesión de la Class 323).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "V2"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from replay_jsonl import _tick_to_snap  # noqa: E402
from tsw6v2.command import BrakeReleaseState  # noqa: E402
from tsw6v2.decision import evaluate_p1_tick  # noqa: E402
from tsw6v2.learner import LearnerProfile  # noqa: E402
from tsw6v2.limits import LimitBrakeState  # noqa: E402


def dump(out: Path, sessions: list[Path]) -> int:
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for path in sessions:
            limit_state, release_state, learner = (
                LimitBrakeState(),
                BrakeReleaseState(),
                LearnerProfile(),
            )
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                t = json.loads(line)
                if t.get("type") != "tick":
                    continue
                snap = _tick_to_snap(t)
                if snap.speed_ms is None:
                    continue
                stn = t.get("stn_dist_m")
                d = evaluate_p1_tick(
                    limit_state,
                    release_state,
                    snap,
                    learner=learner,
                    station_distance_m=float(stn) if stn and stn > 0 else None,
                    station_fsm=t.get("fsm"),
                )
                c = d.command
                row = [
                    t.get("seq"),
                    c.kind if c else None,
                    c.target_notch if c else None,
                    c.target_fraction if c else None,
                    d.reason,
                    d.target_kind,
                    d.phase,
                    d.apply_now,
                    d.station_dist_m,
                    d.handle_notch,
                    limit_state.station_stop_m,
                ]
                fh.write(json.dumps(row, default=str) + "\n")
                n += 1
    return n


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    logging.disable(logging.CRITICAL)  # las emergencias escriben mucho al log
    n = dump(Path(sys.argv[1]), [Path(a) for a in sys.argv[2:]])
    print(f"{n} ticks -> {sys.argv[1]}")


if __name__ == "__main__":
    main()
