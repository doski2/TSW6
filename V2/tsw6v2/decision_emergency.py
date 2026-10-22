"""Fase 2 del tick P1: emergencia de andén / señal roja (``docs/v2/DECISION_MODULOS.md``)."""

from __future__ import annotations

from typing import Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand
from tsw6v2.decision_prep import signal_distance_m
from tsw6v2.decision_types import LimitBrakeDecision, TickPrep
from tsw6v2.p1_emergency import EmergencyTargetKind, check_p1_emergency
from tsw6v2.signal_plan import (
    should_suppress_signal_braking_for_departure,
    signal_in_play,
)
from tsw6v2.station_brake import station_distance_for_brake_plan
from tsw6v2.station_plan import (
    DEFAULT_STATION_CFG,
    should_suppress_station_braking_for_departure,
)


def _decision_from_emergency(
    prep: TickPrep,
    cmd: BrakeCommand,
    *,
    target_kind: EmergencyTargetKind,
    distance_m: float,
) -> LimitBrakeDecision:
    station_dist = distance_m if target_kind == "STATION" else None
    return prep.ctx.decide(
        cmd,
        "emergency",
        phase=cmd.phase or "B3",
        dist_start_m=distance_m,
        apply_now=True,
        detail=cmd.reason,
        handle_notch=cmd.target_notch,
        target_kind=target_kind,
        station_dist_m=station_dist,
    )


def _station_emergency_suppressed(
    *,
    speed_mph: float,
    station_distance_m: float,
    throttle_notch: int,
    station_fsm: Optional[str] = None,
) -> bool:
    """Salida en marcha: no emergencia andén a velocidad de arranque."""
    if station_fsm == "DEPARTING":
        from tsw6v2.station_plan import is_departure_creep_context

        if is_departure_creep_context(
            station_distance_m,
            speed_mph,
            station_fsm=station_fsm,
        ):
            return True
    if not should_suppress_station_braking_for_departure(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        throttle_notch=throttle_notch,
    ):
        return False
    cap = DEFAULT_STATION_CFG.departure_speed_mph * 1.35
    return speed_mph <= cap


def _signal_emergency_suppressed(
    *,
    speed_mph: float,
    signal_distance_m: float,
    throttle_notch: int,
    station_distance_m: Optional[float] = None,
) -> bool:
    """Misma ventana que el plan gradual: rojo de salida con tracción lenta."""
    return should_suppress_signal_braking_for_departure(
        speed_mph=speed_mph,
        signal_distance_m=signal_distance_m,
        throttle_notch=throttle_notch,
        station_distance_m=station_distance_m,
    )


def attempt_p1_emergency(
    prep: TickPrep,
    snap: ProbeSnapshot,
    *,
    station_distance_m: Optional[float] = None,
    station_fsm: Optional[str] = None,
) -> Optional[LimitBrakeDecision]:
    signal_dist = signal_distance_m(snap)
    checks: list[tuple[EmergencyTargetKind, float]] = []
    if (
        signal_dist is not None
        and signal_in_play(
            signal_dist_m=signal_dist,
            station_dist_m=station_distance_m,
        )
    ):
        checks.append(("SIGNAL", signal_dist))
    if station_distance_m is not None:
        emerg_stn = station_distance_for_brake_plan(
            station_distance_m,
            prep.ctx.speed_mph,
        )
        if emerg_stn is not None:
            checks.append(("STATION", emerg_stn))
    throttle = prep.throttle_notch
    for kind, dist in checks:
        if (
            kind == "SIGNAL"
            and _signal_emergency_suppressed(
                speed_mph=prep.ctx.speed_mph,
                signal_distance_m=dist,
                throttle_notch=throttle,
                station_distance_m=station_distance_m,
            )
        ):
            continue
        if (
            kind == "STATION"
            and _station_emergency_suppressed(
                speed_mph=prep.ctx.speed_mph,
                station_distance_m=dist,
                throttle_notch=throttle,
                station_fsm=station_fsm,
            )
        ):
            continue
        cmd = check_p1_emergency(
            target_kind=kind,
            speed_mph=prep.ctx.speed_mph,
            urgent_dist_m=dist,
            gradient_pct=prep.ctx.grad,
            brake_transition_s=prep.fill_s,
            accel_ms2=snap.accel_ms2,
        )
        if cmd is not None:
            return _decision_from_emergency(prep, cmd, target_kind=kind, distance_m=dist)
    return None
