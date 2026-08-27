#!/usr/bin/env python3
"""
station_brake.py — Frenada en andén (v2).

Reutiliza el planificador v1 probado; convierte a ``BrakeTargetResult``.
OCR / precisión fina: pendiente de integrar distancia tablón.
"""

from __future__ import annotations

from typing import Optional

from tsw6.braking.v2.physics import DEFAULT_BRAKE_FILL_S, is_in_brake_action_window
from tsw6.braking.v2.planner import plan_brake_for_station
from tsw6.braking.v2.types import BrakeTargetResult


def evaluate_station_brake(
    *,
    speed_mph: float,
    station_distance_m: Optional[float],
    gradient_pct: float = 0.0,
    base_decel: float = 0.8,
    predict_decel=None,
    throttle_notch: int = 0,
    station_eta: Optional[str] = None,
    station_traveled_m: Optional[float] = None,
    station_anchor_m: Optional[float] = None,
    schedule_slack_enabled: bool = True,
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
    step = plan.active_step
    if step is not None and not step.apply_now and not is_in_brake_action_window(
        step.dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=plan.distance_to_target_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
    ):
        late = [s for s in plan.steps if s.apply_now and s.dist_start <= 0]
        step = late[-1] if late else None
    if step is None:
        return None
    if not step.apply_now and not is_in_brake_action_window(
        step.dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=plan.distance_to_target_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
    ):
        return None
    return BrakeTargetResult(
        target_kind="STATION",
        distance_m=plan.distance_to_target_m,
        target_speed_mph=0.0,
        handle_notch=step.handle_notch,
        phase=step.notch,
        dist_start=step.dist_start,
        apply_now=step.apply_now,
        detail=f"Estación dist={plan.distance_to_target_m:.0f}m",
    )
