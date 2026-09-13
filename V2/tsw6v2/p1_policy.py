"""Prioridad cartel ↔ andén (cluster Four Oaks / Sutton)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.limit_station_cluster import (
    limit_sign_beyond_station,
    merged_approach_overspeed,
    should_merge_limit_and_station_plans,
    station_may_ignore_limit_approach,
    station_waits_for_approach_limit,
)
from tsw6v2.constants import LIMIT_RELEASE_MAX_OVER_MPH, STATION_APPROACH_PRIORITY_M
from tsw6v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    TARGET_CLUSTER_GAP_M,
    brake_ctx_for_decel,
    braking_distance_mph,
    decel_for_notch,
)
from tsw6v2.plan import SERVICE_DECEL_FRAC_BY_HANDLE
from tsw6v2.signal_plan import (
    resolve_signal_dist_m,
    should_block_creep_release_from_signal,
    signal_deferred_to_station_at_platform,
    signal_in_play,
    signal_within_pick_priority_m,
)
from tsw6v2.target import BrakeTargetResult

# Margen sobre bd(v→0): sesión 20260909T224556Z entró STATION tarde @ 444 m.
HORIZON_SLACK_M = 10.0
# Por debajo: cartel WATCH no gana al andén si el servicio ya debe planificar.
STATION_APPROACH_MIN_SPEED_MPH = 15.0


def _active_limit_or_none(
    limit_target: Optional[BrakeTargetResult],
) -> Optional[BrakeTargetResult]:
    """Solo cartel con APPLY; WATCH no es objetivo P1 con andén diferido."""
    if limit_target is None or not limit_target.apply_now:
        return None
    return limit_target


def _ignorable_limit_on_deferred_approach(
    *,
    speed_mph: float,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
) -> bool:
    """Cartel WATCH next en cluster sin exigir freno (164240Z: 50 tras zona 15)."""
    if (
        limit_mph is None
        or limit_dist_m is None
        or station_dist_m is None
        or limit_dist_m > STATION_APPROACH_PRIORITY_M
    ):
        return False
    return station_may_ignore_limit_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    )


def should_allow_station_watch_when_deferred(
    *,
    speed_mph: float,
    station_dist_m: Optional[float],
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    gradient_pct: float = 0.0,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    accel_ms2: Optional[float] = None,
) -> bool:
    """
    Andén diferido pero cartel next ignorable en cluster (164240Z: 50 tras zona 15).

    No activar con cartel 15 real delante (153551Z).
    """
    if station_dist_m is None or station_dist_m <= 0:
        return False
    if station_dist_m > STATION_APPROACH_PRIORITY_M:
        return False
    if not should_defer_station_brake(
        speed_mph=speed_mph,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        brake_fill_s=brake_fill_s,
    ):
        return False
    return _ignorable_limit_on_deferred_approach(
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    )


def _deferred_station_limit_target(
    limit_target: Optional[BrakeTargetResult],
    limit_dist_m: Optional[float],
    *,
    speed_mph: float = 0.0,
    limit_mph: Optional[float] = None,
    station_dist_m: Optional[float] = None,
    gradient_pct: float = 0.0,
    accel_ms2: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """
    Andén lejos: APPLY siempre; WATCH solo si cartel next <600 m (153551Z).

    Cartel WATCH lejano → None (221258Z salida andén).
    Cartel ignorable en cluster (50 tras zona 15) → None (164240Z).
    """
    active = _active_limit_or_none(limit_target)
    if active is not None:
        return active
    if (
        limit_target is not None
        and limit_dist_m is not None
        and limit_dist_m <= STATION_APPROACH_PRIORITY_M
    ):
        if _ignorable_limit_on_deferred_approach(
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
        ):
            return None
        return limit_target
    return None


def _resolve_deferred_station_pick(
    *,
    limit_target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult],
    limit_dist_m: Optional[float],
    speed_mph: float,
    limit_mph: Optional[float],
    station_dist_m: Optional[float],
    gradient_pct: float,
    accel_ms2: Optional[float],
) -> Optional[BrakeTargetResult]:
    deferred_limit = _deferred_station_limit_target(
        limit_target,
        limit_dist_m,
        speed_mph=speed_mph,
        limit_mph=limit_mph,
        station_dist_m=station_dist_m,
        gradient_pct=gradient_pct,
        accel_ms2=accel_ms2,
    )
    if deferred_limit is not None:
        return deferred_limit
    if station_target is not None and not station_target.apply_now:
        return station_target
    return None


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
    if speed_mph < STATION_APPROACH_MIN_SPEED_MPH:
        return False
    if limit_sign_beyond_station(limit_dist_m, station_dist_m):
        return station_dist_m <= STATION_APPROACH_PRIORITY_M + TARGET_CLUSTER_GAP_M
    if station_dist_m > STATION_APPROACH_PRIORITY_M:
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


def should_prefer_signal_over_limit(
    signal_target: BrakeTargetResult,
    limit_target: BrakeTargetResult,
    *,
    signal_dist_m: Optional[float] = None,
) -> bool:
    """
    Rojo gana al cartel si APPLY o cerca del poste.

    WATCH lejos no bloquea HOLD_DH / BRAKE_LIMIT (102222Z: zona 15 @20 mph,
    señal WATCH @283 m).
    """
    if signal_target.apply_now:
        return True
    return signal_within_pick_priority_m(signal_dist_m, signal_target)


def should_prefer_signal_over_station(
    signal_target: BrakeTargetResult,
    station_target: BrakeTargetResult,
    *,
    signal_dist_m: Optional[float] = None,
) -> bool:
    """Parada a 0: gana el objetivo más cercano (salida andén: señal antes que marcador)."""
    sig_dist = resolve_signal_dist_m(signal_dist_m, signal_target)
    if signal_deferred_to_station_at_platform(
        signal_dist_m=sig_dist,
        station_dist_m=station_target.distance_m,
        max_station_dist_m=STATION_APPROACH_PRIORITY_M,
    ):
        return False
    if signal_target.apply_now and not station_target.apply_now:
        return True
    if not signal_target.apply_now and station_target.apply_now:
        return False
    return signal_target.distance_m <= station_target.distance_m


def limit_release_allowed(
    station_dist: Optional[float],
    target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult] = None,
    signal_target: Optional[BrakeTargetResult] = None,
    signal_dist_m: Optional[float] = None,
    speed_mph: Optional[float] = None,
) -> bool:
    """Modo cartel siempre; con andén solo si no hay freno STATION/SIGNAL activo."""
    if target is not None and target.target_kind == "SIGNAL":
        return False
    sig_dist = resolve_signal_dist_m(signal_dist_m, signal_target)
    signal_active = signal_in_play(
        signal_dist_m=sig_dist,
        station_dist_m=station_dist,
    )
    # Solo bloquear creep si el rojo es obstáculo real (no salida tras andén, 150617Z).
    if (
        signal_active
        and should_block_creep_release_from_signal(
            signal_dist_m=sig_dist,
            speed_mph=speed_mph,
        )
    ):
        return False
    if signal_target is not None and signal_target.apply_now and signal_active:
        return False
    if station_dist is None:
        return True
    if target is not None and target.target_kind == "STATION":
        return False
    if target is not None and target.target_kind == "SPEED_LIMIT":
        return True
    if station_target is not None and station_target.apply_now:
        return False
    # pick=None (andén lejos): aún soltar HOLD_DH / BRAKE_LIMIT (sesión 224046Z).
    return True


def _pick_limit_station_target(
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
    """Elige cartel o andén (sin señal)."""
    station_deferred: Optional[bool] = None
    if station_dist_m is not None:
        station_deferred = should_defer_station_brake(
            speed_mph=speed_mph,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
            brake_fill_s=brake_fill_s,
        )

    if station_target is None:
        if station_deferred:
            return _resolve_deferred_station_pick(
                limit_target=limit_target,
                station_target=None,
                limit_dist_m=limit_dist_m,
                speed_mph=speed_mph,
                limit_mph=limit_mph,
                station_dist_m=station_dist_m,
                gradient_pct=gradient_pct,
                accel_ms2=accel_ms2,
            )
        return limit_target
    if limit_target is None:
        if station_dist_m is None:
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

    if station_deferred:
        return _resolve_deferred_station_pick(
            limit_target=limit_target,
            station_target=station_target,
            limit_dist_m=limit_dist_m,
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            station_dist_m=station_dist_m,
            gradient_pct=gradient_pct,
            accel_ms2=accel_ms2,
        )

    if limit_target.urgency <= station_target.urgency:
        return limit_target
    return station_target


def pick_p1_brake_target(
    *,
    speed_mph: float,
    limit_target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult],
    signal_target: Optional[BrakeTargetResult] = None,
    signal_dist_m: Optional[float] = None,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    effective_limit: Optional[float] = None,
    gradient_pct: float = 0.0,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    accel_ms2: Optional[float] = None,
) -> Optional[BrakeTargetResult]:
    """Elige un solo objetivo P1 (cartel, andén o señal)."""
    chosen = _pick_limit_station_target(
        speed_mph=speed_mph,
        limit_target=limit_target,
        station_target=station_target,
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        effective_limit=effective_limit,
        gradient_pct=gradient_pct,
        brake_fill_s=brake_fill_s,
        accel_ms2=accel_ms2,
    )
    if signal_target is None:
        return chosen
    if not signal_in_play(
        signal_dist_m=resolve_signal_dist_m(signal_dist_m, signal_target),
        station_dist_m=station_dist_m,
    ):
        return chosen
    if chosen is None:
        return signal_target
    if chosen.target_kind == "STATION":
        if should_prefer_signal_over_station(
            signal_target,
            chosen,
            signal_dist_m=signal_dist_m,
        ):
            return signal_target
        return chosen
    if should_prefer_signal_over_limit(
        signal_target,
        chosen,
        signal_dist_m=signal_dist_m,
    ):
        return signal_target
    return chosen
