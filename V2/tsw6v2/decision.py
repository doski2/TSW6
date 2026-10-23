"""Un tick P1: cartel + andén + RELEASE/COAST."""

from __future__ import annotations

from typing import Optional

from tsw6v2.plan import PredictDecelFn
from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand, BrakeReleaseState
from tsw6v2.decision_emergency import attempt_p1_emergency
from tsw6v2.decision_mc import (
    continue_station_stop,
    mc_limit_fraction,
    mc_station_stop_fraction,
    station_stop_continues,
)
from tsw6v2.decision_prep import brake_applied, brake_kind, prepare_tick, signal_distance_m
from tsw6v2.decision_release import (
    attempt_departing_brake_release,
    attempt_p1_releases,
    attempt_platform_parked_bleed,
    attempt_platform_parked_bleed_release,
)
from tsw6v2.decision_types import LimitBrakeDecision, TickCtx
from tsw6v2.p1_station_gate import (
    departure_limit_target_or_coast,
    should_skip_p1_release,
)
from tsw6v2.constants import LIMIT_SIGN_PASSED_M
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.p1_policy import (
    limit_release_allowed,
    pick_p1_brake_target,
    should_allow_station_watch_when_deferred,
)
from tsw6v2.station_plan import (
    STATION_SCHEDULE_SLACK_ENABLED,
    station_within_dwell_zone,
)
from tsw6v2.signal_brake import evaluate_signal_brake
from tsw6v2.signal_plan import signal_in_play
from tsw6v2.station_brake import (
    evaluate_station_brake,
    station_distance_for_brake_plan,
)
from tsw6v2.target import BrakeTargetResult


def _overlay_active_zone_hold(
    pick: Optional[BrakeTargetResult],
    limit_target: Optional[BrakeTargetResult],
) -> Optional[BrakeTargetResult]:
    """
    HOLD_DH activo manda aunque el pick sea STATION/SIGNAL WATCH (173809Z).

    ``p1tgt`` sigue siendo el pick; el mando usa contención de zona.
    """
    if (
        limit_target is None
        or not limit_target.apply_now
        or not limit_target.downhill_hold
    ):
        return pick
    if pick is None:
        return limit_target
    if pick.target_kind == "SPEED_LIMIT" and pick.apply_now:
        return pick
    if pick.target_kind in ("STATION", "SIGNAL") and not pick.apply_now:
        return limit_target
    return pick


def _air_apply_block(
    learner: Optional[LearnerProfile],
    cmd: BrakeCommand,
    cyl: Optional[float],
    lever: int,
) -> Optional[tuple[str, str]]:
    if learner is None or cmd.kind != "APPLY":
        return None
    if cmd.target_fraction is not None:
        return None
    if cmd.target_notch is not None and int(cmd.target_notch) == int(lever):
        return None
    if learner.inhibit_reapply(cyl):
        return ("air_recharge", "Esperar recarga aire tras soltar")
    if not learner.air_ready(cyl, lever=lever):
        return ("air_fill", "Esperando presión cilindro")
    return None


def _plan_reason(cmd: BrakeCommand, target: BrakeTargetResult) -> str:
    if cmd.kind == "RELEASE":
        return "release"
    if cmd.kind == "COAST_THROTTLE":
        return "coast_throttle"
    if target.downhill_hold and cmd.kind == "APPLY":
        return "downhill_hold"
    return "plan"




def _finalize_target_decision(
    ctx: TickCtx,
    target: BrakeTargetResult,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    learner: Optional[LearnerProfile],
    lever: int,
    throttle_notch: int,
    dist_m: Optional[float],
    next_limit_mph: Optional[float],
    grad: float,
) -> LimitBrakeDecision:
    """Convierte ``BrakeTargetResult`` ganador en ``LimitBrakeDecision``."""
    if target.target_kind == "SPEED_LIMIT" and release_state.should_inhibit_limit_rebrake(
        speed_mph=ctx.speed_mph,
        next_limit_mph=next_limit_mph,
        handle_notch=lever,
        plan=None,
        gradient_pct=grad,
        distance_next_m=dist_m,
        effective_limit=ctx.effective,
    ):
        return ctx.idle("coast_latch", target=target)

    cmd = target.to_brake_command(
        throttle_notch=throttle_notch,
        current_notch=lever,
        speed_mph=ctx.speed_mph,
        gradient_pct=grad,
        brake_committed=(
            limit_state.committed_handle is not None
            if target.target_kind == "SPEED_LIMIT"
            else False
        ),
    )
    cmd = mc_station_stop_fraction(cmd, target, ctx, limit_state)
    cmd = mc_limit_fraction(cmd, target, ctx, limit_state)

    if cmd is None or (cmd.kind == "APPLY" and not target.apply_now):
        continued = continue_station_stop(ctx, limit_state, target)
        if continued is not None:
            return continued
        if cmd is None:
            return ctx.idle("command_none", target=target)
        return ctx.idle("apply_deferred", target=target)

    air_block = _air_apply_block(learner, cmd, ctx.cyl, lever)
    if air_block is not None:
        reason, detail = air_block
        return ctx.idle(reason, target=target, detail=detail)

    decision = ctx.from_target(cmd, target, _plan_reason(cmd, target))
    if (
        cmd.target_notch is None
        and cmd.target_fraction is not None
        and target.target_kind == "STATION"
    ):
        decision.phase = cmd.phase or ""
        decision.handle_notch = None
    decision.target_kind = target.target_kind
    decision.station_dist_m = (
        target.distance_m if target.target_kind == "STATION" else None
    )
    return decision


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

    signal_dist = signal_distance_m(snap)
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

    if (
        limit_state.station_stop_m is not None
        and not station_stop_continues(limit_state, station_dist_geo, ctx.speed_mph)
    ):
        limit_state.station_stop_m = None

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

    command_target = _overlay_active_zone_hold(target, limit_target)
    if command_target is None:
        if (
            station_dist_geo is None
            and (not limit_brake_enabled or prep.next_limit_mph is None or prep.dist_m is None)
            and signal_target is None
        ):
            return ctx.idle("no_limit_sign")
        continued = continue_station_stop(
            ctx, limit_state, station_target, station_dist_geo
        )
        if continued is not None:
            return continued
        return ctx.idle("no_plan", target=target)

    decision = _finalize_target_decision(
        ctx,
        command_target,
        limit_state=limit_state,
        release_state=release_state,
        snap=snap,
        learner=learner,
        lever=prep.lever,
        throttle_notch=prep.throttle_notch,
        dist_m=prep.dist_m,
        next_limit_mph=prep.next_limit_mph,
        grad=ctx.grad,
    )
    if target is not None:
        decision.target_kind = target.target_kind
        if target.target_kind == "STATION":
            decision.station_dist_m = target.distance_m
    return decision


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
