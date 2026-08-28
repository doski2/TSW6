#!/usr/bin/env python3
"""
station_plan.py — Perfil de parada en andén (TSW6).

Datos reales: distancia HUD, ETA HH:MM, palanca, gradiente, decel aprendida.
No usa OCR / ancla de tablón Dastsc; traveled/anchor son opcionales (tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from tsw6.braking.v2.physics import (
    DEFAULT_BRAKE_FILL_S,
    DEFAULT_MAX_BRAKE_DECEL,
    MPH_TO_MS,
    STATION_COAST_CUTOFF_M,
    apply_zone_margin_m,
    brake_reaction_margin_m,
    braking_distance_m,
    is_in_apply_zone,
)
from tsw6.braking.v2.plan import (
    UK_SERVICE_PHASES,
    BrakePlan,
    BrakePlanStep,
    PredictDecelFn,
    notch_strength,
    prefer_strongest_step,
    prefer_weakest_step,
    resolve_phase_decel,
)

# ── Horario (Dastsc schedule.ts) ──────────────────────────────────────────────

_ETA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def normalize_station_eta(eta: Optional[str]) -> Optional[str]:
    """``HH:MM`` o ``HH:MM:SS`` del HUD → ``HH:MM`` para el plan de andén."""
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
            return prefer_weakest_step(not_yet)

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
            return prefer_strongest_step(pool)
        return prefer_strongest_step(steps)

    if final_approach or late_for_schedule:
        pool = _moderate_or_stronger([*due, *in_zone])
        if pool:
            return prefer_strongest_step(pool)
        if upcoming:
            return prefer_strongest_step(upcoming)
        return prefer_strongest_step(steps)

    if distance_to_target_m < 380 and upcoming:
        step = upcoming[0]
        zone = apply_zone_margin_m(speed_ms, step.apply_at_remaining_m)
        if step.dist_start < zone:
            return prefer_weakest_step(upcoming)

    if due or in_zone:
        pool = [*due, *in_zone]
        service = _moderate_or_stronger(pool)
        if service:
            moderate = [s for s in service if s.notch == moderate_label]
            if moderate:
                return prefer_weakest_step(moderate)
            return prefer_weakest_step(service)
        return prefer_weakest_step(pool)

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


