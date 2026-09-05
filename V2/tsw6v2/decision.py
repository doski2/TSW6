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
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S
from tsw6v2.ipc import probe_lever
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.planning import effective_limit_mph, next_speed_limit

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


def _throttle_notch(lever: int) -> int:
    return max(0, int(lever) - NEUTRAL_NOTCH)


def _from_target(
    cmd: BrakeCommand,
    *,
    target_phase: str,
    target,
    effective: float,
    speed_mph: float,
    dist_m: Optional[float],
    next_limit_mph: Optional[float],
    reason: str,
) -> LimitBrakeDecision:
    return LimitBrakeDecision(
        cmd,
        phase=target_phase or (cmd.phase or ""),
        limit_dist_m=dist_m,
        limit_mph=next_limit_mph,
        effective_mph=effective,
        speed_mph=speed_mph,
        dist_start_m=target.dist_start,
        apply_now=target.apply_now,
        detail=target.detail,
        reason=reason,
        handle_notch=cmd.target_notch,
    )


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
    speed_mph = float(snap.speed_ms) * MS_TO_MPH
    lever = probe_lever(snap)
    if lever is None:
        lever = NEUTRAL_NOTCH
    effective = effective_limit_mph(snap)
    grad = float(snap.gradient_pct or 0.0)
    predict = predict_decel or (learner.predict_decel if learner else None)
    brake_fill_s = learner.brake_fill_s if learner else None

    fill_s = brake_fill_s if brake_fill_s is not None else DEFAULT_BRAKE_FILL_S
    cyl = snap.brake_cyl_bar

    if learner is not None and lever is not None:
        learner.observe_air(int(lever), cyl)

    escalate_cap: Callable[[int, int], int] | None = None
    if learner is not None:

        def _escalate_cap(prev: int, stepped: int) -> int:
            return learner.cap_escalation(
                committed=prev,
                requested=stepped,
                brake_cyl_bar=cyl,
            )

        escalate_cap = _escalate_cap

    release_state.update(speed_mph, next_limit_mph)
    if is_brake_applied(lever):
        rel = resolve_release_command(
            speed_mph=speed_mph,
            handle_notch=lever,
            effective_limit=effective,
            next_limit_mph=next_limit_mph,
            distance_next_m=dist_m,
            gradient_pct=grad,
        )
        if rel is not None:
            if next_limit_mph is not None:
                release_state.latch(next_limit_mph)
            return LimitBrakeDecision(
                rel,
                phase=rel.phase or "NEU",
                limit_dist_m=dist_m,
                limit_mph=next_limit_mph,
                effective_mph=effective,
                speed_mph=speed_mph,
                detail=rel.reason,
                reason="release",
                handle_notch=rel.target_notch,
            )

    if next_limit_mph is None or dist_m is None:
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            reason="no_limit_sign",
        )

    posted = effective_limit_mph(snap) if snap.speed_limit_ms else None
    target = evaluate_limit_brake(
        limit_state,
        speed_mph=speed_mph,
        limit_mph=next_limit_mph,
        distance_m=dist_m,
        gradient_pct=grad,
        accel_ms2=snap.accel_ms2,
        predict_decel=predict,
        posted_limit_mph=posted,
        brake_fill_s=fill_s,
        escalate_cap=escalate_cap,
    )
    if target is None:
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            reason="no_plan",
        )

    if release_state.should_inhibit_limit_rebrake(
        speed_mph=speed_mph,
        next_limit_mph=next_limit_mph,
        handle_notch=lever,
        plan=None,
        gradient_pct=grad,
        distance_next_m=dist_m,
        effective_limit=effective,
    ):
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            phase=target.phase,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            reason="coast_latch",
        )

    cmd = target.to_brake_command(
        throttle_notch=_throttle_notch(lever),
        current_notch=lever,
        speed_mph=speed_mph,
        gradient_pct=grad,
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
        return LimitBrakeDecision(
            coast,
            phase="NEU",
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            reason="coast_throttle",
            handle_notch=coast.target_notch,
        )
    if cmd is None:
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            phase=target.phase,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            reason="command_none",
        )
    if cmd.kind == "APPLY" and not target.apply_now:
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            phase=target.phase,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail=target.detail,
            reason="apply_deferred",
        )
    if (
        learner is not None
        and cmd.kind == "APPLY"
        and learner.inhibit_reapply(cyl)
    ):
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            phase=target.phase,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail="Esperar recarga aire tras soltar",
            reason="air_recharge",
        )
    if (
        learner is not None
        and cmd.kind == "APPLY"
        and not learner.air_ready(cyl)
    ):
        return LimitBrakeDecision.idle(
            limit_dist_m=dist_m,
            limit_mph=next_limit_mph,
            effective_mph=effective,
            speed_mph=speed_mph,
            phase=target.phase,
            dist_start_m=target.dist_start,
            apply_now=target.apply_now,
            detail="Esperando presión cilindro",
            reason="air_fill",
        )
    reason = "release" if cmd.kind == "RELEASE" else "plan"
    if cmd.kind == "COAST_THROTTLE":
        reason = "coast_throttle"
    elif target.downhill_hold and cmd.kind == "APPLY":
        reason = "downhill_hold"
    return _from_target(
        cmd,
        target_phase=target.phase,
        target=target,
        effective=effective,
        speed_mph=speed_mph,
        dist_m=dist_m,
        next_limit_mph=next_limit_mph,
        reason=reason,
    )
