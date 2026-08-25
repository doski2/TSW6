#!/usr/bin/env python3
"""
Overrides P1-CRITICO / P1-EMERGENCIA — solo parada total.

Aplica únicamente a:
  - andén (velocidad objetivo 0 mph)
  - semáforo en rojo (DANGER)

Los carteles de velocidad usan el plan B1–B3 normal (sin emergencia).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional, Tuple

from tsw6.braking.v2.command import BrakeCommand
from tsw6.braking.v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    BrakePhysicsContext,
    braking_distance_mph,
    decel_for_notch,
)
from tsw6.autopilot.control_actions import BRAKE, EMERGENCY
from tsw6.governor.governor_constants import (
    EMERGENCY_BRAKE_HANDLE,
    EMERGENCY_BRAKE_MAX_DIST_M,
    P1_CRITICO_DIST,
    P1_CRITICO_MPH,
    P1_EMERGENCIA_DIST,
    P1_EMERGENCIA_MPH,
    SERVICE_MIN_HANDLE,
)

_log = logging.getLogger("tsw.governor.v2")

_UK_SERVICE_FRAC = 0.80
EmergencyTargetKind = Literal["STATION", "SIGNAL"]
_RED_SIGNAL_ASPECTS = frozenset({"DANGER", "RED", "STOP"})


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

    if urgent_dist_m <= P1_CRITICO_DIST and exceso_mph > P1_CRITICO_MPH:
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

    if (exceso_mph > 0 and urgent_dist_m <= bd * 0.5) or (
        urgent_dist_m <= P1_EMERGENCIA_DIST and exceso_mph > P1_EMERGENCIA_MPH
    ):
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
