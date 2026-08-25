#!/usr/bin/env python3
"""
control_actions.py — Nombres de acción del autopilot (solo-frenado).

Semántica:
  COAST      — soltar tracción hacia neutro
  BRAKE      — un paso de freno de servicio (fallback teclado)
  BRAKE_FAST — freno servicio máximo (hasta B3): DMI, watchdog
  EMERGENCY  — muesca 0 ATP (P1-CRITICO a ≤25 m)
  HOLD       — no tocar mando; P1 activo delega en ``BrakeCommand``
  PAUSED     — operador pausó el autopilot
  RELEASE    — neutro tras objetivo (``BrakeCommand``)

P1 v2: la muesca real va en ``BrakeCommand``; muchas acciones son etiquetas de log.
"""

from __future__ import annotations

from typing import Final

COAST: Final = "COAST"
BRAKE: Final = "BRAKE"
BRAKE_FAST: Final = "BRAKE_FAST"
EMERGENCY: Final = "EMERGENCY"
HOLD: Final = "HOLD"
PAUSED: Final = "PAUSED"
RELEASE: Final = "RELEASE"

GOVERNOR_ACTIONS = frozenset({
    COAST, BRAKE, BRAKE_FAST, EMERGENCY, HOLD, PAUSED, RELEASE,
})
