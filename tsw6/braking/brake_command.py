#!/usr/bin/env python3
"""
brake_command.py — Comandos de freno estilo Dastsc (notch directo).

Dastsc no usa COAST/BRAKE genéricos para P1: el plan activo define B1/B2/B3
y commandBus escribe el valor absoluto al IPC. TSW6 conserva COAST/BRAKE para
P2/ACK/emergencias; P1 con plan activo usa ``BrakeCommand``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from tsw6.braking.brake_planner import BrakePlan, profile_cap_from_plan

BrakeCommandKind = Literal["APPLY", "RELEASE", "COAST_THROTTLE"]


@dataclass(frozen=True)
class BrakeCommand:
    """Mando de freno Dastsc — notch absoluto vía IPC cuando hay plan P1."""

    kind: BrakeCommandKind
    target_notch: Optional[int] = None   # handle combinado UK 0–8
    phase: Optional[str] = None        # B1, B2, B3
    reason: str = ""

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

    if not step.apply_now and step.dist_start > 60:
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
    if step.dist_start < -30 or speed_mph > plan.target_speed_mph + 8:
        target = 0 if step.handle_notch <= 1 else target

    return BrakeCommand(
        kind="APPLY",
        target_notch=target,
        phase=step.notch,
        reason=f"Aplicar {step.notch} (distStart={step.dist_start:.0f}m)",
    ), min(effective_limit, plan.target_speed_mph)


def governor_action_for_command(cmd: BrakeCommand) -> str:
    """
    Acción del decider cuando P1 tiene ``BrakeCommand``.

    La muesca la ejecuta ``HandleController`` vía ``brake_command``;
    no usar COAST/BRAKE/HARDBRAKE legacy en paralelo.
    """
    if cmd.kind == "RELEASE":
        return "RELEASE"
    if cmd.kind == "COAST_THROTTLE":
        return "COAST"
    return "HOLD"


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
