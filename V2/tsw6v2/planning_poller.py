"""Distancia de andén: HTTP DriverAid en hilo aparte + ``v×dt``; fallback ``Planning.txt``."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from tsw6v2.bridge.http_api import find_api_key, probe_http_api
from tsw6v2.driver_aid_stations import poll_station_planning
from tsw6v2.planning_feed import (
    PlanningFeed,
    PlanningSnapshot,
    default_planning_path,
    planning_distance_accept,
    tick_station_distance_m,
    write_planning_snapshot,
)

_log = logging.getLogger("tsw6v2.planning_poller")

PLANNING_MIN_INTERVAL_S = 2.0
PLANNING_READ_TIMEOUT_S = 1.0


class StationPlanning:
    """
    Fuente unificada para P1 andén.

    Intenta HTTP ``DriverAid.TrackData`` (~2 s); si no hay API, lee ``Planning.txt``.
    Un solo hilo hace poll HTTP (sin duplicar con el tick del agente).
    """

    def __init__(
        self,
        *,
        path: Optional[Path] = None,
        http_enabled: bool = True,
        poll_interval_s: float = PLANNING_MIN_INTERVAL_S,
        reload_interval_s: float = 0.5,
    ) -> None:
        self.path = path
        self.http_enabled = http_enabled
        self.poll_interval_s = poll_interval_s
        self._snap = PlanningSnapshot()
        self._file_feed = PlanningFeed(path=path or default_planning_path())
        self._file_feed.reload_interval_s = reload_interval_s
        self._http_ok = False
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cache_lock = threading.Lock()
        self._last_tick_t = 0.0
        self._last_speed_mph = 0.0
        self._source = "none"
        self._schedule_source = ""
        if self.http_enabled and find_api_key() is not None:
            self._http_ok = probe_http_api(timeout_s=PLANNING_READ_TIMEOUT_S)
            if self._http_ok:
                self._source = "http"
                self._poll_thread = threading.Thread(
                    target=self._poll_loop,
                    daemon=True,
                    name="tsw6v2-planning",
                )
                self._poll_thread.start()
            else:
                _log.debug("HTTPAPI no responde; fallback Planning.txt")
        if not self._http_ok:
            self._source = "file"

    @property
    def source(self) -> str:
        return self._source

    @property
    def http_active(self) -> bool:
        return self._http_ok

    @property
    def schedule_source(self) -> str:
        """``hud_db`` | ``timetable_json`` | ``track_only`` | ```` (sin poll aún)."""
        return self._schedule_source

    def close(self) -> None:
        self._stop_event.set()

    def update(self, speed_mph: float) -> PlanningSnapshot:
        now = time.monotonic()
        if self._last_tick_t <= 0:
            self._last_tick_t = now
        dt = now - self._last_tick_t
        self._last_tick_t = now
        self._last_speed_mph = float(speed_mph)

        if self._http_ok:
            with self._cache_lock:
                self._snap.station_distance_m = tick_station_distance_m(
                    self._snap.station_distance_m, speed_mph, dt
                )
            return self._snap
        return self._file_feed.update(speed_mph)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            if self._stop_event.wait(self.poll_interval_s):
                break

    def _poll_once(self) -> None:
        try:
            result = poll_station_planning()
        except Exception as exc:
            _log.debug("poll_station_planning: %s", exc)
            return
        nxt = result.get("next_stop")
        if not isinstance(nxt, dict):
            return
        dist = nxt.get("distance_m")
        name = nxt.get("name")
        if dist is None or float(dist) <= 0:
            return
        new_dist = float(dist)
        with self._cache_lock:
            prev = self._snap.station_distance_m
            if not planning_distance_accept(prev, new_dist, self._last_speed_mph):
                _log.info(
                    "planning: ignorar salto HTTP %.0f -> %.0f m (spd=%.1f)",
                    prev or -1,
                    new_dist,
                    self._last_speed_mph,
                )
                return
            sched = str(result.get("schedule_source") or "")
            self._schedule_source = sched
            snap = PlanningSnapshot(
                station_distance_m=new_dist,
                station_name=str(name) if name else None,
                service_name=result.get("service_name"),
                schedule_source=sched,
                hud_timetable_id=result.get("hud_timetable_id"),
            )
            self._snap = snap
        write_planning_snapshot(
            station_distance_m=snap.station_distance_m,
            station_name=snap.station_name,
            path=self.path,
        )
