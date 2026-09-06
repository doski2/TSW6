"""
Compat mínima — tipos y adaptador P1 cartel en ``tsw6v2``.

Orchestración legacy (coordinator/policy/station_plan) eliminada; ver
``archive/braking_v1_autopilot/``.
"""

from __future__ import annotations

from tsw6v2.autopilot_limit import BrakeCoordinatorV2, LimitP1Adapter
from tsw6v2.target import BrakeTargetKind, BrakeTargetResult

__all__ = [
    "BrakeCoordinatorV2",
    "BrakeTargetKind",
    "BrakeTargetResult",
    "LimitP1Adapter",
]
