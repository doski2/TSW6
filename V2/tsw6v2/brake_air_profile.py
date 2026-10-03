"""Perfil L4 aire/freno por paquete G-B (323 vs MC US y futuros)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

MODEL_UK_EMU = "uk_emu"
MODEL_MASTER_CONTROLLER = "master_controller"


@dataclass(frozen=True)
class BrakeAirProfile:
    """
    ``uk_emu``: presión cilindro estilo Class 323 (reposo ~1 bar).
    ``master_controller``: MC US — presión reposo alta; IPC analog; lever HUD ≠ UK.
    """

    model: str = MODEL_UK_EMU

    @classmethod
    def uk_emu(cls) -> BrakeAirProfile:
        return cls(model=MODEL_UK_EMU)

    @classmethod
    def from_vehicle_package(cls, package: Optional[dict[str, Any]]) -> BrakeAirProfile:
        from tsw6v2.vehicle_package import resolve_brake_air_profile

        return resolve_brake_air_profile(package)

    def is_master_controller(self) -> bool:
        return self.model == MODEL_MASTER_CONTROLLER
