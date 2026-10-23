"""Un tick P1: cartel + andén + RELEASE/COAST."""

from __future__ import annotations

from typing import Optional

from tsw6v2.plan import PredictDecelFn
from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision_emergency import attempt_p1_emergency
from tsw6v2.decision_finalize import finalize_p1_decision
from tsw6v2.decision_mc import station_stop_continues
from tsw6v2.decision_prep import prepare_tick, signal_distance_m
from tsw6v2.decision_release import (
    attempt_departing_brake_release,
    attempt_p1_releases,
    attempt_platform_parked_bleed,
    attempt_platform_parked_bleed_release,
)
from tsw6v2.decision_targets import (
    evaluate_limit_target,
    evaluate_signal_target,
    evaluate_station_target,
)
from tsw6v2.decision_types import LimitBrakeDecision
from tsw6v2.p1_station_gate import should_skip_p1_release
from tsw6v2.constants import LIMIT_SIGN_PASSED_M, STATION_PLAN_LOST_RELEASE_TICKS
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_policy import limit_release_allowed, pick_p1_brake_target
from tsw6v2.station_plan import STATION_SCHEDULE_SLACK_ENABLED
from tsw6v2.vehicle_adapter import adapter_for_package
from tsw6v2.target import BrakeTargetResult


def evaluate_p1_tick(
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile] = None,
    predict_decel: Optional[PredictDecelFn] = None,
    station_distance_m: Optional[float] = None,
    station_eta: Optional[str] = None,
    schedule_slack_enabled: bool = STATION_SCHEDULE_SLACK_ENABLED,
    limit_brake_enabled: bool = True,
    station_brake_enabled: bool = True,
    signal_brake_enabled: bool = True,
    station_fsm: Optional[str] = None,
    platform_bleed_episode: bool = False,
    platform_bleed_b1_confirmed: bool = False,
) -> LimitBrakeDecision:
    """Cartel + andén + señal → un ``BrakeCommand`` o sin mando."""
    if not limit_brake_enabled and not station_brake_enabled and not signal_brake_enabled:
        return LimitBrakeDecision.idle(reason="p1_off")

    station_dist_geo: Optional[float] = None
    if station_distance_m is not None and station_distance_m > 0:
        station_dist_geo = float(station_distance_m)
    # ``station_dist``: plan STATION; ``station_dist_geo``: señal/release/FSM geometría.
    station_dist: Optional[float] = (
        station_dist_geo if station_brake_enabled else None
    )

    prep = prepare_tick(snap, learner, predict_decel)
    if prep is None:
        return LimitBrakeDecision.idle(reason="no_speed")

    emerg = attempt_p1_emergency(
        prep,
        snap,
        station_distance_m=station_dist_geo,
        station_fsm=station_fsm,
    )
    if emerg is not None:
        return emerg

    ctx = prep.ctx
    limit_target = evaluate_limit_target(
        ctx,
        prep,
        snap,
        limit_state=limit_state,
        release_state=release_state,
        learner=learner,
        limit_brake_enabled=limit_brake_enabled,
        station_dist_geo=station_dist_geo,
        station_fsm=station_fsm,
    )
    station_target = evaluate_station_target(
        ctx,
        prep,
        snap,
        learner=learner,
        station_dist=station_dist,
        station_eta=station_eta,
        schedule_slack_enabled=schedule_slack_enabled,
    )
    signal_dist = signal_distance_m(snap)
    signal_target = evaluate_signal_target(
        ctx,
        prep,
        signal_brake_enabled=signal_brake_enabled,
        signal_dist=signal_dist,
        station_dist_geo=station_dist_geo,
    )

    target = pick_p1_brake_target(
        speed_mph=ctx.speed_mph,
        limit_target=limit_target if limit_brake_enabled else None,
        station_target=station_target,
        signal_target=signal_target,
        signal_dist_m=signal_dist,
        limit_mph=prep.next_limit_mph,
        limit_dist_m=prep.dist_m,
        station_dist_m=station_dist_geo,
        effective_limit=ctx.effective,
        gradient_pct=ctx.grad,
        brake_fill_s=prep.fill_s,
        accel_ms2=snap.accel_ms2,
    )

    notch_layout = not adapter_for_package(ctx.vehicle_package).analog_lever
    if limit_state.station_stop_m is not None and notch_layout:
        if station_target is not None and station_target.apply_now:
            limit_state.station_plan_lost_ticks = 0
        else:
            limit_state.station_plan_lost_ticks += 1
            if limit_state.station_plan_lost_ticks >= STATION_PLAN_LOST_RELEASE_TICKS:
                limit_state.station_stop_m = None
    if (
        limit_state.station_stop_m is not None
        and not station_stop_continues(limit_state, station_dist_geo, ctx.speed_mph)
    ):
        limit_state.station_stop_m = None
    if limit_state.station_stop_m is None:
        limit_state.station_plan_lost_ticks = 0

    def _limit_release_ok(pick: Optional[BrakeTargetResult]) -> bool:
        if station_stop_continues(limit_state, station_dist_geo, ctx.speed_mph):
            return False
        return limit_release_allowed(
            station_dist_geo,
            pick,
            station_target,
            signal_target,
            signal_dist,
            speed_mph=ctx.speed_mph,
        )

    platform_bleed = attempt_platform_parked_bleed(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
        platform_bleed_episode=platform_bleed_episode,
        snap=snap,
    )
    if platform_bleed is not None:
        return platform_bleed

    platform_bleed_release = attempt_platform_parked_bleed_release(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
        platform_bleed_episode=platform_bleed_episode,
        platform_bleed_b1_confirmed=platform_bleed_b1_confirmed,
        snap=snap,
        station_stop_running=limit_state.station_stop_m is not None,
        other_target_active=bool(
            (limit_target is not None and limit_target.apply_now)
            or (signal_target is not None and signal_target.apply_now)
            or (limit_target is not None and limit_target.downhill_hold)
        ),
        limit_sign_passed=prep.dist_m is not None and prep.dist_m <= LIMIT_SIGN_PASSED_M,
    )
    if platform_bleed_release is not None:
        return platform_bleed_release

    departing_release = attempt_departing_brake_release(
        ctx,
        prep,
        station_fsm=station_fsm,
        station_dist_m=station_dist_geo,
    )
    if departing_release is not None:
        return departing_release

    skip_release = should_skip_p1_release(
        speed_mph=ctx.speed_mph,
        station_dist_m=station_dist_geo,
        combined_lever=prep.combined_lever,
        station_fsm=station_fsm,
        brake_cyl_bar=prep.ctx.cyl,
        platform_bleed_episode=platform_bleed_episode,
    )
    # Parado en andén (323): el freno de puertas lo manda el bucle y se suelta en DEPARTING;
    # soltar por el cartel pelea con él (APPLY puertas ↔ RELEASE cada tick, 20261023T214704Z).
    skip_release = skip_release or (station_fsm == "STOPPED" and notch_layout)
    if not skip_release:
        released = attempt_p1_releases(
            ctx,
            prep,
            limit_state=limit_state,
            release_state=release_state,
            snap=snap,
            target=target,
            station_target=station_target,
            signal_target=signal_target,
            limit_target=limit_target if limit_brake_enabled else None,
            limit_release_ok=_limit_release_ok,
            limit_brake_enabled=limit_brake_enabled,
            signal_brake_enabled=signal_brake_enabled,
        )
        if released is not None:
            return released

    return finalize_p1_decision(
        ctx,
        prep,
        snap,
        target=target,
        limit_target=limit_target,
        station_target=station_target,
        signal_target=signal_target,
        limit_state=limit_state,
        release_state=release_state,
        learner=learner,
        limit_brake_enabled=limit_brake_enabled,
        station_dist_geo=station_dist_geo,
    )


def evaluate_limit_tick(
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile] = None,
    predict_decel: Optional[PredictDecelFn] = None,
) -> LimitBrakeDecision:
    """Cartel → ``BrakeCommand`` (delega en ``evaluate_p1_tick``)."""
    return evaluate_p1_tick(
        limit_state,
        release_state,
        snap,
        learner=learner,
        predict_decel=predict_decel,
        station_brake_enabled=False,
        limit_brake_enabled=True,
    )
