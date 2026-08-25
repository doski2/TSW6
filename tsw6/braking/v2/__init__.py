"""
Frenado v2 — módulo único de frenado TSW6.

- ``physics``    — cinemática y distancias
- ``plan``         — tipos de plan (BrakePlan, steps)
- ``command``      — APPLY/RELEASE, coast latch
- ``cluster``      — cartel ↔ estación (350 m)
- ``planner``      — planificación estación/límite (Dastsc)
- ``limit_brake``  — cartel activo v2
- ``station_brake``— parada en andén
- ``signal_brake`` — semáforo (pendiente)
- ``priority``     — qué objetivo gana
- ``coordinator``  — orquestación P1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tsw6.braking.v2.coordinator import BrakeCoordinatorV2
    from tsw6.braking.v2.types import BrakeTargetKind, BrakeTargetResult

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
        from tsw6.braking.v2.types import BrakeTargetKind

        return BrakeTargetKind
    if name == "BrakeTargetResult":
        from tsw6.braking.v2.types import BrakeTargetResult

        return BrakeTargetResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
