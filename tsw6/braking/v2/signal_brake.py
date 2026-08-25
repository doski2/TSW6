#!/usr/bin/env python3
"""
signal_brake.py — Frenada ante semáforo en rojo (v2, pendiente).

Dastsc: ``planBrakeForSignal`` solo con aspect DANGER; misma prioridad que
estación en ``selectStationActiveStep``; gana sobre límite si dist ≤ limit+350 m.
"""

from __future__ import annotations

from typing import Optional

from tsw6.braking.v2.types import BrakeTargetResult


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
