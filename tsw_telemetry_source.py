#!/usr/bin/env python3
"""
tsw_telemetry_source.py — Telemetría TSW (UE4SS in-process + HTTPAPI fallback).

Lectura preferente vía ``TelemetryProbeMod`` (~17–20 Hz, ``GetData.txt``).
Escritura de mandos vía ``tsw_command_bus`` (HTTP API, requiere ``-HTTPAPI``).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from control_layout import detect_control_layout
from driver_aid_parser import (
    parse_driver_aid_planning,
    parse_gradient_pct,
    parse_track_data_stations,
)
from tsw_api_client import TswApiClient, client_from_key_file
from tsw_command_bus import combined_value_to_notch, dispatch_brake, dispatch_combined_notch
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
SLOW_EVERY = 30
PLANNING_MIN_INTERVAL_S = 4.0
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
        self._api_lock = threading.Lock()
        self._api_ok_cache: Optional[bool] = None
        self._api_ok_ts = 0.0

    def probe(self) -> str:
        """Detecta UE4SS (GetData.txt) o HTTPAPI."""
        ue4ss_snap = self._read_ue4ss_snapshot()
        if ue4ss_snap is not None:
            self.mode = "ue4ss"
            self.last_probe_info = f"UE4SS probe ({self._ue4ss_path})"
            self._poll_ue4ss(ue4ss_snap)
            self._ensure_api_client(silent=True)
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
        if not _ue4ss_is_fresh(path):
            return None
        snap = read_probe_file(path)
        if snap is None or snap.speed_ms is None:
            return None
        return snap

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
            return out
        finally:
            self._api_lock.release()

    def _merge_planning(self, parsed: dict[str, Any],
                        planning: dict[str, Any],
                        probe_gradient: Optional[float] = None) -> None:
        """Fusiona planning HTTP; el gradiente del probe tiene prioridad."""
        if probe_gradient is not None:
            planning = {k: v for k, v in planning.items() if k != "gradient_pct"}
        for key, val in planning.items():
            if val is not None:
                parsed[key] = val

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
            return

        self._poll_tick += 1
        if self._poll_tick == 1 or self._poll_tick % SLOW_EVERY == 0:
            self._kick_planning_refresh()
        planning = self._get_cached_planning()

        age_ms = 0.0
        try:
            age_ms = max(0.0, (time.time() - self._ue4ss_path.stat().st_mtime) * 1000.0)
        except OSError:
            pass

        parsed = _telem_from_probe(
            snap,
            age_ms=age_ms,
            gradient_fallback=planning.get("gradient_pct")
            if snap.gradient_pct is None else None,
        )
        self._merge_planning(parsed, planning, probe_gradient=snap.gradient_pct)
        if snap.vehicle and snap.vehicle != "?":
            self._vehicle_name = snap.vehicle

        with self._telem_lock:
            self._telem.update(parsed)

    def _poll(self) -> None:
        if self._reader is None:
            return

        self._poll_tick += 1
        if self._poll_tick == 1 or self._poll_tick % SLOW_EVERY == 0:
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
                planning["stations"] = stations
        self._merge_planning(parsed, planning)

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
        out["vehicle_name"] = vehicle
        out["control_layout"] = detect_control_layout(vehicle)
        return out

    def has_control_api(self) -> bool:
        """True si HTTPAPI está disponible para escribir mandos."""
        now = time.monotonic()
        if self._api_ok_cache is not None and now - self._api_ok_ts < 10.0:
            return self._api_ok_cache
        self._api_ok_cache = self._ensure_api_client(silent=True)
        self._api_ok_ts = now
        return self._api_ok_cache

    def _kick_planning_refresh(self) -> None:
        """Actualiza DriverAid en segundo plano (no bloquea el bucle de control)."""
        now = time.monotonic()
        if now - self._planning_last_kick < PLANNING_MIN_INTERVAL_S:
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
            finally:
                self._planning_refreshing = False

        threading.Thread(target=_work, daemon=True, name="tsw-planning").start()

    def _get_cached_planning(self) -> dict[str, Any]:
        with self._planning_lock:
            return dict(self._planning_cache)

    def get_vehicle_name(self) -> Optional[str]:
        return self._vehicle_name

    def set_control_value(self, control: str, val: float) -> bool:
        """Escritura de mandos vía API TSW (prioridad sobre planning)."""
        if not self._ensure_api_client(silent=True):
            return False
        if not self._api_lock.acquire(blocking=False):
            _log.debug("set_control_value: API ocupada, reintentar próximo ciclo")
            return False
        try:
            client = self._client
            if client is None:
                return False
            name = str(control or "").strip()
            if name == "PowerBrakeHandle":
                notch = combined_value_to_notch(val)
                result = dispatch_combined_notch(
                    client, notch, timeout=CONTROL_API_TIMEOUT)
            else:
                result = dispatch_brake(
                    client, name, val, timeout=CONTROL_API_TIMEOUT)
            ok = bool(result.get("ok"))
            if not ok:
                _log.debug("set_control_value falló: %s", result)
            return ok
        finally:
            self._api_lock.release()


# Alias para migración gradual de imports
TswConnection = TswTelemetrySource
