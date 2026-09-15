"""Plan P1 señal roja — perfil servicio v→0 (paso 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from tsw6v2.constants import STATION_APPROACH_PRIORITY_M
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S, DEFAULT_MAX_BRAKE_DECEL

if TYPE_CHECKING:
    from tsw6v2.target import BrakeTargetResult
from tsw6v2.limit_station_cluster import exit_signal_clustered_with_platform_stop
from tsw6v2.plan import BrakePlan, PredictDecelFn
from tsw6v2.station_plan import (
    DEFAULT_STATION_CFG,
    StationBrakeConfig,
    build_immediate_stop_plan,
    plan_station_final_stop,
    plan_station_service_brake,
    should_suppress_station_braking_for_departure,
)

# Señal de salida andén: rojo a ~2 m con tracción — no frenar hasta arrancar en verde.
SIGNAL_DEPARTURE_MAX_DIST_M = 25.0
# WATCH lejos no bloquea cartel; rojo cercano (<150 m) sigue mandando señal.
SIGNAL_WATCH_LIMIT_DEFER_M = 150.0
# APPLY / parada total solo dentro de ~100 yd (152037Z: no parar a 217 m).
SIGNAL_BRAKE_HORIZON_M = 91.0
SIGNAL_IMMEDIATE_MAX_SPEED_MPH = 30.0
# Fase final ~50 yd antes del poste (terminal approach).
SIGNAL_TERMINAL_APPROACH_M = 46.0
# No soltar freno en creep dentro del horizonte (102222Z @70 m).
SIGNAL_RELEASE_BLOCK_MIN_DIST_M = 15.0
SIGNAL_RELEASE_BLOCK_MAX_SPEED_MPH = 8.0


@dataclass(frozen=True)
class SignalBrakeConfig:
    reaction_time_s: float = 1.0
    terminal_approach_m: float = SIGNAL_TERMINAL_APPROACH_M
    final_stop_max_distance_m: float = 35.0


DEFAULT_SIGNAL_CFG = SignalBrakeConfig()


def signal_behind_station(
    *,
    signal_dist_m: Optional[float],
    station_dist_m: Optional[float],
) -> bool:
    """
    True si el marcador de andén está antes que el rojo en la vía.

    Parada en andén, no al semáforo de salida (150617Z: stn 120 m, sig 280 m).
    Salida: sig más cerca que stn (29 m vs 31 m) → False → señal manda.
    """
    if signal_dist_m is None or station_dist_m is None:
        return False
    if signal_dist_m <= 0 or station_dist_m <= 0:
        return False
    return station_dist_m < signal_dist_m


def exit_signal_close_behind_platform(
    *,
    signal_dist_m: Optional[float],
    station_dist_m: Optional[float],
) -> bool:
    """Rojo de salida tras marker del andén pero dentro del horizonte (~91 m, 213920Z)."""
    if signal_dist_m is None or signal_dist_m <= 0:
        return False
    return signal_behind_station(
        signal_dist_m=signal_dist_m,
        station_dist_m=station_dist_m,
    ) and signal_dist_m <= SIGNAL_BRAKE_HORIZON_M


def signal_deferred_to_station_at_platform(
    *,
    signal_dist_m: Optional[float],
    station_dist_m: Optional[float],
    max_station_dist_m: float = STATION_APPROACH_PRIORITY_M,
) -> bool:
    """
    Geometría donde la parada es el andén, no el poste (150617Z, 164240Z).

    - Rojo **lejos** detrás del marker (``stn < sig``, 150617Z).
    - Rojo **pegado** al marker con marker delante del poste (cluster 164240Z).
    """
    if signal_behind_station(
        signal_dist_m=signal_dist_m,
        station_dist_m=station_dist_m,
    ):
        return not exit_signal_close_behind_platform(
            signal_dist_m=signal_dist_m,
            station_dist_m=station_dist_m,
        )
    return exit_signal_clustered_with_platform_stop(
        signal_dist_m,
        station_dist_m,
        max_station_dist_m=max_station_dist_m,
    )


def signal_in_play(
    *,
    signal_dist_m: Optional[float],
    station_dist_m: Optional[float],
) -> bool:
    """True si el rojo cuenta para plan/bloqueo (lejos detrás del marker: no)."""
    if signal_dist_m is None or signal_dist_m <= 0:
        return False
    if signal_behind_station(
        signal_dist_m=signal_dist_m,
        station_dist_m=station_dist_m,
    ):
        return exit_signal_close_behind_platform(
            signal_dist_m=signal_dist_m,
            station_dist_m=station_dist_m,
        )
    return True


def signal_apply_horizon_m(speed_mph: float) -> float:
    """
    Horizonte APPLY: ~100 yd en marcha moderada; hasta 150 m si spd >30 mph (155148Z).

    Lejos (217 m @ 20 mph) sigue WATCH — no repetir parada temprana 152037Z.
    """
    if speed_mph > SIGNAL_IMMEDIATE_MAX_SPEED_MPH:
        return SIGNAL_WATCH_LIMIT_DEFER_M
    return SIGNAL_BRAKE_HORIZON_M


def signal_in_brake_horizon(signal_dist_m: float, speed_mph: float = 0.0) -> bool:
    """True si el poste está dentro del horizonte APPLY para esta velocidad."""
    return 0 < signal_dist_m <= signal_apply_horizon_m(speed_mph)


def resolve_signal_dist_m(
    signal_dist_m: Optional[float],
    signal_target: Optional["BrakeTargetResult"] = None,
) -> Optional[float]:
    """Distancia al poste: probe primero, luego objetivo planificado."""
    if signal_dist_m is not None:
        return signal_dist_m
    if signal_target is not None:
        return signal_target.distance_m
    return None


def signal_within_pick_priority_m(
    signal_dist_m: Optional[float],
    signal_target: Optional["BrakeTargetResult"] = None,
) -> bool:
    """Rojo dentro de 150 m — prioridad pick sobre cartel (155148Z)."""
    dist = resolve_signal_dist_m(signal_dist_m, signal_target)
    return dist is not None and dist <= SIGNAL_WATCH_LIMIT_DEFER_M


def should_block_creep_release_from_signal(
    *,
    signal_dist_m: Optional[float],
    speed_mph: Optional[float],
) -> bool:
    """Creep dentro del horizonte (~100 yd): no RELEASE hasta el poste (102222Z)."""
    if signal_dist_m is None or speed_mph is None:
        return False
    horizon = signal_apply_horizon_m(speed_mph or 0.0)
    if signal_dist_m > horizon:
        return False
    return (
        signal_dist_m > SIGNAL_RELEASE_BLOCK_MIN_DIST_M
        and speed_mph < SIGNAL_RELEASE_BLOCK_MAX_SPEED_MPH
    )


def should_suppress_signal_braking_for_departure(
    *,
    speed_mph: float,
    signal_distance_m: float,
    throttle_notch: int,
    station_distance_m: Optional[float] = None,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
) -> bool:
    """Parado/salida en andén: rojo de salida a pocos m con tracción — esperar verde."""
    if signal_distance_m > SIGNAL_DEPARTURE_MAX_DIST_M:
        return False
    if speed_mph > cfg.departure_speed_mph:
        return False
    stn = station_distance_m
    if stn is not None and stn > cfg.dwell_max_distance_m:
        # HUD puede apuntar al siguiente andén (km); salida = señal a ~2 m.
        stn = signal_distance_m
    return should_suppress_station_braking_for_departure(
        speed_mph=speed_mph,
        station_distance_m=stn if stn is not None else signal_distance_m,
        throttle_notch=throttle_notch,
        cfg=cfg,
    )


def _plan_to_signal(plan: BrakePlan) -> BrakePlan:
    return BrakePlan(
        target_kind="SIGNAL",
        distance_to_target_m=plan.distance_to_target_m,
        target_speed_mph=0.0,
        reaction_margin_m=plan.reaction_margin_m,
        steps=plan.steps,
        active_step=plan.active_step,
    )


def _immediate_signal_plan(signal_distance_m: float, speed_mph: float) -> BrakePlan:
    return _plan_to_signal(
        build_immediate_stop_plan(signal_distance_m, max(speed_mph, 0.1))
    )


def plan_brake_for_signal(
    *,
    speed_mph: float,
    signal_distance_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
    throttle_notch: int = 0,
    station_distance_m: Optional[float] = None,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
    station_cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
    signal_cfg: SignalBrakeConfig = DEFAULT_SIGNAL_CFG,
) -> Optional[BrakePlan]:
    """Plan gradual a 0 frente a semáforo rojo (sin holgura de horario)."""
    if signal_distance_m <= 0:
        return None
    if should_suppress_signal_braking_for_departure(
        speed_mph=speed_mph,
        signal_distance_m=signal_distance_m,
        throttle_notch=throttle_notch,
        station_distance_m=station_distance_m,
        cfg=station_cfg,
    ):
        return None
    if speed_mph <= 0.5:
        # Crawl dentro de ~100 yd (143544Z); lejos → sin plan (acercar con cartel).
        if (
            signal_in_brake_horizon(signal_distance_m, speed_mph)
            and signal_distance_m > SIGNAL_RELEASE_BLOCK_MIN_DIST_M
        ):
            return _immediate_signal_plan(signal_distance_m, speed_mph)
        return None

    final_stop = plan_station_final_stop(
        speed_mph=speed_mph,
        station_distance_m=signal_distance_m,
        throttle_notch=throttle_notch,
        cfg=station_cfg,
    )
    if final_stop is not None:
        return _plan_to_signal(final_stop)

    station_cfg_signal = StationBrakeConfig(
        final_stop_max_distance_m=signal_cfg.final_stop_max_distance_m,
        platform_tail_m=station_cfg.platform_tail_m,
        final_stop_speed_mph=station_cfg.final_stop_speed_mph,
        hold_max_speed_mph=station_cfg.hold_max_speed_mph,
        departure_speed_mph=station_cfg.departure_speed_mph,
        dwell_max_distance_m=station_cfg.dwell_max_distance_m,
        terminal_approach_m=signal_cfg.terminal_approach_m,
        station_reaction_time_s=signal_cfg.reaction_time_s,
    )
    plan = plan_station_service_brake(
        speed_mph=speed_mph,
        station_distance_m=signal_distance_m,
        gradient_pct=gradient_pct,
        base_decel=base_decel,
        predict_decel=predict_decel,
        station_eta=None,
        cfg=station_cfg_signal,
        schedule_slack_enabled=False,
        brake_fill_s=brake_fill_s,
        min_speed_ms=0.35,
    )
    if (
        speed_mph > 0.5
        and signal_in_brake_horizon(signal_distance_m, speed_mph)
        and (
            plan is None
            or plan.active_step is None
            or not plan.active_step.apply_now
        )
    ):
        return _immediate_signal_plan(signal_distance_m, speed_mph)
    if plan is None:
        return None
    return _plan_to_signal(plan)
