#!/usr/bin/env python3
"""
objectives.py — Cómo frenar cada objetivo: andén, señal (stub), emergencia.
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from tsw6.autopilot.control_actions import BRAKE, EMERGENCY
from tsw6v2.command import BrakeCommand
from tsw6v2.constants import EMERGENCY_BRAKE_HANDLE
from tsw6v2.p1_emergency import EmergencyTargetKind, check_p1_emergency as _check_cmd
from tsw6v2.target import BrakeTargetResult

_RED_SIGNAL_ASPECTS = frozenset({"DANGER", "RED", "STOP"})


def evaluate_signal_brake(
    *,
    speed_mph: float,
    signal_distance_m: Optional[float],
    signal_aspect: Optional[str] = None,
    gradient_pct: float = 0.0,
    base_decel: float = 0.8,
    predict_decel=None,
) -> Optional[BrakeTargetResult]:
    """Stub — implementar cuando haya telemetría de aspecto DANGER."""
    _ = (speed_mph, signal_distance_m, signal_aspect, gradient_pct,
         base_decel, predict_decel)
    return None


def is_red_signal_aspect(aspect: Optional[str]) -> bool:
    """True si el aspecto exige parada (Dastsc: DANGER)."""
    if not aspect:
        return False
    upper = aspect.strip().upper()
    return upper in _RED_SIGNAL_ASPECTS or "DANGER" in upper


def check_p1_emergency(
    *,
    target_kind: EmergencyTargetKind,
    speed_mph: float,
    urgent_dist_m: Optional[float],
    base_decel: float,
    gradient_pct: float,
    brake_transition_s: float,
    accel_ms2: Optional[float],
) -> Optional[Tuple[str, float, BrakeCommand]]:
    """Adaptador legacy → ``(action, effective_limit, cmd)``."""
    cmd = _check_cmd(
        target_kind=target_kind,
        speed_mph=speed_mph,
        urgent_dist_m=urgent_dist_m,
        base_decel=base_decel,
        gradient_pct=gradient_pct,
        brake_transition_s=brake_transition_s,
        accel_ms2=accel_ms2,
    )
    if cmd is None:
        return None
    action = EMERGENCY if cmd.target_notch == EMERGENCY_BRAKE_HANDLE else BRAKE
    return action, 0.0, cmd
