"""Emergencia P1 andén / señal (FLUJO_FRENOS escala #2)."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from tsw6v2.command import BrakeCommand
from tsw6v2.constants import (
    EMERGENCY_BRAKE_HANDLE,
    EMERGENCY_BRAKE_MAX_DIST_M,
    P1_CRITICO_MPH,
    SERVICE_MIN_HANDLE,
)
from tsw6v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    brake_ctx_for_decel,
    braking_distance_mph,
    decel_for_notch,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE

_log = logging.getLogger("tsw6v2.p1_emergency")

EmergencyTargetKind = Literal["STATION", "SIGNAL"]


def _service_decel(base_decel: float) -> float:
    return decel_for_notch(SERVICE_DECEL_FRAC_BY_HANDLE[1], base_decel)


def _stop_distance(
    speed_mph: float,
    *,
    base_decel: float,
    gradient_pct: float,
    brake_transition_s: float,
    accel_ms2: Optional[float],
) -> float:
    ctx = brake_ctx_for_decel(
        gradient_pct=gradient_pct,
        using_learned=False,
        current_accel_ms2=accel_ms2,
        brake_transition_s=brake_transition_s,
        base_decel_ms2=base_decel,
    )
    return braking_distance_mph(
        speed_mph,
        0.0,
        decel_ms2=_service_decel(base_decel),
        ctx=ctx,
        apply_margin=True,
    )


def check_p1_emergency(
    *,
    target_kind: EmergencyTargetKind,
    speed_mph: float,
    urgent_dist_m: Optional[float],
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    gradient_pct: float = 0.0,
    brake_transition_s: float = DEFAULT_BRAKE_FILL_S,
    accel_ms2: Optional[float] = None,
) -> Optional[BrakeCommand]:
    """B3 / notch 0 si distancia crítica al objetivo."""
    if urgent_dist_m is None or urgent_dist_m <= 0:
        return None

    base = base_decel if base_decel > 0 else DEFAULT_MAX_BRAKE_DECEL
    grad = gradient_pct or 0.0
    bd = _stop_distance(
        speed_mph,
        base_decel=base,
        gradient_pct=grad,
        brake_transition_s=brake_transition_s,
        accel_ms2=accel_ms2,
    )

    if urgent_dist_m <= bd * 0.25 and speed_mph > P1_CRITICO_MPH:
        _log.critical(
            "P1v2 CRITICO %s spd=%.1f dist=%.0fm",
            target_kind,
            speed_mph,
            urgent_dist_m,
        )
        notch = (
            EMERGENCY_BRAKE_HANDLE
            if urgent_dist_m <= EMERGENCY_BRAKE_MAX_DIST_M
            else SERVICE_MIN_HANDLE
        )
        return BrakeCommand(
            kind="APPLY",
            target_notch=notch,
            phase="B3",
            reason=f"P1-CRITICO-{target_kind}",
            distance_m=urgent_dist_m,
        )

    if speed_mph > 0 and urgent_dist_m <= bd * 0.5:
        _log.warning(
            "P1v2 EMERGENCIA %s spd=%.1f dist=%.0fm bd=%.0fm",
            target_kind,
            speed_mph,
            urgent_dist_m,
            bd,
        )
        return BrakeCommand(
            kind="APPLY",
            target_notch=SERVICE_MIN_HANDLE,
            phase="B3",
            reason=f"P1-EMERGENCIA-{target_kind}",
            distance_m=urgent_dist_m,
        )

    return None
