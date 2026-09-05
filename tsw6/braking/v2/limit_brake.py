"""
Compat v1 — cartel P1 canónico en ``V2/tsw6v2/`` (``limits`` + ``limit_*``).

Diseño: docs/v2/REGLAS_FRENOS_P1.md. No mantener lógica aquí.
"""

from tsw6v2.limit_notch import apply_notch_hysteresis
from tsw6v2.limit_state import (
    LimitBrakeLatch,
    LimitBrakeState,
    decel_for_handle,
    latch_limit_target,
    limit_changed,
    refresh_latch_physics,
)
from tsw6v2.limits import evaluate_limit_brake

# Tests legacy importaban el nombre privado v1.
_apply_notch_hysteresis = apply_notch_hysteresis

__all__ = [
    "LimitBrakeLatch",
    "LimitBrakeState",
    "_apply_notch_hysteresis",
    "apply_notch_hysteresis",
    "decel_for_handle",
    "evaluate_limit_brake",
    "latch_limit_target",
    "limit_changed",
    "refresh_latch_physics",
]
