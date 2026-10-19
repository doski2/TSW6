"""Distancia de andén: HTTP DriverAid en hilo aparte + ``v×dt``; fallback ``Planning.txt``."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.http_api import POLL_TIMING_MS, find_api_key, probe_http_api
from tsw6v2.driver_aid_stations import poll_station_planning, station_base_name
from tsw6v2.constants import MPH_TO_MS
from tsw6v2.hud_anchor import MIN_HUD_M, AnchorReading, HudAnchor
from tsw6v2.hud_db import default_hud_db_path
from tsw6v2.planning_feed import (
    PLANNING_JUMP_REJECT_M,
    PLANNING_NEXT_STOP_MIN_SPEED_MPH,
    PLATFORM_MARKER_PASSED_M,
    PlanningFeed,
    PlanningSnapshot,
    advance_station_distance_tick,
    apply_station_distance_reading,
    compensate_http_distance_m,
    default_planning_path,
    resolve_station_tick_dt,
    write_planning_snapshot,
)
from tsw6v2.vehicle_package import station_planning_trusted

_log = logging.getLogger("tsw6v2.planning_poller")

PLANNING_MIN_INTERVAL_S = 2.0
# Solo el sondeo inicial ``probe_http_api``; los GET de poll usan ``DEFAULT_READ_TIMEOUT_S`` (3 s).
PLANNING_READ_TIMEOUT_S = 1.0
# Ciclo real de sondeo ≈ espera (2 s) + 2 GET de ~1-2 s ≈ 4-6 s (223124Z: 4,2 s; 104709Z: ~6,2 s).
# Congelar a los 2 s dejaba ~59% de ticks en marcha sin v×dt (~40 m de error a 40 mph).
# 103432Z: 1 de cada 3 polls falla y el hueco pasa de 4,2 a 8,3 s; con 5 s la distancia se
# congelaba ~3,3 s a 30-47 mph (50-70 m de error). Dos ciclos fallidos seguidos ≈ 12,5 s.
PLANNING_STALE_AFTER_S = 13.0
# HTTP vs OCR (marco tablón): una lectura que difiere más es sospechosa (162907Z: 3 m vs 34 m).
HTTP_OCR_AGREE_M = 20.0
HTTP_OCR_MAX_AGE_S = 2.0


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
        self.last_poll_ms = 0.0  # duración del último poll (HTTP + BD), para diagnóstico
        self.last_poll_http_ms = 0.0
        self.last_poll_json_ms = 0.0
        # Última respuesta HTTP con distancia válida (reloj de pared, como el poll).
        self._last_reading_t: Optional[float] = None
        self._last_probe_seq: Optional[int] = None
        self._last_seq_change_t: Optional[float] = None
        self._last_probe_vehicle: Optional[str] = None
        self._startup_invalidate_pending = True
        self._schedule_identity: tuple[str, str, Optional[int]] = ("", "", None)
        self._served_bases: set[str] = set()
        self._anchor: Optional[HudAnchor] = None
        self._last_ocr: Optional[AnchorReading] = None
        # Algún poll ya cruzó paradas del horario con TrackData: si luego ninguna coincide es que
        # la siguiente parada está lejos (no que los nombres no cuadren).
        self._schedule_matched_once = False
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

    def set_hud_anchor(self, anchor: Optional[HudAnchor]) -> None:
        """Activa el ancla al HUD (OCR): el objetivo pasa a ser el marcador del juego."""
        self._anchor = anchor

    @property
    def board_frame(self) -> bool:
        """True si la distancia de estación ya va en el marco del tablón (ancla HUD)."""
        return self._anchor is not None and self._anchor.board_frame

    def anchor_status(self) -> Optional[str]:
        anchor = self._anchor
        return None if anchor is None else anchor.status()

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
            self._served_bases = set()
            self._schedule_matched_once = False
            if self._anchor is not None:
                self._anchor.reset()
        self._file_feed.reset()
        self._last_tick_t = 0.0

    def _clear_served_bases(self) -> None:
        with self._cache_lock:
            if not self._served_bases:
                return
            self._served_bases = set()

    def _mark_stop_served(self, name: Optional[str]) -> None:
        """Llamar con ``_cache_lock`` ya tomado (p. ej. desde ``_poll_once``)."""
        base = station_base_name(name or "")
        if base:
            self._served_bases.add(base)

    def _maybe_mark_departed_stop(
        self,
        prev_dist: Optional[float],
        prev_name: Optional[str],
        new_dist: float,
        speed_mph: float,
    ) -> None:
        """Tras pasar marker con marcha: excluir esa parada del picker HTTP."""
        if prev_dist is None or prev_dist > PLATFORM_MARKER_PASSED_M:
            return
        if new_dist <= PLANNING_JUMP_REJECT_M:
            return
        if speed_mph < PLANNING_NEXT_STOP_MIN_SPEED_MPH:
            return
        self._mark_stop_served(prev_name)

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

    def _note_probe_vehicle(self, probe_vehicle: Optional[str]) -> None:
        text = (probe_vehicle or "").strip()
        if not text or text == "?":
            return
        prev = self._last_probe_vehicle
        self._last_probe_vehicle = text
        if prev is not None and prev != text:
            _log.info("planning: reset tras cambio vehicle %s -> %s", prev, text)
            self.invalidate()

    @staticmethod
    def _cleared_foreign_stop_snapshot(
        snap: PlanningSnapshot,
        probe_vehicle: Optional[str],
        *,
        hud_route_name: Optional[str] = None,
    ) -> Optional[PlanningSnapshot]:
        """
        Snap sin parada si HUD y tren son de regiones distintas.

        ``hud_route_name`` opcional (p. ej. metadatos HTTP en caché principal
        mientras ``Planning.txt`` no trae ruta).
        """
        if not probe_vehicle:
            return None
        hud = (hud_route_name if hud_route_name is not None else snap.hud_route_name)
        if station_planning_trusted(probe_vehicle, hud):
            return None
        if snap.station_distance_m is None and not snap.station_name:
            return None
        _log.info(
            "planning: parada ignorada %s @ %s m (HUD %s, vehicle %s)",
            snap.station_name or "?",
            snap.station_distance_m,
            (hud or "?"),
            probe_vehicle,
        )
        return PlanningSnapshot(
            station_distance_m=None,
            station_name=None,
            service_name=snap.service_name,
            hud_route_name=snap.hud_route_name or hud_route_name,
            schedule_source=snap.schedule_source,
            hud_timetable_id=snap.hud_timetable_id,
        )

    def _suppress_untrusted_station_cache(self, probe_vehicle: Optional[str]) -> None:
        with self._cache_lock:
            cleared = self._cleared_foreign_stop_snapshot(
                self._snap, probe_vehicle
            )
            if cleared is None:
                return
            self._snap.station_distance_m = None
            self._snap.station_name = None

    def _strip_untrusted_station_fields(
        self,
        snap: PlanningSnapshot,
        probe_vehicle: Optional[str],
    ) -> PlanningSnapshot:
        hud = snap.hud_route_name
        if not hud and not self._http_ok:
            with self._cache_lock:
                hud = self._snap.hud_route_name
        cleared = self._cleared_foreign_stop_snapshot(
            snap, probe_vehicle, hud_route_name=hud
        )
        return cleared if cleared is not None else snap

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

    def _note_schedule_identity(self, result: dict) -> None:
        """Actualiza metadatos HUD; no vacía distancia (parpadeo andén, 215536Z)."""
        identity = self._identity_from_poll(result)
        if not any(identity):
            return
        prev = self._schedule_identity
        if prev != ("", "", None) and identity != prev:
            prev_tid = prev[2]
            new_tid = identity[2]
            if (
                prev_tid is not None
                and new_tid is not None
                and prev_tid != new_tid
            ):
                _log.info(
                    "planning: cambio timetable %s -> %s; limpiar paradas servidas",
                    prev_tid,
                    new_tid,
                )
                self._clear_served_bases()
                self._schedule_matched_once = False  # otro servicio: sin historial de nombres
            _log.info(
                "planning: cambio servicio %s / %s -> %s / %s (conservar dist)",
                prev[0] or "?",
                prev[2] or "?",
                identity[0] or "?",
                identity[2] or "?",
            )
        self._schedule_identity = identity

    def update(
        self,
        speed_mph: float,
        *,
        probe_seq: Optional[int] = None,
        probe_vehicle: Optional[str] = None,
        hud_ocr: Optional[AnchorReading] = None,
    ) -> PlanningSnapshot:
        self._note_probe_vehicle(probe_vehicle)
        self._suppress_untrusted_station_cache(probe_vehicle)
        if not self._http_ok:
            self._note_probe_seq(probe_seq)
            snap = self._file_feed.update(speed_mph, probe_seq=probe_seq)
            return self._strip_untrusted_station_fields(snap, probe_vehicle)

        now = time.monotonic()
        if self._last_tick_t <= 0:
            self._last_tick_t = now
        dt = resolve_station_tick_dt(
            last_probe_seq=self._last_probe_seq,
            probe_seq=probe_seq,
            last_wall_t=self._last_tick_t,
            now=now,
            last_seq_change_t=self._last_seq_change_t,
        )
        self._last_tick_t = now
        self._last_speed_mph = float(speed_mph)
        if hud_ocr is not None:
            self._last_ocr = hud_ocr
        if probe_seq is not None and probe_seq != self._last_probe_seq:
            self._last_seq_change_t = now
        self._note_probe_seq(probe_seq)
        with self._cache_lock:
            advance_station_distance_tick(
                self._snap,
                speed_mph,
                dt,
                freeze=self._reading_stale(),
            )
            if self._anchor is not None and hud_ocr is not None:
                anchored = self._anchor.apply(
                    self._snap.station_distance_m,
                    hud_ocr,
                    now=now,
                    speed_mph=float(speed_mph),
                )
                if anchored is not None:
                    self._snap.station_distance_m = anchored
            snap = self._snap
        return self._strip_untrusted_station_fields(snap, probe_vehicle)

    def _contradicts_ocr(self, board_dist_m: float) -> bool:
        """True si la lectura HTTP (marco tablón) difiere del OCR reciente más de ``HTTP_OCR_AGREE_M``."""
        anchor, ocr = self._anchor, self._last_ocr
        if anchor is None or ocr is None or not anchor.board_frame:
            return False
        age = time.monotonic() - ocr.t
        if age > HTTP_OCR_MAX_AGE_S:
            return False
        hud_now = ocr.value_m - self._last_speed_mph * MPH_TO_MS * age
        return hud_now >= MIN_HUD_M and abs(board_dist_m - hud_now) > HTTP_OCR_AGREE_M

    def _reading_stale(self) -> bool:
        """True si hace más de un poll que no llega una distancia HTTP válida.

        Sin ninguna lectura previa no hay nada que congelar (la distancia solo viene de una lectura).
        """
        if self._last_reading_t is None:
            return False
        return (time.monotonic() - self._last_reading_t) > PLANNING_STALE_AFTER_S

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            if self._stop_event.wait(self.poll_interval_s):
                break

    def _poll_once(self, *, skip_identity_check: bool = False) -> None:
        with self._cache_lock:
            exclude_bases = set(self._served_bases)
            service_hint = self._snap.service_name
            allow_fallback = not self._schedule_matched_once
        POLL_TIMING_MS["http"] = POLL_TIMING_MS["json"] = 0.0
        t_poll = time.perf_counter()
        try:
            result = poll_station_planning(
                exclude_bases=exclude_bases,
                hud_db_path=default_hud_db_path(),
                service_name_hint=service_hint,
                fallback_all_when_unmatched=allow_fallback,
            )
        except Exception as exc:
            _log.debug("poll_station_planning: %s", exc)
            return
        finally:
            self.last_poll_ms = (time.perf_counter() - t_poll) * 1000.0
            self.last_poll_http_ms = POLL_TIMING_MS["http"]
            self.last_poll_json_ms = POLL_TIMING_MS["json"]
        if result.get("schedule_source") == "hud_db" and result.get("stations"):
            self._schedule_matched_once = True
        if not skip_identity_check:
            self._note_schedule_identity(result)
        self._apply_poll_metadata(result)
        vehicle = self._last_probe_vehicle
        with self._cache_lock:
            hud = self._snap.hud_route_name
        if vehicle and not station_planning_trusted(vehicle, hud):
            return
        nxt = result.get("next_stop")
        if not isinstance(nxt, dict):
            return
        dist = nxt.get("distance_m")
        name = nxt.get("name")
        if dist is None or float(dist) <= 0:
            return
        new_dist = compensate_http_distance_m(float(dist), self._last_speed_mph)
        self._last_reading_t = time.monotonic()
        with self._cache_lock:
            prev = self._snap.station_distance_m
            prev_name = self._snap.station_name
            anchor = self._anchor
            end_dist = new_dist
            if anchor is not None:
                if prev_name and name and str(name) != prev_name:
                    anchor.reset()  # otra estación: el desfase aprendido ya no vale
                else:
                    new_dist = anchor.to_board(end_dist)
            if self._contradicts_ocr(new_dist):
                self._snap.planning_rejected_n += 1
                _log.info(
                    "planning: ignorar lectura HTTP %.0f m (contradice al OCR del HUD)",
                    new_dist,
                )
                return
            if not apply_station_distance_reading(
                self._snap,
                new_dist,
                self._last_speed_mph,
                new_name=str(name) if name else None,
                exclude_bases=self._served_bases,
            ):
                self._snap.planning_rejected_n += 1
                _log.info(
                    "planning: ignorar lectura HTTP %.0f -> %.0f m (spd=%.1f, stop=%s)",
                    prev or -1,
                    new_dist,
                    self._last_speed_mph,
                    name or "?",
                )
                return
            if anchor is not None:
                # Solo con la lectura ya validada: una rechazada no debe mover el desfase.
                anchor.note_http_end(end_dist, prev, now=time.monotonic())
            self._maybe_mark_departed_stop(
                prev,
                prev_name,
                new_dist,
                self._last_speed_mph,
            )
            if name:
                self._snap.station_name = str(name)
            raw_cm = nxt.get("raw_distance_cm")
            self._snap.raw_station_distance_m = (
                float(raw_cm) / 100.0 if raw_cm is not None else None
            )
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
