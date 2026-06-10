#!/usr/bin/env python3
"""
online_learner.py — Aprendizaje en línea de constantes físicas del tren.

Observa los períodos de notch estable mientras el autopilot conduce y
actualiza las constantes de frenado/tracción/inercia mediante media móvil
exponencial (EMA), persistiendo el resultado en JSON.

Notches observados (handle combinado 0-8):
  0 → MAX_DECEL_MS2    (Freno-4 máximo)
  1 → TARGET_DECEL_MS2 (Freno-3)
  2 → TARGET_DECEL_MS2 (Freno-2)
  3 → TARGET_DECEL_MS2 (Freno-1)
  4 → COAST_DECEL_MS2  (Neutro)
  7 → TARGET_ACCEL_MS2 (Tracción-3)
  8 → TARGET_ACCEL_MS2 (Tracción-4 máxima)

Mejoras v2:
  - Filtro de coherencia de signo (tracción no acepta a<0, freno no acepta a>0)
  - Límites duros (clamp) en constantes aprendidas
  - Decay/reset si diverge >50% del valor inicial
  - Separación por banda de velocidad (0-30, 30-60, 60+ mph)

Mejoras v3:
  - Separación por banda de gradiente (plano/subida/bajada)
  - Compensación gravitacional en mediciones fuera del plano
  - Permite aprender en pendientes (antes solo en plano)
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
MAX_GRAD_PCT = 3.0    # |gradiente| máximo (%) para aceptar mediciones (ampliado v3)
MIN_SPEED    = 5.0    # mph mínimo (descarta mediciones cerca de parado)

# Umbral de gradiente para separar bandas (v3)
GRAD_FLAT_THRESHOLD = 0.5  # |grad| < 0.5% = plano

# Notches que se observan y a qué constante alimentan
_BRAKE_NOTCHES    = (1, 2, 3)   # promedio → TARGET_DECEL_MS2
_MAX_NOTCH        = 0           # → MAX_DECEL_MS2
_COAST_NOTCH      = 4           # → COAST_DECEL_MS2
_TRACTION_NOTCHES = (7, 8)      # promedio → TARGET_ACCEL_MS2

_OBSERVED = {_MAX_NOTCH, *_BRAKE_NOTCHES, _COAST_NOTCH, *_TRACTION_NOTCHES}

# ── Límites duros (clamp) para constantes aprendidas ──────────────────────────
_CLAMP = {
    "TARGET_ACCEL_MS2": (0.15, 0.80),
    "TARGET_DECEL_MS2": (0.30, 1.20),
    "COAST_DECEL_MS2":  (0.02, 0.25),
    "MAX_DECEL_MS2":    (0.50, 1.50),
}

# ── Divergencia máxima antes de resetear EMA ──────────────────────────────────
_MAX_DIVERGENCE_RATIO = 0.50  # 50% del valor inicial → reset

# ── Bandas de velocidad para separar aprendizaje ──────────────────────────────
_SPEED_BANDS = ((0, 30), (30, 60), (60, 200))  # mph rangos

# ── Bandas de gradiente (v3) ──────────────────────────────────────────────────
# Convención idéntica al resto del código: positivo = subida, negativo = bajada.
# 0=plano (|grad|<0.5%), 1=subida (grad>+0.5%), 2=bajada (grad<-0.5%)
_GRAD_BANDS = ("flat", "uphill", "downhill")
_NUM_GRAD_BANDS = len(_GRAD_BANDS)

# Valores iniciales de referencia para detección de divergencia
_INITIAL_REFS = {
    "TARGET_ACCEL_MS2": 0.298,
    "TARGET_DECEL_MS2": 0.433,
    "COAST_DECEL_MS2":  0.095,
    "MAX_DECEL_MS2":    1.071,
}


def _speed_band_index(speed_mph: float) -> int:
    """Devuelve el índice de banda de velocidad (0, 1, 2)."""
    for i, (lo, hi) in enumerate(_SPEED_BANDS):
        if lo <= speed_mph < hi:
            return i
    return len(_SPEED_BANDS) - 1


def _grad_band_index(grad_pct: float) -> int:
    """Devuelve el índice de banda de gradiente: 0=plano, 1=subida, 2=bajada.
    Convención (igual que governor_physics): positivo = subida, negativo = bajada."""
    if abs(grad_pct) < GRAD_FLAT_THRESHOLD:
        return 0  # plano
    elif grad_pct > GRAD_FLAT_THRESHOLD:
        return 1  # subida (grad positivo = pendiente ascendente)
    else:
        return 2  # bajada (grad negativo = pendiente descendente)


def _gravity_compensation(grad_pct: float) -> float:
    """Componente gravitacional a restar de la medición para normalizar a plano.
    Convención: positivo = subida (gravedad frena → comp negativa),
                negativo = bajada (gravedad ayuda → comp positiva).
    Se usa como: measured_normalized = measured - _gravity_compensation(grad)
    lo que equivale a: measured + |g_comp_bajada| o measured - |g_comp_subida|."""
    return -9.81 * (grad_pct / 100.0)


class OnlineLearner:
    """
    Aprende por EMA los valores de aceleración para cada notch del handle.
    Guarda y carga el estado en save_path (JSON).
    Separado por bandas de velocidad para mayor precisión.
    """

    DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "calibration.json")

    def __init__(self, save_path: str = DEFAULT_PATH):
        self.save_path = save_path
        # Almacenamiento por banda de velocidad: band_idx → {notch → ema_value}
        self._ema_bands: list[dict[int, float]] = [{} for _ in _SPEED_BANDS]
        self._n_bands:   list[dict[int, int]]   = [{} for _ in _SPEED_BANDS]

        # Almacenamiento por banda de gradiente (v3): grad_band_idx → {notch → ema}
        self._ema_grad_bands: list[dict[int, float]] = [{} for _ in _GRAD_BANDS]
        self._n_grad_bands:   list[dict[int, int]]   = [{} for _ in _GRAD_BANDS]

        # Compatibilidad: EMA combinada (media ponderada de bandas)
        self._ema: dict[int, float] = {}   # notch → valor EMA combinado
        self._n:   dict[int, int]   = {}   # notch → número total de muestras

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

        # 4. Gradiente máximo absoluto (filtro de seguridad ampliado v3)
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

        # ── v3: Compensar componente gravitacional para normalizar a plano ────
        avg_grad = sum(g for _, _, _, g, _ in self._window) / len(self._window)
        grad_band = _grad_band_index(avg_grad)
        if abs(avg_grad) >= GRAD_FLAT_THRESHOLD:
            # Restar la componente gravitacional para obtener la fuerza del tren
            g_comp = _gravity_compensation(avg_grad)
            measured_normalized = measured - g_comp
        else:
            measured_normalized = measured

        # ── Filtro de coherencia de signo ─────────────────────────────────────
        # Tracción (notch >= 5): solo aceptar aceleración positiva (normalizada)
        if notch in _TRACTION_NOTCHES and measured_normalized < 0:
            _log.debug(
                "Learner DESCARTADO notch=%d  a_medida=%.3f  a_norm=%.3f (negativa en tracción)",
                notch, measured, measured_normalized)
            self._window.clear()
            return None
        # Freno (notch <= 3): solo aceptar aceleración negativa (normalizada)
        if notch in (_MAX_NOTCH, *_BRAKE_NOTCHES) and measured_normalized > 0:
            _log.debug(
                "Learner DESCARTADO notch=%d  a_medida=%.3f  a_norm=%.3f (positiva en freno)",
                notch, measured, measured_normalized)
            self._window.clear()
            return None

        # ── Determinar banda de velocidad ─────────────────────────────────────
        avg_speed = sum(speeds) / len(speeds)
        band_idx = _speed_band_index(avg_speed)

        # ── Actualizar EMA por banda de velocidad (usa valor normalizado) ─────
        band_ema = self._ema_bands[band_idx]
        band_n   = self._n_bands[band_idx]

        if notch not in band_ema:
            band_ema[notch] = measured_normalized
            band_n[notch]   = 1
        else:
            band_ema[notch] = EMA_ALPHA * measured_normalized + (1 - EMA_ALPHA) * band_ema[notch]
            band_n[notch]   = min(band_n[notch] + 1, 9999)

        # ── v3: Actualizar EMA por banda de gradiente (valor bruto sin normalizar) ─
        grad_ema = self._ema_grad_bands[grad_band]
        grad_n   = self._n_grad_bands[grad_band]

        if notch not in grad_ema:
            grad_ema[notch] = measured
            grad_n[notch]   = 1
        else:
            grad_ema[notch] = EMA_ALPHA * measured + (1 - EMA_ALPHA) * grad_ema[notch]
            grad_n[notch]   = min(grad_n[notch] + 1, 9999)

        # ── Recalcular EMA combinada (media ponderada por nº muestras) ────────
        self._recalculate_combined()

        _log.info(
            "Learner notch=%d  a_medida=%.3f  a_norm=%.3f  a_ema=%.3f  n=%d  "
            "band=%d-%dmph  grad_band=%s",
            notch, measured, measured_normalized,
            self._ema.get(notch, 0.0), self._n.get(notch, 0),
            _SPEED_BANDS[band_idx][0], _SPEED_BANDS[band_idx][1],
            _GRAD_BANDS[grad_band],
        )

        # Vaciar ventana para evitar solapamiento de mediciones
        self._window.clear()

        # ── Decay/reset si diverge demasiado del valor inicial ────────────────
        self._check_divergence()

        # Guardar y devolver constantes si hay suficiente confianza
        consts = self.get_constants()
        if consts:
            self._save()
            return consts
        return None

    def _recalculate_combined(self) -> None:
        """Recalcula _ema y _n combinando todas las bandas de velocidad."""
        all_notches = set()
        for band_ema in self._ema_bands:
            all_notches.update(band_ema.keys())

        for notch in all_notches:
            total_n = 0
            weighted_sum = 0.0
            for i in range(len(_SPEED_BANDS)):
                n = self._n_bands[i].get(notch, 0)
                if n > 0 and notch in self._ema_bands[i]:
                    total_n += n
                    weighted_sum += self._ema_bands[i][notch] * n
            if total_n > 0:
                self._ema[notch] = weighted_sum / total_n
                self._n[notch]   = total_n

    def _check_divergence(self) -> None:
        """Resetea EMA de un notch si diverge >50% de su valor inicial."""
        for const_name, ref_val in _INITIAL_REFS.items():
            if const_name == "TARGET_ACCEL_MS2":
                notches = _TRACTION_NOTCHES
            elif const_name == "TARGET_DECEL_MS2":
                notches = _BRAKE_NOTCHES
            elif const_name == "COAST_DECEL_MS2":
                notches = (_COAST_NOTCH,)
            elif const_name == "MAX_DECEL_MS2":
                notches = (_MAX_NOTCH,)
            else:
                continue

            for notch in notches:
                if notch in self._ema and self._n.get(notch, 0) >= MIN_SAMPLES:
                    current = abs(self._ema[notch])
                    if abs(current - ref_val) / ref_val > _MAX_DIVERGENCE_RATIO:
                        _log.warning(
                            "Learner RESET notch=%d  ema=%.3f diverge >50%% de ref=%.3f "
                            "— reseteando todas las bandas",
                            notch, self._ema[notch], ref_val)
                        for band_ema in self._ema_bands:
                            band_ema.pop(notch, None)
                        for band_n in self._n_bands:
                            band_n.pop(notch, None)
                        self._ema.pop(notch, None)
                        self._n.pop(notch, None)

    # ── Constantes físicas derivadas ─────────────────────────────────────────

    def get_constants(self) -> dict:
        """
        Devuelve las constantes físicas derivadas de las EMAs confiables.
        Solo incluye valores con n >= MIN_SAMPLES.
        Aplica clamp (límites duros) a los valores antes de devolverlos.
        """
        result: dict = {}

        def _trusted_abs(notch: int) -> Optional[float]:
            if self._n.get(notch, 0) >= MIN_SAMPLES and notch in self._ema:
                return abs(self._ema[notch])
            return None

        def _trusted_avg(notches: tuple) -> Optional[float]:
            vals = [v for n in notches if (v := _trusted_abs(n)) is not None]
            return sum(vals) / len(vals) if vals else None

        def _clamp(value: float, const_name: str) -> float:
            """Aplica límites duros a una constante aprendida."""
            lo, hi = _CLAMP.get(const_name, (0.0, 999.0))
            return max(lo, min(hi, value))

        v = _trusted_abs(_MAX_NOTCH)
        if v is not None and v > 0.3:
            result["MAX_DECEL_MS2"] = _clamp(v, "MAX_DECEL_MS2")

        v = _trusted_avg(_BRAKE_NOTCHES)
        if v is not None and v > 0.15:
            result["TARGET_DECEL_MS2"] = _clamp(v, "TARGET_DECEL_MS2")

        v = _trusted_abs(_COAST_NOTCH)
        if v is not None:
            result["COAST_DECEL_MS2"] = _clamp(v, "COAST_DECEL_MS2")

        v = _trusted_avg(_TRACTION_NOTCHES)
        if v is not None and v > 0.05:
            result["TARGET_ACCEL_MS2"] = _clamp(v, "TARGET_ACCEL_MS2")

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

    def confidence_by_band(self) -> dict[str, dict[str, int]]:
        """Devuelve el número de muestras por notch y banda de velocidad."""
        labels = {
            0: "MAX_DECEL(n0)",
            1: "DECEL(n1)", 2: "DECEL(n2)", 3: "DECEL(n3)",
            4: "COAST(n4)",
            7: "ACCEL(n7)", 8: "ACCEL(n8)",
        }
        result = {}
        for i, (lo, hi) in enumerate(_SPEED_BANDS):
            band_label = f"{lo}-{hi}mph"
            result[band_label] = {labels[n]: self._n_bands[i].get(n, 0)
                                  for n in _OBSERVED}
        return result

    def confidence_by_gradient(self) -> dict[str, dict[str, int]]:
        """Devuelve el número de muestras por notch y banda de gradiente (v3)."""
        labels = {
            0: "MAX_DECEL(n0)",
            1: "DECEL(n1)", 2: "DECEL(n2)", 3: "DECEL(n3)",
            4: "COAST(n4)",
            7: "ACCEL(n7)", 8: "ACCEL(n8)",
        }
        result = {}
        for i, band_name in enumerate(_GRAD_BANDS):
            result[band_name] = {labels[n]: self._n_grad_bands[i].get(n, 0)
                                 for n in _OBSERVED}
        return result

    def get_gradient_constants(self, grad_band: int) -> dict:
        """Devuelve constantes para una banda de gradiente específica (valor bruto).
        Útil para predecir comportamiento real en pendiente sin compensar."""
        result: dict = {}
        grad_ema = self._ema_grad_bands[grad_band]
        grad_n = self._n_grad_bands[grad_band]

        def _trusted_abs_g(notch: int) -> Optional[float]:
            if grad_n.get(notch, 0) >= MIN_SAMPLES and notch in grad_ema:
                return abs(grad_ema[notch])
            return None

        def _trusted_avg_g(notches: tuple) -> Optional[float]:
            vals = [v for n in notches if (v := _trusted_abs_g(n)) is not None]
            return sum(vals) / len(vals) if vals else None

        v = _trusted_abs_g(_MAX_NOTCH)
        if v is not None and v > 0.3:
            result["MAX_DECEL_MS2"] = v
        v = _trusted_avg_g(_BRAKE_NOTCHES)
        if v is not None and v > 0.15:
            result["TARGET_DECEL_MS2"] = v
        v = _trusted_abs_g(_COAST_NOTCH)
        if v is not None:
            result["COAST_DECEL_MS2"] = v
        v = _trusted_avg_g(_TRACTION_NOTCHES)
        if v is not None and v > 0.05:
            result["TARGET_ACCEL_MS2"] = v
        return result

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if os.path.exists(self.save_path):
                with open(self.save_path, encoding="utf-8") as f:
                    d = json.load(f)
                # Cargar formato nuevo (con bandas) o formato legacy
                if "ema_bands" in d:
                    for i, band_data in enumerate(d["ema_bands"]):
                        if i < len(self._ema_bands):
                            self._ema_bands[i] = {int(k): float(v)
                                                  for k, v in band_data.items()}
                    for i, band_data in enumerate(d.get("n_bands", [])):
                        if i < len(self._n_bands):
                            self._n_bands[i] = {int(k): int(v)
                                                for k, v in band_data.items()}
                else:
                    # Legacy: cargar en banda 1 (30-60 mph, la más común)
                    legacy_ema = {int(k): float(v) for k, v in d.get("ema", {}).items()}
                    legacy_n   = {int(k): int(v)   for k, v in d.get("n",   {}).items()}
                    self._ema_bands[1] = legacy_ema
                    self._n_bands[1]   = legacy_n

                # v3: cargar bandas de gradiente
                if "ema_grad_bands" in d:
                    for i, band_data in enumerate(d["ema_grad_bands"]):
                        if i < len(self._ema_grad_bands):
                            self._ema_grad_bands[i] = {int(k): float(v)
                                                      for k, v in band_data.items()}
                    for i, band_data in enumerate(d.get("n_grad_bands", [])):
                        if i < len(self._n_grad_bands):
                            self._n_grad_bands[i] = {int(k): int(v)
                                                    for k, v in band_data.items()}

                self._recalculate_combined()
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
                        "ema_bands": [{str(k): v for k, v in band.items()}
                                      for band in self._ema_bands],
                        "n_bands":   [{str(k): v for k, v in band.items()}
                                      for band in self._n_bands],
                        # v3: bandas de gradiente
                        "ema_grad_bands": [{str(k): v for k, v in band.items()}
                                           for band in self._ema_grad_bands],
                        "n_grad_bands":   [{str(k): v for k, v in band.items()}
                                           for band in self._n_grad_bands],
                        # Legacy compat: also write combined values
                        "ema": {str(k): v for k, v in self._ema.items()},
                        "n":   {str(k): v for k, v in self._n.items()},
                    },
                    f, indent=2,
                )
        except Exception as _exc:
            _log.warning("OnlineLearner: no se pudo guardar calibración (%s)", _exc)
