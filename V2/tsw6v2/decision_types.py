"""Tipos del tick P1: resultado (``LimitBrakeDecision``), contexto y preparación.

Módulo hoja de la capa de decisión (``docs/v2/DECISION_MODULOS.md``): no importa ninguna fase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from tsw6v2.command import BrakeCommand
from tsw6v2.physics import VehiclePhysics
from tsw6v2.plan import PredictDecelFn
from tsw6v2.target import BrakeTargetResult
from tsw6v2.vehicle_package import apply_vehicle_brake_actuator, vehicle_physics


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
    plan_decel_ms2: Optional[float] = None
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
class TickCtx:
    dist_m: Optional[float]
    next_limit_mph: Optional[float]
    effective: float
    speed_mph: float
    grad: float
    lever: int
    cyl: Optional[float]
    vehicle_package: Optional[dict[str, Any]] = None
    click_decel_ms2: Optional[float] = None
    mc_decel_table: Optional[dict[float, float]] = None
    physics: VehiclePhysics = field(default_factory=lambda: vehicle_physics(None))

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
        plan_decel_ms2: Optional[float] = None,
        fb_shortfall: bool = False,
        fb_escalated: bool = False,
        target_kind: str = "",
        station_dist_m: Optional[float] = None,
    ) -> LimitBrakeDecision:
        # Único sitio MC en tick P1 (323: paquete None → sin target_fraction).
        if command is not None and self.vehicle_package is not None:
            command = apply_vehicle_brake_actuator(command, self.vehicle_package)
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
            plan_decel_ms2=plan_decel_ms2,
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
            kw.setdefault("plan_decel_ms2", target.plan_decel_ms2)
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
            plan_decel_ms2=target.plan_decel_ms2,
            fb_shortfall=target.fb_shortfall,
            fb_escalated=target.fb_escalated,
            target_kind=target.target_kind,
            station_dist_m=(
                target.distance_m if target.target_kind == "STATION" else None
            ),
        )


@dataclass(frozen=True)
class TickPrep:
    ctx: TickCtx
    dist_m: Optional[float]
    next_limit_mph: Optional[float]
    lever: int
    combined_lever: int
    throttle_notch: int
    escalate_cap: Optional[Callable[[int, int], int]]
    fill_s: float
    predict: Optional[PredictDecelFn]
