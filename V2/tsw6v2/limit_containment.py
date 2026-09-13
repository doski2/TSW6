"""HOLD_DH y contención bajada — ver REGLAS_FRENOS_P1.md."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from tsw6v2.constants import (
    posted_zone_hold_ceiling_mph,
    posted_zone_coast_floor_mph,
)
from tsw6v2.planning import (
    is_ascending_limit_exit,
    is_descending_limit_zone,
    should_skip_zone_hold_for_ascending_exit,
)
from tsw6v2.limit_horizon import within_next_brake_horizon
from tsw6v2.limit_notch import apply_notch_hysteresis, phase_for_handle
from tsw6v2.limit_state import LimitBrakeState
from tsw6v2.physics import (
    MPH_TO_MS,
    apply_zone_margin_m,
    is_downhill_gradient,
    is_uphill_gradient,
)
from tsw6v2.target import BrakeTargetResult

if TYPE_CHECKING:
    from tsw6v2.command import BrakeReleaseState

# Re-export para tests y callers existentes.
from tsw6v2.limit_horizon import next_limit_brake_horizon_m  # noqa: F401


def _hold_detail(posted_limit_mph: float, hold_target: float) -> str:
    return (
        f"Mantener bajada @{hold_target:.1f} mph "
        f"(posted {posted_limit_mph:.0f})"
    )


def _build_downhill_hold_result(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    hold_target: float,
    gradient_pct: float,
    next_distance_m: Optional[float],
    detail: str,
) -> BrakeTargetResult:
    speed_ms = speed_mph * MPH_TO_MS
    start_handle = 3
    handle, phase = apply_notch_hysteresis(
        state,
        handle=start_handle,
        phase=phase_for_handle(start_handle),
        dist_start=0.0,
        apply_now=True,
        apply_zone_m=apply_zone_margin_m(speed_ms, 0.0),
        speed_mph=speed_mph,
        limit_mph=hold_target,
        gradient_pct=gradient_pct,
    )
    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=next_distance_m if next_distance_m is not None else 0.0,
        target_speed_mph=hold_target,
        handle_notch=handle,
        phase=phase,
        dist_start=0.0,
        apply_now=True,
        downhill_hold=True,
        detail=detail,
    )


def _hold_if_over_zone_ceiling(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_distance_m: Optional[float],
    release_state: Optional[BrakeReleaseState] = None,
) -> Optional[BrakeTargetResult]:
    if release_state is not None and release_state.should_inhibit_downhill_hold(
        speed_mph,
        posted_limit_mph,
    ):
        return None
    hold_target = posted_zone_hold_ceiling_mph(posted_limit_mph, gradient_pct)
    if speed_mph <= hold_target:
        return None
    return _build_downhill_hold_result(
        state,
        speed_mph=speed_mph,
        hold_target=hold_target,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
        detail=_hold_detail(posted_limit_mph, hold_target),
    )


def _defer_zone_contain_for_next_horizon(
    *,
    speed_mph: float,
    posted_limit_mph: float,
    next_limit_mph: Optional[float],
    next_distance_m: Optional[float],
    gradient_pct: float,
) -> bool:
    """Dentro del horizonte BRAKE_LIMIT al next: no HOLD zona vigente."""
    return (
        next_limit_mph is not None
        and next_distance_m is not None
        and is_descending_limit_zone(posted_limit_mph, next_limit_mph)
        and within_next_brake_horizon(
            speed_mph=speed_mph,
            next_limit_mph=next_limit_mph,
            next_distance_m=next_distance_m,
            gradient_pct=gradient_pct,
        )
    )


def try_current_zone_contain(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
    release_state: Optional[BrakeReleaseState] = None,
) -> Optional[BrakeTargetResult]:
    """
    Techo zona vigente lejos del next (60.5 @ +0.3 %%, 60.2 @ −1 %%).

    60→55/50 lejos: B1 suave si superas posted+margen; el techo depende de la
    pendiente vía ``posted_zone_hold_ceiling_mph`` (sesiones 204031Z, 203100Z).
    """
    if _defer_zone_contain_for_next_horizon(
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        gradient_pct=gradient_pct,
    ):
        return None
    # Salida lenta→rápida en cuesta: no HOLD_DH (sesión 201456Z: 45→60 @ +1 %%).
    if (
        is_uphill_gradient(gradient_pct)
        and is_ascending_limit_exit(posted_limit_mph, next_limit_mph)
    ):
        return None
    return _hold_if_over_zone_ceiling(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
        release_state=release_state,
    )


# Mínimo sobre posted para vigilar/coast (no arrancar desde 0 mph en andén).
_DOWNHILL_COAST_WATCH_MIN_UNDER_POSTED_MPH = 5.0


def try_downhill_coast_watch(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """
    Vigilar bajada bajo techo HOLD: WATCH + ``COAST_THROTTLE`` si hay tracción.

    Sesión 150916Z: ~28 mph en zona 30 con P6 hasta superar 30.2 sin soltar.
    """
    del state
    if not is_downhill_gradient(gradient_pct):
        return None
    if _defer_zone_contain_for_next_horizon(
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        gradient_pct=gradient_pct,
    ):
        return None
    hold_target = posted_zone_hold_ceiling_mph(posted_limit_mph, gradient_pct)
    if speed_mph >= hold_target:
        return None
    if speed_mph < posted_limit_mph - _DOWNHILL_COAST_WATCH_MIN_UNDER_POSTED_MPH:
        return None
    return BrakeTargetResult(
        target_kind="SPEED_LIMIT",
        distance_m=next_distance_m if next_distance_m is not None else 0.0,
        target_speed_mph=hold_target,
        handle_notch=4,
        phase="WATCH",
        dist_start=0.0,
        apply_now=False,
        detail=(
            f"Vigilar bajada @{hold_target:.1f} mph "
            f"(posted {posted_limit_mph:.0f})"
        ),
    )


def try_posted_downhill_hold(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
    release_state: Optional[BrakeReleaseState] = None,
) -> Optional[BrakeTargetResult]:
    """
    HOLD_DH — cartel siguiente no baja (60→60).

    En 60→55 lejos del cartel usar ``try_current_zone_contain``.
    """
    if not is_downhill_gradient(gradient_pct):
        return None

    if is_descending_limit_zone(posted_limit_mph, next_limit_mph):
        return None

    if next_limit_mph is not None and next_distance_m is not None:
        if within_next_brake_horizon(
            speed_mph=speed_mph,
            next_limit_mph=next_limit_mph,
            next_distance_m=next_distance_m,
            gradient_pct=gradient_pct,
        ):
            return None

    return _hold_if_over_zone_ceiling(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_distance_m=next_distance_m,
        release_state=release_state,
    )


def pick_downhill_containment(
    state: LimitBrakeState,
    *,
    speed_mph: float,
    posted_limit_mph: float,
    gradient_pct: float,
    next_limit_mph: Optional[float] = None,
    next_distance_m: Optional[float] = None,
    release_state: Optional[BrakeReleaseState] = None,
) -> Optional[BrakeTargetResult]:
    """Zona vigente lejos del next o HOLD_DH (60→60 en bajada)."""
    if release_state is not None:
        release_state.update_downhill_zone(speed_mph, posted_limit_mph)
    if should_skip_zone_hold_for_ascending_exit(posted_limit_mph, next_limit_mph):
        return None
    zone = try_current_zone_contain(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        release_state=release_state,
    )
    if zone is not None:
        return zone
    held = try_posted_downhill_hold(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
        release_state=release_state,
    )
    if held is not None:
        return held
    return try_downhill_coast_watch(
        state,
        speed_mph=speed_mph,
        posted_limit_mph=posted_limit_mph,
        gradient_pct=gradient_pct,
        next_limit_mph=next_limit_mph,
        next_distance_m=next_distance_m,
    )


def downhill_brake_release_floor_mph(
    *,
    speed_mph: float,
    effective_limit: float,
    next_limit_mph: float,
    distance_next_m: float,
    gradient_pct: float,
    release_over_mph: float,
) -> Optional[float]:
    """
    Suelo RELEASE en bajada (ops + 0.5).

    - Acercándose al cartel next (55→45): soltar ~44.5, también en horizonte.
    - Zona vigente lejos del next (60→55): coast ~59.5.
    - Subida de cartel (15→50 lejos, 10→30 en horizonte): coast ~14.5 / ~9.5 en zona vigente
      (sesiones `081745Z`, `142034Z`).
    - En banda zona vigente tras frenar (45 @ ~44.5): no seguir con B1 hasta 40.
    """
    if not is_downhill_gradient(gradient_pct):
        return None

    in_horizon = within_next_brake_horizon(
        speed_mph=speed_mph,
        next_limit_mph=next_limit_mph,
        next_distance_m=distance_next_m,
        gradient_pct=gradient_pct,
    )
    ascending_exit = is_ascending_limit_exit(effective_limit, next_limit_mph)
    if not in_horizon or ascending_exit:
        eff_floor = posted_zone_coast_floor_mph(effective_limit)
        ceiling = posted_zone_hold_ceiling_mph(effective_limit, gradient_pct)
        if eff_floor <= speed_mph <= ceiling:
            return eff_floor
        if eff_floor - 1.0 <= speed_mph <= eff_floor + release_over_mph:
            return eff_floor

    if ascending_exit:
        return None

    next_floor = posted_zone_coast_floor_mph(next_limit_mph)
    if speed_mph <= next_floor + release_over_mph:
        return next_floor

    return None
