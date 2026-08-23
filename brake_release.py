#!/usr/bin/env python3
"""
brake_release.py — RELEASE y anti-rebrake (Dastsc commandBus).

Puerto de ``resolveReleaseAction`` + ``shouldInhibitLimitRebrake``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from brake_command import BrakeCommand, release_brake_command
from brake_planner import DOWNHILL_LIMIT_GRADIENT_PCT, BrakePlan

_log = logging.getLogger("tsw.governor")

NEUTRAL_NOTCH = 4

# Dastsc agentConfig defaults (MPH)
RELEASE_MARGIN_MPH = 2.0
COAST_REBRAKE_MARGIN_MPH = 5.0
COAST_CLEAR_OVERSHOOT_MPH = 8.0


def is_brake_applied(handle_notch: int) -> bool:
    return handle_notch < NEUTRAL_NOTCH


def is_brake_released(handle_notch: int) -> bool:
    return handle_notch >= NEUTRAL_NOTCH


def is_downhill_limit_approach(
    gradient_pct: float,
    distance_next_m: Optional[float],
) -> bool:
    return (
        gradient_pct < DOWNHILL_LIMIT_GRADIENT_PCT
        and distance_next_m is not None
        and distance_next_m > 0
    )


def target_speed_mph(
    plan: Optional[BrakePlan],
    next_limit_mph: Optional[float],
    effective_limit: float,
) -> float:
    if plan is not None and plan.target_kind == "STATION":
        return 0.0
    if next_limit_mph is not None:
        return float(next_limit_mph)
    return float(effective_limit)


@dataclass
class SpeedLimitCoastLatch:
    """Tras RELEASE en límite — evita re-frenar por inercia (Dastsc)."""

    limit_speed_mph: float


class BrakeReleaseState:
    """Estado del latch coast entre ticks."""

    def __init__(self) -> None:
        self._coast_latch: Optional[SpeedLimitCoastLatch] = None

    def reset(self) -> None:
        self._coast_latch = None

    def latch(self, limit_speed_mph: float) -> None:
        self._coast_latch = SpeedLimitCoastLatch(limit_speed_mph=limit_speed_mph)

    def update(
        self,
        speed_mph: float,
        next_limit_mph: Optional[float],
    ) -> None:
        if next_limit_mph is None:
            self._coast_latch = None
            return
        if self._coast_latch is None:
            return
        if self._coast_latch.limit_speed_mph != next_limit_mph:
            self._coast_latch = None
            return
        if speed_mph > next_limit_mph + COAST_CLEAR_OVERSHOOT_MPH:
            self._coast_latch = None

    def should_inhibit_limit_rebrake(
        self,
        speed_mph: float,
        next_limit_mph: Optional[float],
        handle_notch: int,
        plan: Optional[BrakePlan],
        gradient_pct: float,
        distance_next_m: Optional[float],
        effective_limit: float,
    ) -> bool:
        if self._coast_latch is None or plan is None:
            return False
        if plan.target_kind != "SPEED_LIMIT":
            return False
        if is_downhill_limit_approach(gradient_pct, distance_next_m):
            return False
        if speed_mph > effective_limit + 0.5:
            return False
        if next_limit_mph is None:
            return False
        if next_limit_mph != self._coast_latch.limit_speed_mph:
            return False
        if is_brake_applied(handle_notch):
            return False
        return speed_mph <= next_limit_mph + COAST_REBRAKE_MARGIN_MPH


def resolve_release_command(
    *,
    speed_mph: float,
    handle_notch: int,
    effective_limit: float,
    next_limit_mph: Optional[float],
    distance_next_m: Optional[float],
    gradient_pct: float,
    plan: Optional[BrakePlan] = None,
) -> Optional[BrakeCommand]:
    """
    Soltar freno (NEU) cuando la velocidad objetivo ya se alcanzó.

    Puerto de ``resolveReleaseAction`` (solo límites de velocidad por ahora).
    """
    if is_brake_released(handle_notch):
        return None

    # Sin límite objetivo en planning: no soltar freno residual del conductor.
    if next_limit_mph is None:
        return None

    if is_downhill_limit_approach(gradient_pct, distance_next_m):
        return None

    if speed_mph > effective_limit + 0.5:
        return None

    target = target_speed_mph(plan, next_limit_mph, effective_limit)
    if speed_mph > target + RELEASE_MARGIN_MPH:
        return None

    cmd = release_brake_command(at_target=True)
    if cmd:
        _log.info(
            "P1 RELEASE  spd=%.1f  target=%.1f  handle=%d  next=%s",
            speed_mph,
            target,
            handle_notch,
            f"{next_limit_mph:.0f}mph" if next_limit_mph is not None else "—",
        )
    return cmd
