"""Adaptador de vehículo: lo que cambia entre layouts, tras una interfaz única.

Sustituye los ``if uses_mc_analog_ipc(pkg)`` dispersos (ANALISIS §2.4 paso 2). Se migra una
operación cada vez; las que aún no están aquí siguen consultando el paquete directamente.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol

from tsw6v2.constants import MC_INPUT_VALUE_EPS, NEUTRAL_NOTCH
from tsw6v2.vehicle_package import (
    mc_has_traction_above_neutral,
    probe_mc_input_fraction,
    profile_neutral_fraction,
    uses_mc_analog_ipc,
)

if TYPE_CHECKING:
    from tsw6v2.bridge.getdata import ProbeSnapshot


class VehicleAdapter(Protocol):
    def throttle_notch(self, snap: "ProbeSnapshot") -> int:
        """Tracción pedida (0 = ninguna) para COAST / salida de andén."""
        ...

    def station_lever(self, snap: "ProbeSnapshot", lever: Optional[int]) -> int:
        """Muesca combinada UK equivalente para la FSM de andén."""
        ...

    def lever_says_brake(self, snap: Optional["ProbeSnapshot"], lever: Optional[int]) -> Optional[bool]:
        """¿La palanca indica freno de servicio? ``None`` = no se puede saber."""
        ...

    analog_lever: bool
    """``True`` si la palanca es analógica (``lever_notch`` UK no es fiable; manda ``mc_input``)."""

    single_step: bool
    """``True`` si un solo mando IPC lleva la palanca al objetivo (sin pasos intermedios)."""

    def wire_fraction(self, target: int) -> Optional[float]:
        """Fracción 0..1 en línea para la muesca lógica ``target``; ``None`` = mando por muesca."""
        ...

    def fraction_feedback(self, snap: "ProbeSnapshot") -> Optional[float]:
        """Posición 0..1 de la palanca leída del probe (feedback del mando por fracción)."""
        ...


class NotchAdapter:
    """Palanca combinada por muescas (Class 323)."""

    analog_lever = False
    single_step = False

    def __init__(self, package: Optional[dict] = None) -> None:
        self.package = package

    def throttle_notch(self, snap: "ProbeSnapshot") -> int:
        lever = snap.combined_handle_notch()
        if lever is None:
            return 0
        return max(0, int(lever) - NEUTRAL_NOTCH)

    def station_lever(self, snap: "ProbeSnapshot", lever: Optional[int]) -> int:
        return int(lever) if lever is not None else NEUTRAL_NOTCH

    def lever_says_brake(self, snap: Optional["ProbeSnapshot"], lever: Optional[int]) -> Optional[bool]:
        from tsw6v2.command import is_brake_applied

        return is_brake_applied(int(lever) if lever is not None else NEUTRAL_NOTCH)

    def wire_fraction(self, target: int) -> Optional[float]:
        return None

    def fraction_feedback(self, snap: "ProbeSnapshot") -> Optional[float]:
        tb = snap.train_brake
        return float(tb) if tb is not None else None


class McAnalogAdapter:
    """Palanca MC analógica (M3A): la tracción sale de ``power`` / ``mc_input``, no de la muesca."""

    analog_lever = True
    single_step = True

    def __init__(self, package: dict) -> None:
        self.package = package

    def throttle_notch(self, snap: "ProbeSnapshot") -> int:
        return 1 if mc_has_traction_above_neutral(snap, self.package) else 0

    def station_lever(self, snap: "ProbeSnapshot", lever: Optional[int]) -> int:
        th = self.throttle_notch(snap)
        return NEUTRAL_NOTCH + th if th > 0 else NEUTRAL_NOTCH

    def wire_fraction(self, target: int) -> Optional[float]:
        from tsw6v2.vehicle_package import combined_notch_to_ipc_value

        return combined_notch_to_ipc_value(target, self.package)

    def fraction_feedback(self, snap: "ProbeSnapshot") -> Optional[float]:
        return probe_mc_input_fraction(snap, self.package)

    def lever_says_brake(self, snap: Optional["ProbeSnapshot"], lever: Optional[int]) -> Optional[bool]:
        neutral = profile_neutral_fraction(self.package)
        if neutral is None:
            return None
        est = probe_mc_input_fraction(snap, self.package)
        if est is None:
            return None
        return float(est) < float(neutral) - MC_INPUT_VALUE_EPS


def adapter_for_package(package: Optional[dict]) -> VehicleAdapter:
    if package and uses_mc_analog_ipc(package):
        return McAnalogAdapter(package)
    return NotchAdapter(package)
