#!/usr/bin/env python3
"""
freight_learner.py — Aprendizaje multi-eje para diesel NA (Fase 2).

Cuatro ejes independientes: throttle, train_brake, ind_brake, dyn_brake.
Perfil JSON schema_version 2 (layout freight_na).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Optional

from online_learner import (
    EMA_ALPHA,
    GRAD_FLAT_THRESHOLD,
    MAX_GRAD_PCT,
    MIN_DV_MPH,
    MIN_SAMPLES,
    MIN_SPEED_FREIGHT,
    MIN_STABLE_S,
    OnlineLearner,
    _CLAMP,
    _GRAD_BANDS,
    _SPEED_BANDS,
    _grad_band_index,
    _gravity_compensation,
    _speed_band_index,
    path_for_vehicle,
)

_log = logging.getLogger("tsw.learner.freight")

FREIGHT_AXES = ("throttle", "train_brake", "ind_brake", "dyn_brake")
_LEVEL_EPS = 0.02


def profile_layout_from_file(path: str) -> Optional[str]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("schema_version") == 2:
            return str(d.get("layout") or "freight_na")
        return "combined"
    except Exception:
        return None


def freight_quantize_level(axis: str, level: float) -> int:
    if axis == "throttle":
        return max(0, min(8, int(round(level))))
    if axis == "dyn_brake":
        return max(0, min(8, int(round(level * 8))))
    if axis == "train_brake":
        return max(0, min(10, int(round(max(0.0, level) * 10))))
    if axis == "ind_brake":
        return max(-10, min(10, int(round(level * 10))))
    return int(round(level))


def _empty_axis_stores() -> dict[str, dict]:
    return {
        axis: {
            "ema_bands": [{} for _ in _SPEED_BANDS],
            "n_bands":   [{} for _ in _SPEED_BANDS],
            "ema_grad_bands": [{} for _ in _GRAD_BANDS],
            "n_grad_bands":   [{} for _ in _GRAD_BANDS],
            "ema": {},
            "n":   {},
        }
        for axis in FREIGHT_AXES
    }


def _merge_level_dicts(dst_ema: dict, dst_n: dict,
                       src_ema: dict, src_n: dict) -> None:
    for level, s_cnt in src_n.items():
        s_val = src_ema.get(level)
        if s_val is None or s_cnt <= 0:
            continue
        d_cnt = dst_n.get(level, 0)
        d_val = dst_ema.get(level)
        if d_val is not None and d_cnt > 0:
            dst_ema[level] = (d_val * d_cnt + s_val * s_cnt) / (d_cnt + s_cnt)
            dst_n[level] = d_cnt + s_cnt
        else:
            dst_ema[level] = s_val
            dst_n[level] = s_cnt


def _parse_axis_stores(data: dict) -> dict[str, dict]:
    stores = _empty_axis_stores()
    for axis in FREIGHT_AXES:
        block = data.get(axis)
        if not isinstance(block, dict):
            continue
        st = stores[axis]
        for i, band_data in enumerate(block.get("ema_bands", [])):
            if i < len(_SPEED_BANDS) and isinstance(band_data, dict):
                st["ema_bands"][i] = {int(k): float(v) for k, v in band_data.items()}
        for i, band_data in enumerate(block.get("n_bands", [])):
            if i < len(_SPEED_BANDS) and isinstance(band_data, dict):
                st["n_bands"][i] = {int(k): int(v) for k, v in band_data.items()}
        for i, band_data in enumerate(block.get("ema_grad_bands", [])):
            if i < len(_GRAD_BANDS) and isinstance(band_data, dict):
                st["ema_grad_bands"][i] = {int(k): float(v) for k, v in band_data.items()}
        for i, band_data in enumerate(block.get("n_grad_bands", [])):
            if i < len(_GRAD_BANDS) and isinstance(band_data, dict):
                st["n_grad_bands"][i] = {int(k): int(v) for k, v in band_data.items()}
        if isinstance(block.get("ema"), dict):
            st["ema"] = {int(k): float(v) for k, v in block["ema"].items()}
        if isinstance(block.get("n"), dict):
            st["n"] = {int(k): int(v) for k, v in block["n"].items()}
    return stores


def infer_active_axis(prev: Optional[dict], curr: dict) -> tuple[Optional[str], Optional[float]]:
    """Detecta qué eje cambió entre dos snapshots de controles."""
    if not prev:
        return None, None
    candidates: list[tuple[str, float]] = []
    for axis, key in (
        ("throttle", "throttle"),
        ("train_brake", "train_brake"),
        ("ind_brake", "ind_brake"),
        ("dyn_brake", "dyn_brake"),
    ):
        p, c = prev.get(key), curr.get(key)
        if p is None or c is None:
            continue
        if abs(float(c) - float(p)) > _LEVEL_EPS:
            candidates.append((axis, float(c)))
    if len(candidates) == 1:
        return candidates[0]
    return None, None


class FreightLearner:
    """Learner multi-eje freight_na (Fase 2)."""

    DEFAULT_PATH = OnlineLearner.DEFAULT_PATH

    def __init__(self, save_path: str = DEFAULT_PATH,
                 vehicle: Optional[str] = None,
                 min_speed: Optional[float] = None):
        self.save_path = path_for_vehicle(vehicle) if vehicle else save_path
        self._vehicle = vehicle
        self._min_speed = min_speed if min_speed is not None else MIN_SPEED_FREIGHT
        self._stores = _empty_axis_stores()
        self._window: list[tuple] = []
        self.last_reason: str = "esperando datos"
        self.last_axis: Optional[str] = None
        self._load()

    def _recalculate_axis(self, axis: str) -> None:
        st = self._stores[axis]
        all_levels: set[int] = set()
        for band in st["ema_bands"]:
            all_levels.update(band.keys())
        for level in all_levels:
            total_n = 0
            weighted = 0.0
            for i in range(len(_SPEED_BANDS)):
                n = st["n_bands"][i].get(level, 0)
                if n > 0 and level in st["ema_bands"][i]:
                    total_n += n
                    weighted += st["ema_bands"][i][level] * n
            if total_n > 0:
                st["ema"][level] = weighted / total_n
                st["n"][level] = total_n

    def load_profile(self, vehicle: str) -> dict:
        new_path = path_for_vehicle(vehicle)
        if new_path != self.save_path:
            self.save_path = new_path
            self._vehicle = vehicle
            self._stores = _empty_axis_stores()
            self._window = []
            self._load()
        consts = self.get_constants()
        _log.info("FreightLearner perfil: %s", os.path.basename(self.save_path))
        return consts

    def adopt_profile(self, vehicle: str) -> None:
        new_path = path_for_vehicle(vehicle)
        if new_path == self.save_path:
            return
        mem = copy.deepcopy(self._stores)
        n_prev = sum(sum(b.values()) for ax in mem.values() for b in ax["n_bands"])
        self.save_path = new_path
        self._vehicle = vehicle
        self._stores = _empty_axis_stores()
        self._load()
        for axis in FREIGHT_AXES:
            dst, src = self._stores[axis], mem[axis]
            for i in range(len(_SPEED_BANDS)):
                _merge_level_dicts(dst["ema_bands"][i], dst["n_bands"][i],
                                   src["ema_bands"][i], src["n_bands"][i])
            for i in range(len(_GRAD_BANDS)):
                _merge_level_dicts(dst["ema_grad_bands"][i], dst["n_grad_bands"][i],
                                   src["ema_grad_bands"][i], src["n_grad_bands"][i])
            self._recalculate_axis(axis)
        self._save()
        _log.info("FreightLearner adoptado: %s (%d muestras)", os.path.basename(new_path), n_prev)

    def feed(self, axis: str, level: float, speed_mph: float,
             grad_pct: float, accel_ms2: Optional[float],
             controls: Optional[dict] = None) -> Optional[dict]:
        if axis not in FREIGHT_AXES:
            self.last_reason = f"eje desconocido: {axis}"
            return None

        now = time.time()
        snap = dict(controls or {})
        self._window.append((now, speed_mph, axis, level, grad_pct, accel_ms2, snap))
        cutoff = now - (MIN_STABLE_S + 1.5)
        self._window = [w for w in self._window if w[0] >= cutoff]

        if len(self._window) < 4:
            self.last_reason = f"acumulando ({len(self._window)}/4)"
            return None

        if len({w[2] for w in self._window}) != 1:
            self.last_reason = "eje inestable (un mando ~2s)"
            return None

        levels_q = [freight_quantize_level(axis, w[3]) for w in self._window]
        if len(set(levels_q)) != 1:
            self.last_reason = f"nivel inestable ({axis})"
            return None
        level_key = levels_q[0]

        if axis == "throttle" and level_key < 1:
            self.last_reason = "ralentí — no calibrar"
            return None
        if axis in ("train_brake", "ind_brake") and abs(level_key) < 2:
            self.last_reason = f"{axis}: nivel bajo"
            return None
        if axis == "dyn_brake" and level_key < 1:
            self.last_reason = "dyn brake off"
            return None

        for other in FREIGHT_AXES:
            if other == axis:
                continue
            vals = [w[6].get(other) for w in self._window if other in w[6]]
            if len(vals) < 2:
                continue
            if any(v is None for v in vals):
                continue
            if any(abs(float(vals[i]) - float(vals[0])) > _LEVEL_EPS
                   for i in range(1, len(vals))):
                self.last_reason = f"otro eje activo ({other})"
                return None

        t0, t1 = self._window[0][0], self._window[-1][0]
        if t1 - t0 < MIN_STABLE_S:
            self.last_reason = f"estable {t1 - t0:.1f}/{MIN_STABLE_S:.0f}s"
            return None
        if max(abs(w[4]) for w in self._window) > MAX_GRAD_PCT:
            self.last_reason = f"gradiente >{MAX_GRAD_PCT:.0f}%"
            return None

        speeds = [w[1] for w in self._window]
        if min(speeds) < self._min_speed:
            self.last_reason = f"v <{self._min_speed:.0f} mph"
            return None

        dv = speeds[-1] - speeds[0]
        if abs(dv) < MIN_DV_MPH:
            self.last_reason = f"sin Δv ({abs(dv):.2f} mph)"
            return None

        api_vals = [w[5] for w in self._window if w[5] is not None]
        measured = (sum(api_vals) / len(api_vals) if api_vals
                    else dv * 0.44704 / (t1 - t0))

        avg_grad = sum(w[4] for w in self._window) / len(self._window)
        grad_band = _grad_band_index(avg_grad)
        measured_norm = (measured - _gravity_compensation(avg_grad)
                         if abs(avg_grad) >= GRAD_FLAT_THRESHOLD else measured)

        if axis == "throttle" and measured_norm < 0:
            self.last_reason = "a<0 en tracción"
            self._window.clear()
            return None
        if axis != "throttle" and measured_norm > 0:
            self.last_reason = "a>0 en freno"
            self._window.clear()
            return None

        st = self._stores[axis]
        band_idx = _speed_band_index(sum(speeds) / len(speeds))
        be, bn = st["ema_bands"][band_idx], st["n_bands"][band_idx]
        if level_key not in be:
            be[level_key] = measured_norm
            bn[level_key] = 1
        else:
            be[level_key] = EMA_ALPHA * measured_norm + (1 - EMA_ALPHA) * be[level_key]
            bn[level_key] = min(bn[level_key] + 1, 9999)

        ge, gn = st["ema_grad_bands"][grad_band], st["n_grad_bands"][grad_band]
        if level_key not in ge:
            ge[level_key] = measured
            gn[level_key] = 1
        else:
            ge[level_key] = EMA_ALPHA * measured + (1 - EMA_ALPHA) * ge[level_key]
            gn[level_key] = min(gn[level_key] + 1, 9999)

        self._recalculate_axis(axis)
        self.last_axis = axis
        self.last_reason = (f"✓ {axis} n={level_key}  a={measured_norm:+.2f}  "
                            f"samples={st['n'].get(level_key, 0)}")
        self._window.clear()

        consts = self.get_constants()
        self._save()
        return consts if consts else None

    def _predict(self, axis: str, level_key: int, speed_mph: float,
                 grad_pct: float) -> Optional[float]:
        st = self._stores[axis]
        band = _speed_band_index(speed_mph)
        flat: Optional[float] = None
        if (st["n_bands"][band].get(level_key, 0) >= MIN_SAMPLES
                and level_key in st["ema_bands"][band]):
            flat = st["ema_bands"][band][level_key]
        elif st["n"].get(level_key, 0) >= MIN_SAMPLES:
            flat = st["ema"].get(level_key)
        if flat is None:
            return None
        return flat + _gravity_compensation(grad_pct)

    def predict_accel(self, axis: str, level: float, speed_mph: float,
                      grad_pct: float) -> Optional[float]:
        if axis != "throttle":
            return None
        return self._predict("throttle", freight_quantize_level("throttle", level),
                             speed_mph, grad_pct)

    def predict_decel(self, axis: str, level: float, speed_mph: float,
                      grad_pct: float) -> Optional[float]:
        if axis not in ("train_brake", "ind_brake", "dyn_brake"):
            return None
        return self._predict(axis, freight_quantize_level(axis, level),
                             speed_mph, grad_pct)

    def get_constants(self) -> dict:
        result: dict = {}

        def _avg(axis: str, levels: tuple[int, ...], min_val: float) -> Optional[float]:
            st = self._stores[axis]
            vals = [abs(st["ema"][lv]) for lv in levels
                    if st["n"].get(lv, 0) >= MIN_SAMPLES and lv in st["ema"]]
            if not vals:
                return None
            v = sum(vals) / len(vals)
            return v if v >= min_val else None

        v = _avg("throttle", (6, 7, 8), 0.05)
        if v is not None:
            lo, hi = _CLAMP["TARGET_ACCEL_MS2"]
            result["TARGET_ACCEL_MS2"] = max(lo, min(hi, v))
        v = _avg("train_brake", tuple(range(4, 11)), 0.15)
        if v is not None:
            lo, hi = _CLAMP["TARGET_DECEL_MS2"]
            result["TARGET_DECEL_MS2"] = max(lo, min(hi, v))
        v = _avg("train_brake", (10,), 0.3)
        if v is not None:
            lo, hi = _CLAMP["MAX_DECEL_MS2"]
            result["MAX_DECEL_MS2"] = max(lo, min(hi, v))
        return result

    def confidence(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for axis in FREIGHT_AXES:
            for lv, n in self._stores[axis]["n"].items():
                out[f"{axis}:{lv}"] = n
        return out

    def sample_count(self, axis: str) -> int:
        return int(sum(self._stores[axis]["n"].values()))

    def band_count(self, axis: str, band: int, level: int) -> int:
        """Muestras en una celda (eje × banda velocidad × nivel)."""
        if axis not in FREIGHT_AXES or band < 0 or band >= len(_SPEED_BANDS):
            return 0
        return int(self._stores[axis]["n_bands"][band].get(level, 0))

    def save(self) -> None:
        self._save()

    def _load(self) -> None:
        try:
            if not os.path.exists(self.save_path):
                return
            with open(self.save_path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("schema_version") != 2:
                return
            self._stores = _parse_axis_stores(d)
            if d.get("vehicle"):
                self._vehicle = str(d["vehicle"])
        except Exception as exc:
            _log.warning("FreightLearner load: %s", exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.save_path)), exist_ok=True)
            payload: dict = {
                "schema_version": 2,
                "layout": "freight_na",
                "vehicle": self._vehicle or "",
            }
            for axis in FREIGHT_AXES:
                st = self._stores[axis]
                payload[axis] = {
                    "ema_bands": [{str(k): v for k, v in b.items()} for b in st["ema_bands"]],
                    "n_bands":   [{str(k): v for k, v in b.items()} for b in st["n_bands"]],
                    "ema_grad_bands": [{str(k): v for k, v in b.items()}
                                       for b in st["ema_grad_bands"]],
                    "n_grad_bands":   [{str(k): v for k, v in b.items()}
                                       for b in st["n_grad_bands"]],
                    "ema": {str(k): v for k, v in st["ema"].items()},
                    "n":   {str(k): v for k, v in st["n"].items()},
                }
            with open(self.save_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            _log.warning("FreightLearner save: %s", exc)


def create_learner(vehicle: Optional[str] = None,
                   layout: Optional[str] = None,
                   min_speed: Optional[float] = None,
                   save_path: Optional[str] = None):
    path = save_path or (path_for_vehicle(vehicle) if vehicle else OnlineLearner.DEFAULT_PATH)
    if layout is None:
        layout = profile_layout_from_file(path)
    if layout is None and vehicle:
        try:
            from control_layout import detect_control_layout
            layout = detect_control_layout(vehicle)
        except Exception:
            layout = "combined"
    if layout == "freight_na":
        return FreightLearner(save_path=path, vehicle=vehicle, min_speed=min_speed)
    return OnlineLearner(save_path=path, vehicle=vehicle, min_speed=min_speed)
