#!/usr/bin/env python3
"""
governor_physics.py — Física del tren: acelerómetro, frenado, clima y aprendizaje.

Contiene TrainPhysics, una clase que agrupa:
  - Acelerómetro (dv/dt + API nativa)
  - Cálculo de distancia de frenado (con gradiente y transición aceleración→freno)
  - Ajuste por lluvia (adherencia reducida)
  - Aprendizaje online de constantes físicas
"""

import logging
import math
import time
from typing import Optional

from tsw6.braking.v2.physics import (
    BrakePhysicsContext,
    DEFAULT_BRAKE_FILL_S,
    braking_distance_mph,
    should_brake_for_target,
)
from tsw6.learning.online_learner import OnlineLearner
from tsw6.learning.freight_learner import FreightLearner, create_learner, profile_layout_from_file
from tsw6.governor.governor_constants import (
    MAX_DECEL_MS2, SAFETY_MARGIN, COAST_DECEL_MS2, BRAKE_TRANSITION_S,
    TARGET_DECEL_MS2, CRITICAL_DECEL_THRESHOLD,
)

_log = logging.getLogger("tsw.physics")


class TrainPhysics:
    """Física del tren: aceleración, frenado, clima y aprendizaje online."""

    def __init__(self):
        # Acelerómetro: historial dv/dt + valor nativo de la API
        self._speed_hist: list[tuple[float, float]] = []
        self._HIST_WINDOW = 5.0
        self._api_accel: Optional[float] = None

        # Constantes físicas (actualizables por OnlineLearner)
        self.max_decel_ms2    = MAX_DECEL_MS2
        self.target_decel_ms2 = TARGET_DECEL_MS2
        self.coast_decel_ms2  = COAST_DECEL_MS2

        self.brake_transition_s: float = BRAKE_TRANSITION_S
        self.brake_fill_s: float = DEFAULT_BRAKE_FILL_S

        # Clima: factor de reducción de adherencia 0.0 (seco) … 1.0 (tormenta)
        self._rain_intensity: float = 0.0
        self._WET_DECEL_REDUCTION = 0.35

        # Aprendiz online (combined o freight_na según tren)
        self._layout = "combined"
        self.learner = create_learner()
        self._apply_constants(self.learner.get_constants())

    # ── Aprendizaje online ───────────────────────────────────────────────────

    def _apply_constants(self, consts: dict) -> None:
        """Aplica constantes físicas aprendidas."""
        if not consts:
            return
        if "MAX_DECEL_MS2"    in consts:
            self.max_decel_ms2    = consts["MAX_DECEL_MS2"]
        if "TARGET_DECEL_MS2" in consts:
            self.target_decel_ms2 = consts["TARGET_DECEL_MS2"]
        if "COAST_DECEL_MS2"  in consts:
            self.coast_decel_ms2  = consts["COAST_DECEL_MS2"]
        if "BRAKE_FILL_S" in consts:
            self.brake_fill_s = float(consts["BRAKE_FILL_S"])
        _log.info(
            "Constantes físicas: MAX_DECEL=%.3f  TARGET_DECEL=%.3f  COAST=%.3f  FILL=%.2fs",
            self.max_decel_ms2, self.target_decel_ms2, self.coast_decel_ms2,
            self.brake_fill_s,
        )

    def feed_learner(self, speed_mph: float, current_notch: int,
                     grad_pct: float, accel_ms2: Optional[float],
                     brake_cyl_bar: Optional[float] = None) -> None:
        """Alimenta el aprendiz online (layout combined)."""
        if isinstance(self.learner, FreightLearner):
            return
        updated = self.learner.feed(
            speed_mph, current_notch, grad_pct, accel_ms2,
            brake_cyl_bar=brake_cyl_bar,
        )
        if updated:
            _log.info("OnlineLearner actualizó constantes: %s", updated)
            self._apply_constants(updated)

    def feed_learner_freight(self, axis: str, level: float,
                             speed_mph: float, grad_pct: float,
                             accel_ms2: Optional[float],
                             controls: dict) -> None:
        """Alimenta FreightLearner (layout freight_na)."""
        if not isinstance(self.learner, FreightLearner):
            return
        updated = self.learner.feed(axis, level, speed_mph, grad_pct, accel_ms2, controls)
        if updated:
            _log.info("FreightLearner actualizó: %s", updated)
            self._apply_constants(updated)

    def predict_brake_decel_ms2(self, handle_notch: int, speed_mph: float,
                                grad_pct: float = 0.0) -> Optional[float]:
        """Decel aprendida por muesca de freno (0–3), o None."""
        if isinstance(self.learner, FreightLearner):
            return None
        return self.learner.predict_brake_decel_ms2(handle_notch, speed_mph, grad_pct)

    def _rebind_learner(self, vehicle: str) -> None:
        path = self.learner.save_path
        from tsw6.learning.online_learner import path_for_vehicle
        new_path = path_for_vehicle(vehicle)
        file_layout = profile_layout_from_file(new_path)
        try:
            from tsw6.learning.control_layout import detect_control_layout
            layout = file_layout or detect_control_layout(vehicle)
        except Exception:
            layout = file_layout or "combined"
        if layout != self._layout or type(self.learner).__name__ != (
                "FreightLearner" if layout == "freight_na" else "OnlineLearner"):
            self.learner = create_learner(vehicle=vehicle, layout=layout,
                                          min_speed=getattr(self.learner, "_min_speed", None))
            self._layout = layout
        else:
            self.learner.load_profile(vehicle)

    def set_vehicle_profile(self, vehicle: str) -> None:
        """Carga el perfil de calibración del tren detectado y aplica sus
        constantes. Si el perfil no existe, parte de los valores por defecto."""
        self._rebind_learner(vehicle)
        self._apply_constants(self.learner.get_constants())

    def adopt_vehicle_profile(self, vehicle: str) -> None:
        """Adopta el perfil del tren detectado a mitad de sesión SIN perder
        las muestras ya aprendidas (las fusiona con el perfil en disco)."""
        from tsw6.learning.online_learner import path_for_vehicle
        new_path = path_for_vehicle(vehicle)
        file_layout = profile_layout_from_file(new_path)
        try:
            from tsw6.learning.control_layout import detect_control_layout
            layout = file_layout or detect_control_layout(vehicle)
        except Exception:
            layout = file_layout or "combined"
        want_freight = layout == "freight_na"
        is_freight = isinstance(self.learner, FreightLearner)
        if want_freight != is_freight:
            self.learner = create_learner(vehicle=vehicle, layout=layout,
                                          min_speed=getattr(self.learner, "_min_speed", None))
            self._layout = layout
        else:
            self.learner.adopt_profile(vehicle)
        self._apply_constants(self.learner.get_constants())

    # ── Clima / lluvia ───────────────────────────────────────────────────────

    def set_rain_intensity(self, intensity: float) -> None:
        """Actualiza la intensidad de lluvia (0.0=seco, 1.0=tormenta fuerte)."""
        intensity = max(0.0, min(1.0, float(intensity)))
        prev = self._rain_intensity
        if abs(intensity - prev) >= 0.15:
            self._rain_intensity = intensity
            eff = self.eff_max_decel
            if intensity > 0.0:
                _log.warning(
                    "⚠ LLUVIA (intensity=%.2f) — MAX_DECEL reducida: %.3f → %.3f m/s²",
                    intensity, self.max_decel_ms2, eff,
                )
            else:
                _log.info(
                    "Vía seca — MAX_DECEL restaurada a %.3f m/s²", self.max_decel_ms2,
                )

    @property
    def eff_max_decel(self) -> float:
        """max_decel_ms2 ajustado por lluvia (adherencia reducida en vía mojada)."""
        return self.max_decel_ms2 * (1.0 - self._rain_intensity * self._WET_DECEL_REDUCTION)

    @property
    def eff_k_stop(self) -> float:
        """k_stop recalculado con la desaceleración efectiva."""
        return math.sqrt(2.0 * self.eff_max_decel / SAFETY_MARGIN) / 0.44704

    # ── Acelerómetro ─────────────────────────────────────────────────────────

    def record_speed(self, speed_mph: float) -> None:
        """Registra una muestra de velocidad para el acelómetro (fallback dv/dt)."""
        now = time.time()
        self._speed_hist.append((now, speed_mph))
        cutoff = now - self._HIST_WINDOW
        self._speed_hist = [(t, v) for t, v in self._speed_hist if t >= cutoff]

    @property
    def acceleration_ms2(self) -> Optional[float]:
        """
        Aceleración en m/s².
        Prioridad: valor nativo de la API → regresión lineal sobre historial.
        """
        if self._api_accel is not None:
            return self._api_accel
        if len(self._speed_hist) < 2:
            return None
        ts = [t for t, _ in self._speed_hist]
        vs = [v for _, v in self._speed_hist]
        t_mean = sum(ts) / len(ts)
        v_mean = sum(vs) / len(vs)
        num = sum((t - t_mean) * (v - v_mean) for t, v in zip(ts, vs))
        den = sum((t - t_mean) ** 2 for t in ts)
        if den < 1e-9:
            return None
        return (num / den) * 0.44704   # mph/s → m/s²

    @property
    def g_force(self) -> Optional[float]:
        """Fuerza g (aceleración / 9.81)."""
        a = self.acceleration_ms2
        return a / 9.81 if a is not None else None

    # ── Física de frenado ────────────────────────────────────────────────────

    def effective_decel_for_gradient(self, gradient_pct: Optional[float] = None,
                                     decel: Optional[float] = None) -> float:
        """Calcula la deceleración efectiva considerando gradiente y lluvia.
        Devuelve el valor en m/s² (siempre >= coast_decel_ms2)."""
        if decel is None:
            decel = self.eff_max_decel
        if gradient_pct is not None:
            g_comp = 9.81 * gradient_pct / 100.0
            return max(decel + g_comp, self.coast_decel_ms2)
        return decel

    def is_critical_gradient(self, gradient_pct: Optional[float] = None) -> bool:
        """True si la deceleración efectiva en esta pendiente es críticamente baja.
        Indica que el freno de servicio es insuficiente y se necesita MAX_BRAKE."""
        eff = self.effective_decel_for_gradient(gradient_pct)
        return eff < CRITICAL_DECEL_THRESHOLD

    def _brake_ctx(
        self,
        gradient_pct: Optional[float] = None,
        current_accel_ms2: Optional[float] = None,
        decel: Optional[float] = None,
        margin: float = SAFETY_MARGIN,
    ) -> BrakePhysicsContext:
        return BrakePhysicsContext(
            base_decel_ms2=decel if decel is not None else self.eff_max_decel,
            safety_margin=margin,
            coast_decel_ms2=self.coast_decel_ms2,
            brake_transition_s=self.brake_transition_s,
            gradient_pct=gradient_pct or 0.0,
            current_accel_ms2=current_accel_ms2,
        )

    def braking_distance(self, from_mph: float, to_mph: float,
                         decel: Optional[float] = None,
                         margin: float = SAFETY_MARGIN,
                         gradient_pct: Optional[float] = None,
                         current_accel_ms2: Optional[float] = None) -> float:
        """
        Distancia de frenado en metros (delega en ``brake_physics``).
        """
        return braking_distance_mph(
            from_mph,
            to_mph,
            decel_ms2=decel,
            ctx=self._brake_ctx(gradient_pct, current_accel_ms2, decel, margin),
            apply_margin=True,
        )

    def should_brake_for_next(self, speed_mph: float,
                               next_limit_mph: Optional[float],
                               distance_m: Optional[float],
                               gradient_pct: Optional[float] = None,
                               react_s: float = 0.0,
                               current_accel_ms2: Optional[float] = None) -> bool:
        """¿Hay que empezar a frenar ya para el próximo límite?"""
        return should_brake_for_target(
            speed_mph,
            next_limit_mph,
            distance_m,
            ctx=self._brake_ctx(gradient_pct, current_accel_ms2),
            react_s=react_s,
        )
