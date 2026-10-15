"""DIAGNÓSTICO TEMPORAL (borrar tras la investigación 212814Z).

Activo solo con TSW6_DIAG_STATION=1. Escribe una línea JSON por tick de estación
en logs/v2/diag_station.jsonl con las entradas reales de plan_brake_for_station.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

ENV_FLAG = "TSW6_DIAG_STATION"
OUT_PATH = Path("logs") / "v2" / "diag_station.jsonl"


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "") == "1"


def log_station_tick(
    *,
    tick_ctx: Any,
    station_plan_dist: Optional[float],
    station_eta: Optional[str],
    station_allow_watch: bool,
    throttle_notch: int,
    station_target: Any,
    predict_decel: Any,
    brake_fill_s: float,
    base_decel: float,
) -> None:
    if not enabled() or station_plan_dist is None:
        return
    from tsw6v2.station_plan import plan_brake_for_station

    speed_mph = float(tick_ctx.speed_mph)
    plan = plan_brake_for_station(
        speed_mph=speed_mph,
        station_distance_m=float(station_plan_dist),
        gradient_pct=float(tick_ctx.grad),
        base_decel=base_decel,
        predict_decel=predict_decel,
        throttle_notch=throttle_notch,
        station_eta=station_eta,
        brake_fill_s=brake_fill_s,
    )
    step = getattr(plan, "active_step", None) if plan is not None else None
    row = {
        "spd_mph": round(speed_mph, 3),
        "stn_plan_dist_m": round(float(station_plan_dist), 2),
        "throttle_notch": throttle_notch,
        "station_eta": station_eta,
        "allow_watch": station_allow_watch,
        "plan_none": plan is None,
        "plan_dist_to_target_m": None if plan is None else round(plan.distance_to_target_m, 2),
        "step_dist_start": None if step is None else round(step.dist_start, 2),
        "step_apply_now": None if step is None else step.apply_now,
        "step_apply_at_remaining_m": None if step is None else getattr(step, "apply_at_remaining_m", None),
        "target_is_none": station_target is None,
        "target_apply_now": None if station_target is None else station_target.apply_now,
        "target_handle": None if station_target is None else station_target.handle_notch,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
