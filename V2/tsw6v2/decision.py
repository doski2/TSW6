"""Un tick P1: cartel + andén + RELEASE/COAST."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    is_brake_applied,
    resolve_release_command,
)
from tsw6v2.constants import MS_TO_MPH, NEUTRAL_NOTCH
from tsw6v2.ipc import probe_lever
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.p1_emergency import EmergencyTargetKind, check_p1_emergency
from tsw6v2.p1_policy import pick_p1_brake_target
from tsw6v2.station_plan import (
    DEFAULT_STATION_CFG,
    STATION_SCHEDULE_SLACK_ENABLED,
    should_suppress_station_braking_for_departure,
)
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S, DEFAULT_MAX_BRAKE_DECEL
from tsw6v2.planning import effective_limit_mph, next_speed_limit
from tsw6v2.signal_brake import evaluate_signal_brake
from tsw6v2.signal_plan import (
    should_suppress_signal_braking_for_departure,
    signal_behind_station,
)
from tsw6v2.station_brake import evaluate_station_brake
from tsw6v2.target import BrakeTargetResult

PredictDecelFn = Callable[[int, float, float], Optional[float]]


@dataclass
class LimitBrakeDecision:
    command: Optional[BrakeCommand]
    phase: str = ""
    limit_dist_m: Optional[float] = None
    limit_mph: Optional[float] = None
    effective_mph: Optional[float] = None
    speed_mph: Optional[float] = None
    dist_start_m: Optional[float] = None
    apply_now: Optional[bool] = None
    detail: str = ""
    reason: str = ""
    handle_notch: Optional[int] = None
    fb_a_pred_ms2: Optional[float] = None
    fb_a_obs_ms2: Optional[float] = None
    fb_shortfall: bool = False
    fb_escalated: bool = False
    target_kind: str = ""
    station_dist_m: Optional[float] = None

    @classmethod
    def idle(
        cls,
        *,
        limit_dist_m: Optional[float] = None,
        limit_mph: Optional[float] = None,
        effective_mph: Optional[float] = None,
        speed_mph: Optional[float] = None,
        phase: str = "",
        dist_start_m: Optional[float] = None,
        apply_now: Optional[bool] = None,
        detail: str = "",
        reason: str = "",
    ) -> LimitBrakeDecision:
        return cls(
            None,
            phase=phase,
            limit_dist_m=limit_dist_m,
            limit_mph=limit_mph,
            effective_mph=effective_mph,
            speed_mph=speed_mph,
            dist_start_m=dist_start_m,
            apply_now=apply_now,
            detail=detail,
            reason=reason,
        )


@dataclass(frozen=True)
class _TickCtx:
    dist_m: Optional[float]
    next_limit_mph: Optional[float]
    effective: float
    speed_mph: float
    grad: float
    lever: int
    cyl: Optional[float]

    def decide(
        self,
        command: Optional[BrakeCommand],
        reason: str,
        *,
        phase: str = "",
        dist_start_m: Optional[float] = None,
        apply_now: Optional[bool] = None,
        detail: str = "",
        handle_notch: Optional[int] = None,
        fb_a_pred_ms2: Optional[float] = None,
        fb_a_obs_ms2: Optional[float] = None,
        fb_shortfall: bool = False,
        fb_escalated: bool = False,
        target_kind: str = "",
        station_dist_m: Optional[float] = None,
    ) -> LimitBrakeDecision:
        return LimitBrakeDecision(
            command,
            phase=phase,
            limit_dist_m=self.dist_m,
            limit_mph=self.next_limit_mph,
            effective_mph=self.effective,
            speed_mph=self.speed_mph,
            dist_start_m=dist_start_m,
            apply_now=apply_now,
            detail=detail,
            reason=reason,
            handle_notch=handle_notch,
            fb_a_pred_ms2=fb_a_pred_ms2,
            fb_a_obs_ms2=fb_a_obs_ms2,
            fb_shortfall=fb_shortfall,
            fb_escalated=fb_escalated,
            target_kind=target_kind,
            station_dist_m=station_dist_m,
        )

    def idle(self, reason: str, target: Optional[BrakeTargetResult] = None, **kw) -> LimitBrakeDecision:
        if target is not None:
            kw.setdefault("phase", target.phase)
            kw.setdefault("dist_start_m", target.dist_start)
            kw.setdefault("apply_now", target.apply_now)
            kw.setdefault("detail", target.detail)
            kw.setdefault("fb_a_pred_ms2", target.fb_a_pred_ms2)
            kw.setdefault("fb_a_obs_ms2", target.fb_a_obs_ms2)
            kw.setdefault("fb_shortfall", target.fb_shortfall)
            kw.setdefault("fb_escalated", target.fb_escalated)
            kw.setdefault("target_kind", target.target_kind)
            if target.target_kind == "STATION":
                kw.setdefault("station_dist_m", target.distance_m)
        return self.decide(None, reason, **kw)

    def from_target(self, cmd: BrakeCommand, target: BrakeTargetResult, reason: str) -> LimitBrakeDecision:
        fb_reason = reason
        if target.fb_escalated:
            fb_reason = "decel_feedback"
        return self.decide(
            cmd,
            fb_reason,
            phase=target.phase or (cmd.phase or ""),
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            handle_notch=cmd.target_notch,
            fb_a_pred_ms2=target.fb_a_pred_ms2,
            fb_a_obs_ms2=target.fb_a_obs_ms2,
            fb_shortfall=target.fb_shortfall,
            fb_escalated=target.fb_escalated,
            target_kind=target.target_kind,
            station_dist_m=(
                target.distance_m if target.target_kind == "STATION" else None
            ),
        )


@dataclass(frozen=True)
class _TickPrep:
    ctx: _TickCtx
    dist_m: Optional[float]
    next_limit_mph: Optional[float]
    lever: int
    escalate_cap: Optional[Callable[[int, int], int]]
    fill_s: float
    predict: Optional[PredictDecelFn]


def _throttle_notch(lever: int) -> int:
    return max(0, int(lever) - NEUTRAL_NOTCH)


def _escalate_cap_fn(
    learner: LearnerProfile,
    cyl: Optional[float],
) -> Callable[[int, int], int]:
    def _cap(prev: int, stepped: int) -> int:
        return learner.cap_escalation(
            committed=prev,
            requested=stepped,
            brake_cyl_bar=cyl,
        )

    return _cap


def _air_apply_block(
    learner: Optional[LearnerProfile],
    cmd: BrakeCommand,
    cyl: Optional[float],
    lever: int,
) -> Optional[tuple[str, str]]:
    if learner is None or cmd.kind != "APPLY":
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


def _prepare_tick(
    snap: ProbeSnapshot,
    learner: Optional[LearnerProfile],
    predict_decel: Optional[PredictDecelFn],
) -> Optional[_TickPrep]:
    if snap.speed_ms is None:
        return None
    dist_m, next_limit_mph = next_speed_limit(snap)
    lever = probe_lever(snap)
    if lever is None:
        lever = NEUTRAL_NOTCH
    ctx = _TickCtx(
        dist_m=dist_m,
        next_limit_mph=next_limit_mph,
        effective=effective_limit_mph(snap),
        speed_mph=float(snap.speed_ms) * MS_TO_MPH,
        grad=float(snap.gradient_pct or 0.0),
        lever=lever,
        cyl=snap.brake_cyl_bar,
    )
    if learner is not None:
        learner.observe_air(lever, ctx.cyl)
    return _TickPrep(
        ctx=ctx,
        dist_m=dist_m,
        next_limit_mph=next_limit_mph,
        lever=lever,
        escalate_cap=_escalate_cap_fn(learner, ctx.cyl) if learner else None,
        fill_s=learner.brake_fill_s if learner else DEFAULT_BRAKE_FILL_S,
        predict=predict_decel or (learner.predict_decel if learner else None),
    )


def _signal_distance_m(snap: ProbeSnapshot) -> Optional[float]:
    if snap.signal_red is not True or snap.signal_dist_cm is None:
        return None
    dist = float(snap.signal_dist_cm) / 100.0
    return dist if dist > 0 else None


def _decision_from_emergency(
    prep: _TickPrep,
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
) -> bool:
    """Salida en marcha: no emergencia andén a velocidad de arranque."""
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


def _attempt_p1_emergency(
    prep: _TickPrep,
    snap: ProbeSnapshot,
    *,
    station_distance_m: Optional[float] = None,
) -> Optional[LimitBrakeDecision]:
    signal_dist = _signal_distance_m(snap)
    checks: list[tuple[EmergencyTargetKind, float]] = []
    if signal_dist is not None and not signal_behind_station(
        signal_dist_m=signal_dist,
        station_dist_m=station_distance_m,
    ):
        checks.append(("SIGNAL", signal_dist))
    if station_distance_m is not None and station_distance_m > 0:
        checks.append(("STATION", float(station_distance_m)))
    throttle = _throttle_notch(prep.lever)
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


def _limit_release_allowed(
    station_dist: Optional[float],
    target: Optional[BrakeTargetResult],
    station_target: Optional[BrakeTargetResult] = None,
    signal_target: Optional[BrakeTargetResult] = None,
    signal_dist_m: Optional[float] = None,
) -> bool:
    """Modo cartel siempre; con andén solo si no hay freno STATION/SIGNAL activo."""
    if target is not None and target.target_kind == "SIGNAL":
        return False
    if (
        signal_target is not None
        and not signal_behind_station(
            signal_dist_m=signal_dist_m if signal_dist_m is not None else signal_target.distance_m,
            station_dist_m=station_dist,
        )
    ):
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


def _attempt_release(
    prep: _TickPrep,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    limit_brake_enabled: bool = True,
) -> Optional[LimitBrakeDecision]:
    if not limit_brake_enabled or not is_brake_applied(prep.lever):
        return None
    release_state.update(prep.ctx.speed_mph, prep.next_limit_mph)
    latch_ops = (
        limit_state.latch.limit_mph if limit_state.latch is not None else None
    )
    rel = resolve_release_command(
        speed_mph=prep.ctx.speed_mph,
        handle_notch=prep.lever,
        effective_limit=prep.ctx.effective,
        next_limit_mph=prep.next_limit_mph,
        distance_next_m=prep.dist_m,
        gradient_pct=prep.ctx.grad,
        latch_ops_target=latch_ops,
        accel_ms2=snap.accel_ms2,
        brake_fill_s=prep.fill_s,
        predict_decel=prep.predict,
    )
    if rel is None:
        return None
    limit_state.clear_commitment()
    if prep.next_limit_mph is not None:
        release_state.latch(prep.next_limit_mph)
    return prep.ctx.decide(
        rel,
        "release",
        phase=rel.phase or "NEU",
        detail=rel.reason,
        handle_notch=rel.target_notch,
        target_kind="SPEED_LIMIT",
    )


def _finalize_target_decision(
    ctx: _TickCtx,
    target: BrakeTargetResult,
    *,
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    learner: Optional[LearnerProfile],
    lever: int,
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
        throttle_notch=_throttle_notch(lever),
        current_notch=lever,
        speed_mph=ctx.speed_mph,
        gradient_pct=grad,
        brake_committed=(
            limit_state.committed_handle is not None
            if target.target_kind == "SPEED_LIMIT"
            else False
        ),
    )

    if cmd is None:
        return ctx.idle("command_none", target=target)
    if cmd.kind == "APPLY" and not target.apply_now:
        return ctx.idle("apply_deferred", target=target)

    air_block = _air_apply_block(learner, cmd, ctx.cyl, lever)
    if air_block is not None:
        reason, detail = air_block
        return ctx.idle(reason, target=target, detail=detail)

    decision = ctx.from_target(cmd, target, _plan_reason(cmd, target))
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
) -> LimitBrakeDecision:
    """Cartel + andén + señal → un ``BrakeCommand`` o sin mando."""
    if not limit_brake_enabled and not station_brake_enabled and not signal_brake_enabled:
        return LimitBrakeDecision.idle(reason="p1_off")

    station_dist: Optional[float] = None
    if (
        station_brake_enabled
        and station_distance_m is not None
        and station_distance_m > 0
    ):
        station_dist = float(station_distance_m)

    prep = _prepare_tick(snap, learner, predict_decel)
    if prep is None:
        return LimitBrakeDecision.idle(reason="no_speed")

    emerg = _attempt_p1_emergency(
        prep,
        snap,
        station_distance_m=station_dist if station_brake_enabled else None,
    )
    if emerg is not None:
        return emerg

    ctx = prep.ctx
    limit_target: Optional[BrakeTargetResult] = None
    if (
        limit_brake_enabled
        and prep.next_limit_mph is not None
        and prep.dist_m is not None
    ):
        posted = ctx.effective if snap.speed_limit_ms else None
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
        )

    station_target: Optional[BrakeTargetResult] = None
    if station_dist is not None:
        station_target = evaluate_station_brake(
            speed_mph=ctx.speed_mph,
            station_distance_m=station_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=_throttle_notch(prep.lever),
            station_eta=station_eta,
            schedule_slack_enabled=schedule_slack_enabled,
            brake_fill_s=prep.fill_s,
            base_decel=DEFAULT_MAX_BRAKE_DECEL,
        )

    signal_dist = _signal_distance_m(snap)
    signal_target: Optional[BrakeTargetResult] = None
    if (
        signal_brake_enabled
        and signal_dist is not None
        and not signal_behind_station(
            signal_dist_m=signal_dist,
            station_dist_m=station_dist,
        )
    ):
        signal_target = evaluate_signal_brake(
            speed_mph=ctx.speed_mph,
            signal_distance_m=signal_dist,
            gradient_pct=ctx.grad,
            predict_decel=prep.predict,
            throttle_notch=_throttle_notch(prep.lever),
            station_distance_m=station_dist,
            brake_fill_s=prep.fill_s,
            base_decel=DEFAULT_MAX_BRAKE_DECEL,
        )

    target = pick_p1_brake_target(
        speed_mph=ctx.speed_mph,
        limit_target=limit_target if limit_brake_enabled else None,
        station_target=station_target,
        signal_target=signal_target,
        signal_dist_m=signal_dist,
        limit_mph=prep.next_limit_mph,
        limit_dist_m=prep.dist_m,
        station_dist_m=station_dist,
        effective_limit=ctx.effective,
        gradient_pct=ctx.grad,
        brake_fill_s=prep.fill_s,
        accel_ms2=snap.accel_ms2,
    )

    # Tras pick: RELEASE cartel no debe soltar freno de andén/señal (sesión 123139Z).
    if _limit_release_allowed(
        station_dist, target, station_target, signal_target, signal_dist
    ):
        released = _attempt_release(
            prep,
            limit_state=limit_state,
            release_state=release_state,
            snap=snap,
            limit_brake_enabled=limit_brake_enabled,
        )
        if released is not None:
            return released

    if target is None:
        if (
            station_dist is None
            and (not limit_brake_enabled or prep.next_limit_mph is None or prep.dist_m is None)
            and signal_target is None
        ):
            return ctx.idle("no_limit_sign")
        return ctx.idle("no_plan")

    decision = _finalize_target_decision(
        ctx,
        target,
        limit_state=limit_state,
        release_state=release_state,
        snap=snap,
        learner=learner,
        lever=prep.lever,
        dist_m=prep.dist_m,
        next_limit_mph=prep.next_limit_mph,
        grad=ctx.grad,
    )
    decision.target_kind = target.target_kind
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
