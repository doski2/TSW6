"""Lectura de perfiles learner v1 (``ema`` / ``ema_bands``) sin depender de ``tsw6``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

MIN_SAMPLES = 3
_SPEED_BANDS = ((0, 30), (30, 60), (60, 200))
_BRAKE_HANDLES = (0, 1, 2, 3)


def speed_band_index(speed_mph: float) -> int:
    for i, (lo, hi) in enumerate(_SPEED_BANDS):
        if lo <= speed_mph < hi:
            return i
    return len(_SPEED_BANDS) - 1


def gravity_compensation(grad_pct: float) -> float:
    """Igual que v1 ``online_learner._gravity_compensation``."""
    return -9.81 * (grad_pct / 100.0)


def _parse_float_map(raw: dict[Any, Any]) -> dict[int, float]:
    return {int(k): float(v) for k, v in raw.items()}


def _parse_int_map(raw: dict[Any, Any]) -> dict[int, int]:
    return {int(k): int(v) for k, v in raw.items()}


def _parse_float_band_list(
    raw_bands: list[dict[Any, Any]] | None,
    *,
    n_slots: int,
) -> list[dict[int, float]]:
    out: list[dict[int, float]] = [{} for _ in range(n_slots)]
    if not raw_bands:
        return out
    for i, band in enumerate(raw_bands):
        if i < n_slots:
            out[i] = _parse_float_map(band)
    return out


def _parse_int_band_list(
    raw_bands: list[dict[Any, Any]] | None,
    *,
    n_slots: int,
) -> list[dict[int, int]]:
    out: list[dict[int, int]] = [{} for _ in range(n_slots)]
    if not raw_bands:
        return out
    for i, band in enumerate(raw_bands):
        if i < n_slots:
            out[i] = _parse_int_map(band)
    return out


@dataclass
class V1LearnerData:
    ema: dict[int, float] = field(default_factory=dict)
    n: dict[int, int] = field(default_factory=dict)
    ema_bands: list[dict[int, float]] = field(default_factory=lambda: [{} for _ in _SPEED_BANDS])
    n_bands: list[dict[int, int]] = field(default_factory=lambda: [{} for _ in _SPEED_BANDS])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Optional[V1LearnerData]:
        if not (data.get("ema") or data.get("ema_bands")):
            return None
        ema = _parse_float_map(data.get("ema") or {})
        n = _parse_int_map(data.get("n") or {})
        ema_bands = _parse_float_band_list(
            data.get("ema_bands"), n_slots=len(_SPEED_BANDS)
        )
        n_bands = _parse_int_band_list(data.get("n_bands"), n_slots=len(_SPEED_BANDS))
        return cls(ema=ema, n=n, ema_bands=ema_bands, n_bands=n_bands)

    def predict_accel(
        self,
        notch: int,
        speed_mph: float,
        grad_pct: float,
    ) -> Optional[float]:
        """Aceleración real m/s² (negativa = freno), como v1 ``predict_accel``."""
        band = speed_band_index(speed_mph)
        flat: Optional[float] = None
        if (
            self.n_bands[band].get(notch, 0) >= MIN_SAMPLES
            and notch in self.ema_bands[band]
        ):
            flat = self.ema_bands[band][notch]
        elif self.n.get(notch, 0) >= MIN_SAMPLES and notch in self.ema:
            flat = self.ema[notch]
        if flat is None:
            return None
        return flat + gravity_compensation(grad_pct)

    def predict_brake_decel_ms2(
        self,
        handle_notch: int,
        speed_mph: float,
        grad_pct: float = 0.0,
    ) -> Optional[float]:
        """Decel positiva m/s² para muescas de servicio 0–3."""
        if handle_notch not in _BRAKE_HANDLES:
            return None
        accel = self.predict_accel(handle_notch, speed_mph, grad_pct)
        if accel is None or accel >= -0.05:
            return None
        return abs(accel)
