"""Planificador P1 andén — perfil servicio v→0."""

from __future__ import annotations

from typing import Callable, Optional

from tsw6v2.physics import DEFAULT_BRAKE_FILL_S
from tsw6v2.service_brake import target_from_stop_plan
from tsw6v2.station_plan import (
    STATION_SCHEDULE_SLACK_ENABLED,
    plan_brake_for_station,
)
from tsw6v2.target import BrakeTargetResult

PredictDecelFn = Callable[[int, float, float], Optional[float]]


def evaluate_station_brake(
    *,
    speed_mph: float,
    station_distance_m: Optional[float],
    gradient_pct: float = 0.0,
    base_decel: float = 0.8,
    predict_decel: Optional[PredictDecelFn] = None,
    throttle_notch: int = 0,
    station_eta: Optional[str] = None,
    station_traveled_m: Optional[float] = None,
    station_anchor_m: Optional[float] = None,
    schedule_slack_enabled: bool = STATION_SCHEDULE_SLACK_ENABLED,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakeTargetResult]:
    if station_distance_m is None or station_distance_m <= 0:
        return None

    plan = plan_brake_for_station(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        gradient_pct=gradient_pct,
        base_decel=base_decel,
        predict_decel=predict_decel,
        throttle_notch=throttle_notch,
        station_eta=station_eta,
        station_traveled_m=station_traveled_m,
        station_anchor_m=station_anchor_m,
        schedule_slack_enabled=schedule_slack_enabled,
        brake_fill_s=brake_fill_s,
    )
    if plan is None:
        return None
    return target_from_stop_plan(
        plan,
        speed_mph=speed_mph,
        detail=f"Estación dist={plan.distance_to_target_m:.0f}m",
        allow_watch=False,
    )
