#!/usr/bin/env python3
"""
brake_planner.py — Planificación de frenado (Dastsc planBrake.ts).

Un solo módulo para límites, estación y horario. Señales (SIGNAL) se añadirán aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from tsw6.braking.v2.physics import (
    BrakePhysicsContext,
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    DOWNHILL_LIMIT_GRADIENT_PCT,
    MPH_TO_MS,
    STATION_COAST_CUTOFF_M,
    TARGET_CLUSTER_GAP_M,
    apply_zone_margin_m,
    brake_reaction_margin_m,
    braking_distance_m,
    braking_distance_mph as _braking_distance_mph_core,
    decel_for_notch,
    is_in_apply_zone,
    low_speed_reaction_scale,
    reaction_margin_m,
    should_emit_brake_command,
)
from tsw6.braking.v2.plan import (
    BrakePlan,
    BrakePlanStep,
    TargetKind,
    profile_cap_from_plan,
)
from tsw6.braking.v2.cluster import (
    is_unified_limit_station_stop,
    sequential_limit_stop_feasible,
    should_delay_unified_station_plan,
    should_merge_limit_and_station_plans,
    targets_are_clustered,
)


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


PredictDecelFn = Callable[[int, float, float], Optional[float]]


@dataclass
class ApproachChain:
    """Cadena cartel ↔ estación (Dastsc ``formatClusteredBrakeDetail``)."""
    limit_mph: Optional[float]
    limit_dist_m: Optional[float]
    station_dist_m: Optional[float]
    station_name: str
    gap_m: float
    clustered: bool
    phase: int          # 1 = cartel primero, 2 = parada en andén
    closer: str           # "limit" | "station" | "same"
    detail: str
    unified_stop: bool = False   # parada continua sin soltar en cartel intermedio


@dataclass
class ApproachPlanResult:
    """Plan activo + parada de freno siguiente si hay cadena."""
    active: BrakePlan
    follow_up: Optional[BrakePlan] = None
    chain: Optional[ApproachChain] = None


# ── Planificación (Dastsc planBrake.ts) ───────────────────────────────────────

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
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
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

    reaction = brake_reaction_margin_m(speed_ms, brake_fill_s=brake_fill_s)
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


def resolve_chained_limit_target(
    limits_ahead: list[dict],
) -> Optional[dict]:
    """
    Objetivo de frenada en cola de límites (Dastsc ``resolveChainedLimitTarget``).

    Si el 2.º cartel está muy pegado y es más restrictivo, salta directamente
  a ese objetivo (p. ej. 75→25 mph en pocos metros).
    """
    if not limits_ahead:
        return None
    first = limits_ahead[0]
    lim1 = first.get("limit_mph")
    dist1 = first.get("distance_m")
    if lim1 is None or dist1 is None or float(dist1) <= 0:
        return None
    if len(limits_ahead) < 2:
        return first
    second = limits_ahead[1]
    lim2 = second.get("limit_mph")
    dist2 = second.get("distance_m")
    if lim2 is None or dist2 is None or float(dist2) <= 0:
        return first
    gap = float(dist2) - float(dist1)
    if 0 < gap <= TARGET_CLUSTER_GAP_M and float(lim2) < float(lim1):
        return second
    return first


def limit_phase_complete(
    speed_mph: float,
    limit_mph: float,
    distance_next_m: Optional[float],
    *,
    pass_margin_m: float = 80.0,
) -> bool:
    """True cuando el tren ha cumplido la 1.ª fase (cartel intermedio)."""
    if distance_next_m is not None and distance_next_m <= pass_margin_m:
        return True
    return speed_mph <= limit_mph + 1.5


def braking_distance_mph(
    speed_mph: float,
    target_speed_mph: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
) -> float:
    """Distancia de frenado (m) con decel de servicio máximo (B3), sin margen."""
    decel = decel_for_notch(
        UK_SERVICE_PHASES[-1].fraction, base_decel, gradient_pct)
    return _braking_distance_mph_core(
        speed_mph,
        target_speed_mph,
        decel_ms2=decel,
        ctx=BrakePhysicsContext(
            base_decel_ms2=base_decel,
            gradient_pct=gradient_pct,
        ),
        apply_margin=False,
    )


# ── Horario (Dastsc schedule.ts) ──────────────────────────────────────────────

_ETA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def normalize_station_eta(eta: Optional[str]) -> Optional[str]:
    """``HH:MM`` o ``HH:MM:SS`` del HUD → ``HH:MM`` para el planner."""
    if eta is None:
        return None
    s = str(eta).strip()
    if not s:
        return None
    m = _ETA_RE.match(s)
    if not m:
        return None
    return f"{int(m.group(1))}:{m.group(2)}"


def parse_eta_minutes(eta: str) -> Optional[int]:
    norm = normalize_station_eta(eta)
    if norm is None:
        return None
    match = _ETA_RE.match(norm)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def minutes_until_eta(eta: str, now: Optional[datetime] = None) -> Optional[int]:
    eta_min = parse_eta_minutes(eta)
    if eta_min is None:
        return None
    now = now or datetime.now()
    now_min = now.hour * 60 + now.minute
    diff = eta_min - now_min
    if diff < -12 * 60:
        diff += 24 * 60
    return diff


def schedule_slack_sec(
    distance_m: float,
    speed_mph: float,
    eta: Optional[str],
    now: Optional[datetime] = None,
    *,
    schedule_slack_enabled: bool = True,
) -> Optional[float]:
    """Segundos de holgura (+ = pronto, - = tarde)."""
    if not schedule_slack_enabled:
        return None
    if not eta or not eta.strip() or speed_mph < 0.5 or distance_m <= 0:
        return None
    diff_min = minutes_until_eta(eta, now)
    if diff_min is None:
        return None
    speed_ms = speed_mph * MPH_TO_MS
    return diff_min * 60.0 - distance_m / max(speed_ms, 0.1)


def schedule_reaction_scale(
    distance_m: float,
    speed_mph: float,
    eta: Optional[str],
    now: Optional[datetime] = None,
    *,
    schedule_slack_enabled: bool = True,
) -> float:
    if not schedule_slack_enabled:
        return 1.0
    slack = schedule_slack_sec(
        distance_m, speed_mph, eta, now, schedule_slack_enabled=True)
    if slack is None:
        return 1.0
    if slack > 60:
        return max(0.5, 1.0 - slack / 150.0)
    if slack > 30:
        return max(0.62, 1.0 - slack / 170.0)
    if slack > 15:
        return max(0.78, 1.0 - slack / 200.0)
    if slack < -30:
        return min(1.4, 1.0 - slack / 70.0)
    if slack < -15:
        return min(1.2, 1.0 - slack / 90.0)
    return 1.0


def schedule_coast_allowance_m(
    distance_m: float,
    speed_mph: float,
    eta: Optional[str],
    now: Optional[datetime] = None,
    *,
    schedule_slack_enabled: bool = True,
) -> float:
    if not schedule_slack_enabled:
        return 0.0
    if distance_m < STATION_COAST_CUTOFF_M:
        return 0.0
    slack = schedule_slack_sec(
        distance_m, speed_mph, eta, now, schedule_slack_enabled=True)
    if slack is None or slack <= 8 or speed_mph < 0.5:
        return 0.0
    speed_ms = speed_mph * MPH_TO_MS
    slack_dist = slack * speed_ms
    if slack > 90:
        return min(slack_dist * 0.48, 480.0)
    if slack > 45:
        return min(slack_dist * 0.38, 340.0)
    if slack > 20:
        return min(slack_dist * 0.28, 220.0)
    if slack > 10:
        return min(slack_dist * 0.15, 120.0)
    return 0.0


# ── Estación (Dastsc planBrakeForStation) ─────────────────────────────────────

TURNAROUND_DEPARTURE_MAX_DIST_M = 150.0
TURNAROUND_DEPARTURE_MAX_TRAVELED_M = 250.0
BAD_ANCHOR_DWELL_MAX_TRAVELED_M = 15.0
SHORT_TURNAROUND_ANCHOR_MAX_M = 200.0
SHORT_TURNAROUND_MAX_TRAVELED_M = 100.0


@dataclass(frozen=True)
class StationBrakeConfig:
    final_stop_max_distance_m: float = 35.0
    platform_tail_m: float = 0.0
    final_stop_speed_mph: float = 0.45
    hold_max_speed_mph: float = 2.2
    departure_speed_mph: float = 11.2
    dwell_max_distance_m: float = 80.0
    terminal_approach_m: float = 80.0
    station_reaction_time_s: float = 1.2


DEFAULT_STATION_CFG = StationBrakeConfig()


def _moderate_service_notch_label() -> str:
    return UK_SERVICE_PHASES[1].label


def _has_throttle(throttle_notch: int) -> bool:
    return throttle_notch > 0


def _moderate_or_stronger(steps: list[BrakePlanStep]) -> list[BrakePlanStep]:
    return [s for s in steps if notch_strength(s.handle_notch) >= 2]


def select_station_active_step(
    steps: list[BrakePlanStep],
    speed_ms: float,
    distance_to_target_m: float,
    schedule_eta: Optional[str] = None,
    now: Optional[datetime] = None,
    *,
    schedule_slack_enabled: bool = True,
) -> Optional[BrakePlanStep]:
    """Puerto de ``selectStationActiveStep`` (Dastsc)."""
    if not steps:
        return None

    moderate_label = _moderate_service_notch_label()
    speed_mph = speed_ms / MPH_TO_MS
    slack_sec = schedule_slack_sec(
        distance_to_target_m,
        speed_mph,
        schedule_eta,
        now,
        schedule_slack_enabled=schedule_slack_enabled,
    )
    coasting_for_schedule = (
        slack_sec is not None and slack_sec > 18 and distance_to_target_m > 300
    )

    if coasting_for_schedule:
        not_yet = sorted(
            [s for s in steps if s.dist_start > 0],
            key=lambda s: s.dist_start,
        )
        if not_yet:
            moderate = next((s for s in not_yet if s.notch == moderate_label), None)
            if moderate is not None:
                return moderate
            return _prefer_weakest(not_yet)

    due = [s for s in steps if s.dist_start <= 0]
    in_zone = [
        s for s in steps
        if is_in_apply_zone(
            s.dist_start,
            apply_zone_margin_m(speed_ms, s.apply_at_remaining_m),
        )
    ]
    upcoming = sorted(
        [s for s in steps if s.dist_start > 0],
        key=lambda s: s.dist_start,
    )

    late_for_schedule = slack_sec is not None and slack_sec < -12
    final_approach = distance_to_target_m < 280
    terminal_zone = distance_to_target_m < 50

    if terminal_zone:
        pool = _moderate_or_stronger([*due, *in_zone, *upcoming])
        if pool:
            return _prefer_strongest(pool)
        return _prefer_strongest(steps)

    if final_approach or late_for_schedule:
        pool = _moderate_or_stronger([*due, *in_zone])
        if pool:
            return _prefer_strongest(pool)
        if upcoming:
            return _prefer_strongest(upcoming)
        return _prefer_strongest(steps)

    if distance_to_target_m < 380 and upcoming:
        step = upcoming[0]
        zone = apply_zone_margin_m(speed_ms, step.apply_at_remaining_m)
        if step.dist_start < zone:
            return _prefer_weakest(upcoming)

    if due or in_zone:
        pool = [*due, *in_zone]
        service = _moderate_or_stronger(pool)
        if service:
            moderate = [s for s in service if s.notch == moderate_label]
            if moderate:
                return _prefer_weakest(moderate)
            return _prefer_weakest(service)
        return _prefer_weakest(pool)

    return (
        next((s for s in steps if s.notch == moderate_label), None)
        or (upcoming[0] if upcoming else None)
        or steps[0]
    )


def is_stale_platform_departure(
    *,
    speed_mph: float,
    station_distance_m: float,
    throttle_notch: int,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
) -> bool:
    speed_ms = speed_mph * MPH_TO_MS
    if station_distance_m <= cfg.final_stop_max_distance_m:
        return False
    if station_distance_m > cfg.dwell_max_distance_m:
        return False
    if not _has_throttle(throttle_notch):
        return False
    if speed_ms <= cfg.final_stop_speed_mph * MPH_TO_MS:
        return False
    return speed_mph < cfg.departure_speed_mph


def should_suppress_station_braking_for_departure(
    *,
    speed_mph: float,
    station_distance_m: float,
    throttle_notch: int,
    station_traveled_m: Optional[float] = None,
    station_anchor_m: Optional[float] = None,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
) -> bool:
    if is_stale_platform_departure(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        throttle_notch=throttle_notch,
        cfg=cfg,
    ):
        return True

    traveled = station_traveled_m or 0.0
    throttle = _has_throttle(throttle_notch)
    speed_ms = speed_mph * MPH_TO_MS
    final_stop_ms = cfg.final_stop_speed_mph * MPH_TO_MS
    hold_ms = cfg.hold_max_speed_mph * MPH_TO_MS

    if (
        station_anchor_m is not None
        and station_anchor_m > 0
        and station_anchor_m < SHORT_TURNAROUND_ANCHOR_MAX_M
        and traveled <= SHORT_TURNAROUND_MAX_TRAVELED_M
    ):
        return True

    if (
        station_distance_m <= cfg.final_stop_max_distance_m
        and throttle
        and speed_ms > final_stop_ms
    ):
        return True

    if (
        station_distance_m > cfg.dwell_max_distance_m
        and station_distance_m <= TURNAROUND_DEPARTURE_MAX_DIST_M
        and traveled < BAD_ANCHOR_DWELL_MAX_TRAVELED_M
        and speed_ms <= hold_ms
    ):
        return True

    if (
        station_distance_m > cfg.final_stop_max_distance_m
        and station_distance_m <= TURNAROUND_DEPARTURE_MAX_DIST_M
        and traveled <= TURNAROUND_DEPARTURE_MAX_TRAVELED_M
        and throttle
        and speed_ms > final_stop_ms
    ):
        return True

    return False


def _pick_final_stop_notch(speed_ms: float) -> str:
    if speed_ms > 4:
        return UK_SERVICE_PHASES[-1].label
    if speed_ms > 1.5:
        return UK_SERVICE_PHASES[1].label
    return UK_SERVICE_PHASES[0].label


def _handle_for_notch(notch: str) -> int:
    for phase in UK_SERVICE_PHASES:
        if phase.label == notch:
            return phase.handle_notch
    return UK_SERVICE_PHASES[0].handle_notch


def build_immediate_stop_plan(
    distance_m: float,
    speed_mph: float,
) -> BrakePlan:
    speed_ms = speed_mph * MPH_TO_MS
    notch = _pick_final_stop_notch(speed_ms)
    step = BrakePlanStep(
        notch=notch,
        handle_notch=_handle_for_notch(notch),
        phase="stop",
        distance_m=0.0,
        apply_at_remaining_m=distance_m,
        dist_start=0.0,
        meters_until_action_m=0.0,
        apply_now=True,
    )
    return BrakePlan(
        target_kind="STATION",
        distance_to_target_m=distance_m,
        target_speed_mph=0.0,
        reaction_margin_m=0.0,
        steps=[step],
        active_step=step,
    )


def plan_station_final_stop(
    *,
    speed_mph: float,
    station_distance_m: float,
    throttle_notch: int = 0,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
) -> Optional[BrakePlan]:
    if (
        station_distance_m > cfg.final_stop_max_distance_m
        or station_distance_m < cfg.platform_tail_m
    ):
        return None
    speed_ms = speed_mph * MPH_TO_MS
    if speed_ms <= cfg.final_stop_speed_mph * MPH_TO_MS:
        return None
    if (
        station_distance_m <= cfg.final_stop_max_distance_m
        and _has_throttle(throttle_notch)
        and speed_ms > cfg.final_stop_speed_mph * MPH_TO_MS
    ):
        return None
    if station_distance_m <= 5 and speed_mph > cfg.departure_speed_mph:
        return None
    return build_immediate_stop_plan(station_distance_m, speed_mph)


def plan_station_service_brake(
    *,
    speed_mph: float,
    station_distance_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
    station_eta: Optional[str] = None,
    now: Optional[datetime] = None,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
    schedule_slack_enabled: bool = True,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakePlan]:
    speed_ms = speed_mph * MPH_TO_MS
    target_ms = 0.0

    if speed_ms < 0.5 or station_distance_m is None:
        return None
    if speed_ms <= target_ms + 0.05:
        return None
    if station_distance_m < -10:
        return None

    reaction = brake_reaction_margin_m(
        speed_ms,
        brake_fill_s=brake_fill_s,
        reaction_base_s=cfg.station_reaction_time_s,
    )
    reaction *= schedule_reaction_scale(
        station_distance_m,
        speed_mph,
        station_eta,
        now,
        schedule_slack_enabled=schedule_slack_enabled,
    )
    if station_distance_m < cfg.terminal_approach_m:
        t = max(0.0, station_distance_m / cfg.terminal_approach_m)
        reaction *= 0.45 + 0.55 * t

    coast_allowance_m = schedule_coast_allowance_m(
        station_distance_m,
        speed_mph,
        station_eta,
        now,
        schedule_slack_enabled=schedule_slack_enabled,
    )

    steps: list[BrakePlanStep] = []
    for i, phase in enumerate(UK_SERVICE_PHASES):
        decel, using_learned = resolve_phase_decel(
            phase, speed_mph, gradient_pct, base_decel, predict_decel)
        dist_needed = braking_distance_m(speed_ms, target_ms, decel)
        apply_at = dist_needed + reaction
        dist_start = station_distance_m - apply_at + coast_allowance_m
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

    active = select_station_active_step(
        steps,
        speed_ms,
        station_distance_m,
        station_eta,
        now,
        schedule_slack_enabled=schedule_slack_enabled,
    )
    return BrakePlan(
        target_kind="STATION",
        distance_to_target_m=station_distance_m,
        target_speed_mph=0.0,
        reaction_margin_m=reaction,
        steps=steps,
        active_step=active,
    )


def plan_brake_for_station(
    *,
    speed_mph: float,
    station_distance_m: float,
    gradient_pct: float = 0.0,
    base_decel: float = DEFAULT_MAX_BRAKE_DECEL,
    predict_decel: Optional[PredictDecelFn] = None,
    throttle_notch: int = 0,
    station_eta: Optional[str] = None,
    station_traveled_m: Optional[float] = None,
    station_anchor_m: Optional[float] = None,
    now: Optional[datetime] = None,
    cfg: StationBrakeConfig = DEFAULT_STATION_CFG,
    schedule_slack_enabled: bool = True,
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakePlan]:
    if station_distance_m < 0:
        return None
    if should_suppress_station_braking_for_departure(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        throttle_notch=throttle_notch,
        station_traveled_m=station_traveled_m,
        station_anchor_m=station_anchor_m,
        cfg=cfg,
    ):
        return None

    final_stop = plan_station_final_stop(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        throttle_notch=throttle_notch,
        cfg=cfg,
    )
    if final_stop is not None:
        return final_stop

    if station_distance_m <= 0:
        return None

    return plan_station_service_brake(
        speed_mph=speed_mph,
        station_distance_m=station_distance_m,
        gradient_pct=gradient_pct,
        base_decel=base_decel,
        predict_decel=predict_decel,
        station_eta=station_eta,
        now=now,
        cfg=cfg,
        schedule_slack_enabled=schedule_slack_enabled,
        brake_fill_s=brake_fill_s,
    )


def _build_limit_plan(
    speed_mph: float,
    entry: dict,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn],
    brake_fill_s: float = DEFAULT_BRAKE_FILL_S,
) -> Optional[BrakePlan]:
    lim = entry.get("limit_mph")
    dist = entry.get("distance_m")
    if lim is None or dist is None or float(lim) >= speed_mph - 0.3:
        return None
    return plan_brake(
        speed_mph=speed_mph,
        distance_to_target_m=float(dist),
        target_speed_mph=float(lim),
        gradient_pct=gradient_pct,
        base_decel=base_decel,
        target_kind="SPEED_LIMIT",
        predict_decel=predict_decel,
        brake_fill_s=brake_fill_s,
    )


def _describe_approach_chain(
    *,
    limit_mph: Optional[float],
    limit_dist_m: Optional[float],
    station_dist_m: Optional[float],
    station_name: str,
    phase: int,
    unified_stop: bool = False,
) -> ApproachChain:
    gap = 0.0
    clustered = False
    closer = "same"
    if limit_dist_m is not None and station_dist_m is not None:
        gap = abs(station_dist_m - limit_dist_m)
        clustered = targets_are_clustered(limit_dist_m, station_dist_m)
        if limit_dist_m < station_dist_m - 5:
            closer = "limit"
        elif station_dist_m < limit_dist_m - 5:
            closer = "station"
    if unified_stop and limit_dist_m is not None and station_dist_m is not None:
        lim_lbl = f"{limit_mph:.0f}" if limit_mph is not None else "?"
        detail = (
            f"Parada unificada {station_name}: cartel {lim_lbl} mph "
            f"a {limit_dist_m:.0f}m, andén a {station_dist_m:.0f}m "
            f"(+{gap:.0f}m insuficiente tras cartel)"
        )
    elif clustered and limit_dist_m is not None and station_dist_m is not None:
        lim_lbl = f"{limit_mph:.0f}" if limit_mph is not None else "?"
        if limit_dist_m <= station_dist_m:
            detail = (
                f"Cadena: {lim_lbl}→PARADA {station_name} "
                f"en +{gap:.0f}m — fase {phase}/2"
            )
        else:
            detail = (
                f"Estación {station_name} antes del cartel "
                f"({station_dist_m:.0f}m vs {limit_dist_m:.0f}m)"
            )
    elif limit_dist_m is not None and station_dist_m is not None:
        if closer == "limit":
            lim_lbl = f"{limit_mph:.0f}" if limit_mph is not None else "?"
            detail = (
                f"Cartel {lim_lbl} mph más cerca "
                f"({limit_dist_m:.0f}m vs estación {station_dist_m:.0f}m)"
            )
        elif closer == "station":
            detail = (
                f"Estación {station_name} más cerca "
                f"({station_dist_m:.0f}m vs cartel {limit_dist_m:.0f}m)"
            )
        else:
            detail = f"Cartel y {station_name} a distancia similar"
    elif station_dist_m is not None:
        detail = f"Parada {station_name} a {station_dist_m:.0f}m"
    elif limit_dist_m is not None:
        detail = (
            f"Cartel {limit_mph:.0f} mph a {limit_dist_m:.0f}m"
            if limit_mph is not None
            else f"Cartel a {limit_dist_m:.0f}m"
        )
    else:
        detail = "Sin objetivos de aproximación"

    return ApproachChain(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_dist_m,
        station_name=station_name,
        gap_m=gap,
        clustered=clustered,
        phase=phase,
        closer=closer,
        detail=detail,
        unified_stop=unified_stop,
    )


def select_urgent_brake_plan(
    plans: list[BrakePlan],
    *,
    limit_dist_m: Optional[float] = None,
    station_dist_m: Optional[float] = None,
    limit_mph: Optional[float] = None,
    gradient_pct: float = 0.0,
) -> Optional[BrakePlan]:
    """Elige plan urgente. Unificado (gap corto) → estación; dos fases → cartel."""
    if not plans:
        return None
    pool = list(plans)
    if (
        limit_dist_m is not None
        and station_dist_m is not None
        and limit_dist_m > 0
        and station_dist_m > 0
        and should_merge_limit_and_station_plans(limit_dist_m, station_dist_m)
    ):
        has_limit = any(p.target_kind == "SPEED_LIMIT" for p in pool)
        has_station = any(p.target_kind == "STATION" for p in pool)
        if has_limit and has_station:
            unified = (
                limit_mph is not None
                and is_unified_limit_station_stop(
                    limit_mph=limit_mph,
                    limit_dist_m=limit_dist_m,
                    station_dist_m=station_dist_m,
                    gradient_pct=gradient_pct,
                )
            )
            if unified:
                if limit_dist_m <= 8.0:
                    pool = [p for p in pool if p.target_kind != "SPEED_LIMIT"]
            elif limit_mph is not None and sequential_limit_stop_feasible(
                limit_mph=limit_mph,
                limit_dist_m=limit_dist_m,
                station_dist_m=station_dist_m,
                gradient_pct=gradient_pct,
            ):
                pool = [p for p in pool if p.target_kind != "STATION"]
    if len(pool) == 1:
        return pool[0]
    if (
        limit_dist_m is not None
        and limit_dist_m > 8.0
        and limit_mph is not None
        and any(p.target_kind == "SPEED_LIMIT" for p in pool)
        and any(p.target_kind == "STATION" for p in pool)
        and is_unified_limit_station_stop(
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_dist_m or 0.0,
            gradient_pct=gradient_pct,
        )
    ):
        return next(p for p in pool if p.target_kind == "SPEED_LIMIT")
    return min(pool, key=brake_plan_urgency)


def plan_to_governor_action(
    plan: BrakePlan,
    *,
    speed_mph: float,
    throttle_notch: int,
    effective_limit: float,
) -> tuple[Optional[str], float]:
    """
    Convierte el plan activo en acción TSW (COAST/BRAKE/HOLD; P1 usa BrakeCommand).

    Returns:
        (action_or_none, effective_limit_ajustado)
    """
    step = plan.active_step
    if step is None:
        return None, effective_limit

    cap = profile_cap_from_plan(plan, speed_mph, effective_limit)
    effective_limit = min(effective_limit, cap)

    if not should_emit_brake_command(
        apply_now=step.apply_now,
        dist_start=step.dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=plan.distance_to_target_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
    ):
        return None, effective_limit

    if throttle_notch > 0:
        return "COAST", effective_limit

    return "BRAKE", min(effective_limit, plan.target_speed_mph)


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
    chained = resolve_chained_limit_target(limits_ahead)
    if chained:
        p = _build_limit_plan(
            speed_mph, chained, gradient_pct, base_decel, predict_decel,
        )
        if p is not None:
            plans.append(p)
    for entry in limits_ahead[:3]:
        if chained and entry is limits_ahead[0]:
            continue
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


def plan_for_approach_targets(
    speed_mph: float,
    limits_ahead: list[dict],
    station_distance_m: Optional[float],
    _effective_limit: float,
    gradient_pct: float,
    base_decel: float,
    predict_decel: Optional[PredictDecelFn] = None,
    *,
    station_name: str = "estación",
    limit_phase_done: bool = False,
    station_eta: Optional[str] = None,
    throttle_notch: int = 0,
    station_traveled_m: Optional[float] = None,
    station_anchor_m: Optional[float] = None,
) -> Optional[ApproachPlanResult]:
    """
    P1 con dos fases: cartel intermedio y parada en andén (Dastsc).

    Compara distancias, construye ambos planes y devuelve el activo + el
    siguiente si están agrupados (p. ej. 55 mph y Alden a +300 m).
    """
    limit_entry = resolve_chained_limit_target(limits_ahead)
    limit_mph = (
        float(limit_entry["limit_mph"]) if limit_entry else None
    )
    limit_dist_m = (
        float(limit_entry["distance_m"]) if limit_entry else None
    )

    plan_limit = (
        _build_limit_plan(
            speed_mph, limit_entry, gradient_pct, base_decel, predict_decel,
        )
        if limit_entry else None
    )
    plan_station: Optional[BrakePlan] = None
    if station_distance_m is not None and station_distance_m > 0:
        plan_station = plan_brake_for_station(
            speed_mph=speed_mph,
            station_distance_m=float(station_distance_m),
            gradient_pct=gradient_pct,
            base_decel=base_decel,
            predict_decel=predict_decel,
            throttle_notch=throttle_notch,
            station_eta=station_eta,
            station_traveled_m=station_traveled_m,
            station_anchor_m=station_anchor_m,
        )

    if plan_limit is None and plan_station is None:
        return None

    follow_up: Optional[BrakePlan] = None
    phase = 1
    active: Optional[BrakePlan] = None
    unified_stop = False

    clustered_merge = (
        limit_dist_m is not None
        and station_distance_m is not None
        and limit_dist_m > 0
        and station_distance_m > 0
        and should_merge_limit_and_station_plans(limit_dist_m, station_distance_m)
    )

    if limit_phase_done and plan_station:
        active = plan_station
        follow_up = None
        phase = 2
    elif clustered_merge and plan_limit and plan_station:
        two_phase_ok = (
            limit_mph is not None
            and limit_dist_m is not None
            and station_distance_m is not None
            and sequential_limit_stop_feasible(
                limit_mph=limit_mph,
                limit_dist_m=limit_dist_m,
                station_dist_m=station_distance_m,
                gradient_pct=gradient_pct,
                base_decel=base_decel,
            )
        )
        if two_phase_ok:
            active = plan_limit
            follow_up = plan_station
            phase = 1
        else:
            # Sin margen tras el cartel: frenar ya hacia parada (respetando límite).
            active = plan_station
            follow_up = None
            phase = 2
            unified_stop = True
    elif (
        limit_dist_m is not None
        and station_distance_m is not None
        and station_distance_m < limit_dist_m - 5
        and plan_station
    ):
        # Cartel detrás del andén — parada primero (Dastsc)
        active = plan_station
        follow_up = plan_limit if plan_limit else None
        phase = 2
    else:
        candidates = [p for p in (plan_limit, plan_station) if p is not None]
        active = select_urgent_brake_plan(
            candidates,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_distance_m,
            limit_mph=limit_mph,
            gradient_pct=gradient_pct,
        )
        if active is plan_station and plan_limit:
            follow_up = None
            phase = 2
        elif active is plan_limit and plan_station:
            if (
                limit_dist_m is not None
                and station_distance_m is not None
                and targets_are_clustered(limit_dist_m, station_distance_m)
            ):
                follow_up = plan_station
                phase = 1

    if (
        active is plan_station
        and not limit_phase_done
        and should_delay_unified_station_plan(
            speed_mph=speed_mph,
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            station_dist_m=station_distance_m,
        )
    ):
        return None

    if active is None:
        return None

    chain = _describe_approach_chain(
        limit_mph=limit_mph,
        limit_dist_m=limit_dist_m,
        station_dist_m=station_distance_m,
        station_name=station_name,
        phase=phase,
        unified_stop=unified_stop,
    )
    return ApproachPlanResult(active=active, follow_up=follow_up, chain=chain)
