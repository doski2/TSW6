#!/usr/bin/env python3
"""
autopilot_core.py — Motor del autopilot (bucle de control sin UI).

Expone AutopilotEngine.tick() para consola o GUI. La lógica de decisión
permanece en SpeedDecider; aquí solo orquesta telemetría, OCR y mandos.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Optional

from handle_controller import HandleController, SafetyWatchdog
from speed_decider import SpeedDecider
from train_state import build_train_state
from tsw_keys import user32
from tsw_ocr import TswOcr
from tsw_telemetry_source import TswTelemetrySource

EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))


def find_tsw_window() -> Optional[int]:
    """Devuelve el handle (hwnd) de la ventana principal de TSW6."""
    found: list[int] = []

    @EnumWindowsProc
    def _cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "Train Sim World" in title or "TrainSimWorld" in title:
                    found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


@dataclass
class AutopilotConfig:
    target_mph: float = 0.0
    no_control: bool = False
    manual: bool = False
    learn: bool = False
    stop_miles: Optional[float] = None
    loop_hz: float = 5.0


@dataclass
class AutopilotSnapshot:
    """Instantánea para la GUI o depuración."""
    speed_mph: Optional[float] = None
    limit_mph: Optional[float] = None
    effective_limit: float = 0.0
    target_mph: float = 0.0
    action: str = "HOLD"
    final_action: str = "HOLD"
    override: Optional[str] = None
    station_state: Optional[str] = None
    station_name: Optional[str] = None
    handle_notch: Optional[int] = None
    next_limit_mph: Optional[float] = None
    distance_next_m: Optional[float] = None
    next_limit_2_mph: Optional[float] = None
    distance_next_2_m: Optional[float] = None
    brake_marker_m: Optional[float] = None
    gradient_pct: Optional[float] = None
    acceleration_ms2: Optional[float] = None
    conn_mode: str = "searching"
    fps: float = 0.0
    paused: bool = False
    vehicle_name: Optional[str] = None
    ack_required: bool = False
    doors_open: bool = False
    stations: list = field(default_factory=list)
    speed_limits_ahead: list = field(default_factory=list)
    hwnd: Optional[int] = None
    ocr_stop_dist_m: Optional[float] = None
    ocr_task: Optional[str] = None
    rain_intensity: float = 0.0
    supervision: str = ""
    control_api_ok: bool = False
    control_channel: str = "none"
    last_cmd_sent: bool = False
    probe_seq: Optional[int] = None
    probe_age_ms: Optional[float] = None


class _GuiLogHandler(logging.Handler):
    def __init__(self, buffer: Deque[str], max_lines: int = 80) -> None:
        super().__init__()
        self._buffer = buffer
        self._max = max_lines

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._buffer.append(msg)
            while len(self._buffer) > self._max:
                self._buffer.popleft()
        except Exception:
            pass


class AutopilotEngine:
    """Bucle de control del autopilot, independiente de consola o GUI."""

    PROBE_INTERVAL = 5.0

    def __init__(self, config: AutopilotConfig,
                 log_path: Optional[Path] = None) -> None:
        self.config = config
        self.conn = TswTelemetrySource()
        if config.manual:
            self.conn.mode = "manual"

        self.decider = SpeedDecider(target_mph=config.target_mph)
        self.controller = HandleController()
        self.watchdog = SafetyWatchdog()

        if config.stop_miles is not None:
            self.decider.target_stop_min_m = config.stop_miles * 1609.344

        self.hwnd: Optional[int] = find_tsw_window()
        self.ocr = TswOcr(self.hwnd or 0)

        self._handle_synced = False
        self._last_state_handle: int = 4
        self._vehicle_profiled = False
        self._veh_detected: dict[str, Optional[str]] = {"v": None}
        self._veh_thread_started = False

        self.telem: dict = {}
        self.loop_times: list[float] = []
        self.snapshot = AutopilotSnapshot(target_mph=config.target_mph)
        self._running = True
        self._manual_prompt: Optional[Callable[[], dict]] = None
        self._control_api_ok = False
        self._control_api_check_t = 0.0
        self._ipc_armed = False
        self._log_cycle_n = 0
        self._telem_ready_logged = False
        self._telem_partial_logged = False
        self._searching_warn_t = 0.0
        self._heartbeat_t = 0.0

        if not config.no_control:
            self.conn.purge_ipc_on_start()

        self._log_buffer: Deque[str] = deque(maxlen=80)
        self._log = logging.getLogger("tsw.autopilot")
        if log_path:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d [%(name)-14s] %(levelname)-7s %(message)s",
                datefmt="%H:%M:%S"))
            self._log.addHandler(fh)
            self._log.setLevel(logging.DEBUG)
        gh = _GuiLogHandler(self._log_buffer)
        gh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                          datefmt="%H:%M:%S"))
        self._log.addHandler(gh)
        telem_log = logging.getLogger("tsw.telemetry")
        telem_log.setLevel(logging.INFO)
        telem_log.addHandler(gh)
        if log_path:
            telem_log.addHandler(fh)

        self._probe_lock = threading.Lock()
        with self._probe_lock:
            mode = self.conn.connect_fast()
        self._log.info(
            "Conexión inicial: modo=%s — %s",
            mode, self.conn.last_probe_info)
        threading.Thread(target=self._bg_probe, daemon=True).start()

    @property
    def log_lines(self) -> list[str]:
        return list(self._log_buffer)

    def set_manual_prompt(self, fn: Callable[[], dict]) -> None:
        self._manual_prompt = fn

    def _bg_probe(self) -> None:
        while self._running:
            time.sleep(self.PROBE_INTERVAL)
            with self._probe_lock:
                if self.conn.mode == "searching":
                    self.conn.probe()

    def pause(self) -> None:
        self.decider.paused = True

    def resume(self) -> None:
        self.decider.paused = False

    def toggle_pause(self) -> bool:
        self.decider.paused = not self.decider.paused
        return self.decider.paused

    def set_target_mph(self, mph: float) -> None:
        self.decider.target_mph = max(0.0, min(200.0, mph))
        self.config.target_mph = self.decider.target_mph

    def adjust_target(self, delta: float) -> None:
        self.set_target_mph(self.decider.target_mph + delta)

    def clear_stop(self) -> None:
        self.decider.target_stop_min_m = None
        self.decider._locked_stop_name = None
        self._log.info("Parada manual desactivada – modo automático")

    def set_stop_miles(self, miles: float) -> None:
        self.decider.target_stop_min_m = miles * 1609.344
        self.decider._locked_stop_name = None
        self._log.info("Parada manual: %.2f millas (%.0f m)",
                       miles, self.decider.target_stop_min_m)

    def force_neutral(self) -> None:
        if not self.config.no_control:
            self._log.info("Sincronización manual del handle")
            self.controller.force_neutral(self.hwnd, self.conn)
            self._handle_synced = True

    def reset_neutral(self) -> None:
        if not self.config.no_control and self.hwnd:
            self.controller.reset_neutral(self.hwnd, self._last_state_handle)

    def stop(self) -> None:
        self._running = False
        self.ocr.stop()
        if not self.config.no_control:
            self.conn.release_controls()

    def tick(self) -> AutopilotSnapshot:
        """Un ciclo de control. Devuelve instantánea actualizada."""
        t0 = time.perf_counter()

        if self.conn.mode in ("manual", "searching"):
            if self.conn.mode == "searching":
                with self._probe_lock:
                    self.conn.try_connect_ue4ss()
                if self.conn.mode == "ue4ss":
                    new = self.conn.get_telemetry()
                    if new:
                        self.telem = new
            elif self._manual_prompt:
                new = self._manual_prompt()
                if new:
                    self.telem = new
        else:
            new = self.conn.get_telemetry()
            if new:
                self.telem = new

        self._log_searching_hint()
        self._log_telemetry_ready()
        self._log_heartbeat()

        if not self.hwnd:
            self.hwnd = find_tsw_window()
            if self.hwnd:
                self.ocr._hwnd = self.hwnd

        self._detect_vehicle()
        self._sync_handle()

        speed = self.telem.get("speed_mph")
        limit = self.telem.get("limit_mph")
        api_accel = self.telem.get("accel_mps2")

        if speed is not None:
            self.decider.update_physics(
                speed_mph=speed,
                api_accel=api_accel,
                gradient_pct=self.telem.get("gradient_pct") or 0.0,
            )
            if self.config.learn or (self._last_state_handle is not None
                                    and self._last_state_handle <= 3):
                self.decider.feed_learner(
                    speed_mph=speed,
                    handle_notch=self._last_state_handle,
                    gradient_pct=self.telem.get("gradient_pct") or 0.0,
                    accel_ms2=api_accel,
                )

        rain = self.telem.get("rain_intensity", 0.0) or 0.0
        self.decider.set_rain_intensity(rain)

        need_ocr = self._needs_ocr()
        self.ocr.set_active(need_ocr)
        ocr_dist = self.ocr.get_distance() if need_ocr else None
        ocr_task = self.ocr.get_task() if need_ocr else None

        action = "HOLD"
        final = "HOLD"
        override: Optional[str] = None
        cmd_sent = False

        if speed is not None and limit is not None and self.conn.mode != "searching":
            state = build_train_state(
                self.telem,
                target_mph=self.decider.target_mph,
                paused=self.decider.paused,
                acceleration_ms2=self.decider.acceleration_ms2,
                station_state=self.decider.station_state,
                station_name=self.decider.station_name,
                ocr_stop_dist_m=ocr_dist,
                ocr_task=ocr_task,
            )
            action = self.decider.decide(state)
            override = self.watchdog.check(state)
            final = override or action

            if not self.config.no_control:
                cmd_sent = self.controller.execute(final, state, self.conn, self.hwnd)

            self._log_cycle(speed, limit, action, final)
        else:
            self.decider.last_action = "HOLD"

        elapsed = time.perf_counter() - t0
        self.loop_times.append(elapsed)
        if len(self.loop_times) > 20:
            self.loop_times.pop(0)
        fps = 1.0 / (sum(self.loop_times) / len(self.loop_times)) if self.loop_times else 0.0

        now = time.monotonic()
        if now - self._control_api_check_t >= 5.0:
            self._control_api_ok = self.conn.has_control_api()
            self._control_api_check_t = now

        if (not self.config.no_control
                and not self._ipc_armed
                and self.conn.has_ipc_control()):
            self.conn.arm_ipc_controls()
            self._ipc_armed = True
            self._log.info("Mandos vía SendCommand.txt (UE4SS IPC)")

        self.snapshot = AutopilotSnapshot(
            speed_mph=speed,
            limit_mph=limit,
            effective_limit=self.decider.effective_limit,
            target_mph=self.decider.target_mph,
            action=action,
            final_action=final,
            override=override,
            station_state=self.decider.station_state,
            station_name=self.decider.station_name,
            handle_notch=self.telem.get("handle_notch"),
            next_limit_mph=self.telem.get("next_limit_mph"),
            distance_next_m=self.telem.get("distance_next_m"),
            next_limit_2_mph=self.telem.get("next_limit_2_mph"),
            distance_next_2_m=self.telem.get("distance_next_2_m"),
            brake_marker_m=self.telem.get("brake_marker_m"),
            gradient_pct=self.telem.get("gradient_pct"),
            acceleration_ms2=self.decider.acceleration_ms2,
            conn_mode=self.conn.mode,
            fps=fps,
            paused=self.decider.paused,
            vehicle_name=self._veh_detected.get("v"),
            ack_required=bool(self.telem.get("ack_required")),
            doors_open=bool(self.telem.get("doors_open")),
            stations=list(self.telem.get("stations") or []),
            speed_limits_ahead=list(self.telem.get("speed_limits_ahead") or []),
            hwnd=self.hwnd,
            ocr_stop_dist_m=ocr_dist,
            ocr_task=ocr_task,
            rain_intensity=rain,
            supervision=str(self.telem.get("supervision") or ""),
            control_api_ok=self._control_api_ok,
            control_channel=self.conn.control_channel(),
            last_cmd_sent=cmd_sent,
            probe_seq=self.telem.get("probe_seq"),
            probe_age_ms=self.telem.get("telemetry_age_ms"),
        )
        return self.snapshot

    def _needs_ocr(self) -> bool:
        if self.decider.station_state in ("APPROACHING", "STOPPED", "DEPARTING"):
            return True
        for st in (self.telem.get("stations") or [])[:1]:
            if st.get("distance_m", 99999) < 1500:
                return True
        return False

    def sleep_remainder(self, elapsed: float) -> None:
        target_dt = 1.0 / self.config.loop_hz if self.conn.mode != "manual" else 1.0
        time.sleep(max(0.0, target_dt - elapsed))

    def _detect_vehicle(self) -> None:
        if self._vehicle_profiled or self.conn.mode not in ("ue4ss", "tsw_api"):
            return
        name = self.telem.get("vehicle_name") or self.conn.get_vehicle_name()
        if name:
            self._veh_detected["v"] = name
        elif not self._veh_thread_started:
            self._veh_thread_started = True

            def _search() -> None:
                while self._veh_detected["v"] is None and self._running:
                    name = self.conn.get_vehicle_name()
                    if name:
                        self._veh_detected["v"] = name
                        return
                    time.sleep(2.0)

            threading.Thread(target=_search, daemon=True).start()

        if self._veh_detected["v"]:
            veh = self._veh_detected["v"]
            if self.config.learn:
                self.decider.adopt_vehicle_profile(veh)
            else:
                self.decider.set_vehicle_profile(veh)
            self._log.info("Perfil de tren cargado: %s", veh)
            self._vehicle_profiled = True

    def _log_searching_hint(self) -> None:
        if self.conn.mode != "searching":
            return
        now = time.monotonic()
        if self._searching_warn_t > 0 and now - self._searching_warn_t < 10.0:
            return
        first = self._searching_warn_t == 0.0
        self._searching_warn_t = now
        msg = (
            "Sin probe UE4SS (%s) — carga escenario, F7 activo, "
            "install_ue4ss_probe.bat"
        )
        if first:
            self._log.info(msg, self.conn.last_probe_info)
        else:
            self._log.warning(msg, self.conn.last_probe_info)

    def _log_telemetry_ready(self) -> None:
        if self._telem_ready_logged or self.conn.mode not in ("ue4ss", "tsw_api"):
            return
        speed = self.telem.get("speed_mph")
        limit = self.telem.get("limit_mph")
        if speed is not None and limit is not None:
            self._telem_ready_logged = True
            self._log.info(
                "Telemetría lista: modo=%s  spd=%.1f  lim=%.0f  notch=%s  mandos=%s",
                self.conn.mode,
                float(speed),
                float(limit),
                self.telem.get("handle_notch", "?"),
                self.conn.control_channel())
            return
        if self._telem_partial_logged or speed is None:
            return
        self._telem_partial_logged = True
        self._log.warning(
            "Telemetría parcial: spd=%.1f  lim=%s  seq=%s  "
            "(falta límite vía en probe — ¿en cabina con F7?)",
            float(speed),
            f"{limit:.0f}" if limit is not None else "—",
            self.telem.get("probe_seq", "?"))

    def _log_heartbeat(self) -> None:
        """Estado cada ~2 s visible en panel Depuración."""
        now = time.monotonic()
        if now - self._heartbeat_t < 2.0:
            return
        self._heartbeat_t = now
        t = self.telem
        spd = t.get("speed_mph")
        lim = t.get("limit_mph")
        dist = t.get("distance_next_m")
        self._log.info(
            "heartbeat modo=%s  spd=%s  lim=%s  seq=%s  dist=%s  mandos=%s",
            self.conn.mode,
            f"{spd:.1f}" if spd is not None else "—",
            f"{lim:.0f}" if lim is not None else "—",
            t.get("probe_seq", "?"),
            f"{dist:.1f}m" if dist is not None else "—",
            self.conn.control_channel())

    def _sync_handle(self) -> None:
        handle_notch = self.telem.get("handle_notch")
        if handle_notch is not None:
            self._last_state_handle = int(handle_notch)
            self._handle_synced = True
            return
        if self._handle_synced:
            return
        # No bloquear ~5s con teclado hasta que el probe/API esté conectado.
        if self.conn.mode not in ("ue4ss", "tsw_api") or not self.telem:
            return
        if self.telem.get("ack_required"):
            self._log.warning(
                "handle_notch no disponible con ACK activo — omitiendo force_neutral")
            self._last_state_handle = 4
            self._handle_synced = True
            return
        if self.config.no_control:
            self._log.warning(
                "handle_notch no disponible — asumiendo neutro (no_control)")
            self._handle_synced = True
            return
        self._log.warning(
            "handle_notch no disponible — sincronizando handle (~5s)")
        self.controller.force_neutral(self.hwnd, self.conn)
        self._handle_synced = True

    def _log_cycle(self, speed: float, limit: float,
                   action: str, final: str) -> None:
        self._log_cycle_n += 1
        if self._log_cycle_n > 5 and self._log_cycle_n % 20 != 0:
            return
        telem = self.telem
        dmi_d = telem.get("doors_dmi")
        dmi_d_str = "O" if dmi_d is True else ("C" if dmi_d is False else "?")
        line = (
            "spd=%5.1f  lim=%4.1f  elim=%5.1f  notch=%-2s  action=%-11s  "
            "final=%-11s  fsm=%-10s  stop=%-30s  next=%s@%sm  ack=%s  "
            "doors=%s  dmi_d=%s  grad=%s  rain=%.2f"
        )
        args = (
            speed, limit,
            self.decider.effective_limit,
            telem.get("handle_notch", "?"),
            action, final,
            self.decider.station_state or "-",
            self.decider.station_name or "-",
            f"{telem.get('next_limit_mph', '?')}",
            f"{telem.get('distance_next_m', '?')}",
            "Y" if telem.get("ack_required") else "N",
            "Y" if telem.get("doors_open") else "N",
            dmi_d_str,
            f"{telem.get('gradient_pct') or 0.0:+.1f}%",
            telem.get("rain_intensity", 0.0) or 0.0,
        )
        if self._log_cycle_n <= 5:
            self._log.info(line, *args)
        else:
            self._log.debug(line, *args)
