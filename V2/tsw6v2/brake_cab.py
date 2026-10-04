"""Estado de cabina y fase de servicio — layout-agnóstico (PLAN_ACTUACION_MC fase 0)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional

from tsw6v2.constants import MC_INPUT_VALUE_EPS, NEUTRAL_NOTCH
from tsw6v2.command import is_brake_applied
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
    from tsw6v2.vehicle_package import (
        probe_mc_input_fraction,
        profile_neutral_fraction,
        uses_mc_analog_ipc,
        vehicle_package_from_snap,
    )

    lev = int(lever) if lever is not None else NEUTRAL_NOTCH
    pkg = vehicle_package_from_snap(snap, vehicle_package) if snap is not None else vehicle_package

    if pkg and uses_mc_analog_ipc(pkg):
        neutral = profile_neutral_fraction(pkg)
        if neutral is not None:
            est = probe_mc_input_fraction(snap, pkg)
            if est is not None:
                if float(est) < float(neutral) - MC_INPUT_VALUE_EPS:
                    return BrakeCabState.HELD_SERVICE
                if float(est) >= float(neutral) - MC_INPUT_VALUE_EPS:
                    if _residual_brake_pressure(snap):
                        return BrakeCabState.HELD_SERVICE
                    return BrakeCabState.RELEASED
        if _residual_brake_pressure(snap):
            return BrakeCabState.HELD_SERVICE
        return BrakeCabState.UNKNOWN

    if is_brake_applied(lev):
        return BrakeCabState.HELD_SERVICE
    if _residual_brake_pressure(snap):
        return BrakeCabState.HELD_SERVICE
    return BrakeCabState.RELEASED


def service_brake_held_from_probe(
    snap: Optional["ProbeSnapshot"],
    lever: Optional[int],
    vehicle_package: Optional[dict] = None,
) -> bool:
    """¿Freno de servicio aplicado o aire residual (RELEASE / dwell)?"""
    state = brake_state_from_probe(snap, lever, vehicle_package)
    return state in (BrakeCabState.HELD_SERVICE, BrakeCabState.HELD_EMERGENCY)
