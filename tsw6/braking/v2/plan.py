#!/usr/bin/env python3
"""Tipos de plan de frenado (BrakePlan, steps)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

TargetKind = Literal["SPEED_LIMIT", "STATION", "SIGNAL"]


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
