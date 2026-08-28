#!/usr/bin/env python3
"""Tipos de plan de frenado y fases B1–B3 (compartido cartel / andén)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

TargetKind = Literal["SPEED_LIMIT", "STATION", "SIGNAL"]
PredictDecelFn = Callable[[int, float, float], Optional[float]]


@dataclass
class BrakePlanStep:
    notch: str
    handle_notch: int
    phase: str
    distance_m: float
    apply_at_remaining_m: float
    dist_start: float
    meters_until_action_m: float
    apply_now: bool
    using_learned: bool = False


@dataclass
class BrakePlan:
    target_kind: TargetKind
    distance_to_target_m: float
    target_speed_mph: float
    reaction_margin_m: float
    steps: list[BrakePlanStep] = field(default_factory=list)
    active_step: Optional[BrakePlanStep] = None


@dataclass(frozen=True)
class BrakePhase:
    label: str
    handle_notch: int   # TSW: 3=B1, 2=B2, 1=B3
    fraction: float


# Class 323 UK — freno de servicio (handle 3→1)
UK_SERVICE_PHASES: tuple[BrakePhase, ...] = (
    BrakePhase("B1", 3, 0.33),
    BrakePhase("B2", 2, 0.55),
    BrakePhase("B3", 1, 0.80),
)


def resolve_phase_decel(
    phase: BrakePhase,
    speed_mph: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn] = None,
) -> tuple[float, bool]:
    """Decel (m/s²): perfil aprendido o fracción fija × base_decel."""
    from tsw6.braking.v2.physics import decel_for_notch

    if predict_decel is not None:
        learned = predict_decel(phase.handle_notch, speed_mph, gradient_pct)
        if learned is not None and learned > 0.05:
            return learned, True
    return decel_for_notch(phase.fraction, base_decel, gradient_pct), False


def notch_strength(handle_notch: int) -> int:
    """Mayor = freno más fuerte (handle 1 > handle 3)."""
    if handle_notch <= 0:
        return 4
    if handle_notch == 1:
        return 3
    if handle_notch == 2:
        return 2
    if handle_notch >= 3:
        return 1
    return 0


def prefer_weakest_step(steps: list[BrakePlanStep]) -> BrakePlanStep:
    return min(steps, key=lambda s: notch_strength(s.handle_notch))


def prefer_strongest_step(steps: list[BrakePlanStep]) -> BrakePlanStep:
    return max(steps, key=lambda s: notch_strength(s.handle_notch))


def profile_cap_from_plan(
    plan: BrakePlan,
    speed_mph: float,
    effective_limit: float,
) -> float:
    if not plan.steps:
        return effective_limit
    horizon = max(
        (s.apply_at_remaining_m for s in plan.steps),
        default=1.0,
    ) * 1.5
    cap = effective_limit
    target = plan.target_speed_mph
    if target >= speed_mph - 0.3:
        return cap
    for step in plan.steps:
        if step.dist_start > horizon:
            continue
        frac = min(1.0, max(0.0, (horizon - step.dist_start) / horizon))
        step_cap = target + (speed_mph - target) * frac
        cap = min(cap, step_cap)
    return cap
