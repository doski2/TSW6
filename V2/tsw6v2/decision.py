"""Un tick P1 cartel: limit_brake + RELEASE/COAST (paso 3)."""

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
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S
from tsw6v2.planning import effective_limit_mph, next_speed_limit
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
        )

    def idle(self, reason: str, target: Optional[BrakeTargetResult] = None, **kw) -> LimitBrakeDecision:
        if target is not None:
            kw.setdefault("phase", target.phase)
            kw.setdefault("dist_start_m", target.dist_start)
            kw.setdefault("apply_now", target.apply_now)
            kw.setdefault("detail", target.detail)
        return self.decide(None, reason, **kw)

    def from_target(self, cmd: BrakeCommand, target: BrakeTargetResult, reason: str) -> LimitBrakeDecision:
        return self.decide(
            cmd,
            reason,
            phase=target.phase or (cmd.phase or ""),
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            handle_notch=cmd.target_notch,
        )


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


def evaluate_limit_tick(
    limit_state: LimitBrakeState,
    release_state: BrakeReleaseState,
    snap: ProbeSnapshot,
    *,
    learner: Optional[LearnerProfile] = None,
    predict_decel: Optional[PredictDecelFn] = None,
) -> LimitBrakeDecision:
    """Cartel → ``BrakeCommand`` (APPLY / RELEASE / COAST) o sin mando."""
    if snap.speed_ms is None:
        return LimitBrakeDecision.idle(reason="no_speed")

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

    escalate_cap = _escalate_cap_fn(learner, ctx.cyl) if learner else None
    fill_s = learner.brake_fill_s if learner else DEFAULT_BRAKE_FILL_S
    predict = predict_decel or (learner.predict_decel if learner else None)

    release_state.update(ctx.speed_mph, next_limit_mph)
    if is_brake_applied(lever):
        latch_ops = (
            limit_state.latch.limit_mph if limit_state.latch is not None else None
        )
        rel = resolve_release_command(
            speed_mph=ctx.speed_mph,
            handle_notch=lever,
            effective_limit=ctx.effective,
            next_limit_mph=next_limit_mph,
            distance_next_m=dist_m,
            gradient_pct=ctx.grad,
            latch_ops_target=latch_ops,
        )
        if rel is not None:
            if next_limit_mph is not None:
                release_state.latch(next_limit_mph)
            return ctx.decide(
                rel,
                "release",
                phase=rel.phase or "NEU",
                detail=rel.reason,
                handle_notch=rel.target_notch,
            )

    if next_limit_mph is None or dist_m is None:
        return ctx.idle("no_limit_sign")

    posted = ctx.effective if snap.speed_limit_ms else None
    target = evaluate_limit_brake(
        limit_state,
        speed_mph=ctx.speed_mph,
        limit_mph=next_limit_mph,
        distance_m=dist_m,
        gradient_pct=ctx.grad,
        accel_ms2=snap.accel_ms2,
        predict_decel=predict,
        posted_limit_mph=posted,
        brake_fill_s=fill_s,
        escalate_cap=escalate_cap,
    )
    if target is None:
        return ctx.idle("no_plan")

    if release_state.should_inhibit_limit_rebrake(
        speed_mph=ctx.speed_mph,
        next_limit_mph=next_limit_mph,
        handle_notch=lever,
        plan=None,
        gradient_pct=ctx.grad,
        distance_next_m=dist_m,
        effective_limit=ctx.effective,
    ):
        return ctx.idle("coast_latch", target=target)

    cmd = target.to_brake_command(
        throttle_notch=_throttle_notch(lever),
        current_notch=lever,
        speed_mph=ctx.speed_mph,
        gradient_pct=ctx.grad,
        brake_committed=limit_state.committed_handle is not None,
    )
    if (
        target.downhill_hold
        and lever > NEUTRAL_NOTCH
        and cmd is not None
        and cmd.kind == "APPLY"
    ):
        coast = BrakeCommand(
            kind="COAST_THROTTLE",
            target_notch=NEUTRAL_NOTCH,
            reason="Quitar tracción (mantener bajada)",
        )
        return ctx.decide(
            coast,
            "coast_throttle",
            phase="NEU",
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            handle_notch=coast.target_notch,
        )

    if cmd is None:
        return ctx.idle("command_none", target=target)
    if cmd.kind == "APPLY" and not target.apply_now:
        return ctx.idle("apply_deferred", target=target)

    air_block = _air_apply_block(learner, cmd, ctx.cyl, lever)
    if air_block is not None:
        reason, detail = air_block
        return ctx.idle(reason, target=target, detail=detail)

    return ctx.from_target(cmd, target, _plan_reason(cmd, target))
