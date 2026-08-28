#!/usr/bin/env python3
"""
command.py — BrakeCommand, BrakeTargetResult, APPLY/RELEASE (Dastsc commandBus).
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


def command_from_target(
    *,
    target_kind: str,
    distance_m: float,
    target_speed_mph: float,
    handle_notch: int,
    phase: str,
    dist_start: float,
    apply_now: bool,
    throttle_notch: int,
    current_notch: int,
    speed_mph: float,
    apply_at_remaining_m: Optional[float] = None,
    detail: str = "",
) -> Optional[BrakeCommand]:
    """
    Un solo camino APPLY / RELEASE / COAST (P1 v2).

    Orden: tracción→COAST; cartel/andén alcanzados→RELEASE; si no, ventana o
    overspeed→APPLY (B3 si ya tarde).
    """
    traction = throttle_notch > 0 or current_notch > 4
    if traction and (target_kind == "SPEED_LIMIT" or dist_start <= 800.0):
        return BrakeCommand(
            kind="COAST_THROTTLE",
            target_notch=4,
            reason="Soltar tracción antes de freno",
        )
    if (
        target_kind == "SPEED_LIMIT"
        and current_notch < 4
        and speed_mph <= target_speed_mph + LIMIT_RELEASE_MAX_OVER_MPH
    ):
        return release_brake_command(at_target=True)
    if (
        target_kind == "STATION"
        and current_notch < 4
        and speed_mph <= target_speed_mph + RELEASE_MARGIN_MPH
    ):
        return BrakeCommand(
            kind="RELEASE",
            target_notch=4,
            phase="NEU",
            reason="Parada en andén",
            distance_m=distance_m,
        )
    overspeed = (
        target_kind == "SPEED_LIMIT"
        and speed_mph > target_speed_mph + LIMIT_SCORING_MAX_OVER_MPH
        and current_notch <= 4
        and throttle_notch <= 0
    )
    if not overspeed and not should_emit_brake_command(
        apply_now=apply_now,
        dist_start=dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=distance_m,
        apply_at_remaining_m=apply_at_remaining_m,
    ):
        return None
    target = int(handle_notch)
    if speed_mph > target_speed_mph + 8:
        target = SERVICE_MIN_HANDLE
    else:
        late_zone_m = brake_command_apply_zone_m(
            speed_mph=speed_mph,
            distance_to_target_m=distance_m,
            apply_at_remaining_m=apply_at_remaining_m,
            dist_start=dist_start,
        )
        if (
            dist_start < -late_zone_m
            and speed_mph > target_speed_mph + RELEASE_MARGIN_MPH
        ):
            target = SERVICE_MIN_HANDLE
    target = clamp_brake_handle(target, distance_m)
    return BrakeCommand(
        kind="APPLY",
        target_notch=target,
        phase=phase,
        reason=detail or f"{phase} distStart={dist_start:.0f}m",
        distance_m=distance_m,
    )


def plan_to_brake_command(
    plan: BrakePlan,
    *,
    speed_mph: float,
    throttle_notch: int,
    effective_limit: float,
    current_notch: int,
) -> tuple[Optional[BrakeCommand], float]:
    """Convierte ``BrakePlan`` vía ``command_from_target`` (tests / cap de perfil)."""
    step = plan.active_step
    if step is None:
        return None, effective_limit

    cap = profile_cap_from_plan(plan, speed_mph, effective_limit)
    effective_limit = min(effective_limit, cap)
    cmd = command_from_target(
        target_kind=plan.target_kind,
        distance_m=plan.distance_to_target_m,
        target_speed_mph=plan.target_speed_mph,
        handle_notch=int(step.handle_notch),
        phase=step.notch,
        dist_start=step.dist_start,
        apply_now=step.apply_now,
        throttle_notch=throttle_notch,
        current_notch=current_notch,
        speed_mph=speed_mph,
        apply_at_remaining_m=step.apply_at_remaining_m,
        detail=f"Aplicar {step.notch} (distStart={step.dist_start:.0f}m)",
    )
    if cmd is not None and cmd.kind in ("APPLY", "RELEASE"):
        return cmd, min(effective_limit, plan.target_speed_mph)
    return cmd, effective_limit


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


BrakeTargetKind = Literal["SPEED_LIMIT", "STATION", "SIGNAL"]

# Handle UK servicio: 3=B1 (suave) … 1=B3 (fuerte)
SERVICE_HANDLES_WEAK_TO_STRONG: tuple[tuple[int, str], ...] = (
    (3, "B1"),
    (2, "B2"),
    (1, "B3"),
)


@dataclass
class BrakeTargetResult:
    """Resultado de un planificador por objetivo (antes de prioridad)."""

    target_kind: BrakeTargetKind
    distance_m: float
    target_speed_mph: float
    handle_notch: int
    phase: str
    dist_start: float
    apply_now: bool
    detail: str = ""

    @property
    def urgency(self) -> float:
        """Menor dist_start = frenar antes (Dastsc)."""
        return self.dist_start

    def to_brake_command(
        self,
        *,
        throttle_notch: int = 0,
        current_notch: int = 4,
        speed_mph: float = 0.0,
    ) -> Optional[BrakeCommand]:
        return command_from_target(
            target_kind=self.target_kind,
            distance_m=self.distance_m,
            target_speed_mph=self.target_speed_mph,
            handle_notch=self.handle_notch,
            phase=self.phase,
            dist_start=self.dist_start,
            apply_now=self.apply_now,
            throttle_notch=throttle_notch,
            current_notch=current_notch,
            speed_mph=speed_mph,
            apply_at_remaining_m=self.distance_m - self.dist_start,
            detail=self.detail,
        )
