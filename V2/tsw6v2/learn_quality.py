"""Filtros de calidad para aprendizaje online (ventana estable, outliers)."""

from __future__ import annotations

from dataclasses import dataclass, field

from tsw6v2.learner_v1 import (
    MAX_OBSERVE_GRAD_PCT,
    MIN_OBSERVE_SPEED_MPH,
    gravity_compensation,
)

MIN_STABLE_S = 2.0
MIN_DV_MPH = 0.6
MIN_WINDOW_SAMPLES = 4
OUTLIER_RATIO = 0.30
MIN_OUTLIER_ABS_MS2 = 0.08
FILL_OUTLIER_RATIO = 0.35
FILL_OUTLIER_MIN_S = 0.40


@dataclass(frozen=True)
class LearnEvent:
    kind: str
    accepted: bool
    reason: str


@dataclass
class _DecelTick:
    t: float
    speed_mph: float
    handle: int
    grad_pct: float
    accel_ms2: float


@dataclass
class DecelObserveWindow:
    """Ventana estable (~2 s, misma muesca, Δv mínimo) antes de EMA decel."""

    _samples: list[_DecelTick] = field(default_factory=list)
    last_reason: str = "accumulating"

    def feed(
        self,
        *,
        t: float,
        handle: int,
        speed_mph: float,
        grad_pct: float,
        accel_ms2: float,
    ) -> tuple[int, float, float, float] | None:
        """
        Añade un tick y devuelve ``(handle, measured_norm, avg_speed, avg_grad)``
        cuando la ventana es válida; si no, ``None``.
        """
        cutoff = t - (MIN_STABLE_S + 1.5)
        self._samples = [s for s in self._samples if s.t >= cutoff]

        if float(speed_mph) < MIN_OBSERVE_SPEED_MPH:
            self.last_reason = "speed_low"
            return None
        if abs(float(grad_pct)) > MAX_OBSERVE_GRAD_PCT:
            self.last_reason = "gradient"
            return None
        if float(accel_ms2) >= -0.05:
            self.last_reason = "not_braking"
            return None

        self._samples.append(
            _DecelTick(
                t=float(t),
                speed_mph=float(speed_mph),
                handle=int(handle),
                grad_pct=float(grad_pct),
                accel_ms2=float(accel_ms2),
            )
        )

        if len(self._samples) < MIN_WINDOW_SAMPLES:
            self.last_reason = f"accumulating ({len(self._samples)}/{MIN_WINDOW_SAMPLES})"
            return None

        handles = [s.handle for s in self._samples]
        if len(set(handles)) != 1 or handles[-1] != int(handle):
            self.last_reason = "notch_unstable"
            self._samples.clear()
            return None

        t0 = self._samples[0].t
        t1 = self._samples[-1].t
        if t1 - t0 < MIN_STABLE_S:
            self.last_reason = f"stable {t1 - t0:.1f}/{MIN_STABLE_S:.0f}s"
            return None

        if max(abs(s.grad_pct) for s in self._samples) > MAX_OBSERVE_GRAD_PCT:
            self.last_reason = "gradient"
            return None
        if min(s.speed_mph for s in self._samples) < MIN_OBSERVE_SPEED_MPH:
            self.last_reason = "speed_low"
            return None

        speeds = [s.speed_mph for s in self._samples]
        dv = speeds[-1] - speeds[0]
        if abs(dv) < MIN_DV_MPH:
            self.last_reason = f"no_dv (Δ{abs(dv):.2f}<{MIN_DV_MPH} mph)"
            return None

        accels = [s.accel_ms2 for s in self._samples]
        measured = sum(accels) / len(accels)
        avg_grad = sum(s.grad_pct for s in self._samples) / len(self._samples)
        measured_norm = measured - gravity_compensation(avg_grad)
        if measured_norm > 0.0:
            self.last_reason = "positive_brake"
            self._samples.clear()
            return None

        handle_i = handles[0]
        avg_speed = sum(speeds) / len(speeds)
        self._samples.clear()
        self.last_reason = "accepted"
        return handle_i, measured_norm, avg_speed, avg_grad

    def clear(self) -> None:
        self._samples.clear()
        self.last_reason = "accumulating"


def decel_outlier_rejected(
    measured_norm: float,
    prior_ema: float | None,
) -> bool:
    """True si la muestra se aleja demasiado de la EMA vigente."""
    if prior_ema is None:
        return False
    dev = abs(measured_norm - prior_ema)
    limit = max(MIN_OUTLIER_ABS_MS2, abs(prior_ema) * OUTLIER_RATIO)
    return dev > limit


def fill_outlier_rejected(elapsed_s: float, prior_fill_s: float) -> bool:
    if prior_fill_s <= 0.0:
        return False
    dev = abs(elapsed_s - prior_fill_s)
    return dev > max(FILL_OUTLIER_MIN_S, prior_fill_s * FILL_OUTLIER_RATIO)
