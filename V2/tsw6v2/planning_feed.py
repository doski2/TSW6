"""Distancia de andén fuera de GetData (HTTP planning → sidecar). ETA: ver ``station_plan``."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tsw6v2.bridge.getdata import parse_probe_line
from tsw6v2.constants import MPH_TO_MS


def default_planning_path() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(temp) / "TSW6Bridge" / "Planning.txt"


@dataclass
class PlanningSnapshot:
    station_distance_m: Optional[float] = None
    station_name: Optional[str] = None
    service_name: Optional[str] = None
    hud_route_name: Optional[str] = None
    schedule_source: str = ""
    hud_timetable_id: Optional[int] = None


# Rechazar salto HTTP a la siguiente parada tras pasar sin dwell (sesión 20260909T224556Z).
PLANNING_JUMP_REJECT_M = 500.0
PLATFORM_PASSED_MAX_M = 80.0
# Marker pasado (HUD ≈0 m): aceptar salto a la siguiente parada (225330Z).
PLATFORM_MARKER_PASSED_M = 5.0
# TrackData suele devolver ~5 m más lejos que v×dt (sesión 145832Z: 230→235 m).
PLANNING_HTTP_REGRESSION_M = 1.0
PLANNING_APPROACH_MIN_SPEED_MPH = 3.0
# Tras pasar andén: aceptar siguiente parada solo con marcha clara (225330Z).
PLANNING_NEXT_STOP_MIN_SPEED_MPH = 8.0
# Salto hacia atrás en marcha (sesión 211414Z: 22184→120 m @ 45 mph).
PLANNING_APPROACH_PREV_MIN_M = 1000.0


def planning_distance_accept(
    prev_m: Optional[float],
    new_m: float,
    speed_mph: float,
    *,
    jump_reject_m: float = PLANNING_JUMP_REJECT_M,
    platform_passed_max_m: float = PLATFORM_PASSED_MAX_M,
    regression_m: float = PLANNING_HTTP_REGRESSION_M,
    approach_min_speed_mph: float = PLANNING_APPROACH_MIN_SPEED_MPH,
    approach_prev_min_m: float = PLANNING_APPROACH_PREV_MIN_M,
) -> bool:
    """``False`` si el HTTP salta a la siguiente estación o aleja del andén en marcha."""
    if prev_m is None:
        return True
    # Salida: marker pasado (≈0 m) → HTTP de la siguiente parada (km). No confundir con
    # creep en andén (152306Z @ 3.4 mph) ni salto desde ~52 m aún en plataforma.
    if (
        prev_m <= PLATFORM_MARKER_PASSED_M
        and new_m > jump_reject_m
        and speed_mph >= PLANNING_NEXT_STOP_MIN_SPEED_MPH
    ):
        return True
    # En marcha con distancia consolidada: rechazar yo-yo grande (atrás o adelante).
    # Tras invalidate() prev=None acepta save/load; prev<1000 m deja pasar 235→1800 m.
    if (
        speed_mph >= approach_min_speed_mph
        and prev_m >= approach_prev_min_m
        and abs(new_m - prev_m) > jump_reject_m
    ):
        return False
    # Tras pasar andén (dwell o creep): rechazar salto a cualquier velocidad
    # (sesión 20260911T152306Z: 0→2012 m @ 3.4 mph).
    if new_m > prev_m + jump_reject_m and prev_m < platform_passed_max_m:
        return False
    # En marcha: no aceptar HTTP que aleja (confiar en v×dt hasta el próximo poll válido).
    if (
        speed_mph >= approach_min_speed_mph
        and new_m > prev_m + regression_m
        and new_m < prev_m + jump_reject_m
    ):
        return False
    return True


def tick_station_distance_m(
    distance_m: Optional[float],
    speed_mph: float,
    dt: float,
    *,
    min_speed_mph: float = 0.3,
) -> Optional[float]:
    """Resta ``v×dt`` entre lecturas HTTP o de archivo."""
    if distance_m is None or dt <= 0 or speed_mph < min_speed_mph:
        return distance_m
    delta = speed_mph * MPH_TO_MS * dt
    return max(0.0, float(distance_m) - delta)


def advance_station_distance_tick(
    snap: PlanningSnapshot,
    speed_mph: float,
    dt: float,
) -> None:
    """Un tick de dead-reckoning sobre ``snap`` (HTTP y archivo)."""
    snap.station_distance_m = tick_station_distance_m(
        snap.station_distance_m,
        speed_mph,
        dt,
    )


def apply_station_distance_reading(
    snap: PlanningSnapshot,
    new_dist: float,
    speed_mph: float,
) -> bool:
    """Actualiza ``snap`` si la lectura HTTP/archivo pasa filtros. ``False`` si se ignora."""
    if not planning_distance_accept(snap.station_distance_m, new_dist, speed_mph):
        return False
    snap.station_distance_m = new_dist
    return True


class PlanningFeed:
    """
    Lee ``Planning.txt`` (mismo estilo key=value que GetData) y estima
    ``station_distance_m`` entre lecturas con v×dt.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_planning_path()
        self._snap = PlanningSnapshot()
        self._last_reload = 0.0
        self._last_tick_t = 0.0
        self._last_speed_mph = 0.0
        self.reload_interval_s = 0.5

    def update(self, speed_mph: float) -> PlanningSnapshot:
        now = time.monotonic()
        if self._last_tick_t <= 0:
            self._last_tick_t = now
        if now - self._last_reload >= self.reload_interval_s:
            self._reload()
            self._last_reload = now
        dt = now - self._last_tick_t
        self._last_tick_t = now
        self._last_speed_mph = float(speed_mph)
        advance_station_distance_tick(self._snap, speed_mph, dt)
        return self._snap

    def reset(self) -> None:
        """Vaciar caché (p. ej. tras cargar partida en modo archivo)."""
        self._snap = PlanningSnapshot()
        self._last_tick_t = 0.0

    def force_reload(self) -> None:
        """Releer ``Planning.txt`` sin esperar intervalo."""
        self._reload()

    def _reload(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not raw:
            return
        line = raw.splitlines()[-1].strip()
        data = parse_probe_line(line)
        dist = data.get("station_dist_m")
        if dist is not None:
            apply_station_distance_reading(
                self._snap,
                float(dist),
                self._last_speed_mph,
            )
        name = data.get("next_stop") or data.get("station_name")
        if isinstance(name, str) and name.strip():
            self._snap.station_name = name.strip()


def format_planning_line(
    *,
    station_distance_m: Optional[float] = None,
    station_name: Optional[str] = None,
) -> str:
    parts: list[str] = []
    if station_distance_m is not None:
        parts.append(f"station_dist_m={float(station_distance_m):.1f}")
    if station_name:
        safe = str(station_name).strip().replace(" ", "_")
        if safe:
            parts.append(f"next_stop={safe}")
    return " ".join(parts)


_last_write_t = 0.0


def write_planning_snapshot(
    *,
    station_distance_m: Optional[float] = None,
    station_name: Optional[str] = None,
    path: Optional[Path] = None,
    min_interval_s: float = 0.5,
) -> bool:
    """Escribe ``Planning.txt`` para el agente V2 ``--mode station``."""
    global _last_write_t
    if station_distance_m is None or station_distance_m <= 0:
        return False
    now = time.monotonic()
    if now - _last_write_t < min_interval_s:
        return False
    line = format_planning_line(
        station_distance_m=station_distance_m,
        station_name=station_name,
    )
    if not line:
        return False
    dest = path or default_planning_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(line + "\n", encoding="utf-8")
    except OSError:
        return False
    _last_write_t = now
    return True
