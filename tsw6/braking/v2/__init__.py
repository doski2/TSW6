"""
Frenado v2 — módulo único de frenado TSW6.

- ``physics`` / ``plan`` — cinemática y tipos de plan
- ``policy``             — cluster cartel↔andén y prioridad
- ``objectives``         — andén (vía station_plan), señal stub, emergencia
- ``station_plan``       — perfil B1–B3 a 0 mph (HUD + ETA)
- ``limit_brake``        — cartel activo (estado latch)
- ``command``            — BrakeCommand + BrakeTargetResult
- ``coordinator``        — un tick P1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tsw6.braking.v2.command import BrakeTargetKind, BrakeTargetResult
    from tsw6.braking.v2.coordinator import BrakeCoordinatorV2

__all__ = [
    "BrakeCoordinatorV2",
    "BrakeTargetKind",
    "BrakeTargetResult",
]


def __getattr__(name: str):
    if name == "BrakeCoordinatorV2":
        from tsw6.braking.v2.coordinator import BrakeCoordinatorV2

        return BrakeCoordinatorV2
    if name == "BrakeTargetKind":
        from tsw6.braking.v2.command import BrakeTargetKind

        return BrakeTargetKind
    if name == "BrakeTargetResult":
        from tsw6.braking.v2.command import BrakeTargetResult

        return BrakeTargetResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
