#!/usr/bin/env python3
"""
control_layout.py — Detección de layout de mandos (combined vs freight_na).

Fase 1 FREIGHT NA: usa esquema Fase 0 + heurísticas por nombre de loco.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Optional

LAYOUT_COMBINED = "combined"
LAYOUT_FREIGHT_NA = "freight_na"

_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "logs", "control_schemas", "freight_na_railbridge_v3.json",
)

# Subcadenas en friendly_name → freight_na (diesel NA multi-mando)
_FREIGHT_NA_HINTS: tuple[str, ...] = (
    "sd40", "sd45", "sd70", "sd90",
    "gp38", "gp40", "gp50",
    "es44", "et44", "dash 9", "dash-9", "dash9",
    "ac4400", "c40-8", "c40-9", "c44-9",
    "bnsf", "csx", "ns ", "norfolk southern",
    "union pacific", "up ", "cn ", "canadian national",
    "cp ", "canadian pacific",
)

# Subcadenas → combined (UK EMU / handle PowerBrakeHandle)
_COMBINED_HINTS: tuple[str, ...] = (
    "class 323", "class 350", "class 387", "class 390",
    "class 221", "class 220", "class 158", "class 170",
    "class 153", "class 156", "class 319", "class 331",
    "class 377", "class 378", "class 379", "class 380",
    "class 800", "class 801", "class 802",
    "powerbrake", "emu", "dms", "ms ",
)


@lru_cache(maxsize=1)
def _load_freight_schema() -> dict:
    try:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def validated_freight_vehicles() -> frozenset[str]:
    """Nombres exactos validados en Fase 0 (esquema JSON)."""
    schema = _load_freight_schema()
    names = schema.get("phase0", {}).get("validated_vehicles") or []
    return frozenset(str(n) for n in names)


def detect_control_layout(vehicle_name: Optional[str]) -> str:
    """
    Devuelve 'combined' o 'freight_na'.

    Prioridad:
      1. Lista validated_vehicles del esquema Fase 0
      2. Heurísticas _FREIGHT_NA_HINTS / _COMBINED_HINTS en el nombre
      3. Por defecto 'combined' (Class 323 y desconocidos UK)
    """
    if not vehicle_name or not str(vehicle_name).strip():
        return LAYOUT_COMBINED

    name = str(vehicle_name).strip()
    if name in validated_freight_vehicles():
        return LAYOUT_FREIGHT_NA

    lower = name.lower()
    for hint in _FREIGHT_NA_HINTS:
        if hint in lower:
            return LAYOUT_FREIGHT_NA

    for hint in _COMBINED_HINTS:
        if hint in lower:
            return LAYOUT_COMBINED

    # Patrones diesel NA genéricos: "SD40-2", "ES44AC", etc.
    if re.search(r"\bsd\d{2}\b", lower) or re.search(r"\bes44", lower):
        return LAYOUT_FREIGHT_NA

    return LAYOUT_COMBINED
