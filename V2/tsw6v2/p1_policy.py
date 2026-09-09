"""Prioridad cartel ↔ andén (cluster Four Oaks / Sutton)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.limit_station_cluster import (
    merged_approach_overspeed,
    should_merge_limit_and_station_plans,
    station_may_ignore_limit_approach,
    station_waits_for_approach_limit,
)
from tsw6v2.constants import LIMIT_RELEASE_MAX_OVER_MPH
from tsw6v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    brake_ctx_for_decel,
    braking_distance_mph,
    decel_for_notch,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE
from tsw6v2.target import BrakeTargetResult

# Margen sobre bd(v→0): sesión 20260909T224556Z entró STATION tarde @ 444 m.
HORIZON_SLACK_M = 15.0
# Por debajo: cartel WATCH no gana al andén si el servicio ya debe planificar.
STATION_APPROACH_PRIORITY_M = 600.0
STATION_APPROACH_MIN_SPEED_MPH = 15.0


def should_defer_station_brake(
    *,
    speed_mph: float,
    station_dist_m: float,
    gradient_pct: float = 0.0,
    base_decel_ms2: float = DEFAULT_MAX_BRAKE_DECEL,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> bool:
    """No emitir STATION hasta horizonte v→0 de servicio (+ slack)."""
    if station_dist_m <= 0:
        return True
    decel = decel_for_notch(SERVICE_DECEL_FRAC_BY_HANDLE[1], base_decel_ms2)
    ctx = brake_ctx_for_decel(
        gradient_pct=gradient_pct,
        using_learned=False,
        base_decel_ms2=base_decel_ms2,
        brake_transition_s=brake_fill_s,
    )
    bd = braking_distance_mph(
        speed_mph,
        0.0,
        decel_ms2=decel,
        ctx=ctx,
        apply_margin=True,
    )
    return station_dist_m > bd + HORIZON_SLACK_M


def should_prefer_station_in_approach(
    *,
    speed_mph: float,
    station_dist_m: float,
    limit_target: BrakeTargetResult,
    limit_mph: Optional[float] = None,
    limit_dist_m: Optional[float] = None,
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
) -> bool:
    """
    Andén <600 m: priorizar STATION si el cartel no exige freno.

    - WATCH / sin APPLY (regla previa).
    - Ya bajo el cartel siguiente y la proyección al pasarlo sigue legal.
    """
    if station_dist_m > STATION_APPROACH_PRIORITY_M:
        return False
    if speed_mph < STATION_APPROACH_MIN_SPEED_MPH:
        return False
    if station_may_ignore_limit_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return True
    return not limit_target.apply_now


def is_unified_limit_station_stop(
    *,
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
) -> bool:
    if limit_dist_m is None or station_dist_m is None:
        return False
    if limit_dist_m <= 0 or station_dist_m <= 0:
        return False
    return should_merge_limit_and_station_plans(limit_dist_m, station_dist_m)


def should_delay_unified_station_plan(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float] = None,
    station_dist_m: Optional[float] = None,
    unified: bool,
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
) -> bool:
    """Cartel primero en parada unificada (gap ≤ 350 m)."""
    if not unified or limit_mph is None:
        return False
    if station_may_ignore_limit_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return False
    return speed_mph > limit_mph + LIMIT_RELEASE_MAX_OVER_MPH


def pick_p1_brake_target(
    *,
    speed_mph: float,
    limit_target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult],
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    effective_limit: Optional[float] = None,
    gradient_pct: float = 0.0,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    accel_ms2: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """Elige un solo objetivo P1 (cartel o andén)."""
    if station_target is None:
        return limit_target
    if limit_target is None:
        if station_dist_m is None:
            return None
        if should_defer_station_brake(
            speed_mph=speed_mph,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
            brake_fill_s=brake_fill_s,
        ):
            return None
        return station_target

    if station_dist_m is None:
        return limit_target

    if station_waits_for_approach_limit(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        current_limit_mph=effective_limit,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return limit_target

    if merged_approach_overspeed(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return limit_target

    unified = is_unified_limit_station_stop(
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
    )
    if should_delay_unified_station_plan(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        unified=unified,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return limit_target

    deferred = should_defer_station_brake(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        brake_fill_s=brake_fill_s,
    )

    if should_prefer_station_in_approach(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        limit_target=limit_target,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    ):
        return station_target

    if deferred:
        # Cartel APPLY gana; WATCH no debe ocultar que aún no toca andén.
        return limit_target if limit_target.apply_now else None

    if limit_target.urgency <= station_target.urgency:
        return limit_target
    return station_target
