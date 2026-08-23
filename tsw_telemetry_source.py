#!/usr/bin/env python3
"""
tsw_telemetry_source.py — Telemetría TSW (UE4SS in-process + HTTPAPI fallback).

Lectura preferente vía ``TelemetryProbeMod`` (~17–20 Hz, ``GetData.txt``).
Escritura de mandos vía ``SendCommand.txt`` (IPC Lua) o ``tsw_command_bus`` (HTTP).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from control_layout import detect_control_layout
from distance_format import infer_distance_units
from driver_aid_parser import (
    filter_stations_by_service,
    filter_stations_by_stop_names,
    load_service_timetable,
    parse_driver_aid_planning,
    parse_gradient_pct,
    parse_track_data_stations,
    select_next_scheduled_stop,
    _prune_zero_distance_limits,
)
from hud_timetable import HudTimetableStore
from tsw_api_client import TswApiClient, client_from_key_file
from tsw_command_bus import combined_value_to_notch, dispatch_brake, dispatch_combined_notch
from tsw_ipc_bus import (
    dispatch_ipc_brake,
    dispatch_ipc_combined_notch,
    enable_lua_commands,
    purge_lua_commands,
    release_controls,
)
from tsw_fast_telemetry import FastControlReader
from tsw_ue4ss_reader import (
    ProbeSnapshot,
    default_getdata_path,
    power_to_combined_notch,
    read_probe_file,
)

_log = logging.getLogger("tsw.telemetry")

DRIVABLE = "CurrentDrivableActor"
MS_TO_MPH = 2.236936
MPH_TO_MS = 0.44704
SLOW_EVERY = 30
PLANNING_MIN_INTERVAL_S = 2.0
CONTROL_API_TIMEOUT = 0.35
PLANNING_READ_TIMEOUT = 1.0
UE4SS_STALE_S = 0.75

_SLOW_READS: dict[str, str] = {
    "object_class": f"{DRIVABLE}.ObjectClass",
    "max_speed": f"{DRIVABLE}.Function.HUD_GetMaxPermittedSpeed",
    "loco_brake": f"{DRIVABLE}.Function.HUD_GetLocomotiveBrakeHandle",
    "dyn_brake": f"{DRIVABLE}.Function.HUD_GetElectricBrakeHandle",
    "driver_aid": "DriverAid.Data",
    "track_data": "DriverAid.TrackData",
}


def _parse_gradient_pct(node: Any) -> Optional[float]:
    """Alias para tests; ver driver_aid_parser.parse_gradient_pct."""
    return parse_gradient_pct(node)


def _power_to_handle_notch(
    power: Optional[float], power_negative: bool = False
) -> int:
    """HUD Power → muesca combinada 0–8 (Class 323)."""
    notch = power_to_combined_notch(power, power_negative)
    if notch is not None:
        return notch
    return 4


def _ue4ss_path() -> Path:
    return default_getdata_path()


def _ue4ss_is_fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return (time.time() - path.stat().st_mtime) <= UE4SS_STALE_S
    except OSError:
        return False


def _telem_from_probe(
    snap: ProbeSnapshot,
    age_ms: float = 0.0,
    gradient_fallback: Optional[float] = None,
) -> dict[str, Any]:
    """Telemetría base desde probe — velocidad directa, sin caché ni planning.

    CONGELADO (2026-08-22): ``speed_mph`` = ``speed_ms`` × MS_TO_MPH tal cual el probe.
    El planning/distancias no debe modificar este dict; solo añadir campos aparte.
    Tests: ``test_speed_*`` en ``test_telemetry_source.py``.
    """
    handle = snap.combined_handle_notch()
    if handle is None:
        handle = 4

    grad = snap.gradient_pct
    if gradient_fallback is not None:
        grad = gradient_fallback
    elif grad is None:
        grad = 0.0

    parsed: dict[str, Any] = {
        "speed_mph": (snap.speed_ms or 0.0) * MS_TO_MPH,
        "accel_mps2": snap.accel_ms2,
        "handle_notch": handle,
        "supervision": "csm",
        "ack_required": False,
        "gradient_pct": float(grad),
        "rain_intensity": 0.0,
        "telemetry_source": "ue4ss",
        "telemetry_age_ms": age_ms,
    }

    if snap.speed_limit_ms is not None:
        parsed["limit_mph"] = float(snap.speed_limit_ms) * MS_TO_MPH
    if snap.train_brake is not None:
        parsed["train_brake_value"] = float(snap.train_brake)
    if snap.loco_brake is not None:
        parsed["ind_brake_value"] = float(snap.loco_brake)
    if snap.dyn_brake is not None:
        parsed["dyn_brake_value"] = float(snap.dyn_brake)

    return parsed


class TswTelemetrySource:
    """
    Fuente de telemetría compatible con el antiguo ``TswConnection``.

    ``mode`` puede ser: ``ue4ss``, ``tsw_api``, ``manual``, ``searching``.
    """

    def __init__(self) -> None:
        self.mode = "searching"
        self.last_probe_info = "No probado aún"
        self._client: Optional[TswApiClient] = None
        self._reader: Optional[FastControlReader] = None
        self._telem: dict[str, Any] = {}
        self._telem_lock = threading.Lock()
        self._vehicle_name: Optional[str] = None
        self._poll_tick = 0
        self._slow: dict[str, Any] = {}
        self._ue4ss_path = _ue4ss_path()
        self._planning_cache: dict[str, Any] = {}
        self._planning_lock = threading.Lock()
        self._planning_refreshing = False
        self._planning_last_kick = 0.0
        self._planning_dist: dict[str, Any] = {}
        self._planning_dist_last_t = 0.0
        self._planning_probe_seq: Optional[int] = None
        self._planning_probe_dist: Optional[float] = None
        self._planning_odom_seq: Optional[int] = None
        self._station_odom_last_t = 0.0
        self._probe_extrap_last_t = 0.0
        self._probe_seq_changed_t = 0.0
        self._diag_last_log_t = 0.0
        self._diag_poll_n = 0
        self._diag_poll_miss = 0
        self._diag_last_seq: Optional[int] = None
        self._diag_last_dist: Optional[float] = None
        self._diag_last_probe_dist: Optional[float] = None
        self._motion_last_probe_dist: Optional[float] = None
        self._motion_probe_dist_since = 0.0
        self._motion_last_odo_m: Optional[float] = None
        self._motion_odo_since = 0.0
        self._motion_frozen = False
        self._planning_hold = False
        self._api_lock = threading.Lock()
        self._timetable = load_service_timetable()
        self._hud = HudTimetableStore()
        self._hud_match: Optional[dict[str, Any]] = None
        self._player_geo: Optional[tuple[float, float]] = None
        self._service_name: Optional[str] = None
        self._api_ok_cache: Optional[bool] = None
        self._api_ok_ts = 0.0

    def try_connect_ue4ss(self) -> bool:
        """Conecta por GetData.txt sin intentar HTTP (barato para 10 Hz)."""
        if self.mode == "ue4ss":
            return True
        snap = self._read_ue4ss_snapshot()
        if snap is None:
            return False
        self.mode = "ue4ss"
        self.last_probe_info = f"UE4SS probe ({self._ue4ss_path})"
        self._poll_ue4ss(snap)
        self._ensure_api_client(silent=True)
        return True

    def connect_fast(self) -> str:
        """Arranque GUI: solo UE4SS, sin esperar HTTPAPI (~2 s)."""
        if self.try_connect_ue4ss():
            return "ue4ss"
        self.mode = "searching"
        if not self._ue4ss_path.is_file():
            self.last_probe_info = (
                "Sin GetData.txt — install_ue4ss_probe.bat + F7 en cabina"
            )
        else:
            self.last_probe_info = (
                f"GetData.txt sin actualizar (> {UE4SS_STALE_S:.1f}s) — F7 en cabina"
            )
        return "searching"

    def probe(self) -> str:
        """Detecta UE4SS (GetData.txt) o HTTPAPI."""
        if self.try_connect_ue4ss():
            return "ue4ss"

        if self._ensure_api_client(silent=False):
            self.mode = "tsw_api"
            self._poll()
            return "tsw_api"

        self.mode = "searching"
        if not self._ue4ss_path.is_file():
            self.last_probe_info = (
                "Sin UE4SS ni HTTPAPI — instala TelemetryProbeMod o arranca con -HTTPAPI"
            )
        else:
            self.last_probe_info = (
                f"GetData.txt sin actualizar (> {UE4SS_STALE_S:.1f}s) y HTTPAPI no responde"
            )
        return "searching"

    def _read_ue4ss_snapshot(self) -> Optional[ProbeSnapshot]:
        path = self._ue4ss_path
        if not path.is_file():
            return None
        # Conectado: leer siempre. Solo al buscar conexión exigir mtime reciente.
        if self.mode != "ue4ss" and not _ue4ss_is_fresh(path):
            return None
        snap = read_probe_file(path)
        if snap is None or snap.speed_ms is None:
            return None
        return snap

    def _subtract_planning_distance(self, delta_m: float) -> None:
        for key in ("distance_next_m", "distance_next_2_m"):
            d = self._planning_dist.get(key)
            if d is not None:
                self._planning_dist[key] = max(0.0, float(d) - delta_m)
        for entry in self._planning_dist.get("speed_limits_ahead") or []:
            d = entry.get("distance_m")
            if d is not None:
                entry["distance_m"] = max(0.0, float(d) - delta_m)

    def _update_probe_motion_frozen(
        self,
        probe_dist_m: Optional[float],
        odo_m: Optional[float] = None,
    ) -> bool:
        """True si el tren no avanza (odómetro API o distancia probe congelada)."""
        now = time.monotonic()
        prev = self._motion_frozen

        if odo_m is not None:
            if self._motion_last_odo_m is None:
                self._motion_last_odo_m = odo_m
                self._motion_odo_since = now
            elif abs(odo_m - self._motion_last_odo_m) > 0.05:
                self._motion_last_odo_m = odo_m
                self._motion_odo_since = now
                self._motion_frozen = False
            else:
                self._motion_frozen = (now - self._motion_odo_since) > 0.25
        elif probe_dist_m is None:
            self._motion_frozen = False
            if self._motion_frozen != prev:
                _log.info("juego EN MOVIMIENTO  (sin dato dist/odo)")
            return self._motion_frozen
        else:
            if self._motion_last_probe_dist is None:
                self._motion_last_probe_dist = probe_dist_m
                self._motion_probe_dist_since = now
                self._motion_frozen = False
            elif abs(probe_dist_m - self._motion_last_probe_dist) < 0.5:
                self._motion_frozen = (now - self._motion_probe_dist_since) > 0.30
            else:
                self._motion_last_probe_dist = probe_dist_m
                self._motion_probe_dist_since = now
                self._motion_frozen = False

        if self._motion_frozen != prev:
            _log.info(
                "juego %s  probe_dist=%s  odo_m=%s",
                "CONGELADO" if self._motion_frozen else "EN MOVIMIENTO",
                f"{probe_dist_m:.1f}m" if probe_dist_m is not None else "—",
                f"{odo_m:.1f}" if odo_m is not None else "—",
            )
        return self._motion_frozen

    def _maybe_diag_log(
        self,
        snap: Optional[ProbeSnapshot] = None,
        *,
        dist_m: Optional[float] = None,
        probe_dist_m: Optional[float] = None,
        age_ms: float = 0.0,
        probe_fresh: bool = False,
        motion_frozen: bool = False,
    ) -> None:
        """Log periódico de refresco probe (detectar congelación)."""
        now = time.monotonic()
        self._diag_poll_n += 1
        if snap is None:
            self._diag_poll_miss += 1
        if now - self._diag_last_log_t < 3.0:
            return
        elapsed = now - self._diag_last_log_t if self._diag_last_log_t > 0 else 1.0
        hz = self._diag_poll_n / elapsed if elapsed > 0 else 0.0
        seq = snap.seq if snap else None
        seq_delta = (
            seq - self._diag_last_seq
            if seq is not None and self._diag_last_seq is not None
            else None
        )
        dist_delta = (
            dist_m - self._diag_last_dist
            if dist_m is not None and self._diag_last_dist is not None
            else None
        )
        probe_delta = (
            probe_dist_m - self._diag_last_probe_dist
            if probe_dist_m is not None and self._diag_last_probe_dist is not None
            else None
        )
        _log.info(
            "probe poll=%.1fHz miss=%d seq=%s Δseq=%s dist=%.1fm Δdist=%s "
            "probe_raw=%.1fm Δprobe=%s age=%.0fms fresh=%s frozen=%s",
            hz,
            self._diag_poll_miss,
            seq if seq is not None else "?",
            seq_delta if seq_delta is not None else "?",
            dist_m if dist_m is not None else -1.0,
            f"{dist_delta:+.1f}m" if dist_delta is not None else "?",
            probe_dist_m if probe_dist_m is not None else -1.0,
            f"{probe_delta:+.1f}m" if probe_delta is not None else "?",
            age_ms,
            probe_fresh,
            "Y" if motion_frozen else "N",
        )
        self._diag_last_log_t = now
        self._diag_poll_n = 0
        self._diag_poll_miss = 0
        if seq is not None:
            self._diag_last_seq = seq
        if dist_m is not None:
            self._diag_last_dist = dist_m
        if probe_dist_m is not None:
            self._diag_last_probe_dist = probe_dist_m

    def set_planning_hold(self, hold: bool) -> None:
        """Congela distancias de planning (p. ej. autopilot en pausa)."""
        self._planning_hold = hold

    def _ensure_api_client(self, silent: bool = False) -> bool:
        """HTTP API para escritura de mandos (y fallback de lectura)."""
        if self._client is not None:
            if self._reader is None:
                self._reader = FastControlReader(self._client)
                self._reader.setup()
            return True

        client = client_from_key_file()
        if client is None:
            if not silent:
                self.last_probe_info = (
                    "CommAPIKey.txt no encontrado — arranca TSW6 con -HTTPAPI"
                )
            return False

        info = client.get_json("/info")
        if info is None:
            if not silent:
                self.last_probe_info = "TSW6 no responde en localhost:31270"
            return False

        self._client = client
        if self._reader is None:
            self._reader = FastControlReader(client)
            self._reader.setup()

        if self.mode != "ue4ss":
            meta = info.get("Meta") or {}
            self.last_probe_info = (
                f"TSW API v{meta.get('APIVersion', '?')} "
                f"(build {meta.get('GameBuildNumber', '?')})"
            )
        return True

    def _apply_station_filter(
        self,
        stations: list[dict[str, Any]],
        service_name: Optional[str],
    ) -> list[dict[str, Any]]:
        svc = service_name or self._service_name
        if svc and self._hud.available:
            lat = lng = None
            if self._player_geo:
                lat, lng = self._player_geo
            try:
                resolved = self._hud.resolve_service_stops(svc, lat=lat, lng=lng)
            except sqlite3.Error as exc:
                _log.warning("HUD timetable query fallo (svc=%s): %s", svc, exc)
                resolved = None
            if resolved:
                self._hud_match = resolved
                matched = filter_stations_by_stop_names(
                    stations, resolved["stop_names"])
                merged = self._hud.merge_schedule_stations(
                    matched,
                    resolved["entries"],
                    resolved["stop_names"],
                    lat=lat,
                    lng=lng,
                )
                if merged:
                    return merged
        self._hud_match = None
        return filter_stations_by_service(stations, self._timetable, svc)

    def _update_player_geo(self, info: Any) -> None:
        if not isinstance(info, dict):
            return
        geo = info.get("geoLocation") or info.get("playerPosition")
        if not isinstance(geo, dict):
            return
        lat_raw = geo.get("latitude")
        lng_raw = geo.get("longitude")
        if lat_raw is None or lng_raw is None:
            return
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (TypeError, ValueError):
            return
        self._player_geo = (lat, lng)

    def _poll_driver_aid_planning(self) -> dict[str, Any]:
        """DriverAid.Data + TrackData (en hilo aparte) para P1 y paradas."""
        if not self._ensure_api_client(silent=True):
            return {}
        if not self._api_lock.acquire(blocking=True, timeout=2.5):
            return {}
        try:
            client = self._client
            if client is None:
                return {}

            out: dict[str, Any] = {}
            data = client.get_node("DriverAid.Data",
                                   timeout=PLANNING_READ_TIMEOUT)
            if data is not None:
                self._slow["driver_aid"] = data
                out.update(parse_driver_aid_planning(data))

            track = client.get_node("DriverAid.TrackData",
                                    timeout=PLANNING_READ_TIMEOUT)
            if track is not None:
                self._slow["track_data"] = track
                stations = parse_track_data_stations(track)
                if stations:
                    out["stations"] = stations

            info = client.get_node("DriverAid.PlayerInfo",
                                   timeout=PLANNING_READ_TIMEOUT)
            if info is not None:
                self._update_player_geo(info)
                svc = info.get("currentServiceName")
                if svc:
                    out["service_name"] = str(svc).strip()

            if out.get("stations"):
                svc = out.get("service_name") or self._service_name
                out["stations"] = self._apply_station_filter(
                    out["stations"], svc)
            return out
        finally:
            self._api_lock.release()

    def _reset_planning_distances(self, planning: dict[str, Any]) -> None:
        """Sincroniza distancias con un snapshot HTTP de DriverAid."""
        limits = planning.get("speed_limits_ahead")
        if limits:
            limits = _prune_zero_distance_limits([dict(e) for e in limits])
        self._planning_dist = {
            "distance_next_m": planning.get("distance_next_m"),
            "distance_next_2_m": planning.get("distance_next_2_m"),
            "speed_limits_ahead": limits or [],
            "stations": [dict(s) for s in (planning.get("stations") or [])],
        }
        if limits:
            self._planning_dist["distance_next_m"] = limits[0].get("distance_m")
            if len(limits) > 1:
                self._planning_dist["distance_next_2_m"] = limits[1].get("distance_m")
        self._planning_dist_last_t = time.monotonic()

    def _tick_planning_distances(self, speed_mph: float) -> None:
        """Odometría entre lecturas HTTP: dist -= velocidad × Δt."""
        now = time.monotonic()
        if self._planning_dist_last_t <= 0:
            self._planning_dist_last_t = now
            return
        dt = now - self._planning_dist_last_t
        self._planning_dist_last_t = now
        if dt <= 0 or speed_mph < 0.3:
            return
        delta_m = speed_mph * MPH_TO_MS * dt
        for key in ("distance_next_m", "distance_next_2_m"):
            d = self._planning_dist.get(key)
            if d is not None:
                self._planning_dist[key] = max(0.0, float(d) - delta_m)
        for bucket in ("speed_limits_ahead", "stations"):
            for entry in self._planning_dist.get(bucket) or []:
                d = entry.get("distance_m")
                if d is not None:
                    entry["distance_m"] = max(0.0, float(d) - delta_m)

    def _attach_next_stop(self, parsed: dict[str, Any],
                          stations: list[dict[str, Any]]) -> None:
        nxt = select_next_scheduled_stop(stations)
        if nxt is None:
            parsed.pop("next_stop", None)
            parsed.pop("next_stop_name", None)
            parsed.pop("next_stop_distance_m", None)
            return
        parsed["next_stop"] = dict(nxt)
        parsed["next_stop_name"] = nxt.get("name")
        parsed["next_stop_distance_m"] = nxt.get("distance_m")

    def _overlay_planning_distances(self, parsed: dict[str, Any]) -> None:
        """Sustituye distancias del caché por las estimadas en tiempo real."""
        pd = self._planning_dist
        if not pd:
            return
        if not self._planning_hold:
            self._tick_station_distances(float(parsed.get("speed_mph") or 0.0))
        if pd.get("distance_next_m") is not None:
            parsed["distance_next_m"] = pd["distance_next_m"]
        if pd.get("distance_next_2_m") is not None:
            parsed["distance_next_2_m"] = pd["distance_next_2_m"]
        limits = pd.get("speed_limits_ahead") or []
        if limits:
            parsed["speed_limits_ahead"] = [dict(e) for e in limits]
            parsed["next_limit_mph"] = limits[0].get("limit_mph")
            parsed["distance_next_m"] = limits[0].get("distance_m")
            if len(limits) > 1:
                parsed["next_limit_2_mph"] = limits[1].get("limit_mph")
                parsed["distance_next_2_m"] = limits[1].get("distance_m")
        stations = pd.get("stations") or []
        if stations:
            parsed["stations"] = [dict(s) for s in stations]
            self._attach_next_stop(parsed, parsed["stations"])

    def _probe_fresh(self, age_ms: float) -> bool:
        return age_ms <= UE4SS_STALE_S * 1000.0

    def _should_resync_planning(self, source: dict[str, Any],
                                probe_seq: Optional[int] = None) -> bool:
        """True si la distancia del juego cambió (ruta HTTP; probe usa resync directo)."""
        if not self._planning_dist:
            return True
        dist = source.get("distance_next_m")
        if dist is None:
            return False
        prev = self._planning_probe_dist
        if prev is None:
            return True
        return abs(float(dist) - float(prev)) > 0.1

    def _sync_planning_snapshot(self, source: dict[str, Any],
                                probe_seq: Optional[int] = None) -> None:
        self._reset_planning_distances(source)
        if probe_seq is not None:
            self._planning_probe_seq = probe_seq
        dist = source.get("distance_next_m")
        if dist is not None:
            self._planning_probe_dist = float(dist)

    def _odometry_allowed(self, *, speed_mph: float,
                          probe_seq: Optional[int]) -> bool:
        """Odometría solo si hay movimiento y el probe avanzó (no pausa congelada)."""
        if speed_mph < 0.3:
            return False
        if probe_seq is not None:
            if probe_seq == self._planning_odom_seq:
                return False
            self._planning_odom_seq = probe_seq
        return True

    def _advance_probe_seq(self, probe_seq: Optional[int]) -> None:
        if probe_seq is not None:
            self._planning_probe_seq = probe_seq

    def _sync_planning_if_not_frozen_decrease(
        self,
        source: dict[str, Any],
        probe_seq: Optional[int],
        *,
        motion_frozen: bool,
        speed_mph: float,
    ) -> None:
        """Resync desde probe; ignora bajadas si el tren no se mueve."""
        new_dist = source.get("distance_next_m")
        cur_dist = self._planning_dist.get("distance_next_m")
        reject_decrease = motion_frozen or speed_mph < 0.5
        if (
            reject_decrease
            and new_dist is not None
            and cur_dist is not None
            and float(new_dist) < float(cur_dist) - 0.5
        ):
            self._advance_probe_seq(probe_seq)
            dist = source.get("distance_next_m")
            if dist is not None:
                self._planning_probe_dist = float(dist)
            return
        self._sync_planning_snapshot(source, probe_seq)

    def _apply_probe_planning(
        self,
        parsed: dict[str, Any],
        probe_planning: dict[str, Any],
        *,
        probe_seq: Optional[int],
        probe_fresh: bool,
    ) -> None:
        """Distancias desde probe: solo DriverAid (cm→m); sin odometría Python."""
        with self._planning_lock:
            speed = float(parsed.get("speed_mph") or 0.0)
            probe_raw_dist = probe_planning.get("distance_next_m")
            odo_m = parsed.get("odo_m")
            motion_frozen = self._update_probe_motion_frozen(probe_raw_dist, odo_m)
            if self._planning_hold:
                motion_frozen = True
            parsed["probe_motion_frozen"] = motion_frozen
            parsed["planning_hold"] = self._planning_hold
            if probe_raw_dist is not None:
                parsed["probe_dist_limit_m"] = float(probe_raw_dist)

            if self._planning_hold and self._planning_dist:
                self._overlay_planning_distances(parsed)
                return

            seq_changed = (
                probe_seq is not None
                and probe_seq != self._planning_probe_seq
            )

            stations = (
                self._planning_dist.get("stations")
                or self._planning_cache.get("stations")
                or []
            )

            if not self._planning_dist:
                self._sync_planning_snapshot(probe_planning, probe_seq)
            elif seq_changed:
                self._sync_planning_if_not_frozen_decrease(
                    probe_planning,
                    probe_seq,
                    motion_frozen=motion_frozen,
                    speed_mph=speed,
                )

            if stations:
                self._planning_dist["stations"] = [dict(s) for s in stations]
            self._overlay_planning_distances(parsed)

    def _tick_station_distances(self, speed_mph: float) -> None:
        """Odometría solo para estaciones HTTP entre polls (~2 s)."""
        now = time.monotonic()
        if self._station_odom_last_t <= 0:
            self._station_odom_last_t = now
            return
        dt = now - self._station_odom_last_t
        self._station_odom_last_t = now
        if dt <= 0 or speed_mph < 0.3:
            return
        delta_m = speed_mph * MPH_TO_MS * dt
        for entry in self._planning_dist.get("stations") or []:
            d = entry.get("distance_m")
            if d is not None:
                entry["distance_m"] = max(0.0, float(d) - delta_m)

    def _apply_planning_distances(
        self,
        parsed: dict[str, Any],
        *,
        source: Optional[dict[str, Any]] = None,
        probe_seq: Optional[int] = None,
        probe_fresh: bool = True,
        interpolate: bool = False,
    ) -> None:
        """Actualiza distancias de planning (ruta HTTP / fallback sin probe)."""
        with self._planning_lock:
            if self._planning_hold and self._planning_dist:
                self._overlay_planning_distances(parsed)
                return
            if interpolate and probe_fresh:
                speed = float(parsed.get("speed_mph") or 0.0)
                if self._odometry_allowed(speed_mph=speed, probe_seq=probe_seq):
                    self._tick_planning_distances(speed)

            if source and self._should_resync_planning(source, probe_seq):
                self._sync_planning_snapshot(source, probe_seq)
            elif not self._planning_dist and (
                    parsed.get("distance_next_m") is not None
                    or parsed.get("speed_limits_ahead")):
                self._sync_planning_snapshot(parsed)

            self._overlay_planning_distances(parsed)

    def _merge_planning(self, parsed: dict[str, Any],
                        planning: dict[str, Any],
                        probe_gradient: Optional[float] = None) -> None:
        """Fusiona planning HTTP; el gradiente del probe tiene prioridad."""
        if probe_gradient is not None:
            planning = {k: v for k, v in planning.items() if k != "gradient_pct"}
        for key, val in planning.items():
            if val is not None:
                parsed[key] = val
        svc = planning.get("service_name")
        if svc:
            self._service_name = str(svc)
        stations = parsed.get("stations")
        if stations:
            filtered = self._apply_station_filter(
                list(stations), self._service_name)
            parsed["stations"] = filtered
            self._attach_schedule_meta(parsed)
            self._attach_next_stop(parsed, filtered)

    def _attach_schedule_meta(self, parsed: dict[str, Any]) -> None:
        if self._hud_match:
            parsed["schedule_source"] = "hud_db"
            parsed["hud_timetable_id"] = self._hud_match.get("timetable_id")
            route = self._hud_match.get("route_name")
            if route:
                parsed["hud_route_name"] = route
        elif self._timetable:
            parsed["schedule_source"] = "timetable_json"
        else:
            parsed["schedule_source"] = "trackdata"

    def _poll_slow(self) -> None:
        if self._client is None:
            return
        for name, path in _SLOW_READS.items():
            node = self._client.get_node(path)
            if node is not None:
                self._slow[name] = node

    def _poll_ue4ss(self, snap: Optional[ProbeSnapshot] = None) -> None:
        if snap is None:
            snap = self._read_ue4ss_snapshot()
        if snap is None:
            self._maybe_diag_log(None)
            return

        self._poll_tick += 1
        probe_planning = snap.planning_dict()
        if probe_planning:
            self._kick_planning_refresh(stations_only=True)
        elif self._poll_tick == 1 or self._poll_tick % SLOW_EVERY == 0:
            self._kick_planning_refresh()
        planning = self._get_cached_planning()
        if probe_planning:
            for key in (
                "speed_limits_ahead",
                "next_limit_mph",
                "distance_next_m",
                "next_limit_2_mph",
                "distance_next_2_m",
            ):
                if key in probe_planning:
                    planning[key] = probe_planning[key]

        age_ms = 0.0
        try:
            age_ms = max(0.0, (time.time() - self._ue4ss_path.stat().st_mtime) * 1000.0)
        except OSError:
            pass
        probe_fresh = self._probe_fresh(age_ms)

        parsed = _telem_from_probe(
            snap,
            age_ms=age_ms,
            gradient_fallback=planning.get("gradient_pct")
            if snap.gradient_pct is None else None,
        )
        parsed["probe_seq"] = snap.seq
        if snap.odo_m is not None:
            parsed["odo_m"] = float(snap.odo_m)
        self._merge_planning(parsed, planning, probe_gradient=snap.gradient_pct)

        has_probe_dist = bool(probe_planning)
        if has_probe_dist:
            self._apply_probe_planning(
                parsed,
                probe_planning,
                probe_seq=snap.seq,
                probe_fresh=probe_fresh,
            )
        elif planning.get("distance_next_m") or self._planning_dist:
            self._apply_planning_distances(
                parsed,
                source=planning,
                probe_seq=snap.seq,
                probe_fresh=probe_fresh,
                interpolate=probe_fresh,
            )
        probe_raw_m = (
            snap.dist_limit_cm / 100.0 if snap.dist_limit_cm is not None else None
        )
        self._maybe_diag_log(
            snap,
            dist_m=parsed.get("distance_next_m"),
            probe_dist_m=probe_raw_m,
            age_ms=age_ms,
            probe_fresh=probe_fresh,
            motion_frozen=bool(parsed.get("probe_motion_frozen")),
        )
        if snap.vehicle and snap.vehicle != "?":
            self._vehicle_name = snap.vehicle

        with self._telem_lock:
            self._telem.update(parsed)

    def _poll(self) -> None:
        if self._reader is None:
            return

        self._poll_tick += 1
        slow_tick = self._poll_tick == 1 or self._poll_tick % SLOW_EVERY == 0
        if slow_tick:
            self._poll_slow()

        snap = self._reader.read()
        if snap.speed_ms is None:
            return

        parsed: dict[str, Any] = {
            "speed_mph": snap.speed_ms * MS_TO_MPH,
            "accel_mps2": snap.accel_ms2,
            "handle_notch": _power_to_handle_notch(snap.power, snap.power_negative),
            "supervision": "csm",
            "ack_required": False,
            "gradient_pct": 0.0,
            "rain_intensity": 0.0,
            "telemetry_source": snap.source,
            "telemetry_age_ms": snap.age_ms,
        }

        if snap.train_brake is not None:
            parsed["train_brake_value"] = float(snap.train_brake)

        max_node = self._slow.get("max_speed") or {}
        if max_node.get("IsActive") and max_node.get("MaxSpeed (ms)") is not None:
            parsed["limit_mph"] = float(max_node["MaxSpeed (ms)"]) * MS_TO_MPH

        loco = self._slow.get("loco_brake") or {}
        if loco.get("HandlePosition") is not None:
            parsed["ind_brake_value"] = float(loco["HandlePosition"])
            parsed["ind_brake_active"] = bool(loco.get("IsActive", False))

        dyn = self._slow.get("dyn_brake") or {}
        if dyn.get("HandlePosition") is not None:
            parsed["dyn_brake_value"] = float(dyn["HandlePosition"])
            parsed["dyn_brake_active"] = bool(dyn.get("IsActive", False))

        obj = self._slow.get("object_class") or {}
        if obj.get("ObjectClass"):
            self._vehicle_name = str(obj["ObjectClass"])

        planning: dict[str, Any] = {}
        da = self._slow.get("driver_aid")
        if da:
            planning.update(parse_driver_aid_planning(da))
        td = self._slow.get("track_data")
        if td:
            stations = parse_track_data_stations(td)
            if stations:
                planning["stations"] = self._apply_station_filter(
                    stations, self._service_name)
        if slow_tick and planning:
            planning_source = planning
        else:
            planning_source = None
        self._merge_planning(parsed, planning)
        self._apply_planning_distances(
            parsed,
            source=planning_source,
            probe_fresh=True,
            interpolate=True,
        )

        with self._telem_lock:
            self._telem.update(parsed)

    def get_telemetry(self) -> dict[str, Any]:
        """Último snapshot (refresca según fuente activa)."""
        if self.mode == "manual":
            return {}
        if self.mode == "searching":
            return {}

        if self.mode == "ue4ss":
            self._poll_ue4ss()
            # Si el probe deja de actualizar, intentar HTTPAPI una vez.
            if not self._telem and self._ensure_api_client(silent=True):
                self.mode = "tsw_api"
                self._poll()
        else:
            self._poll()

        with self._telem_lock:
            out = dict(self._telem)
        vehicle = self.get_vehicle_name()
        layout = detect_control_layout(vehicle)
        out["vehicle_name"] = vehicle
        out["control_layout"] = layout
        out["distance_units"] = infer_distance_units(vehicle, layout)
        stations = out.get("stations")
        if stations:
            self._attach_next_stop(out, stations)
        return out

    def has_ipc_control(self) -> bool:
        """True si el probe UE4SS está conectado (SendCommand.txt disponible)."""
        return self.mode == "ue4ss"

    def has_control_api(self) -> bool:
        """True si hay canal de escritura (IPC Lua o HTTPAPI)."""
        if self.has_ipc_control():
            return True
        now = time.monotonic()
        if self._api_ok_cache is not None and now - self._api_ok_ts < 10.0:
            return self._api_ok_cache
        self._api_ok_cache = self._ensure_api_client(silent=True)
        self._api_ok_ts = now
        return self._api_ok_cache

    def control_channel(self) -> str:
        """Canal activo para mandos: ipc, http o none."""
        if self.has_ipc_control():
            return "ipc"
        if self._ensure_api_client(silent=True):
            return "http"
        return "none"

    def arm_ipc_controls(self) -> None:
        """Habilita flag Lua y purga archivos huérfanos previos."""
        purge_lua_commands()
        if self.has_ipc_control():
            enable_lua_commands()

    def purge_ipc_on_start(self) -> None:
        """Limpia IPC huérfano al arrancar autopilot."""
        purge_lua_commands()

    def release_controls(self) -> None:
        """Neutro + purga IPC al cerrar autopilot."""
        if self.has_ipc_control():
            release_controls()

    def _kick_planning_refresh(self, stations_only: bool = False) -> None:
        """Actualiza DriverAid en segundo plano (no bloquea el bucle de control)."""
        now = time.monotonic()
        if now - self._planning_last_kick < PLANNING_MIN_INTERVAL_S:
            return
        if stations_only and self._planning_cache.get("stations"):
            return
        if not self._ensure_api_client(silent=True):
            return
        if self._planning_refreshing:
            return
        self._planning_last_kick = now
        self._planning_refreshing = True

        def _work() -> None:
            try:
                result = self._poll_driver_aid_planning()
                with self._planning_lock:
                    self._planning_cache = result
                    if result and self.mode != "ue4ss":
                        self._reset_planning_distances(result)
            finally:
                self._planning_refreshing = False

        threading.Thread(target=_work, daemon=True, name="tsw-planning").start()

    def _get_cached_planning(self) -> dict[str, Any]:
        with self._planning_lock:
            return dict(self._planning_cache)

    def get_vehicle_name(self) -> Optional[str]:
        return self._vehicle_name

    def set_control_value(self, control: str, val: float) -> bool:
        """Escritura de mandos vía IPC Lua (preferido) o HTTPAPI."""
        name = str(control or "").strip()

        if self.has_ipc_control():
            if name == "PowerBrakeHandle":
                result = dispatch_ipc_combined_notch(
                    combined_value_to_notch(val))
            else:
                result = dispatch_ipc_brake(name, val)
            if result.get("ok"):
                return True
            _log.debug("set_control_value IPC falló: %s", result)

        if not self._ensure_api_client(silent=True):
            return False
        if not self._api_lock.acquire(blocking=False):
            _log.debug("set_control_value: API ocupada, reintentar próximo ciclo")
            return False
        try:
            client = self._client
            if client is None:
                return False
            if name == "PowerBrakeHandle":
                notch = combined_value_to_notch(val)
                result = dispatch_combined_notch(
                    client, notch, timeout=CONTROL_API_TIMEOUT)
            else:
                result = dispatch_brake(
                    client, name, val, timeout=CONTROL_API_TIMEOUT)
            ok = bool(result.get("ok"))
            if not ok:
                _log.debug("set_control_value HTTP falló: %s", result)
            return ok
        finally:
            self._api_lock.release()


# Alias para migración gradual de imports
TswConnection = TswTelemetrySource
