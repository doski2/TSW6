"""Normalización ETA del HUD (antes en station_plan v1)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_ETA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def normalize_station_eta(eta: Optional[str]) -> Optional[str]:
    """``HH:MM`` o ``HH:MM:SS`` del HUD → ``HH:MM``."""
    if eta is None:
        return None
    s = str(eta).strip()
    if not s:
        return None
    m = _ETA_RE.match(s)
    if not m:
        return None
    return f"{int(m.group(1))}:{m.group(2)}"


def parse_eta_minutes(eta: str) -> Optional[int]:
    norm = normalize_station_eta(eta)
    if norm is None:
        return None
    match = _ETA_RE.match(norm)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def minutes_until_eta(eta: str, now: Optional[datetime] = None) -> Optional[int]:
    norm = normalize_station_eta(eta)
    if norm is None:
        return None
    match = _ETA_RE.match(norm)
    if not match:
        return None
    now = now or datetime.now()
    target = now.replace(
        hour=int(match.group(1)),
        minute=int(match.group(2)),
        second=0,
        microsecond=0,
    )
    delta = int((target - now).total_seconds() // 60)
    if delta < -12 * 60:
        delta += 24 * 60
    return delta
