#!/usr/bin/env python3
"""
control_schema.py — Esquemas Fase 0 por tren (muescas observadas en diagnóstico).

Generados por control_diag.py en logs/control_schemas/<tren>.json.
Usados por detect_control_layout() y learn_monitor para saber qué muescas calibrar.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Optional

from freight_learner import freight_quantize_level
from online_learner import sanitize_vehicle_name
from train_labels import FREIGHT_AXIS_ROWS

SCHEMAS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "logs", "control_schemas",
)
_FREIGHT_TEMPLATE = os.path.join(SCHEMAS_DIR, "freight_na_railbridge_v3.json")

_SNAP_TO_AXIS = {
    "throttle": "throttle",
    "train_brake_pct": "train_brake",
    "ind_brake_pct": "ind_brake",
    "dyn_brake": "dyn_brake",
}

_API_RANGE_KEYS = {
    "throttle": "throttle_notch",
    "train_brake_pct": "train_brake_handle.handle_position",
    "ind_brake_pct": "locomotive_brake_handle.handle_position",
    "dyn_brake": "electric_brake_handle.handle_position",
}


def schema_path_for_vehicle(name: str) -> str:
    return os.path.join(SCHEMAS_DIR, f"{sanitize_vehicle_name(name)}.json")


def load_vehicle_schema(vehicle_name: Optional[str]) -> Optional[dict]:
    if not vehicle_name or not str(vehicle_name).strip():
        return None
    path = schema_path_for_vehicle(vehicle_name.strip())
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def infer_layout_from_stats(minmax: dict[str, tuple[Any, Any]],
                            seen_values: dict[str, set[Any]]) -> str:
    """freight_na si hay frenos separados; combined si solo handle 0–8."""
    brake_keys = ("train_brake_pct", "ind_brake_pct", "dyn_brake",
                  "train_brake", "ind_brake")
    for key in brake_keys:
        if key in minmax or key in seen_values:
            return "freight_na"
    if "throttle" in minmax or "throttle" in seen_values:
        return "combined"
    return "combined"


def _quantize_snap_values(axis_key: str, values: set[Any]) -> list[int]:
    out: set[int] = set()
    for val in values:
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if axis_key == "throttle":
            out.add(max(0, min(8, int(round(fval)))))
        elif axis_key == "dyn_brake":
            out.add(freight_quantize_level("dyn_brake", fval))
        elif axis_key == "train_brake_pct":
            out.add(freight_quantize_level("train_brake", fval))
        elif axis_key == "ind_brake_pct":
            out.add(freight_quantize_level("ind_brake", fval))
        elif axis_key in ("train_brake", "ind_brake"):
            out.add(max(0, min(10, int(round(fval)))))
    return sorted(out)


def build_observed_notches(layout: str,
                           seen_values: dict[str, set[Any]]) -> dict[str, list[int]]:
    if layout == "combined":
        raw = seen_values.get("throttle") or set()
        levels = _quantize_snap_values("throttle", raw)
        return {"handle": levels} if levels else {}

    observed: dict[str, list[int]] = {}
    for snap_key, axis in _SNAP_TO_AXIS.items():
        raw = seen_values.get(snap_key)
        if not raw:
            continue
        levels = _quantize_snap_values(snap_key, raw)
        if levels:
            observed[axis] = levels
    return observed


def _build_ranges(minmax: dict[str, tuple[Any, Any]]) -> dict[str, dict[str, Any]]:
    ranges: dict[str, dict[str, Any]] = {}
    for snap_key, api_key in _API_RANGE_KEYS.items():
        mm = minmax.get(snap_key)
        if mm:
            ranges[api_key] = {"min": mm[0], "max": mm[1]}
    return ranges


def build_vehicle_schema(
    vehicle: str,
    minmax: dict[str, tuple[Any, Any]],
    seen_values: dict[str, set[Any]],
    diag_log_path: str,
) -> Optional[dict]:
    name = (vehicle or "").strip()
    if not name or name in ("?", "Desconocido", "desconocido"):
        return None

    layout = infer_layout_from_stats(minmax, seen_values)
    observed = build_observed_notches(layout, seen_values)
    if not observed:
        return None

    rel_log = diag_log_path.replace("\\", "/")
    if rel_log.startswith(os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")):
        rel_log = os.path.relpath(
            diag_log_path, os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

    schema: dict[str, Any] = {
        "schema_version": 1,
        "vehicle": name,
        "layout": layout,
        "phase0_completed": date.today().isoformat(),
        "phase0_log": rel_log,
        "ranges": _build_ranges(minmax),
        "observed_notches": observed,
        "axes_detected": list(observed.keys()),
    }

    if layout == "freight_na":
        schema["control_schema"] = "freight_na_railbridge_v3"
    return schema


def save_vehicle_schema(schema: dict) -> str:
    vehicle = schema["vehicle"]
    path = schema_path_for_vehicle(vehicle)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def register_freight_vehicle(vehicle: str, diag_log_path: str) -> bool:
    """Añade el tren a validated_vehicles del esquema plantilla freight NA."""
    try:
        with open(_FREIGHT_TEMPLATE, encoding="utf-8") as f:
            template = json.load(f)
    except Exception:
        return False

    phase0 = template.setdefault("phase0", {})
    names: list[str] = list(phase0.get("validated_vehicles") or [])
    if vehicle not in names:
        names.append(vehicle)
        phase0["validated_vehicles"] = names

    rel_log = diag_log_path.replace("\\", "/")
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        rel_log = os.path.relpath(diag_log_path, base).replace("\\", "/")
    except ValueError:
        pass
    logs: list[str] = list(phase0.get("reference_logs") or [])
    if rel_log not in logs:
        logs.append(rel_log)
        phase0["reference_logs"] = logs

    with open(_FREIGHT_TEMPLATE, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def combined_notch_rows(vehicle: Optional[str],
                        default: tuple[int, ...]) -> tuple[int, ...]:
    schema = load_vehicle_schema(vehicle)
    if not schema or schema.get("layout") != "combined":
        return default
    handle = (schema.get("observed_notches") or {}).get("handle")
    if not handle:
        return default
    return tuple(sorted({int(x) for x in handle}))


def freight_axis_rows(vehicle: Optional[str]) -> dict[str, tuple[str, tuple[int, ...]]]:
    schema = load_vehicle_schema(vehicle)
    if not schema or schema.get("layout") != "freight_na":
        return dict(FREIGHT_AXIS_ROWS)

    observed = schema.get("observed_notches") or {}
    rows: dict[str, tuple[str, tuple[int, ...]]] = {}
    for axis, (title, default_levels) in FREIGHT_AXIS_ROWS.items():
        levels = observed.get(axis)
        if levels:
            wanted = {int(x) for x in levels}
            # Mantener orden habitual; incluir niveles vistos aunque no estén en default
            ordered = [lv for lv in default_levels if lv in wanted]
            extra = sorted(wanted - set(ordered))
            rows[axis] = (title, tuple(ordered + extra))
        else:
            rows[axis] = (title, default_levels)
    return rows
