#!/usr/bin/env python3
"""
online_learner.py — Aprendizaje en línea de constantes físicas del tren.

Observa los períodos de notch estable en tramo plano mientras el autopilot
conduce y actualiza las constantes de frenado/tracción/inercia mediante
media móvil exponencial (EMA), persistiendo el resultado en JSON.

Solo acepta mediciones con |gradiente| < MAX_GRAD_PCT para garantizar
datos de referencia sin corrección (evita errores de compensación).

Notches observados (handle combinado 0-8):
  0 → MAX_DECEL_MS2    (Freno-4 máximo)
  1 → TARGET_DECEL_MS2 (Freno-3)
  2 → TARGET_DECEL_MS2 (Freno-2)
  3 → TARGET_DECEL_MS2 (Freno-1)
  4 → COAST_DECEL_MS2  (Neutro)
  7 → TARGET_ACCEL_MS2 (Tracción-3)
  8 → TARGET_ACCEL_MS2 (Tracción-4 máxima)
"""

import json
import logging
import os
import time
from typing import Optional

_log = logging.getLogger("tsw.learner")

# ── Parámetros de aprendizaje ─────────────────────────────────────────────────

EMA_ALPHA    = 0.10   # tasa EMA (~20 muestras para converger al 90 %)
MIN_SAMPLES  = 3      # mínimo de muestras antes de confiar en un valor
MIN_STABLE_S = 2.0    # segundos de notch estable requeridos
MIN_DV_MPH   = 0.6    # cambio mínimo de velocidad en la ventana
MAX_GRAD_PCT = 1.0    # |gradiente| máximo (%) para considerar "plano"
MIN_SPEED    = 5.0    # mph mínimo (descarta mediciones cerca de parado)

# Notches que se observan y a qué constante alimentan
_BRAKE_NOTCHES    = (1, 2, 3)   # promedio → TARGET_DECEL_MS2
_MAX_NOTCH        = 0           # → MAX_DECEL_MS2
_COAST_NOTCH      = 4           # → COAST_DECEL_MS2
_TRACTION_NOTCHES = (7, 8)      # promedio → TARGET_ACCEL_MS2

_OBSERVED = {_MAX_NOTCH, *_BRAKE_NOTCHES, _COAST_NOTCH, *_TRACTION_NOTCHES}


