#!/usr/bin/env python3
"""
tsw_telemetry_source.py — Telemetría TSW (UE4SS in-process + HTTPAPI fallback).

Fuentes (prioridad)
-------------------
1. **UE4SS probe** (~17–20 Hz): ``GetData.txt`` — velocidad, mandos, límites, puertas.
2. **HTTPAPI** (fallback / planning lento): DriverAid, estaciones HUD, puertas si el probe
   no las expone.

Puertas
-------
- ``doors_telem``: estado físico ``PassengerDoor_*`` (probe o HTTPAPI).
- ``doors_dmi``: mensajes DMI ``dmi-doors-open/closed`` (solo informativo).
- La FSM de estación prioriza ``doors_telem`` sobre DMI.

Planning de distancias
----------------------
- **Límites** (probe): resync si ``dist_limit`` cambia; si el cm está plano y el tren
  se mueve (C.3a), odometría Python como las estaciones (``probe_stale``).
- **Límites** (HTTP): ``_tick_planning_distances`` entre polls.
- **Estaciones** (HTTP): ``_tick_station_distances`` solo en overlay (no duplicar con límites).

Escritura de mandos: ``SendCommand.txt`` (IPC Lua) o ``tsw_command_bus`` (HTTP).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from tsw6.learning.control_layout import detect_control_layout
from tsw6.autopilot.distance_format import infer_distance_units
from tsw6.telemetry.driver_aid_parser import (
    filter_stations_by_service,
    filter_stations_by_stop_names,
    load_service_timetable,
    parse_driver_aid_planning,
    parse_gradient_pct,
    parse_passenger_door_api,
    parse_track_data_stations,
    resolve_display_next_stop,
    _prune_zero_distance_limits,
)
from tsw6.hud.hud_timetable import HudTimetableStore, schedule_times_for_station
from tsw6.telemetry.tsw_api_client import TswApiClient, client_from_key_file
from tsw6.telemetry.tsw_command_bus import combined_value_to_notch
from tsw6.telemetry.tsw_ipc_bus import (
    dispatch_ipc_brake,
    dispatch_ipc_combined_notch,
    enable_lua_commands,
    purge_lua_commands,
    release_controls,
)
from tsw6.telemetry.tsw_fast_telemetry import FastControlReader
from tsw6.telemetry.control_channel import (
    AsyncCommandWriter,
    CommandState,
    TelemetryReader,
    DEFAULT_TELEM_HZ,
)
from tsw6.telemetry.channel_diagnostics import (
    channel_stats_from_state,
    probe_mod_flags,
    probe_mod_label,
)
from tsw6.telemetry.tsw_ue4ss_reader import (
    ProbeSnapshot,
    default_getdata_path,
    power_to_combined_notch,
    read_probe_file,
)

_log = logging.getLogger("tsw.telemetry")

DRIVABLE = "CurrentDrivableActor"
MS_TO_MPH = 2.236936
MPH_TO_MS = 0.44704
# Probe «plano»: DriverAid no bajó el cartel (sesión 2495.8 m fija).
PROBE_LIMIT_FLAT_M = 0.5
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

_DOOR_API_PATHS: tuple[str, ...] = (
    f"{DRIVABLE}/PassengerDoor_FL.Function.GetCurrentInputValue",
    f"{DRIVABLE}/PassengerDoor_FR.Function.GetCurrentInputValue",
    f"{DRIVABLE}/PassengerDoor_FL.Function.GetCurrentOutputValue",
    f"{DRIVABLE}/PassengerDoor_FR.Function.GetCurrentOutputValue",
    f"{DRIVABLE}/PassengerDoor_BL.Function.GetCurrentInputValue",
    f"{DRIVABLE}/PassengerDoor_BR.Function.GetCurrentInputValue",
    "CurrentFormation/0/Door_PassengerDoor_FL.Function.GetCurrentOutputValue",
    "CurrentFormation/0/Door_PassengerDoor_FR.Function.GetCurrentOutputValue",
    "CurrentFormation/1/Door_PassengerDoor_FL.Function.GetCurrentOutputValue",
    "CurrentFormation/1/Door_PassengerDoor_FR.Function.GetCurrentOutputValue",
    "CurrentFormation/1/Door_PassengerDoor_BL.Function.GetCurrentOutputValue",
    "CurrentFormation/1/Door_PassengerDoor_BR.Function.GetCurrentOutputValue",
)


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


def _fetch_door_telemetry(
    client: TswApiClient,
    timeout: float,
) -> Optional[bool]:
    """Puertas físicas vía HTTPAPI (PassengerDoor_*)."""
    nodes = [client.get_node(path, timeout=timeout) for path in _DOOR_API_PATHS]
    return parse_passenger_door_api(*nodes)


def _attach_probe_doors(parsed: dict[str, Any], snap: ProbeSnapshot) -> None:
    """Copia puertas del probe; ``doors_open`` lo resuelve ``_apply_door_state``."""
    if snap.doors_telem is not None:
        parsed["doors_telem"] = bool(snap.doors_telem)
    elif snap.doors_open is not None:
        parsed["doors_telem"] = bool(snap.doors_open)
    if snap.doors_dmi is not None:
        parsed["doors_dmi"] = bool(snap.doors_dmi)


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
    if snap.brake_cyl_bar is not None:
        parsed["brake_cyl_bar"] = float(snap.brake_cyl_bar)
    if snap.lever_notch is not None:
        parsed["lever_notch"] = int(snap.lever_notch)
    if snap.handle_notch is not None:
        parsed["hud_notch"] = int(snap.handle_notch)
    if snap.last_cmd_id is not None:
        parsed["last_cmd_id"] = int(snap.last_cmd_id)
    if snap.last_ack_ok is not None:
        parsed["last_ack_ok"] = bool(snap.last_ack_ok)
    _attach_probe_doors(parsed, snap)

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
        self._diag_last_log_t = 0.0
        self._diag_poll_n = 0
        self._diag_poll_miss = 0
        self._diag_last_seq: Optional[int] = None
        self._diag_last_dist: Optional[float] = None
        self._diag_last_probe_dist: Optional[float] = None
        self._motion_last_probe_dist: Optional[float] = None
        self._motion_probe_dist_since = 0.0
        self._motion_last_speed_ms: Optional[float] = None
        self._motion_speed_since = 0.0
        self._motion_last_odo_m: Optional[float] = None
        self._motion_odo_since = 0.0
        self._motion_frozen = False
        self._planning_hold = False
        self._api_lock = threading.Lock()
        self._timetable = load_service_timetable()
        self._hud = HudTimetableStore()
        self._hud_match: Optional[dict[str, Any]] = None
        self._doors_telem: Optional[bool] = None
        self._doors_dmi: Optional[bool] = None
        self._player_geo: Optional[tuple[float, float]] = None
        self._service_name: Optional[str] = None
        self._station_exclude_bases: set[str] = set()
        self._api_ok_cache: Optional[bool] = None
        self._api_ok_ts = 0.0
        self._driver_input_dead = False
        self._telem_reader: Optional[TelemetryReader] = None
        self._cmd_writer: Optional[AsyncCommandWriter] = None

    def probe_getdata_fresh(self) -> bool:
        """True si GetData.txt existe y se actualizó hace poco (F7 activo)."""
        return _ue4ss_is_fresh(self._ue4ss_path)

    def maybe_upgrade_to_ue4ss(self) -> bool:
        """Pasa de ``tsw_api``/``searching`` a ``ue4ss`` si el probe está activo."""
        if self.mode in ("ue4ss", "manual"):
            return False
        prev = self.mode
        if not self.try_connect_ue4ss():
            return False
        return prev != "ue4ss"

    def probe_status(self) -> dict[str, Any]:
        """Estado del probe para GUI (F7 / GetData.txt)."""
        fresh = self.probe_getdata_fresh()
        if self.mode == "ue4ss":
            return {"live": True, "fresh": fresh, "hint": "PROBE OK (F7)"}
        if fresh:
            return {
                "live": False,
                "fresh": True,
                "hint": "GetData activo — reconectando…",
            }
        if self.mode == "tsw_api":
            return {
                "live": False,
                "fresh": False,
                "hint": "HTTP ~2s — pulsa F7 en cabina",
            }
        if not self._ue4ss_path.is_file():
            return {
                "live": False,
                "fresh": False,
                "hint": "Sin GetData.txt — install_ue4ss_probe.bat",
            }
        return {"live": False, "fresh": False, "hint": "F7 OFF en cabina"}

    def try_connect_ue4ss(self) -> bool:
        """Conecta por GetData.txt sin intentar HTTP (barato para 10 Hz)."""
        if self.mode == "ue4ss":
            return True
        snap = self._read_ue4ss_snapshot()
        if snap is None:
            return False
        self.mode = "ue4ss"
        self.last_probe_info = f"UE4SS probe ({self._ue4ss_path})"
        self._ensure_telem_reader()
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

    def _ensure_telem_reader(self) -> TelemetryReader:
        if self._telem_reader is None:
            self._telem_reader = TelemetryReader(
                self._ue4ss_path, hz=DEFAULT_TELEM_HZ)
            self._telem_reader.start()
        return self._telem_reader

    def _ensure_cmd_writer(self) -> AsyncCommandWriter:
        if self._cmd_writer is None:
            self._cmd_writer = AsyncCommandWriter(
                on_ipc_fail=lambda err: self._mark_driver_input_dead(f"IPC {err}"),
            )
            self._cmd_writer.start()
        return self._cmd_writer

    def telem_poll_hz(self) -> float:
        if self._telem_reader is not None:
            return self._telem_reader.poll_hz()
        return 0.0

    def command_state(self) -> CommandState:
        if self._cmd_writer is not None:
            return self._cmd_writer.state()
        return CommandState()

    def channel_report(self) -> dict[str, Any]:
        """Estadísticas IPC + mod probe para logs de autopilot."""
        flags = probe_mod_flags(self._telem)
        if self._cmd_writer is not None:
            st, acks, enqueued = self._cmd_writer.session_stats()
            stats = channel_stats_from_state(st, acks)
            stats["enqueued"] = enqueued
        else:
            stats = channel_stats_from_state(CommandState(), [])
            stats["enqueued"] = 0
        return {
            "getdata": str(self._ue4ss_path),
            "mod": probe_mod_label(flags),
            "mod_flags": flags,
            "telem_poll_hz": self.telem_poll_hz(),
            **stats,
        }

    def enqueue_control_value(self, control: str, val: float) -> bool:
        """Encola mando IPC sin bloquear el bucle de control."""
        if not self.has_ipc_control():
            return self.set_control_value(control, val)
        cmd_id = self._ensure_cmd_writer().enqueue_control(control, val)
        return cmd_id > 0

    def shutdown_channels(self) -> None:
        if self._cmd_writer is not None:
            self._cmd_writer.stop()
            self._cmd_writer = None
        if self._telem_reader is not None:
            self._telem_reader.stop()
            self._telem_reader = None

    def _read_ue4ss_snapshot(self) -> Optional[ProbeSnapshot]:
        if self._telem_reader is not None:
            snap, _ = self._telem_reader.get_snapshot()
            if snap is not None:
                return snap
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

    def _update_probe_motion_frozen(
        self,
        probe_dist_m: Optional[float],
        odo_m: Optional[float] = None,
        speed_ms: Optional[float] = None,
    ) -> bool:
        """True si el tren no avanza (odómetro o velocidad; no dist. al límite)."""
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
        elif speed_ms is not None:
            if self._motion_last_speed_ms is None:
                self._motion_last_speed_ms = speed_ms
                self._motion_speed_since = now
                self._motion_frozen = False
            elif abs(speed_ms - self._motion_last_speed_ms) > 0.08:
                self._motion_last_speed_ms = speed_ms
                self._motion_speed_since = now
                self._motion_frozen = False
            else:
                self._motion_frozen = (
                    speed_ms > 0.5
                    and (now - self._motion_speed_since) > 0.35
                )
        elif probe_dist_m is None:
            self._motion_frozen = False
        else:
            # dist_limit al cartel: no usar para detectar pausa del juego
            self._motion_frozen = False

        if self._motion_frozen != prev:
            _log.info(
                "juego %s  probe_dist=%s  odo_m=%s  speed_ms=%s",
                "CONGELADO" if self._motion_frozen else "EN MOVIMIENTO",
                f"{probe_dist_m:.1f}m" if probe_dist_m is not None else "—",
                f"{odo_m:.1f}" if odo_m is not None else "—",
                f"{speed_ms:.2f}" if speed_ms is not None else "—",
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
            doors = _fetch_door_telemetry(client, PLANNING_READ_TIMEOUT)
            if doors is not None:
                out["doors_telem"] = doors
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
        for entry in self._planning_dist.get("speed_limits_ahead") or []:
            d = entry.get("distance_m")
            if d is not None:
                entry["distance_m"] = max(0.0, float(d) - delta_m)
        self._refresh_speed_limit_heads()

    def _refresh_speed_limit_heads(self) -> None:
        """Tras odometría: quitar cartel ya pasado y subir el 2.º de Lua."""
        limits = _prune_zero_distance_limits(
            [dict(e) for e in (self._planning_dist.get("speed_limits_ahead") or [])]
        )
        self._planning_dist["speed_limits_ahead"] = limits
        if not limits:
            self._planning_dist["distance_next_m"] = None
            self._planning_dist["distance_next_2_m"] = None
            return
        self._planning_dist["distance_next_m"] = limits[0].get("distance_m")
        self._planning_dist["distance_next_2_m"] = (
            limits[1].get("distance_m") if len(limits) > 1 else None
        )

    def _merge_probe_second_limit(self, probe_planning: dict[str, Any]) -> None:
        """El cm del 1.er cartel está plano; igual hay 2.º en GetData."""
        lim2 = probe_planning.get("next_limit_2_mph")
        d2 = probe_planning.get("distance_next_2_m")
        if lim2 is None or d2 is None or float(d2) <= 8.0:
            return
        limits = self._planning_dist.get("speed_limits_ahead") or []
        entry = {"limit_mph": float(lim2), "distance_m": float(d2)}
        if len(limits) < 2:
            limits.append(entry)
        else:
            limits[1] = entry
        self._planning_dist["speed_limits_ahead"] = limits
        self._refresh_speed_limit_heads()

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

    def set_station_exclude_bases(self, bases: Optional[set[str]]) -> None:
        """Paradas ya servidas (FSM) — no mostrar como próxima en telemetría."""
        self._station_exclude_bases = set(bases or set())

    def hud_schedule_context(
        self,
    ) -> tuple[Optional[list], Optional[list[str]]]:
        if not self._hud_match:
            return None, None
        return (
            self._hud_match.get("entries"),
            self._hud_match.get("stop_names"),
        )

    def _attach_next_stop(self, parsed: dict[str, Any],
                          stations: list[dict[str, Any]]) -> None:
        hud_names = None
        if self._hud_match:
            hud_names = self._hud_match.get("stop_names")
        nxt = resolve_display_next_stop(
            stations,
            exclude_bases=self._station_exclude_bases,
            hud_stop_names=hud_names,
        )
        if nxt is None:
            for key in (
                "next_stop",
                "next_stop_name",
                "next_stop_distance_m",
                "next_stop_arrival",
                "next_stop_departure",
            ):
                parsed.pop(key, None)
            return
        parsed["next_stop"] = dict(nxt)
        parsed["next_stop_name"] = nxt.get("name")
        parsed["next_stop_distance_m"] = nxt.get("distance_m")
        arr = nxt.get("arrival")
        dep = nxt.get("departure")
        if arr is None or dep is None:
            if self._hud_match:
                entries = self._hud_match.get("entries") or []
                name = str(nxt.get("name") or "")
                eta_arr, eta_dep = schedule_times_for_station(entries, name)
                arr = arr or eta_arr
                dep = dep or eta_dep
        if arr:
            parsed["next_stop_arrival"] = arr
        else:
            parsed.pop("next_stop_arrival", None)
        if dep:
            parsed["next_stop_departure"] = dep
        else:
            parsed.pop("next_stop_departure", None)

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

    def _should_resync_planning(self, source: dict[str, Any]) -> bool:
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

    def _probe_limit_flat(self, new_dist: Optional[float]) -> bool:
        """True si el cm del cartel no se ha movido vs último raw (no vs odo)."""
        last_raw = self._planning_probe_dist
        if new_dist is None or last_raw is None:
            return False
        return abs(float(new_dist) - float(last_raw)) <= PROBE_LIMIT_FLAT_M

    def _apply_probe_planning(
        self,
        parsed: dict[str, Any],
        probe_planning: dict[str, Any],
        *,
        probe_seq: Optional[int],
    ) -> None:
        """Límites: cm DriverAid si cambian; odo Python si el probe está plano (C.3a)."""
        with self._planning_lock:
            speed = float(parsed.get("speed_mph") or 0.0)
            probe_raw_dist = probe_planning.get("distance_next_m")
            odo_m = parsed.get("odo_m")
            speed_ms = parsed.get("speed_ms")
            motion_frozen = self._update_probe_motion_frozen(
                probe_raw_dist, odo_m, speed_ms)
            if self._planning_hold:
                motion_frozen = True
            parsed["probe_motion_frozen"] = motion_frozen
            parsed["planning_hold"] = self._planning_hold
            probe_stale = False
            if probe_raw_dist is not None:
                parsed["probe_dist_limit_m"] = float(probe_raw_dist)

            if self._planning_hold and self._planning_dist:
                parsed["probe_stale"] = False
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
                moving = (not motion_frozen) and speed >= 0.3
                parked = (not moving) and speed < 0.5
                if (
                    moving
                    and probe_raw_dist is not None
                    and self._probe_limit_flat(probe_raw_dist)
                ):
                    self._advance_probe_seq(probe_seq)
                    self._planning_probe_dist = float(probe_raw_dist)
                    self._tick_planning_distances(speed)
                    self._merge_probe_second_limit(probe_planning)
                    probe_stale = True
                elif parked and self._planning_dist.get("distance_next_m") is not None:
                    # C.3d: parado — no volver a 2495 m del probe.
                    self._advance_probe_seq(probe_seq)
                    if probe_raw_dist is not None:
                        self._planning_probe_dist = float(probe_raw_dist)
                    probe_stale = True
                else:
                    self._sync_planning_if_not_frozen_decrease(
                        probe_planning,
                        probe_seq,
                        motion_frozen=motion_frozen,
                        speed_mph=speed,
                    )

            parsed["probe_stale"] = probe_stale
            if stations:
                self._planning_dist["stations"] = [dict(s) for s in stations]
            self._overlay_planning_distances(parsed)

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

            if source and self._should_resync_planning(source):
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

    def _apply_door_state(self, parsed: dict[str, Any]) -> None:
        """Mantiene último estado; abierto si telemetría o DMI lo confirman."""
        if parsed.get("doors_telem") is not None:
            self._doors_telem = bool(parsed["doors_telem"])
        if parsed.get("doors_dmi") is not None:
            self._doors_dmi = parsed.get("doors_dmi")

        parsed["doors_telem"] = self._doors_telem
        parsed["doors_dmi"] = self._doors_dmi
        if self._doors_telem is True or self._doors_dmi is True:
            parsed["doors_open"] = True
        elif self._doors_telem is False and self._doors_dmi is False:
            parsed["doors_open"] = False
        elif self._doors_telem is not None:
            parsed["doors_open"] = bool(self._doors_telem)
        elif self._doors_dmi is not None:
            parsed["doors_open"] = bool(self._doors_dmi)
        else:
            parsed["doors_open"] = False

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
        if not self._api_lock.acquire(blocking=False):
            return
        try:
            client = self._client
            if client is None:
                return
            for name, path in _SLOW_READS.items():
                node = client.get_node(path)
                if node is not None:
                    self._slow[name] = node
            doors = _fetch_door_telemetry(client, CONTROL_API_TIMEOUT)
            if doors is not None:
                self._slow["doors_telem"] = doors
        finally:
            self._api_lock.release()

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
        if self._telem_reader is not None:
            _, age_ms = self._telem_reader.get_snapshot()
        else:
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
        if parsed.get("doors_telem") is None and planning.get("doors_telem") is not None:
            parsed["doors_telem"] = bool(planning["doors_telem"])

        has_probe_dist = bool(probe_planning)
        if has_probe_dist:
            self._apply_probe_planning(
                parsed,
                probe_planning,
                probe_seq=snap.seq,
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

        self._apply_door_state(parsed)
        poll_hz = self.telem_poll_hz()
        if poll_hz > 0:
            parsed["telem_poll_hz"] = poll_hz
        if self._cmd_writer is not None:
            self._cmd_writer.update_telem_correlation(
                snap.last_cmd_id,
                snap.last_ack_ok,
                snap.lever_notch,
            )
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
        doors_telem = self._slow.get("doors_telem")
        if doors_telem is not None:
            parsed["doors_telem"] = bool(doors_telem)
        self._merge_planning(parsed, planning)
        self._apply_planning_distances(
            parsed,
            source=planning_source,
            probe_fresh=True,
            interpolate=True,
        )
        self._apply_door_state(parsed)

        with self._telem_lock:
            self._telem.update(parsed)

    def get_telemetry(self) -> dict[str, Any]:
        """Último snapshot (refresca según fuente activa)."""
        if self.mode == "manual":
            return {}
        if self.mode == "searching":
            return {}

        if self.mode == "tsw_api":
            self.maybe_upgrade_to_ue4ss()

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
        """True si hay canal de escritura de palanca (solo IPC Lua)."""
        return self.has_ipc_control()

    def control_channel(self) -> str:
        """Canal activo para mandos: ipc o none (HTTP no se usa para palanca)."""
        if self.has_ipc_control():
            return "ipc"
        return "none"

    def prefer_keyboard_actuator(self) -> bool:
        """True si Lua no mueve la palanca — usar teclas A/D (SendInput)."""
        return self._driver_input_dead

    def _mark_driver_input_dead(self, reason: str) -> None:
        if self._driver_input_dead:
            return
        self._driver_input_dead = True
        _log.warning(
            "Lua no mueve palanca (%s) — mandos vía teclado A/D (TSW en primer plano)",
            reason,
        )

    def arm_ipc_controls(self) -> None:
        """Habilita flag Lua, arranca escritor async y purga archivos huérfanos."""
        purge_lua_commands()
        if self.has_ipc_control():
            enable_lua_commands()
            self._ensure_cmd_writer()

    def purge_ipc_on_start(self) -> None:
        """Limpia IPC huérfano al arrancar autopilot."""
        purge_lua_commands()

    def release_controls(self) -> None:
        """Neutro + purga IPC al cerrar autopilot."""
        self.shutdown_channels()
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
        """Escritura de mandos solo vía IPC Lua. Sin HTTP."""
        name = str(control or "").strip()
        if not self.has_ipc_control():
            return False
        if name == "PowerBrakeHandle":
            result = dispatch_ipc_combined_notch(
                combined_value_to_notch(val))
        else:
            result = dispatch_ipc_brake(name, val)
        if result.get("ok"):
            return True
        err = str(result.get("error") or "?")
        if err == "ack_timeout":
            _log.debug(
                "IPC mandos sin ack (%s) %s=%.3f — %s",
                err, name, val, result.get("ack") or result)
        else:
            _log.warning(
                "IPC mandos falló (%s) %s=%.3f — %s",
                err, name, val, result.get("ack") or result)
            self._mark_driver_input_dead(f"IPC {err}")
        return False


# Alias para migración gradual de imports
TswConnection = TswTelemetrySource
