"""Planificador P1 señal roja — perfil servicio v→0."""

from __future__ import annotations

from typing import Callable, Optional

from tsw6v2.physics import DEFAULT_BRAKE_FILL_S, DEFAULT_MAX_BRAKE_DECEL
from tsw6v2.service_brake import target_from_stop_plan
from tsw6v2.signal_plan import signal_apply_horizon_m, plan_brake_for_signal
from tsw6v2.target import BrakeTargetResult

PredictDecelFn = Callable[[int, float, float], Optional[float]]


def evaluate_signal_brake(
    *,
    speed_mph: float,
    signal_distance_m: Optional[float],
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
    throttle_notch: int = 0,
    station_distance_m: Optional[float] = None,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakeTargetResult]:
    """Rojo adelante → plan gradual a 0 (además de emergencia en ``p1_emergency``)."""
    if signal_distance_m is None or signal_distance_m <= 0:
        return None

    plan = plan_brake_for_signal(
        speed_mph=speed_mph,
        signal_distance_m=float(signal_distance_m),
        gradient_pct=gradient_pct,
        base_decel=base_decel,
        predict_decel=predict_decel,
        throttle_notch=throttle_notch,
        station_distance_m=station_distance_m,
        brake_fill_s=brake_fill_s,
    )
    if plan is None:
        return None
    return target_from_stop_plan(
        plan,
        speed_mph=speed_mph,
        detail=f"Señal roja dist={plan.distance_to_target_m:.0f}m",
        allow_watch=True,
        max_apply_distance_m=signal_apply_horizon_m(speed_mph),
    )
