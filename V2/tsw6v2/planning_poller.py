"""Distancia de andén: HTTP DriverAid en hilo aparte + ``v×dt``; fallback ``Planning.txt``."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.http_api import find_api_key, probe_http_api
from tsw6v2.driver_aid_stations import poll_station_planning
from tsw6v2.planning_feed import (
    PlanningFeed,
    PlanningSnapshot,
    advance_station_distance_tick,
    apply_station_distance_reading,
    default_planning_path,
    write_planning_snapshot,
)

_log = logging.getLogger("tsw6v2.planning_poller")

PLANNING_MIN_INTERVAL_S = 2.0
PLANNING_READ_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class PollMetadata:
    service_name: Optional[str] = None
    hud_route_name: Optional[str] = None
    schedule_source: Optional[str] = None
    hud_timetable_id: Optional[int] = None

    @classmethod
    def from_poll(cls, result: dict[str, Any]) -> PollMetadata:
        tid_raw = result.get("hud_timetable_id")
        return cls(
            service_name=str(result.get("service_name") or "").strip() or None,
            hud_route_name=str(result.get("hud_route_name") or "").strip() or None,
            schedule_source=str(result.get("schedule_source") or "").strip() or None,
            hud_timetable_id=int(tid_raw) if tid_raw is not None else None,
        )

    def populated(self) -> bool:
        return any(
            (
                self.service_name,
                self.hud_route_name,
                self.schedule_source,
                self.hud_timetable_id is not None,
            )
        )


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
        self._last_probe_seq: Optional[int] = None
        self._startup_invalidate_pending = True
        self._schedule_identity: tuple[str, str, Optional[int]] = ("", "", None)
        self._source = "none"
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
        with self._cache_lock:
            return self._snap.schedule_source

    @property
    def detected_route(self) -> str:
        """Ruta comercial HUD (p. ej. ``Birmingham Cross-City``), si el juego la expone."""
        return str(self.context_snapshot().get("detected_route") or "")

    def context_snapshot(self) -> dict[str, object]:
        """Servicio/ruta detectados por HTTP (para metadatos JSONL)."""
        with self._cache_lock:
            snap = self._snap
            return {
                "detected_route": snap.hud_route_name,
                "service_name": snap.service_name,
                "schedule_source": snap.schedule_source or None,
                "hud_timetable_id": snap.hud_timetable_id,
            }

    def close(self) -> None:
        self._stop_event.set()

    def _clear_planning_cache(self) -> None:
        with self._cache_lock:
            self._snap = PlanningSnapshot()
        self._file_feed.reset()
        self._last_tick_t = 0.0

    def invalidate(self) -> None:
        """Partida guardada / discontinuidad probe: vaciar caché y releer HTTP o archivo."""
        self._clear_planning_cache()
        if self._http_ok:
            self._poll_once(skip_identity_check=True)
        else:
            self._file_feed.force_reload()

    @staticmethod
    def _poll_metadata(result: dict[str, Any]) -> PollMetadata:
        return PollMetadata.from_poll(result)

    @classmethod
    def _identity_from_poll(cls, result: dict[str, Any]) -> tuple[str, str, Optional[int]]:
        meta = cls._poll_metadata(result)
        return (
            meta.service_name or "",
            meta.hud_route_name or "",
            meta.hud_timetable_id,
        )

    def _note_probe_seq(self, probe_seq: Optional[int]) -> None:
        if probe_seq is None:
            return
        seq = int(probe_seq)
        last = self._last_probe_seq
        self._last_probe_seq = seq
        if last is None:
            if self._startup_invalidate_pending:
                self._startup_invalidate_pending = False
                _log.info("planning: reset al arranque (primer probe seq=%s)", seq)
                self.invalidate()
            return
        if seq < last - 50:
            _log.info("planning: reset tras probe seq %s -> %s (carga / salto)", last, seq)
            self.invalidate()

    def _maybe_reset_schedule_identity(self, result: dict) -> None:
        identity = self._identity_from_poll(result)
        if not any(identity):
            return
        prev = self._schedule_identity
        if prev != ("", "", None) and identity != prev:
            _log.info(
                "planning: reset tras cambio servicio %s / %s -> %s / %s",
                prev[0] or "?",
                prev[2] or "?",
                identity[0] or "?",
                identity[2] or "?",
            )
            self._clear_planning_cache()
        self._schedule_identity = identity

    def update(
        self,
        speed_mph: float,
        *,
        probe_seq: Optional[int] = None,
    ) -> PlanningSnapshot:
        self._note_probe_seq(probe_seq)
        now = time.monotonic()
        if self._last_tick_t <= 0:
            self._last_tick_t = now
        dt = now - self._last_tick_t
        self._last_tick_t = now
        self._last_speed_mph = float(speed_mph)

        if self._http_ok:
            with self._cache_lock:
                advance_station_distance_tick(self._snap, speed_mph, dt)
            return self._snap
        return self._file_feed.update(speed_mph)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            if self._stop_event.wait(self.poll_interval_s):
                break

    def _poll_once(self, *, skip_identity_check: bool = False) -> None:
        try:
            result = poll_station_planning()
        except Exception as exc:
            _log.debug("poll_station_planning: %s", exc)
            return
        if not skip_identity_check:
            self._maybe_reset_schedule_identity(result)
        self._apply_poll_metadata(result)
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
            if not apply_station_distance_reading(
                self._snap,
                new_dist,
                self._last_speed_mph,
            ):
                _log.info(
                    "planning: ignorar lectura HTTP %.0f -> %.0f m (spd=%.1f)",
                    prev or -1,
                    new_dist,
                    self._last_speed_mph,
                )
                return
            if name:
                self._snap.station_name = str(name)
            snap = self._snap
        write_planning_snapshot(
            station_distance_m=snap.station_distance_m,
            station_name=snap.station_name,
            path=self.path,
        )

    def _apply_poll_metadata(self, result: dict[str, Any]) -> None:
        """Servicio/ruta HUD aunque la distancia HTTP se rechace (yo-yo)."""
        meta = self._poll_metadata(result)
        if not meta.populated():
            return
        with self._cache_lock:
            if meta.service_name:
                self._snap.service_name = meta.service_name
            if meta.hud_route_name:
                self._snap.hud_route_name = meta.hud_route_name
            if meta.schedule_source:
                self._snap.schedule_source = meta.schedule_source
            if meta.hud_timetable_id is not None:
                self._snap.hud_timetable_id = meta.hud_timetable_id
