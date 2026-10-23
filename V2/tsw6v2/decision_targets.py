"""Fases de objetivos del tick P1: cartel, andén y señal (cada una devuelve su ``BrakeTargetResult``).

No son puras: ``evaluate_limit_brake`` confirma estado en ``limit_state`` y el andén llama a
``learner.observe_brake_decel``. El orden de llamada lo fija ``evaluate_p1_tick`` (ver
DECISION_MODULOS.md, «Matiz a la regla 3»).
"""

from __future__ import annotations

from typing import Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision_prep import brake_applied, brake_kind
from tsw6v2.decision_types import TickCtx, TickPrep
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.p1_policy import should_allow_station_watch_when_deferred
from tsw6v2.p1_station_gate import departure_limit_target_or_coast
from tsw6v2.signal_brake import evaluate_signal_brake
from tsw6v2.signal_plan import signal_in_play
from tsw6v2.station_brake import evaluate_station_brake, station_distance_for_brake_plan
from tsw6v2.station_plan import station_within_dwell_zone
from tsw6v2.target import BrakeTargetResult


def evaluate_limit_target(
    ctx: TickCtx,
    prep: TickPrep,
    snap: ProbeSnapshot,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    learner: Optional[LearnerProfile],
    limit_brake_enabled: bool,
    station_dist_geo: Optional[float],
    station_fsm: Optional[str],
) -> Optional[BrakeTargetResult]:
    limit_target: Optional[BrakeTargetResult] = None
    posted = ctx.effective if snap.speed_limit_ms else None
    if limit_brake_enabled and (
        (prep.next_limit_mph is not None and prep.dist_m is not None)
        or posted is not None
    ):
        limit_target = evaluate_limit_brake(
            limit_state,
            speed_mph=ctx.speed_mph,
            limit_mph=prep.next_limit_mph,
            distance_m=prep.dist_m,
            gradient_pct=ctx.grad,
            accel_ms2=snap.accel_ms2,
            predict_decel=prep.predict,
            posted_limit_mph=posted,
            brake_fill_s=prep.fill_s,
            escalate_cap=prep.escalate_cap,
            learner=learner,
            lever=prep.lever,
            brake_cyl_bar=ctx.cyl,
            release_state=release_state,
            brake_kind=brake_kind(snap.train_brake, snap.dyn_brake),
            brake_applied=brake_applied(snap.train_brake, snap.dyn_brake),
            base_decel=ctx.physics.max_decel_ms2,
        )
        limit_target = departure_limit_target_or_coast(
            limit_target,
            limit_state,
            speed_mph=ctx.speed_mph,
            station_dist_m=station_dist_geo,
            combined_lever=prep.combined_lever,
            station_fsm=station_fsm,
            posted_limit_mph=posted,
            gradient_pct=ctx.grad,
            next_limit_mph=prep.next_limit_mph,
            next_distance_m=prep.dist_m,
        )
    return limit_target


def evaluate_station_target(
    ctx: TickCtx,
    prep: TickPrep,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile],
    station_dist: Optional[float],
    station_eta: Optional[str],
    schedule_slack_enabled: bool,
) -> Optional[BrakeTargetResult]:
    station_target: Optional[BrakeTargetResult] = None
    station_plan_dist = station_distance_for_brake_plan(station_dist, ctx.speed_mph)
    if station_plan_dist is not None:
        station_allow_watch = should_allow_station_watch_when_deferred(
            speed_mph=ctx.speed_mph,
            station_dist_m=station_plan_dist,
            limit_mph=prep.next_limit_mph,
            limit_dist_m=prep.dist_m,
            gradient_pct=ctx.grad,
            brake_fill_s=prep.fill_s,
            accel_ms2=snap.accel_ms2,
        ) or station_within_dwell_zone(station_plan_dist)
        station_target = evaluate_station_brake(
            speed_mph=ctx.speed_mph,
            station_distance_m=station_plan_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=prep.throttle_notch,
            station_eta=station_eta,
            schedule_slack_enabled=schedule_slack_enabled,
            brake_fill_s=prep.fill_s,
            base_decel=ctx.physics.max_decel_ms2,
            allow_watch=station_allow_watch,
            plan_decel_ms2=ctx.physics.station_plan_decel_ms2,
        )
        if (
            learner is not None
            and station_target is not None
            and station_target.apply_now
            and station_target.handle_notch in (1, 2, 3)
        ):
            learner.observe_brake_decel(
                handle=station_target.handle_notch,
                speed_mph=ctx.speed_mph,
                gradient_pct=ctx.grad,
                accel_ms2=snap.accel_ms2,
                lever=prep.lever,
                brake_cyl_bar=ctx.cyl,
                brake_kind=brake_kind(snap.train_brake, snap.dyn_brake),
                brake_applied=brake_applied(snap.train_brake, snap.dyn_brake),
            )
    return station_target


def evaluate_signal_target(
    ctx: TickCtx,
    prep: TickPrep,
    *,
    signal_brake_enabled: bool,
    signal_dist: Optional[float],
    station_dist_geo: Optional[float],
) -> Optional[BrakeTargetResult]:
    signal_target: Optional[BrakeTargetResult] = None
    if (
        signal_brake_enabled
        and signal_in_play(
            signal_dist_m=signal_dist,
            station_dist_m=station_dist_geo,
        )
    ):
        signal_target = evaluate_signal_brake(
            speed_mph=ctx.speed_mph,
            signal_distance_m=signal_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=prep.throttle_notch,
            station_distance_m=station_dist_geo,
            brake_fill_s=prep.fill_s,
            base_decel=ctx.physics.max_decel_ms2,
        )
    return signal_target
