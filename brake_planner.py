#!/usr/bin/env python3
"""
brake_planner.py — Planificación de frenado estilo Dastsc/Nexus.

Puerto simplificado de ``planBrake.ts`` para TSW6 (Class 323 UK, mando 0–8).
Genera pasos B1→B3 con ``distStart`` y elige el paso activo según zona de
aplicación, pendiente y urgencia entre varios objetivos (límites en cola).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

MPH_TO_MS = 0.44704
G_MSS = 9.80665

# Dastsc physics.ts
APPLY_NOW_MARGIN_M = 150.0
APPLY_NOW_MARGIN_MIN_M = 25.0
TARGET_CLUSTER_GAP_M = 350.0
DOWNHILL_LIMIT_GRADIENT_PCT = -0.3  # ‰ -3 en Dastsc
DEFAULT_MAX_BRAKE_DECEL = 0.80
DEFAULT_BRAKE_FILL_S = 2.5
DEFAULT_REACTION_S = 1.5

TargetKind = Literal["SPEED_LIMIT", "STATION"]


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


PredictDecelFn = Callable[[int, float, float], Optional[float]]


@dataclass
class BrakePlan:
    target_kind: TargetKind
    distance_to_target_m: float
    target_speed_mph: float
    reaction_margin_m: float
    steps: list[BrakePlanStep] = field(default_factory=list)
    active_step: Optional[BrakePlanStep] = None


# ── Física (Dastsc physics.ts) ────────────────────────────────────────────────

def gravity_acceleration_ms2(gradient_pct: float) -> float:
    return G_MSS * (gradient_pct / 100.0)


def apply_zone_margin_m(speed_ms: float, apply_at_remaining_m: float) -> float:
    speed_based = speed_ms * 2.5
    remaining_based = apply_at_remaining_m * 0.12
    return min(
        APPLY_NOW_MARGIN_M,
        max(APPLY_NOW_MARGIN_MIN_M, speed_based, remaining_based),
    )


def is_in_apply_zone(dist_start: float, apply_zone_m: float) -> bool:
    if dist_start < 0:
        return True
    return dist_start <= apply_zone_m


def low_speed_reaction_scale(speed_ms: float, target_speed_ms: float) -> float:
    if speed_ms <= 0.5:
        return 1.0
    delta = max(0.0, speed_ms - target_speed_ms)
    ratio = delta / speed_ms
    return max(0.35, min(1.0, ratio / 0.4))


def reaction_margin_m(
    speed_ms: float,
    fill_time_s: float = DEFAULT_BRAKE_FILL_S,
    reaction_time_s: Optional[float] = None,
) -> float:
    if reaction_time_s is not None and reaction_time_s > 0:
        return speed_ms * reaction_time_s
    return speed_ms * min(4.0, DEFAULT_REACTION_S + fill_time_s)


def braking_distance_m(
    speed_ms: float,
    target_speed_ms: float,
    decel_ms2: float,
) -> float:
    if decel_ms2 <= 0:
        return float("inf")
    if speed_ms <= target_speed_ms:
        return 0.0
    return (speed_ms ** 2 - target_speed_ms ** 2) / (2.0 * decel_ms2)


def decel_for_notch(
    fraction: float,
    base_decel: float,
    gradient_pct: float,
) -> float:
    grav = gravity_acceleration_ms2(gradient_pct)
    return max(base_decel * fraction + grav, 0.05)


def resolve_phase_decel(
    phase: BrakePhase,
    speed_mph: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn] = None,
) -> tuple[float, bool]:
    """
  Decel (m/s²) para una fase del plan.

  Si hay perfil aprendido (OnlineLearner), usa ``predict_decel``;
  si no, cae a fracción fija × base_decel (como Dastsc sin brakeStats).
    """
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


def _prefer_weakest(steps: list[BrakePlanStep]) -> BrakePlanStep:
    return min(steps, key=lambda s: notch_strength(s.handle_notch))


def _prefer_strongest(steps: list[BrakePlanStep]) -> BrakePlanStep:
    return max(steps, key=lambda s: notch_strength(s.handle_notch))


def select_limit_active_step(
    steps: list[BrakePlanStep],
    speed_ms: float,
    target_speed_ms: float,
    gradient_pct: float,
) -> Optional[BrakePlanStep]:
    """Puerto de ``selectLimitActiveStep`` (Dastsc)."""
    if not steps:
        return None

    late = [s for s in steps if s.dist_start < 0]
    if late:
        return _prefer_strongest(late)

    upcoming = sorted(
        [s for s in steps
         if s.dist_start > apply_zone_margin_m(speed_ms, s.apply_at_remaining_m)],
        key=lambda s: s.dist_start,
    )
    applicable = [
        s for s in steps
        if s.dist_start <= apply_zone_margin_m(speed_ms, s.apply_at_remaining_m)
    ]

    downhill = gradient_pct < DOWNHILL_LIMIT_GRADIENT_PCT
    speed_margin_ms = max(1.5, speed_ms * 0.06)

    if downhill:
        if applicable:
            if speed_ms > target_speed_ms + speed_margin_ms:
                return _prefer_strongest(applicable)
            moderate = [s for s in applicable if notch_strength(s.handle_notch) >= 2]
            if moderate:
                return _prefer_strongest(moderate)
            return _prefer_strongest(applicable)
        if upcoming:
            return _prefer_strongest(upcoming)
        return _prefer_strongest(steps)

    if applicable:
        return _prefer_weakest(applicable)
    if upcoming:
        return _prefer_weakest(upcoming)
    return steps[-1]


def plan_brake(
    *,
    speed_mph: float,
    distance_to_target_m: float,
    target_speed_mph: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    target_kind: TargetKind = "SPEED_LIMIT",
    phases: tuple[BrakePhase, ...] = UK_SERVICE_PHASES,
    predict_decel: Optional[PredictDecelFn] = None,
) -> Optional[BrakePlan]:
    """Puerto de ``planBrake`` para un objetivo (límite o estación)."""
    speed_ms = speed_mph * MPH_TO_MS
    target_ms = target_speed_mph * MPH_TO_MS

    if speed_ms < 0.5 or distance_to_target_m is None:
        return None
    if speed_ms <= target_ms + 0.05:
        return None
    if distance_to_target_m < -10:
        return None

    reaction = reaction_margin_m(speed_ms)
    if target_kind == "SPEED_LIMIT":
        reaction *= low_speed_reaction_scale(speed_ms, target_ms)

    steps: list[BrakePlanStep] = []
    for i, phase in enumerate(phases):
        decel, using_learned = resolve_phase_decel(
            phase, speed_mph, gradient_pct, base_decel, predict_decel)
        dist_needed = braking_distance_m(speed_ms, target_ms, decel)
        apply_at = dist_needed + reaction
        dist_start = distance_to_target_m - apply_at
        zone = apply_zone_margin_m(speed_ms, apply_at)
        steps.append(BrakePlanStep(
            notch=phase.label,
            handle_notch=phase.handle_notch,
            phase=str(i + 1),
            distance_m=dist_needed,
            apply_at_remaining_m=apply_at,
            dist_start=dist_start,
            meters_until_action_m=max(0.0, dist_start),
            apply_now=is_in_apply_zone(dist_start, zone),
            using_learned=using_learned,
        ))

    active = select_limit_active_step(steps, speed_ms, target_ms, gradient_pct)
    return BrakePlan(
        target_kind=target_kind,
        distance_to_target_m=distance_to_target_m,
        target_speed_mph=target_speed_mph,
        reaction_margin_m=reaction,
        steps=steps,
        active_step=active,
    )


def brake_plan_urgency(plan: BrakePlan) -> float:
    step = plan.active_step
    if step is None:
        return float("inf")
    return step.dist_start


def select_urgent_plan(plans: list[BrakePlan]) -> Optional[BrakePlan]:
    """Elige el plan que exige frenar antes (menor distStart)."""
    if not plans:
        return None
    if len(plans) == 1:
        return plans[0]
    return min(plans, key=brake_plan_urgency)


def profile_cap_from_plan(
    plan: BrakePlan,
    speed_mph: float,
    effective_limit: float,
) -> float:
    """Perfil gradual: reduce effective_limit al acercarse al objetivo."""
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


def plan_to_governor_action(
    plan: BrakePlan,
    *,
    speed_mph: float,
    throttle_notch: int,
    effective_limit: float,
) -> tuple[Optional[str], float]:
    """
    Convierte el plan activo en acción TSW (COAST/BRAKE/HARDBRAKE/FULLSTOP).

    Returns:
        (action_or_none, effective_limit_ajustado)
    """
    step = plan.active_step
    if step is None:
        return None, effective_limit

    cap = profile_cap_from_plan(plan, speed_mph, effective_limit)
    effective_limit = min(effective_limit, cap)

    if not step.apply_now and step.dist_start > 60:
        return None, effective_limit

    if throttle_notch > 0:
        return "COAST", effective_limit

    if step.handle_notch >= 3:
        return "BRAKE", min(effective_limit, plan.target_speed_mph)
    if step.handle_notch == 2:
        return "BRAKE", min(effective_limit, plan.target_speed_mph)
    if step.handle_notch == 1:
        if step.dist_start < -30 or speed_mph > plan.target_speed_mph + 8:
            return "HARDBRAKE", min(effective_limit, plan.target_speed_mph)
        return "BRAKE", min(effective_limit, plan.target_speed_mph)
    return "FULLSTOP", min(effective_limit, plan.target_speed_mph)


def plan_for_speed_limits(
    speed_mph: float,
    limits_ahead: list[dict],
    effective_limit: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn] = None,
) -> Optional[BrakePlan]:
    """Planifica contra la cola de límites y devuelve el más urgente."""
    plans: list[BrakePlan] = []
    for entry in limits_ahead[:3]:
        lim = entry.get("limit_mph")
        dist = entry.get("distance_m")
        if lim is None or dist is None:
            continue
        if lim >= speed_mph - 0.3:
            continue
        p = plan_brake(
            speed_mph=speed_mph,
            distance_to_target_m=float(dist),
            target_speed_mph=float(lim),
            gradient_pct=gradient_pct,
            base_decel=base_decel,
            target_kind="SPEED_LIMIT",
            predict_decel=predict_decel,
        )
        if p is not None:
            plans.append(p)
    return select_urgent_plan(plans)
