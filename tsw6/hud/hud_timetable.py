"""
Lectura opcional de horarios desde ``tsw_hud.db`` (proyecto TSW HUD / DynamicHUD).

La BD se genera con ``hud.exe`` → Extraction → Load my DLCs. Sin ella el
autopilot sigue usando ``timetable.json``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tsw6.telemetry.driver_aid_parser import station_base_name
from tsw6.paths import HUD_DB_FILENAME, PROJECT_ROOT

_log = logging.getLogger("tsw.hud_timetable")

_MAX_MATCH_DIST_M = 20_000.0


@dataclass(frozen=True)
class TimetableMatch:
    id: int
    service_name: str
    route_name: str = ""


@dataclass(frozen=True)
class ScheduleEntry:
    location: Optional[str]
    action: str
    is_pass_through: bool
    arrival: Optional[str] = None
    departure: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p = math.pi / 180.0
    d_lat = (lat2 - lat1) * p
    d_lon = (lon2 - lon1) * p
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(d_lon / 2) ** 2
    )
    return 2.0 * r * math.asin(math.sqrt(a))


def _first_coord_from_blob(prefix: Optional[str]) -> Optional[tuple[float, float]]:
    if not prefix:
        return None
    s = prefix.strip()
    if s.startswith("[["):
        inner = s[2:]
        end = inner.find("]")
        if end < 0:
            return None
        parts = inner[:end].split(",")
        if len(parts) < 2:
            return None
        try:
            lng = float(parts[0].strip())
            lat = float(parts[1].strip())
        except ValueError:
            return None
        if lat == 0.0 and lng == 0.0:
            return None
        return lat, lng
    try:
        head = s.lstrip("[")
        end = head.find("}")
        if end < 0:
            return None
        obj = json.loads(head[: end + 1])
        lat = float(obj["latitude"])
        lng = float(obj["longitude"])
        if lat == 0.0 and lng == 0.0:
            return None
        return lat, lng
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def is_pass_through_action(action: str) -> bool:
    act = (action or "").upper()
    return act.startswith("PASS") or "VIA" in act


def is_scheduled_stop_action(action: str) -> bool:
    act = (action or "").upper()
    if not act or is_pass_through_action(act):
        return False
    if "WAIT FOR SERVICE" in act:
        return False
    if "COUPLE" in act or "UNCOUPLE" in act:
        return False
    if "STOP" in act or "LOAD" in act or "UNLOAD" in act:
        return True
    return act == "WAIT"


def default_hud_db_paths() -> list[Path]:
    root = PROJECT_ROOT
    env = os.environ.get("TSW_HUD_DB", "").strip()
    candidates = [
        root / HUD_DB_FILENAME,
        root / "data" / HUD_DB_FILENAME,
        Path(env) if env else None,
        Path.home()
        / "Desktop"
        / "investigacion tsw 6"
        / "tsw_projects-main"
        / "tsw_projects-main"
        / "hud"
        / "resources"
        / "db"
        / "tsw_hud.db",
        Path.home()
        / "Desktop"
        / "investigacion tsw 6"
        / "tsw_projects-main"
        / "tsw_projects-main"
        / "hud"
        / "resources"
        / "tsw_hud.db",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        if p is None:
            continue
        key = str(p.resolve()) if p.is_file() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def discover_hud_db(path: Optional[Path] = None) -> Optional[Path]:
    if path is not None:
        return path if path.is_file() else None
    for candidate in default_hud_db_paths():
        if candidate.is_file():
            return candidate
    return None


class HudTimetableStore:
    """Acceso de solo lectura a ``tsw_hud.db``."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = discover_hud_db(db_path)
        self._local = threading.local()
        if self.db_path:
            _log.info("HUD timetable DB: %s", self.db_path)

    @property
    def available(self) -> bool:
        return self.db_path is not None

    def _connection(self) -> sqlite3.Connection:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            if not self.db_path:
                raise RuntimeError("tsw_hud.db no encontrada")
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def find_active_timetable(
        self,
        service_name: str,
        *,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
    ) -> Optional[TimetableMatch]:
        svc = (service_name or "").strip()
        if not svc:
            return None
        conn = self._connection()
        sql = (
            "SELECT t.id, t.service_name, COALESCE(r.name, ''), "
            "SUBSTR(tc.coordinates, 1, 200) "
            "FROM timetables t "
            "LEFT JOIN routes r ON r.id = t.route_id "
            "LEFT JOIN timetable_coordinates tc ON tc.timetable_id = t.id "
            "WHERE t.current_service_name = ? OR t.service_name = ?"
        )
        rows = conn.execute(sql, (svc, svc)).fetchall()
        if not rows:
            return None

        best: Optional[tuple[int, str, str, float]] = None
        for row in rows:
            tid = int(row[0])
            name = str(row[1] or svc)
            route = str(row[2] or "")
            dist = float("inf")
            if lat is not None and lng is not None:
                coord = _first_coord_from_blob(row[3])
                if coord is not None:
                    dist = haversine_m(lat, lng, coord[0], coord[1])
            if best is None or dist < best[3]:
                best = (tid, name, route, dist)

        if best is None:
            return None
        tid, name, route, dist = best
        if lat is not None and lng is not None and math.isfinite(dist):
            if dist >= _MAX_MATCH_DIST_M:
                _log.debug(
                    "HUD timetable descartado (%.0fm > %.0fm) svc=%s id=%s",
                    dist, _MAX_MATCH_DIST_M, svc, tid)
                return None
        return TimetableMatch(id=tid, service_name=name, route_name=route)

    def _entry_car_stop_coords(self, timetable_id: int) -> dict[int, tuple[float, float]]:
        """Coordenadas car_stop por ``timetable_entries.id`` (como hud.exe)."""
        conn = self._connection()
        try:
            meta = conn.execute(
                "SELECT t.route_id, COALESCE(f.car_count, 0), "
                "COALESCE(LOWER(TRIM(t.bound)), '') "
                "FROM timetables t "
                "LEFT JOIN formations f ON f.id = t.formation_id "
                "WHERE t.id = ?",
                (timetable_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {}
        if not meta or meta[0] is None:
            return {}
        route_id = int(meta[0])
        car_count = int(meta[1] or 0)
        bound = str(meta[2] or "")
        sql = (
            "SELECT te.id, css.latitude, css.longitude "
            "FROM timetable_entries te JOIN locations l ON l.id = te.location_id "
            "JOIN car_stop_signs css ON css.route_id = ? "
            "AND css.platform_name = TRIM(l.name || ' ' || "
            "COALESCE(te.structure,'') || ' ' || COALESCE(te.structure_number,'')) "
            "WHERE te.timetable_id = ? "
            "ORDER BY te.id, "
            "CASE WHEN css.max_rail_vehicles = ? THEN 0 "
            "WHEN css.max_rail_vehicles > ? THEN css.max_rail_vehicles - ? "
            "WHEN css.max_rail_vehicles = 0 THEN 99999 "
            "ELSE 99999 + (? - css.max_rail_vehicles) END, "
            "CASE ? WHEN 'northbound' THEN -css.latitude "
            "WHEN 'southbound' THEN css.latitude "
            "WHEN 'eastbound' THEN -css.longitude "
            "WHEN 'westbound' THEN css.longitude ELSE 0 END"
        )
        try:
            rows = conn.execute(
                sql,
                (route_id, timetable_id, car_count, car_count, car_count,
                 car_count, bound),
            )
        except sqlite3.OperationalError:
            return {}
        out: dict[int, tuple[float, float]] = {}
        for eid, lat, lng in rows:
            eid_i = int(eid)
            if eid_i not in out:
                out[eid_i] = (float(lat), float(lng))
        return out

    def get_schedule_entries(self, timetable_id: int) -> list[ScheduleEntry]:
        conn = self._connection()
        car_coords = self._entry_car_stop_coords(timetable_id)
        rows = conn.execute(
            "SELECT te.id, te.time1, te.time2, te.latitude, te.longitude, "
            "ta.name, l.name "
            "FROM timetable_entries te "
            "LEFT JOIN timetable_actions ta ON ta.id = te.action_id "
            "LEFT JOIN locations l ON l.id = te.location_id "
            "WHERE te.timetable_id = ? "
            "ORDER BY te.sort_order",
            (timetable_id,),
        ).fetchall()

        out: list[ScheduleEntry] = []
        first_wait_done = False
        for row in rows:
            eid, t1, t2, lat_s, lng_s, action, location = row
            act = str(action or "").upper()
            loc = str(location or "").strip() or None
            has_loc = bool(loc)
            is_wait = "WAIT FOR SERVICE" in act
            is_via = is_pass_through_action(act)
            is_first_wait = is_wait and not has_loc and not first_wait_done
            if is_first_wait:
                first_wait_done = True

            if has_loc or is_wait or is_via:
                lat_v = lng_v = None
                try:
                    if lat_s not in (None, ""):
                        lat_v = float(str(lat_s).strip())
                    if lng_s not in (None, ""):
                        lng_v = float(str(lng_s).strip())
                except ValueError:
                    lat_v = lng_v = None
                if lat_v is None and lng_v is None and eid is not None:
                    pair = car_coords.get(int(eid))
                    if pair is not None:
                        lat_v, lng_v = pair
                arrival = str(t1).strip() if t1 else None
                departure = str(t2).strip() if t2 else None
                out.append(ScheduleEntry(
                    location=loc,
                    action=act,
                    is_pass_through=is_via,
                    arrival=arrival or None,
                    departure=departure or None,
                    latitude=lat_v,
                    longitude=lng_v,
                ))
            elif out:
                last = out[-1]
                if last.departure is None:
                    dep = str(t1).strip() if t1 else (str(t2).strip() if t2 else None)
                    if dep:
                        out[-1] = ScheduleEntry(
                            location=last.location,
                            action=last.action,
                            is_pass_through=last.is_pass_through,
                            arrival=last.arrival,
                            departure=dep,
                            latitude=last.latitude,
                            longitude=last.longitude,
                        )
        return out

    def scheduled_stop_names(self, timetable_id: int) -> list[str]:
        return self._stop_names_from_entries(self.get_schedule_entries(timetable_id))

    @staticmethod
    def _stop_names_from_entries(entries: list[ScheduleEntry]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            if entry.is_pass_through or not is_scheduled_stop_action(entry.action):
                continue
            if not entry.location:
                continue
            base = station_base_name(entry.location)
            if base and base not in seen:
                seen.add(base)
                names.append(entry.location.split(",")[0].strip())
        return names

    def merge_schedule_stations(
        self,
        track_stations: list[dict[str, Any]],
        entries: list[ScheduleEntry],
        stop_names: list[str],
        *,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """
        Lista de paradas del horario HUD, con distancia de TrackData si coincide
        el nombre; si no, distancia geográfica (car_stop) desde el tren.
        """
        if not stop_names:
            return []

        track_by_base: dict[str, dict[str, Any]] = {}
        for st in track_stations:
            base = station_base_name(str(st.get("name", "")))
            if not base:
                continue
            prev = track_by_base.get(base)
            dist = float(st.get("distance_m") or 0)
            if prev is None or dist < float(prev.get("distance_m") or 0):
                track_by_base[base] = dict(st)

        coord_by_base: dict[str, tuple[float, float]] = {}
        for entry in entries:
            if not entry.location or entry.is_pass_through:
                continue
            if not is_scheduled_stop_action(entry.action):
                continue
            if entry.latitude is None or entry.longitude is None:
                continue
            base = station_base_name(entry.location)
            if base and base not in coord_by_base:
                coord_by_base[base] = (entry.latitude, entry.longitude)

        out: list[dict[str, Any]] = []
        for stop in stop_names:
            base = station_base_name(stop)
            if not base:
                continue
            if base in track_by_base:
                row = dict(track_by_base[base])
                row["scheduled"] = True
                out.append(row)
                continue
            if lat is not None and lng is not None and base in coord_by_base:
                plat, plng = coord_by_base[base]
                out.append({
                    "name": stop,
                    "distance_m": round(haversine_m(lat, lng, plat, plng), 1),
                    "scheduled": True,
                    "source": "hud_geo",
                })

        out.sort(key=lambda s: float(s.get("distance_m") or 0))
        return out

    def resolve_service_stops(
        self,
        service_name: str,
        *,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        match = self.find_active_timetable(service_name, lat=lat, lng=lng)
        if match is None:
            return None
        entries = self.get_schedule_entries(match.id)
        stops = self._stop_names_from_entries(entries)
        if not stops:
            return None
        return {
            "timetable_id": match.id,
            "service_name": match.service_name,
            "route_name": match.route_name,
            "stop_names": stops,
            "entries": entries,
        }
