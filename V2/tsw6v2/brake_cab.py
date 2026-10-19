"""Estado de cabina y fase de servicio — layout-agnóstico (PLAN_ACTUACION_MC fase 0)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional

from tsw6v2.physics import PRESSURE_IDLE_MAX_BAR

if TYPE_CHECKING:
    from tsw6v2.bridge.getdata import ProbeSnapshot

ServicePhase = Literal["B1", "B2", "B3", "NEU", "RELEASE"]


class BrakeCabState(Enum):
    RELEASED = "released"
    HELD_SERVICE = "held_service"
    HELD_EMERGENCY = "held_emergency"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceBrakeIntent:
    """Fase P1 de freno de servicio (independiente de muesca UK / fracción MC)."""

    phase: ServicePhase
    strength: Optional[float] = None


def _residual_brake_pressure(snap: Optional["ProbeSnapshot"]) -> bool:
    return (
        snap is not None
        and snap.brake_cyl_bar is not None
        and float(snap.brake_cyl_bar) > PRESSURE_IDLE_MAX_BAR
    )


def brake_state_from_probe(
    snap: Optional["ProbeSnapshot"],
    lever: Optional[int],
    vehicle_package: Optional[dict] = None,
) -> BrakeCabState:
    """
    Freno de servicio en cabina para política / dwell / RELEASE.

    UK: ``lever_notch``. MC: ``mc_input`` (D2) o estimación + cilindro residual.
    """
    from tsw6v2.vehicle_adapter import adapter_for_package
    from tsw6v2.vehicle_package import vehicle_package_from_snap

    pkg = vehicle_package_from_snap(snap, vehicle_package) if snap is not None else vehicle_package
    said = adapter_for_package(pkg).lever_says_brake(snap, lever)
    if said or _residual_brake_pressure(snap):
        return BrakeCabState.HELD_SERVICE
    if said is False:
        return BrakeCabState.RELEASED
    return BrakeCabState.UNKNOWN


def service_brake_held_from_probe(
    snap: Optional["ProbeSnapshot"],
    lever: Optional[int],
    vehicle_package: Optional[dict] = None,
) -> bool:
    """¿Freno de servicio aplicado o aire residual (RELEASE / dwell)?"""
    state = brake_state_from_probe(snap, lever, vehicle_package)
    return state in (BrakeCabState.HELD_SERVICE, BrakeCabState.HELD_EMERGENCY)
