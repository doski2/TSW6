"""Adaptador de vehículo: lo que cambia entre layouts, tras una interfaz única.

Sustituye los ``if uses_mc_analog_ipc(pkg)`` dispersos (ANALISIS §2.4 paso 2). Se migra una
operación cada vez; las que aún no están aquí siguen consultando el paquete directamente.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol

from tsw6v2.constants import MC_INPUT_VALUE_EPS, NEUTRAL_NOTCH
from tsw6v2.roll_latch import StationRollLatch
from tsw6v2.vehicle_package import (
    mc_click_hysteresis_m,
    mc_click_wait,
    mc_has_traction_above_neutral,
    mc_limit_brake_fraction,
    mc_platform_bleed_b1_latched,
    mc_platform_bleed_neutral_ipc,
    mc_platform_bleed_should_reapply_b1,
    mc_stop_brake_fraction,
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

    def station_stop_fraction(
        self,
        *,
        speed_mph: float,
        distance_m: float,
        gradient_pct: float,
        decel_table: Optional[dict[float, float]],
    ) -> Optional[float]:
        """Posición 0..1 para parar en el andén; ``None`` = el layout frena por muescas."""
        ...

    def roll_until_click(
        self,
        *,
        speed_mph: float,
        distance_m: float,
        gradient_pct: float,
        click_decel_ms2: Optional[float],
        running: bool,
        latch: Optional[StationRollLatch],
    ) -> bool:
        """¿Rodar en neutro hasta el clic antes de frenar en el andén?"""
        ...

    def limit_fraction(
        self,
        *,
        speed_mph: float,
        target_mph: float,
        distance_m: float,
        gradient_pct: float,
        decel_table: Optional[dict[float, float]],
    ) -> Optional[float]:
        """Posición 0..1 para llegar al cartel; ``None`` = el layout frena por muescas."""
        ...

    def bleed_b1_latched(self, snap: Optional["ProbeSnapshot"]) -> bool:
        """Bleed de andén: ¿B1 sostenido en el eje? (solo layout analógico)."""
        ...

    def bleed_neutral_reached(self, snap: Optional["ProbeSnapshot"]) -> bool:
        """Bleed de andén: ¿el mando ya llegó a neutro? (solo layout analógico)."""
        ...

    def bleed_should_reapply_b1(self, snap: Optional["ProbeSnapshot"]) -> bool:
        """Bleed de andén: ¿mandar otro APPLY B1? (solo layout analógico)."""
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

    def station_stop_fraction(self, **_: object) -> Optional[float]:
        return None

    def roll_until_click(self, **_: object) -> bool:
        return False

    def limit_fraction(self, **_: object) -> Optional[float]:
        return None

    def bleed_b1_latched(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return False

    def bleed_neutral_reached(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return False

    def bleed_should_reapply_b1(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return False


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


    def station_stop_fraction(
        self,
        *,
        speed_mph: float,
        distance_m: float,
        gradient_pct: float,
        decel_table: Optional[dict[float, float]],
    ) -> Optional[float]:
        return mc_stop_brake_fraction(
            self.package,
            speed_mph=speed_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            decel_table=decel_table,
        )

    def roll_until_click(
        self,
        *,
        speed_mph: float,
        distance_m: float,
        gradient_pct: float,
        click_decel_ms2: Optional[float],
        running: bool,
        latch: Optional[StationRollLatch],
    ) -> bool:
        return mc_click_wait(
            self.package,
            speed_mph=speed_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            click_decel_ms2=click_decel_ms2,
            extra_margin_m=mc_click_hysteresis_m(distance_m, stop_running=running),
            latch=latch,
        )

    def limit_fraction(
        self,
        *,
        speed_mph: float,
        target_mph: float,
        distance_m: float,
        gradient_pct: float,
        decel_table: Optional[dict[float, float]],
    ) -> Optional[float]:
        return mc_limit_brake_fraction(
            self.package,
            speed_mph=speed_mph,
            target_mph=target_mph,
            distance_m=distance_m,
            gradient_pct=gradient_pct,
            decel_table=decel_table,
        )

    def bleed_b1_latched(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return mc_platform_bleed_b1_latched(snap, self.package)

    def bleed_neutral_reached(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return mc_platform_bleed_neutral_ipc(snap, self.package)

    def bleed_should_reapply_b1(self, snap: Optional["ProbeSnapshot"]) -> bool:
        return mc_platform_bleed_should_reapply_b1(snap, self.package)


def adapter_for_package(package: Optional[dict]) -> VehicleAdapter:
    if package and uses_mc_analog_ipc(package):
        return McAnalogAdapter(package)
    return NotchAdapter(package)
