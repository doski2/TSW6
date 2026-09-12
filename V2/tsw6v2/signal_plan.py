"""Plan P1 señal roja — perfil servicio v→0 (paso 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tsw6v2.physics import DEFAULT_BRAKE_FILL_S, DEFAULT_MAX_BRAKE_DECEL, MPH_TO_MS
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
# Andén mucho más cerca que la señal → priorizar parada en andén (PLAN_V2 §3).
SIGNAL_BEHIND_STATION_GAP_M = 50.0


@dataclass(frozen=True)
class SignalBrakeConfig:
    reaction_time_s: float = 1.0
    terminal_approach_m: float = 80.0
    final_stop_max_distance_m: float = 35.0


DEFAULT_SIGNAL_CFG = SignalBrakeConfig()


def signal_behind_station(
    *,
    signal_dist_m: Optional[float],
    station_dist_m: Optional[float],
    gap_m: float = SIGNAL_BEHIND_STATION_GAP_M,
) -> bool:
    """True si el andén está ≥gap_m más cerca que la señal (foco en STATION)."""
    if signal_dist_m is None or station_dist_m is None:
        return False
    if signal_dist_m <= 0 or station_dist_m <= 0:
        return False
    return station_dist_m + gap_m < signal_dist_m


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
    if speed_mph * MPH_TO_MS < 0.5:
        return None
    if should_suppress_signal_braking_for_departure(
        speed_mph=speed_mph,
        signal_distance_m=signal_distance_m,
        throttle_notch=throttle_notch,
        station_distance_m=station_distance_m,
        cfg=station_cfg,
    ):
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
    )
    if plan is None and signal_distance_m < 120.0 and speed_mph > 2.0:
        plan = build_immediate_stop_plan(signal_distance_m, speed_mph)
    if plan is None:
        return None
    return _plan_to_signal(plan)
