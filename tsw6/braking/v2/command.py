#!/usr/bin/env python3
"""
command.py — Comandos de freno y RELEASE (Dastsc commandBus).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from tsw6.braking.v2.physics import (
    DOWNHILL_LIMIT_GRADIENT_PCT,
    brake_command_apply_zone_m,
    should_emit_brake_command,
)
from tsw6.braking.v2.plan import BrakePlan, profile_cap_from_plan
from tsw6.autopilot.control_actions import COAST, EMERGENCY, HOLD, RELEASE
from tsw6.governor.governor_constants import (
    EMERGENCY_BRAKE_HANDLE,
    EMERGENCY_BRAKE_MAX_DIST_M,
    SERVICE_MIN_HANDLE,
    STATION_STOPPED_MPH,
)

_log = logging.getLogger("tsw.governor")

BrakeCommandKind = Literal["APPLY", "RELEASE", "COAST_THROTTLE"]

NEUTRAL_NOTCH = 4
RELEASE_MARGIN_MPH = 2.0          # parada en andén (spd muy baja)
# TSW penaliza si spd > límite + 1 mph; techo operativo del autopilot.
LIMIT_SCORING_MAX_OVER_MPH = 0.9
LIMIT_RELEASE_MAX_OVER_MPH = 0.4  # cartel: soltar si spd <= target + esto
LIMIT_COAST_BAND_MPH = 0.25       # bajada: coast si spd <= limit + esto
LIMIT_CONTAIN_ESCALATE_OVER_MPH = 0.65  # B2 si repunte cerca del techo
LIMIT_RELEASE_MIN_SPEED_BAND_MPH = 5.0  # no soltar si spd << cartel (parado al arrancar)
COAST_REBRAKE_MARGIN_MPH = 0.9
COAST_CLEAR_OVERSHOOT_MPH = 2.0


def clamp_brake_handle(
    target: int,
    distance_to_target_m: Optional[float] = None,
) -> int:
    """
    Notch 0 (emergencia TSW) solo si el objetivo está a muy poca distancia.

    En servicio se limita a ``SERVICE_MIN_HANDLE`` (B3) para poder soltar y seguir.
    """
    target = int(target)
    if target >= SERVICE_MIN_HANDLE:
        return min(8, target)
    if (
        distance_to_target_m is not None
        and distance_to_target_m <= EMERGENCY_BRAKE_MAX_DIST_M
    ):
        return EMERGENCY_BRAKE_HANDLE
    return SERVICE_MIN_HANDLE


@dataclass(frozen=True)
class BrakeCommand:
    """Mando de freno Dastsc — notch absoluto vía IPC cuando hay plan P1."""

    kind: BrakeCommandKind
    target_notch: Optional[int] = None   # handle combinado UK 0–8
    phase: Optional[str] = None        # B1, B2, B3
    reason: str = ""
    distance_m: Optional[float] = None   # para limitar notch 0 (emergencia)

    def display_action(self) -> str:
        """Etiqueta para GUI/logs (Dastsc: fase del plan, no COAST/BRAKE)."""
        if self.kind == "RELEASE":
            return "RELEASE"
        if self.kind == "COAST_THROTTLE":
            return "COAST"
        if self.phase:
            return self.phase
        if self.target_notch is not None:
            return f"N{self.target_notch}"
        return "BRAKE"


def plan_to_brake_command(
    plan: BrakePlan,
    *,
    speed_mph: float,
    throttle_notch: int,
    effective_limit: float,
    current_notch: int,
) -> tuple[Optional[BrakeCommand], float]:
    """
    Convierte plan activo en comando Dastsc (notch directo).

    Returns:
        (BrakeCommand o None, effective_limit ajustado)
    """
    step = plan.active_step
    if step is None:
        return None, effective_limit

    cap = profile_cap_from_plan(plan, speed_mph, effective_limit)
    effective_limit = min(effective_limit, cap)

    # Parada en andén: soltar freno cuando ya está casi parado (sin gate de zona).
    if (plan.target_kind == "STATION"
            and current_notch < 4
            and speed_mph <= plan.target_speed_mph + RELEASE_MARGIN_MPH):
        rel = release_brake_command(at_target=True)
        if rel is not None:
            return rel, min(effective_limit, plan.target_speed_mph)

    if not should_emit_brake_command(
        apply_now=step.apply_now,
        dist_start=step.dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=plan.distance_to_target_m,
        apply_at_remaining_m=step.apply_at_remaining_m,
    ):
        return None, effective_limit

    # Tracción activa: soltar a neutro primero (un salto IPC si se puede).
    if throttle_notch > 0 or current_notch > 4:
        return BrakeCommand(
            kind="COAST_THROTTLE",
            target_notch=4,
            phase=None,
            reason="Soltar tracción antes de freno de servicio",
        ), effective_limit

    target = int(step.handle_notch)
    if speed_mph > plan.target_speed_mph + 8:
        target = SERVICE_MIN_HANDLE
    else:
        late_zone_m = brake_command_apply_zone_m(
            speed_mph=speed_mph,
            distance_to_target_m=plan.distance_to_target_m,
            apply_at_remaining_m=step.apply_at_remaining_m,
            dist_start=step.dist_start,
        )
        if (
            step.dist_start < -late_zone_m
            and speed_mph > plan.target_speed_mph + RELEASE_MARGIN_MPH
        ):
            target = SERVICE_MIN_HANDLE
    target = clamp_brake_handle(target, plan.distance_to_target_m)

    return BrakeCommand(
        kind="APPLY",
        target_notch=target,
        phase=step.notch,
        reason=f"Aplicar {step.notch} (distStart={step.dist_start:.0f}m)",
        distance_m=plan.distance_to_target_m,
    ), min(effective_limit, plan.target_speed_mph)


def governor_action_for_command(cmd: BrakeCommand) -> str:
    """
    Acción del decider cuando P1 tiene ``BrakeCommand``.

    La muesca la ejecuta ``HandleController`` vía ``brake_command``;
    no usar acciones de fallback teclado en paralelo.
    """
    if cmd.kind == "RELEASE":
        return RELEASE
    if cmd.kind == "COAST_THROTTLE":
        return COAST
    if (cmd.kind == "APPLY"
            and cmd.target_notch == EMERGENCY_BRAKE_HANDLE):
        return EMERGENCY
    return HOLD


def release_brake_command(*, at_target: bool) -> Optional[BrakeCommand]:
    """Soltar freno a neutro cuando se alcanza el objetivo (Dastsc buildReleaseCommand)."""
    if not at_target:
        return None
    return BrakeCommand(
        kind="RELEASE",
        target_notch=4,
        phase="NEU",
        reason="Objetivo alcanzado — neutro",
    )


# ── RELEASE y anti-rebrake (Dastsc resolveReleaseAction) ─────────────────────


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
    if is_brake_released(handle_notch):
        return None

    if plan is not None and plan.target_kind == "STATION":
        if speed_mph > RELEASE_MARGIN_MPH + 0.5:
            return None
        cmd = release_brake_command(at_target=True)
        if cmd:
            _log.info(
                "P1 RELEASE  spd=%.1f  target=PARADA  handle=%d  dist=%.0fm",
                speed_mph,
                handle_notch,
                plan.distance_to_target_m,
            )
        return cmd

    if next_limit_mph is None:
        return None

    if speed_mph > effective_limit + 0.5:
        return None

    target = target_speed_mph(plan, next_limit_mph, effective_limit)
    if speed_mph > target + LIMIT_RELEASE_MAX_OVER_MPH:
        return None
    # Parado con freno del jugador al iniciar escenario: spd=0 y cartel lejos no es
    # «objetivo alcanzado» — solo soltar si vamos cerca de la velocidad del cartel.
    if speed_mph < target - LIMIT_RELEASE_MIN_SPEED_BAND_MPH:
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
