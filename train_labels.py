#!/usr/bin/env python3
"""
train_labels.py — Etiquetas de mandos y utilidades del companion.

Constantes compartidas por learn_monitor, control_diag, etc.
"""

from __future__ import annotations

from typing import Optional

import requests

COMP_PORT = 51160
COMP_TOKEN = "aaeeb63be194470bb7f97c98b93635aa"

NOTCH_LABELS: dict[int, str] = {
    0: "Freno-4(max)",
    1: "Freno-3",
    2: "Freno-2",
    3: "Freno-1",
    4: "Neutro",
    5: "Tracción-1",
    6: "Tracción-2",
    7: "Tracción-3",
    8: "Tracción-4(max)",
}

# Filas de matriz freight_na (niveles cuantizados que el learner observa)
FREIGHT_AXIS_ROWS: dict[str, tuple[str, tuple[int, ...]]] = {
    "throttle":    ("TRACCIÓN",            (1, 2, 3, 4, 5, 6, 7, 8)),
    "train_brake": ("FRENO AUTOMÁTICO",    (2, 3, 4, 5, 6, 7, 8, 9, 10)),
    "ind_brake":   ("FRENO INDEPENDIENTE", (-8, -6, -4, -2, 2, 4, 6, 8)),
    "dyn_brake":   ("FRENO DINÁMICO",      (1, 2, 3, 4, 5, 6, 7, 8)),
}


def notch_label(n: int) -> str:
    return NOTCH_LABELS.get(n, f"Notch-{n}")


def control_level_label(axis: str, level: int) -> str:
    """Etiqueta de fila en la matriz de calibración freight_na."""
    if axis == "throttle":
        return "Idle" if level == 0 else f"N{level}"
    if axis == "train_brake":
        return f"{level * 10}%"
    if axis == "ind_brake":
        if level == 0:
            return "0%"
        return f"{level * 10:+d}%"
    if axis == "dyn_brake":
        return "Off" if level == 0 else f"D{level}"
    return str(level)


def control_value_label(axis: str, value: Optional[float]) -> str:
    """Etiqueta del valor actual de telemetría (cabecera freight)."""
    if value is None:
        return "?"
    if axis == "throttle":
        return f"N{int(round(value))}"
    if axis == "train_brake":
        return f"{max(0.0, value) * 100:.0f}%"
    if axis == "ind_brake":
        return f"{value * 100:+.0f}%"
    if axis == "dyn_brake":
        return "Off" if value < 0.02 else f"D{int(round(value * 8))}"
    return f"{value:.2f}"


def get_vehicle_name(base_url: str) -> Optional[str]:
    """Intenta leer el nombre del vehículo desde /vehicles."""
    try:
        r = requests.get(
            f"{base_url}/vehicles",
            headers={"Authorization": f"Bearer {COMP_TOKEN}"},
            timeout=2,
        )
        if r.status_code == 200:
            vehicles = r.json()
            if isinstance(vehicles, list) and vehicles:
                v = vehicles[0]
                name = v.get("name") or v.get("displayName") or v.get("className")
                if name and str(name).strip().lower() not in ("none", ""):
                    return str(name).strip()
    except Exception:
        pass
    return None
