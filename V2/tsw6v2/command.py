#!/usr/bin/env python3
"""
command.py — BrakeCommand y mandos IPC (APPLY / COAST / RELEASE).

RELEASE: solo ``resolve_release_command`` (``decision.py`` lo llama con freno puesto).
Plan cartel: ``target.py`` (``BrakeTargetResult``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from tsw6v2.physics import (
    brake_command_apply_zone_m,
    is_downhill_gradient,
    should_emit_brake_command,
    speed_limit_pre_coast_horizon_m,
)
from tsw6v2.plan import BrakePlan, profile_cap_from_plan
from tsw6v2.constants import (
    EMERGENCY_BRAKE_HANDLE,
    EMERGENCY_BRAKE_MAX_DIST_M,
    LIMIT_COAST_BAND_MPH,
    LIMIT_CONTAIN_ESCALATE_OVER_MPH,
    LIMIT_OVER_ACTIVE_MPH,
    LIMIT_RELEASE_MAX_OVER_MPH,
    LIMIT_RELEASE_MIN_SPEED_BAND_MPH,
    LIMIT_SCORING_MAX_OVER_MPH,
    LIMIT_SIGN_PASSED_M,
    NEUTRAL_NOTCH,
    SERVICE_MAX_BRAKE,
    SERVICE_MIN_HANDLE,
    passenger_ops_target_mph,
)
from tsw6v2.limit_containment import downhill_brake_release_floor_mph
from tsw6v2.planning import is_ascending_limit_exit
from tsw6v2.target import (
    BrakeTargetKind,
    BrakeTargetResult,
    SERVICE_HANDLES_WEAK_TO_STRONG,
)

_log = logging.getLogger("tsw6v2.command")

BrakeCommandKind = Literal["APPLY", "RELEASE", "COAST_THROTTLE"]

# Etiquetas para GUI/logs (sin importar tsw6.autopilot)
GOV_RELEASE = "RELEASE"
GOV_COAST = "COAST"
GOV_EMERGENCY = "EMERGENCY"
GOV_HOLD = "HOLD"
RELEASE_MARGIN_MPH = 2.0          # parada en andén (spd muy baja)
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


def limit_release_over_mph(gradient_pct: float = 0.0) -> float:
    """
    Banda RELEASE sobre el suelo objetivo.

    Llano: ``LIMIT_RELEASE_MAX_OVER_MPH`` (0.4).
    Bajada: más ancha cuanto más pendiente — soltar un poco antes; ``g`` corrige
    después (``physics.py`` cabecera). Sesión 323 Cross-City: ~−1 %%.
    """
    if not is_downhill_gradient(gradient_pct):
        return LIMIT_RELEASE_MAX_OVER_MPH
    g = min(1.0, abs(float(gradient_pct)))
    if g <= 0.3:
        return LIMIT_RELEASE_MAX_OVER_MPH
    # −0.3 %% → 0.40 mph; −1.0 %% → 0.55 mph
    t = (g - 0.3) / 0.7
    return LIMIT_RELEASE_MAX_OVER_MPH + t * 0.15


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
    gradient_pct: float = 0.0,
    brake_committed: bool = False,
) -> Optional[BrakeCommand]:
    """
    APPLY / COAST desde plan (sin RELEASE — ver ``resolve_release_command``).

    Cartel: *aware* → *pre-coast* → *APPLY* en ventana cinemática.
    """
    in_window = should_emit_brake_command(
        apply_now=apply_now,
        dist_start=dist_start,
        speed_mph=speed_mph,
        distance_to_target_m=distance_m,
        apply_at_remaining_m=apply_at_remaining_m,
        brake_committed=brake_committed,
    )
    traction = throttle_notch > 0 or current_notch > 4

    if target_kind == "SPEED_LIMIT":
        coast_h = speed_limit_pre_coast_horizon_m(
            speed_mph=speed_mph,
            distance_to_target_m=distance_m,
            apply_at_remaining_m=apply_at_remaining_m,
            dist_start=dist_start,
        )
        if not in_window and dist_start > coast_h:
            return None
        if traction:
            return BrakeCommand(
                kind="COAST_THROTTLE",
                target_notch=4,
                reason="Soltar tracción antes de freno",
            )
        if not in_window:
            return None
    else:
        if traction and dist_start <= 800.0:
            return BrakeCommand(
                kind="COAST_THROTTLE",
                target_notch=4,
                reason="Soltar tracción antes de freno",
            )
        if (
            target_kind == "STATION"
            and speed_mph <= target_speed_mph + RELEASE_MARGIN_MPH
            and distance_m <= 80.0
        ):
            return platform_door_brake_command(distance_m=distance_m)
        if not in_window:
            return None

    target = int(handle_notch)
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
        return GOV_RELEASE
    if cmd.kind == "COAST_THROTTLE":
        return GOV_COAST
    if (cmd.kind == "APPLY"
            and cmd.target_notch == EMERGENCY_BRAKE_HANDLE):
        return GOV_EMERGENCY
    return GOV_HOLD


def platform_door_brake_command(
    *,
    distance_m: Optional[float] = None,
) -> BrakeCommand:
    """B1 en andén: TSW exige freno para abrir puertas; RELEASE al DEPARTING."""
    return BrakeCommand(
        kind="APPLY",
        target_notch=SERVICE_MAX_BRAKE,
        phase="B1",
        reason="Andén: freno para puertas",
        distance_m=distance_m,
    )


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
        is_downhill_gradient(gradient_pct)
        and distance_next_m is not None
        and distance_next_m > 0
    )


def should_hold_limit_brake_downhill(
    *,
    gradient_pct: float,
    distance_next_m: Optional[float],
    speed_mph: float,
    target_mph: float,
) -> bool:
    """No soltar el cartel en bajada hasta pasarlo: g recupera velocidad."""
    if not is_downhill_limit_approach(gradient_pct, distance_next_m):
        return False
    if distance_next_m is None or distance_next_m <= LIMIT_SIGN_PASSED_M:
        return False
    return speed_mph > target_mph - 1.0


def release_target_mph(
    *,
    speed_mph: float,
    effective_limit: float,
    next_limit_mph: Optional[float],
    latch_ops_target: Optional[float] = None,
    gradient_pct: float = 0.0,
) -> float:
    """
    Objetivo para RELEASE.

    Si el cartel siguiente sube (35→60) y ya vamos en banda del límite vigente,
    soltar respecto al posted actual (@34), no al next lejano (@59).
    """
    ops_effective = passenger_ops_target_mph(effective_limit)
    release_over = limit_release_over_mph(gradient_pct)
    if (
        is_ascending_limit_exit(effective_limit, next_limit_mph)
        and speed_mph <= ops_effective + release_over
    ):
        return ops_effective
    if latch_ops_target is not None:
        return latch_ops_target
    if next_limit_mph is not None:
        return passenger_ops_target_mph(next_limit_mph)
    return ops_effective


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
        if self._coast_latch is None:
            return False
        if plan is not None and plan.target_kind != "SPEED_LIMIT":
            return False
        if is_downhill_limit_approach(gradient_pct, distance_next_m):
            return False
        if speed_mph > effective_limit + LIMIT_OVER_ACTIVE_MPH:
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
    latch_ops_target: Optional[float] = None,
) -> Optional[BrakeCommand]:
    if is_brake_released(handle_notch):
        return None

    if plan is not None and plan.target_kind == "STATION":
        # Freno de andén hasta cierre de puertas (FSM DEPARTING).
        return None

    if next_limit_mph is None:
        return None

    if speed_mph > effective_limit + LIMIT_OVER_ACTIVE_MPH:
        return None

    target = release_target_mph(
        speed_mph=speed_mph,
        effective_limit=effective_limit,
        next_limit_mph=next_limit_mph,
        latch_ops_target=latch_ops_target,
        gradient_pct=gradient_pct,
    )
    zone_release_target = None
    release_over = limit_release_over_mph(gradient_pct)
    if next_limit_mph is not None and distance_next_m is not None:
        zone_release_target = downhill_brake_release_floor_mph(
            speed_mph=speed_mph,
            effective_limit=effective_limit,
            next_limit_mph=next_limit_mph,
            distance_next_m=distance_next_m,
            gradient_pct=gradient_pct,
            release_over_mph=release_over,
        )
        if zone_release_target is not None:
            target = zone_release_target
    ops_effective = passenger_ops_target_mph(effective_limit)
    ascending_exit = (
        is_ascending_limit_exit(effective_limit, next_limit_mph)
        and speed_mph <= ops_effective + release_over
    )
    hold_target = (
        passenger_ops_target_mph(next_limit_mph)
        if next_limit_mph is not None
        else target
    )
    if not ascending_exit and zone_release_target is None and should_hold_limit_brake_downhill(
        gradient_pct=gradient_pct,
        distance_next_m=distance_next_m,
        speed_mph=speed_mph,
        target_mph=hold_target,
    ):
        return None
    if speed_mph > target + release_over:
        return None
    # Parado con freno del jugador al iniciar escenario: spd=0 y cartel lejos no es
    # «objetivo alcanzado» — solo soltar si vamos cerca de la velocidad del cartel.
    if speed_mph < target - LIMIT_RELEASE_MIN_SPEED_BAND_MPH:
        return None

    cmd = release_brake_command(at_target=True)
    if cmd:
        _log.debug(
            "P1 RELEASE  spd=%.1f  target=%.1f  handle=%d  next=%s",
            speed_mph,
            target,
            handle_notch,
            f"{next_limit_mph:.0f}mph" if next_limit_mph is not None else "—",
        )
    return cmd


__all__ = [
    "BrakeCommand",
    "BrakeCommandKind",
    "BrakeReleaseState",
    "BrakeTargetKind",
    "BrakeTargetResult",
    "COAST_CLEAR_OVERSHOOT_MPH",
    "COAST_REBRAKE_MARGIN_MPH",
    "GOV_COAST",
    "GOV_EMERGENCY",
    "GOV_HOLD",
    "GOV_RELEASE",
    "LIMIT_COAST_BAND_MPH",
    "LIMIT_CONTAIN_ESCALATE_OVER_MPH",
    "LIMIT_OVER_ACTIVE_MPH",
    "LIMIT_RELEASE_MAX_OVER_MPH",
    "LIMIT_RELEASE_MIN_SPEED_BAND_MPH",
    "LIMIT_SCORING_MAX_OVER_MPH",
    "LIMIT_SIGN_PASSED_M",
    "RELEASE_MARGIN_MPH",
    "SERVICE_HANDLES_WEAK_TO_STRONG",
    "SpeedLimitCoastLatch",
    "clamp_brake_handle",
    "command_from_target",
    "governor_action_for_command",
    "is_brake_applied",
    "is_brake_released",
    "is_downhill_limit_approach",
    "limit_release_over_mph",
    "plan_to_brake_command",
    "platform_door_brake_command",
    "release_brake_command",
    "release_target_mph",
    "resolve_release_command",
    "should_hold_limit_brake_downhill",
]
