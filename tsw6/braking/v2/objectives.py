#!/usr/bin/env python3
"""
objectives.py — Cómo frenar cada objetivo: andén, señal (stub), emergencia.

Antes: station_brake.py + signal_brake.py + emergency.py.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional, Tuple

from tsw6.autopilot.control_actions import BRAKE, EMERGENCY
from tsw6.braking.v2.command import BrakeCommand, BrakeTargetResult
from tsw6.braking.v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    BrakePhysicsContext,
    braking_distance_mph,
    decel_for_notch,
    is_in_brake_action_window,
)
from tsw6.braking.v2.station_plan import plan_brake_for_station
from tsw6.governor.governor_constants import (
    EMERGENCY_BRAKE_HANDLE,
    EMERGENCY_BRAKE_MAX_DIST_M,
    P1_CRITICO_MPH,
    SERVICE_MIN_HANDLE,
)

_log = logging.getLogger("tsw.governor.v2")

_UK_SERVICE_FRAC = 0.80
EmergencyTargetKind = Literal["STATION", "SIGNAL"]
_RED_SIGNAL_ASPECTS = frozenset({"DANGER", "RED", "STOP"})


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


def evaluate_signal_brake(
    *,
    speed_mph: float,
    signal_distance_m: Optional[float],
    signal_aspect: Optional[str] = None,
    gradient_pct: float = 0.0,
    base_decel: float = 0.8,
    predict_decel=None,
) -> Optional[BrakeTargetResult]:
    """Stub — implementar cuando haya telemetría de aspecto DANGER."""
    _ = (speed_mph, signal_distance_m, signal_aspect, gradient_pct,
         base_decel, predict_decel)
    return None


def is_red_signal_aspect(aspect: Optional[str]) -> bool:
    """True si el aspecto exige parada (Dastsc: DANGER)."""
    if not aspect:
        return False
    upper = aspect.strip().upper()
    return upper in _RED_SIGNAL_ASPECTS or "DANGER" in upper


def _service_decel(base_decel: float, gradient_pct: float) -> float:
    return decel_for_notch(_UK_SERVICE_FRAC, base_decel, gradient_pct)


def _stop_distance(
    speed_mph: float,
    *,
    base_decel: float,
    gradient_pct: float,
    brake_transition_s: float,
    accel_ms2: Optional[float],
) -> float:
    ctx = BrakePhysicsContext(
        base_decel_ms2=base_decel,
        gradient_pct=gradient_pct,
        current_accel_ms2=accel_ms2,
        brake_transition_s=brake_transition_s,
    )
    return braking_distance_mph(
        speed_mph,
        0.0,
        decel_ms2=_service_decel(base_decel, gradient_pct),
        ctx=ctx,
        apply_margin=True,
    )


def check_p1_emergency(
    *,
    target_kind: EmergencyTargetKind,
    speed_mph: float,
    urgent_dist_m: Optional[float],
    base_decel: float,
    gradient_pct: float,
    brake_transition_s: float,
    accel_ms2: Optional[float],
) -> Optional[Tuple[str, float, BrakeCommand]]:
    """
    Returns:
        (action, effective_limit, brake_command) o None.
    """
    if urgent_dist_m is None or urgent_dist_m <= 0:
        return None

    base_decel = base_decel if base_decel > 0 else DEFAULT_MAX_BRAKE_DECEL
    grad = gradient_pct or 0.0
    exceso_mph = speed_mph
    bd = _stop_distance(
        speed_mph,
        base_decel=base_decel,
        gradient_pct=grad,
        brake_transition_s=brake_transition_s,
        accel_ms2=accel_ms2,
    )

    if urgent_dist_m <= bd * 0.25 and exceso_mph > P1_CRITICO_MPH:
        _log.critical(
            "P1v2 CRITICO %s spd=%.1f dist=%.0fm exceso=%.1f",
            target_kind,
            speed_mph,
            urgent_dist_m,
            exceso_mph,
        )
        notch = (
            EMERGENCY_BRAKE_HANDLE
            if urgent_dist_m <= EMERGENCY_BRAKE_MAX_DIST_M
            else SERVICE_MIN_HANDLE
        )
        cmd = BrakeCommand(
            kind="APPLY",
            target_notch=notch,
            phase="B3",
            reason=f"P1-CRITICO-{target_kind}",
            distance_m=urgent_dist_m,
        )
        action = EMERGENCY if notch == EMERGENCY_BRAKE_HANDLE else BRAKE
        return action, 0.0, cmd

    if exceso_mph > 0 and urgent_dist_m <= bd * 0.5:
        _log.warning(
            "P1v2 EMERGENCIA %s spd=%.1f dist=%.0fm bd=%.0fm exceso=%.1f",
            target_kind,
            speed_mph,
            urgent_dist_m,
            bd,
            exceso_mph,
        )
        cmd = BrakeCommand(
            kind="APPLY",
            target_notch=SERVICE_MIN_HANDLE,
            phase="B3",
            reason=f"P1-EMERGENCIA-{target_kind}",
            distance_m=urgent_dist_m,
        )
        return BRAKE, 0.0, cmd

    return None
