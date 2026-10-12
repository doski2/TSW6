"""Lector propio de ``tsw_hud.db`` (solo lectura) para V2.

Sin dependencia de ``tsw6/``. Expone paradas programadas de un servicio con
identidad estable (``locations.id``) y coordenadas (``timetable_entries`` o
``car_stop_signs``), para comparar estaciones por distancia y no por nombre.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class HudStop:
    """Parada programada: identidad estable y coordenada."""

    location_id: int
    name: str
    latitude: Optional[float]
    longitude: Optional[float]


SAME_STOP_MAX_M = 150.0


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_same_stop(
    candidate: HudStop,
    served: HudStop,
) -> bool:
    """``True`` si ``candidate`` es la misma parada que ``served``.

    Orden de criterio: ``location_id`` (identidad estable); si no coincide,
    coordenada a menos de ``SAME_STOP_MAX_M`` cuando ambas la tienen; si no,
    nombre igual (solo cuando falta coordenada en alguna de las dos).
    """
    if candidate.location_id == served.location_id:
        return True
    if (
        candidate.latitude is not None
        and candidate.longitude is not None
        and served.latitude is not None
        and served.longitude is not None
    ):
        return (
            _haversine_m(
                candidate.latitude, candidate.longitude,
                served.latitude, served.longitude,
            )
            <= SAME_STOP_MAX_M
        )
    return candidate.name.strip().lower() == served.name.strip().lower()


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_hud_db_path() -> Optional[Path]:
    """Primera ``tsw_hud.db`` existente: ``TSW_HUD_DB``, extracción completa, proyecto."""
    import os

    env = os.environ.get("TSW_HUD_DB", "").strip()
    candidates = [
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
        _PROJECT_ROOT / "tsw_hud.db",
    ]
    for cand in candidates:
        if cand is not None and cand.is_file():
            return cand
    return None


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Conexión de solo lectura. Lanza ``sqlite3.Error`` si no se puede abrir."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _to_float(raw: object) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def car_stop_coords(
    conn: sqlite3.Connection,
    timetable_id: int,
) -> dict[int, tuple[float, float]]:
    """Coordenadas de ``car_stop_signs`` por ``timetable_entries.id``.

    Replica la resolución de ``hud_timetable._entry_car_stop_coords`` (legacy):
    empareja la ubicación con la señal de andén de la misma ruta y ordena por
    ``max_rail_vehicles`` según el número de vagones de la formación.
    """
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
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[int, tuple[float, float]] = {}
    for eid, lat, lng in rows:
        eid_i = int(eid)
        if eid_i not in out:
            out[eid_i] = (float(lat), float(lng))
    return out


def stops_for_service(conn: sqlite3.Connection, service_name: str) -> list[HudStop]:
    """Paradas (con ``location_id``) del horario activo de ``service_name``.

    Devuelve una entrada por ``location_id``, en orden de horario. Solo cuenta
    entradas con ubicación (``location_id`` no nulo).
    """
    rows = conn.execute(
        """
        SELECT t.id AS timetable_id, te.id AS entry_id,
               l.id AS location_id, l.name AS name,
               te.latitude AS latitude, te.longitude AS longitude,
               te.sort_order AS sort_order
        FROM timetables t
        JOIN timetable_entries te ON te.timetable_id = t.id
        JOIN locations l ON l.id = te.location_id
        WHERE (t.current_service_name = ? OR t.service_name = ?)
          AND te.location_id IS NOT NULL
        ORDER BY te.sort_order
        """,
        (service_name, service_name),
    ).fetchall()
    if not rows:
        return []

    fallback = car_stop_coords(conn, int(rows[0]["timetable_id"]))
    seen: set[int] = set()
    out: list[HudStop] = []
    for row in rows:
        loc_id = int(row["location_id"])
        if loc_id in seen:
            continue
        seen.add(loc_id)
        lat = _to_float(row["latitude"])
        lng = _to_float(row["longitude"])
        if lat is None and lng is None:
            pair = fallback.get(int(row["entry_id"]))
            if pair is not None:
                lat, lng = pair
        out.append(
            HudStop(
                location_id=loc_id,
                name=str(row["name"]),
                latitude=lat,
                longitude=lng,
            )
        )
    return out
