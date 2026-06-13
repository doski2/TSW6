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

from online_learner import OnlineLearner
from freight_learner import FreightLearner, create_learner, profile_layout_from_file
from governor_constants import (
    MAX_DECEL_MS2, SAFETY_MARGIN, COAST_DECEL_MS2, BRAKE_TRANSITION_S,
    TARGET_ACCEL_MS2, TARGET_DECEL_MS2, CRITICAL_DECEL_THRESHOLD,
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
        self.target_accel_ms2 = TARGET_ACCEL_MS2
        self.coast_decel_ms2  = COAST_DECEL_MS2

        # D: Transición throttle→brake medida dinámicamente
        self.brake_transition_s: float = BRAKE_TRANSITION_S  # valor inicial hardcodeado
        self._transition_start_t: Optional[float] = None
        self._transition_start_accel: Optional[float] = None
        self._transition_measurements: list[float] = []
        self._MAX_TRANSITION_SAMPLES = 10

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
        if "TARGET_ACCEL_MS2" in consts:
            self.target_accel_ms2 = consts["TARGET_ACCEL_MS2"]
        if "COAST_DECEL_MS2"  in consts:
            self.coast_decel_ms2  = consts["COAST_DECEL_MS2"]
        _log.info(
            "Constantes físicas: MAX_DECEL=%.3f  TARGET_DECEL=%.3f  "
            "TARGET_ACCEL=%.3f  COAST=%.3f",
            self.max_decel_ms2, self.target_decel_ms2,
            self.target_accel_ms2, self.coast_decel_ms2,
        )

    def feed_learner(self, speed_mph: float, current_notch: int,
                     grad_pct: float, accel_ms2: Optional[float]) -> None:
        """Alimenta el aprendiz online (layout combined)."""
        if isinstance(self.learner, FreightLearner):
            return
        updated = self.learner.feed(speed_mph, current_notch, grad_pct, accel_ms2)
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

    def predict_accel(self, notch: int, speed_mph: float,
                      grad_pct: float) -> Optional[float]:
        if isinstance(self.learner, FreightLearner):
            return self.learner.predict_accel("throttle", float(notch), speed_mph, grad_pct)
        return self.learner.predict_accel(notch, speed_mph, grad_pct)

    def _rebind_learner(self, vehicle: str) -> None:
        path = self.learner.save_path
        from online_learner import path_for_vehicle
        new_path = path_for_vehicle(vehicle)
        file_layout = profile_layout_from_file(new_path)
        try:
            from control_layout import detect_control_layout
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
        from online_learner import path_for_vehicle
        new_path = path_for_vehicle(vehicle)
        file_layout = profile_layout_from_file(new_path)
        try:
            from control_layout import detect_control_layout
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

    # ── D: Medición dinámica de BRAKE_TRANSITION_S ────────────────────────────

    def start_brake_transition(self) -> None:
        """Llamar cuando se inicia una transición de throttle a brake.
        Registra el timestamp para medir el tiempo real de transición."""
        self._transition_start_t = time.time()
        self._transition_start_accel = self.acceleration_ms2

    def end_brake_transition(self) -> None:
        """Llamar cuando se confirma que el freno está actuando (aceleración negativa).
        Calcula el tiempo real de transición y actualiza la constante."""
        if self._transition_start_t is None:
            return
        elapsed = time.time() - self._transition_start_t
        self._transition_start_t = None
        self._transition_start_accel = None

        # Solo aceptar mediciones razonables (0.1 a 3.0 segundos)
        if 0.1 <= elapsed <= 3.0:
            self._transition_measurements.append(elapsed)
            if len(self._transition_measurements) > self._MAX_TRANSITION_SAMPLES:
                self._transition_measurements.pop(0)
            # Actualizar constante como media de las mediciones
            avg_transition = sum(self._transition_measurements) / len(self._transition_measurements)
            if abs(avg_transition - self.brake_transition_s) > 0.05:
                _log.info(
                    "Brake transition actualizado: %.2fs → %.2fs (n=%d)",
                    self.brake_transition_s, avg_transition,
                    len(self._transition_measurements))
                self.brake_transition_s = avg_transition

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

    def braking_distance(self, from_mph: float, to_mph: float,
                         decel: Optional[float] = None,
                         margin: float = SAFETY_MARGIN,
                         gradient_pct: Optional[float] = None,
                         current_accel_ms2: Optional[float] = None) -> float:
        """
        Distancia de frenado en metros con margen de seguridad.
        Con gradient_pct se corrige la deceleración efectiva:
          - bajada (< 0): gravedad opone frenado → distancia mayor
          - subida (> 0): gravedad asiste frenado → distancia menor
        Si current_accel_ms2 > 0, modela la distancia extra recorrida durante
        la transición aceleración→neutro→freno (BRAKE_TRANSITION_S segundos).
        """
        if decel is None:
            decel = self.max_decel_ms2
        v1 = from_mph * 0.44704
        v2 = to_mph   * 0.44704
        if v1 <= v2:
            return 0.0
        if gradient_pct is not None:
            g_comp = 9.81 * gradient_pct / 100.0
            effective_decel = max(decel + g_comp, self.coast_decel_ms2)
        else:
            effective_decel = decel
        if current_accel_ms2 is not None and current_accel_ms2 > 0.0:
            t_trans = self.brake_transition_s  # D: usar valor medido dinámicamente
            v_peak = v1 + current_accel_ms2 * t_trans
            d_trans = v1 * t_trans + 0.5 * current_accel_ms2 * t_trans ** 2
            d_brake = (v_peak ** 2 - v2 ** 2) / (2 * effective_decel)
            return (d_trans + d_brake) * margin
        return ((v1 ** 2 - v2 ** 2) / (2 * effective_decel)) * margin

    def should_brake_for_next(self, speed_mph: float,
                               next_limit_mph: Optional[float],
                               distance_m: Optional[float],
                               gradient_pct: Optional[float] = None,
                               react_s: float = 0.0,
                               current_accel_ms2: Optional[float] = None) -> bool:
        """¿Hay que empezar a frenar ya para el próximo límite?
        react_s: segundos de margen de reacción (distancia extra = speed * react_s).
        """
        if next_limit_mph is None or distance_m is None:
            return False
        if next_limit_mph >= speed_mph:
            return False
        react_m = speed_mph * 0.44704 * react_s
        return distance_m <= self.braking_distance(speed_mph, next_limit_mph,
                                                    gradient_pct=gradient_pct,
                                                    current_accel_ms2=current_accel_ms2) + react_m
