"""L4 lite — presión cilindro, fill-time y anti-bombeo de aire."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from tsw6v2.constants import NEUTRAL_NOTCH
from tsw6v2.physics import (
    BRAKE_FILL_CLAMP,
    DEFAULT_BRAKE_FILL_S,
    PRESSURE_BRAKING_MIN_BAR,
    PRESSURE_IDLE_MAX_BAR,
)

EMA_ALPHA = 0.10
MIN_FILL_SAMPLES = 3
_COAST_NOTCH = NEUTRAL_NOTCH

# 323 UK — escala lab (B1 ~2.6, B2 ~3.5, B3 ~4.3 bar parado)
_PRESSURE_FOR_HANDLE: dict[int, float] = {
    3: 2.5,  # B1
    2: 3.2,  # B2
    1: 4.0,  # B3
}


def pressure_for_handle(handle: int) -> float:
    """Presión mínima esperada en cilindro para esa muesca de servicio."""
    return _PRESSURE_FOR_HANDLE.get(int(handle), PRESSURE_BRAKING_MIN_BAR)


@dataclass
class BrakeAirTracker:
    """Observa ``brake_cyl_bar`` y aprende retardo de llenado."""

    brake_fill_s: float = DEFAULT_BRAKE_FILL_S
    brake_fill_n: int = 0
    _last_lever: int = _COAST_NOTCH
    _fill_armed_since: float | None = None
    _released_at: float | None = None
    _pressure_at_release: float | None = None

    def observe(self, lever: int, brake_cyl_bar: float | None, *, now: float | None = None) -> None:
        """Un tick: fill-time EMA y marcas de soltar freno."""
        t = time.monotonic() if now is None else now
        lever = int(lever)
        was_coast = self._last_lever >= _COAST_NOTCH
        is_brake = lever < _COAST_NOTCH

        if brake_cyl_bar is not None:
            p = float(brake_cyl_bar)
            if is_brake and was_coast and p < PRESSURE_BRAKING_MIN_BAR:
                self._fill_armed_since = t
            elif not is_brake and self._last_lever < _COAST_NOTCH:
                self._released_at = t
                self._pressure_at_release = p
                self._fill_armed_since = None
            elif (
                self._fill_armed_since is not None
                and p >= PRESSURE_BRAKING_MIN_BAR
            ):
                elapsed = t - self._fill_armed_since
                if 0.15 < elapsed < 10.0:
                    if self.brake_fill_n == 0:
                        self.brake_fill_s = elapsed
                    else:
                        self.brake_fill_s = (
                            EMA_ALPHA * elapsed
                            + (1.0 - EMA_ALPHA) * self.brake_fill_s
                        )
                    self.brake_fill_n += 1
                    lo, hi = BRAKE_FILL_CLAMP
                    self.brake_fill_s = max(lo, min(hi, self.brake_fill_s))
                self._fill_armed_since = None

        self._last_lever = lever

    def air_ready(self, brake_cyl_bar: float | None) -> bool:
        """¿Hay presión suficiente para medir/aplicar freno?"""
        if brake_cyl_bar is None:
            return True
        return float(brake_cyl_bar) >= PRESSURE_BRAKING_MIN_BAR

    def inhibit_reapply(
        self,
        brake_cyl_bar: float | None,
        *,
        now: float | None = None,
    ) -> bool:
        """
        Tras soltar: no volver a frenar hasta vaciar cilindro o pasar fill-time.
        Evita bombar B3→neutro→B3 con tanques vacíos.
        """
        if self._released_at is None:
            return False
        if brake_cyl_bar is None:
            return False
        t = time.monotonic() if now is None else now
        elapsed = t - self._released_at
        p = float(brake_cyl_bar)
        if p <= PRESSURE_IDLE_MAX_BAR + 0.3:
            self._released_at = None
            return False
        return elapsed < self.brake_fill_s * 1.5

    def cap_escalation(
        self,
        *,
        committed: int | None,
        requested: int,
        brake_cyl_bar: float | None,
    ) -> int:
        """
        Un escalón por tick y solo si la presión confirma la muesca actual.
        requested/committed: handle UK (3=B1 … 1=B3).
        """
        if committed is None:
            return requested
        if brake_cyl_bar is None:
            return requested
        p = float(brake_cyl_bar)
        # Más fuerte = handle menor
        if requested >= committed:
            return requested
        need = pressure_for_handle(committed)
        if p < need * 0.92:
            return committed
        return requested

    def to_dict(self) -> dict[str, float | int]:
        return {
            "brake_fill_s": round(self.brake_fill_s, 3),
            "brake_fill_n": self.brake_fill_n,
        }

    def load_dict(self, data: dict) -> None:
        if "brake_fill_s" in data:
            lo, hi = BRAKE_FILL_CLAMP
            self.brake_fill_s = max(
                lo, min(hi, float(data["brake_fill_s"]))
            )
        if "brake_fill_n" in data:
            self.brake_fill_n = int(data["brake_fill_n"])
