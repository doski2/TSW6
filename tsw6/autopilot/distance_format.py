#!/usr/bin/env python3
"""
distance_format.py — Distancias en unidades del escenario TSW (HUD).

Internamente todo sigue en metros; esto solo formatea para GUI/logs.
"""

from __future__ import annotations

from typing import Optional

from tsw6.learning.control_layout import LAYOUT_COMBINED, LAYOUT_FREIGHT_NA, detect_control_layout

M_PER_MI = 1609.344
M_PER_YD = 0.9144
M_PER_FT = 0.3048

UNITS_UK = "uk_imperial"      # mi / yd (rutas UK, Class 323)
UNITS_US = "us_imperial"      # mi / ft (freight NA)
UNITS_METRIC = "metric"       # km / m (Europa, etc.)

# Por debajo de ~0.6 mi el DMI UK suele mostrar yardas (tsw_ocr).
_UK_YD_THRESHOLD_M = 0.6 * M_PER_MI

_METRIC_HINTS: tuple[str, ...] = (
    "ice ", "br 403", "br 442", "br 101", "br 425", "br 423", "br 146",
    "tgv", "sncf", "ter ", "caf ", "talgo", "renfe", "desiro", "mireo",
    "talent", "coradia", "pendolino", "eurostar",
)


def infer_distance_units(
    vehicle_name: Optional[str],
    control_layout: Optional[str] = None,
) -> str:
    """Unidades de distancia del escenario según tren/ruta."""
    layout = control_layout or detect_control_layout(vehicle_name)
    if layout == LAYOUT_FREIGHT_NA:
        return UNITS_US

    lower = (vehicle_name or "").lower()
    for hint in _METRIC_HINTS:
        if hint in lower:
            return UNITS_METRIC

    return UNITS_UK if layout == LAYOUT_COMBINED else UNITS_US


def distance_unit_label(units: str) -> str:
    """Etiqueta corta para cabeceras de tabla."""
    if units == UNITS_METRIC:
        return "m/km"
    if units == UNITS_US:
        return "ft/mi"
    return "yd/mi"


def format_distance(meters: float, units: str) -> str:
    """Formatea metros como en el HUD TSW."""
    if meters < 0:
        meters = 0.0

    if units == UNITS_METRIC:
        if meters >= 1000.0:
            return f"{meters / 1000.0:.1f} km"
        return f"{meters:.0f} m"

    if units == UNITS_US:
        feet = meters / M_PER_FT
        if feet >= 5280.0:
            return f"{meters / M_PER_MI:.1f} mi"
        return f"{feet:.0f} ft"

    # UK imperial: yardas cerca, millas lejos
    if meters >= _UK_YD_THRESHOLD_M:
        return f"{meters / M_PER_MI:.1f} mi"
    yards = meters / M_PER_YD
    return f"{yards:.0f} yd"


def format_distance_pair(
    planning_m: Optional[float],
    probe_m: Optional[float],
    units: str,
) -> str:
    """Planning + probe raw para comparar con el HUD."""
    if planning_m is None:
        return "—"
    main = format_distance(planning_m, units)
    if probe_m is None:
        return main
    probe = format_distance(probe_m, units)
    if abs(planning_m - probe_m) < 0.5:
        return main
    return f"{main}  (probe {probe})"