class OnlineLearner:
    """
    Aprende por EMA los valores de aceleración para cada notch del handle.
    Guarda y carga el estado en save_path (JSON).
    """

    DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "calibration.json")

    def __init__(self, save_path: str = DEFAULT_PATH):
        self.save_path = save_path
        self._ema: dict[int, float] = {}   # notch → valor EMA acumulado
        self._n:   dict[int, int]   = {}   # notch → número de muestras

        # Ventana deslizante: (t, speed_mph, notch, grad_pct, accel_ms2|None)
        self._window: list[tuple[float, float, int, float, Optional[float]]] = []

        self._load()

    # ── Alimentar muestras ───────────────────────────────────────────────────

    def feed(self, speed_mph: float, notch: int,
             grad_pct: float, accel_ms2: Optional[float]) -> Optional[dict]:
        """
        Recibe una muestra de telemetría.
        Devuelve las constantes actualizadas si hubo un nuevo aprendizaje,
        o None si aún no hay cambio que aplicar.
        """
        now = time.time()
        self._window.append((now, speed_mph, notch, grad_pct, accel_ms2))

        # Purgar entradas antiguas
        cutoff = now - (MIN_STABLE_S + 1.5)
        self._window = [(t, v, n, g, a) for t, v, n, g, a in self._window
                        if t >= cutoff]

        if len(self._window) < 4:
            return None

        # ── Filtros ──────────────────────────────────────────────────────────

        # 1. Notch estable en toda la ventana
        notches_in_window = [n for _, _, n, _, _ in self._window]
        if len(set(notches_in_window)) != 1:
            return None

        # 2. Solo notches de interés
        if notch not in _OBSERVED:
            return None

        # 3. Duración mínima
        t0 = self._window[0][0]
        t1 = self._window[-1][0]
        if t1 - t0 < MIN_STABLE_S:
            return None

        # 4. Gradiente plano
        if max(abs(g) for _, _, _, g, _ in self._window) > MAX_GRAD_PCT:
            return None

        # 5. Velocidad mínima
        if min(v for _, v, _, _, _ in self._window) < MIN_SPEED:
            return None

        # 6. Cambio de velocidad apreciable (confirma que el notch tiene efecto)
        speeds = [v for _, v, _, _, _ in self._window]
        dv = speeds[-1] - speeds[0]
        if abs(dv) < MIN_DV_MPH:
            return None

        # ── Medir aceleración ─────────────────────────────────────────────────
        api_vals = [a for _, _, _, _, a in self._window if a is not None]
        if api_vals:
            measured = sum(api_vals) / len(api_vals)
        else:
            measured = dv * 0.44704 / (t1 - t0)   # mph/s → m/s²

        # ── Actualizar EMA ────────────────────────────────────────────────────
        if notch not in self._ema:
            self._ema[notch] = measured
            self._n[notch]   = 1
        else:
            self._ema[notch] = EMA_ALPHA * measured + (1 - EMA_ALPHA) * self._ema[notch]
            self._n[notch]   = min(self._n[notch] + 1, 9999)

        _log.info(
            "Learner notch=%d  a_medida=%.3f  a_ema=%.3f  n=%d",
            notch, measured, self._ema[notch], self._n[notch],
        )

        # Vaciar ventana para evitar solapamiento de mediciones
        self._window.clear()

        # Guardar y devolver constantes si hay suficiente confianza
        consts = self.get_constants()
        if consts:
            self._save()
            return consts
        return None

    # ── Constantes físicas derivadas ─────────────────────────────────────────

    def get_constants(self) -> dict:
        """
        Devuelve las constantes físicas derivadas de las EMAs confiables.
        Solo incluye valores con n >= MIN_SAMPLES.
        """
        result: dict = {}

        def _trusted_abs(notch: int) -> Optional[float]:
            if self._n.get(notch, 0) >= MIN_SAMPLES and notch in self._ema:
                return abs(self._ema[notch])
            return None

        def _trusted_avg(notches: tuple) -> Optional[float]:
            vals = [v for n in notches if (v := _trusted_abs(n)) is not None]
            return sum(vals) / len(vals) if vals else None

        v = _trusted_abs(_MAX_NOTCH)
        if v is not None and v > 0.3: # Límite inferior de seguridad
            result["MAX_DECEL_MS2"] = v

        v = _trusted_avg(_BRAKE_NOTCHES)
        if v is not None and v > 0.15: # Límite inferior de seguridad (evita el 0.017)
            result["TARGET_DECEL_MS2"] = v

        v = _trusted_abs(_COAST_NOTCH)
        if v is not None:
            result["COAST_DECEL_MS2"] = v

        v = _trusted_avg(_TRACTION_NOTCHES)
        if v is not None and v > 0.05: # Límite inferior de seguridad
            result["TARGET_ACCEL_MS2"] = v

        return result

    def confidence(self) -> dict[str, int]:
        """Devuelve el número de muestras por notch relevante."""
        labels = {
            0: "MAX_DECEL(n0)",
            1: "DECEL(n1)", 2: "DECEL(n2)", 3: "DECEL(n3)",
            4: "COAST(n4)",
            7: "ACCEL(n7)", 8: "ACCEL(n8)",
        }
        return {labels[n]: self._n.get(n, 0) for n in _OBSERVED}

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if os.path.exists(self.save_path):
                with open(self.save_path, encoding="utf-8") as f:
                    d = json.load(f)
                self._ema = {int(k): float(v) for k, v in d.get("ema", {}).items()}
                self._n   = {int(k): int(v)   for k, v in d.get("n",   {}).items()}
                consts = self.get_constants()
                _log.info("OnlineLearner cargado: %s  constantes_confiables=%s",
                          self.save_path, list(consts.keys()))
        except Exception as _exc:
            _log.warning("OnlineLearner: no se pudo cargar calibración (%s) — empezando desde cero", _exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.save_path)),
                        exist_ok=True)
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "ema": {str(k): v for k, v in self._ema.items()},
                        "n":   {str(k): v for k, v in self._n.items()},
                    },
                    f, indent=2,
                )
        except Exception as _exc:
            _log.warning("OnlineLearner: no se pudo guardar calibración (%s)", _exc)
