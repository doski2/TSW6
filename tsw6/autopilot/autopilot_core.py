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
from typing import Callable, Deque, Optional, TypedDict

from tsw6.autopilot.handle_controller import HandleController, SafetyWatchdog
from tsw6.autopilot.speed_decider import SpeedDecider
from tsw6.autopilot.train_state import TrainState, build_train_state
from tsw6.autopilot.tsw_keys import user32
from tsw6.autopilot.tsw_ocr import TswOcr
from tsw6.autopilot.distance_format import format_distance, format_distance_pair
from tsw6.learning.learn_monitor import learn_progress_summary
from tsw6.hud.hud_timetable import schedule_times_for_station
from tsw6.telemetry.driver_aid_parser import resolve_display_next_stop
from tsw6.telemetry.tsw_telemetry_source import TswTelemetrySource
from tsw6.telemetry.control_channel import DEFAULT_TELEM_HZ
from tsw6.telemetry.channel_diagnostics import (
    ControllerMetrics,
    LoopMetrics,
    acceptance_verdict,
    probe_mod_flags,
    probe_mod_label,
)

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
    learn: bool = True
    schedule_slack: bool = False
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
    doors_telem: Optional[bool] = None
    doors_dmi: Optional[bool] = None
    stations: list = field(default_factory=list)
    next_stop_name: Optional[str] = None
    next_stop_distance_m: Optional[float] = None
    next_stop_arrival: Optional[str] = None
    next_stop_departure: Optional[str] = None
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
    probe_live: bool = False
    probe_hint: str = ""
    probe_dist_limit_m: Optional[float] = None
    distance_units: str = "uk_imperial"
    brake_phase: Optional[str] = None
    brake_target_notch: Optional[int] = None
    schedule_source: Optional[str] = None
    hud_timetable_id: Optional[int] = None
    learn_enabled: bool = False
    schedule_slack_enabled: bool = False
    learn_profile: str = ""
    learn_done_cells: int = 0
    learn_total_cells: int = 0
    learn_reason: str = ""
    learn_max_decel: Optional[float] = None
    learn_target_decel: Optional[float] = None
    learn_coast_decel: Optional[float] = None
    eff_max_decel: Optional[float] = None
    learn_confidence: dict = field(default_factory=dict)


class LearnStatus(TypedDict):
    profile: str
    done_cells: int
    total_cells: int
    last_reason: str
    max_decel: float
    target_decel: float
    coast_decel: float
    eff_max_decel: float
    confidence: dict[str, int]


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
        self.decider.set_schedule_slack_enabled(config.schedule_slack)
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
        self._learn_status_t = 0.0
        self._learn_status_cache: Optional[LearnStatus] = None
        self._telem_ready_logged = False
        self._telem_partial_logged = False
        self._searching_warn_t = 0.0
        self._hwnd_search_t = 0.0
        self._search_connect_t = 0.0
        self._heartbeat_t = 0.0
        self._pause_diag_t = 0.0
        self._loop_fps = 0.0
        self._last_tick_ms = 0.0
        self._last_sleep_ms = 0.0
        self._heartbeat_wall_t = 0.0
        self._heartbeat_tick_count = 0
        self._loop_hz_real = 0.0
        self._control_skip_reason = "init"
        self._limit_fallback_logged = False
        self._pressure_warn_logged = False
        self._probe_mod_logged = False
        self._channel_summary_t = 0.0
        self._loop_metrics = LoopMetrics()
        self._session_log_path: Optional[Path] = log_path

        if not config.no_control:
            self.conn.purge_ipc_on_start()

        self._log_buffer: Deque[str] = deque(maxlen=80)
        self._log = logging.getLogger("tsw.autopilot")
        if log_path:
            self._log.info("Log sesión: %s", log_path)
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
            for _name in (
                "tsw.governor", "tsw.governor.v2", "tsw.controller",
                "tsw.physics", "tsw.learner", "tsw.telemetry.channel",
            ):
                _lg = logging.getLogger(_name)
                _lg.setLevel(logging.DEBUG)
                if _name == "tsw.governor.v2":
                    _lg.propagate = False
                _lg.addHandler(fh)
                _lg.addHandler(gh)

        self._probe_lock = threading.Lock()
        with self._probe_lock:
            mode = self.conn.connect_fast()
        self._log.info(
            "Autopilot iniciado  tgt=%.0fHz  control=%s  learn=%s",
            self.config.loop_hz,
            "off" if self.config.no_control else "on",
            "on" if self.config.learn else "off",
        )
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
        if not self.decider.paused:
            self.decider.paused = True
            self.conn.set_planning_hold(True)
            self._pause_diag_t = 0.0
            self._log_pause_state("Autopilot PAUSADO")

    def resume(self) -> None:
        if self.decider.paused:
            self.decider.paused = False
            self.conn.set_planning_hold(False)
            self._log_pause_state("Autopilot REANUDADO")

    def toggle_pause(self) -> bool:
        self.decider.paused = not self.decider.paused
        self.conn.set_planning_hold(self.decider.paused)
        self._pause_diag_t = 0.0
        self._log_pause_state(
            "Autopilot PAUSADO" if self.decider.paused else "Autopilot REANUDADO")
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
        if not self.config.no_control:
            self.controller.reset_neutral(
                self.hwnd, self._last_state_handle, conn=self.conn)

    def stop(self) -> None:
        self._running = False
        self.ocr.stop()
        self._log_session_summary("fin sesión")
        if not self.config.no_control:
            self.conn.release_controls()

    def _resolve_next_stop_snapshot(
        self,
        stations: list[dict],
    ) -> tuple[Optional[str], Optional[float], Optional[str], Optional[str]]:
        """Próxima parada para GUI — excluye servidas y enriquece horario HUD."""
        exclude = self.decider.served_station_bases()
        self.conn.set_station_exclude_bases(exclude)
        hud_entries, hud_names = self.conn.hud_schedule_context()
        nxt = resolve_display_next_stop(
            stations,
            exclude_bases=exclude,
            hud_stop_names=hud_names,
        )
        if nxt is None:
            return None, None, None, None
        name = nxt.get("name")
        dist = nxt.get("distance_m")
        arr = nxt.get("arrival")
        dep = nxt.get("departure")
        if name and hud_entries and (arr is None or dep is None):
            eta_arr, eta_dep = schedule_times_for_station(hud_entries, str(name))
            arr = arr or eta_arr
            dep = dep or eta_dep
        return (
            str(name) if name else None,
            float(dist) if dist is not None else None,
            arr,
            dep,
        )

    def tick(self) -> AutopilotSnapshot:
        """Un ciclo de control. Devuelve instantánea actualizada."""
        t0 = time.perf_counter()

        if self.conn.mode in ("manual", "searching"):
            if self.conn.mode == "searching":
                now_s = time.monotonic()
                if now_s - self._search_connect_t >= 0.5:
                    self._search_connect_t = now_s
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
            elif self.conn.mode == "searching":
                self.telem = {}

        self._log_searching_hint()
        self._log_telemetry_ready()

        if self.hwnd and not user32.IsWindow(self.hwnd):
            self.hwnd = None
            self.ocr._hwnd = 0
        if not self.hwnd:
            now_w = time.monotonic()
            if now_w - self._hwnd_search_t >= 1.0:
                self._hwnd_search_t = now_w
                self.hwnd = find_tsw_window()
                if self.hwnd:
                    self.ocr._hwnd = self.hwnd

        self._detect_vehicle()
        self._sync_handle()

        speed = self.telem.get("speed_mph")
        limit = self.telem.get("limit_mph")
        if limit is None:
            next_lim_fb = self.telem.get("next_limit_mph")
            if next_lim_fb is not None:
                limit = float(next_lim_fb)
                if not self._limit_fallback_logged:
                    self._limit_fallback_logged = True
                    self._log.warning(
                        "limit_mph ausente (max_speed API inactivo) — "
                        "usando next_limit_mph=%.0f para control",
                        limit,
                    )

        api_accel = self.telem.get("accel_mps2")

        if speed is not None:
            self.decider.update_physics(
                speed_mph=speed,
                api_accel=api_accel,
                gradient_pct=self.telem.get("gradient_pct") or 0.0,
            )
            if self.config.learn or (self._last_state_handle is not None
                                    and self._last_state_handle <= 3):
                brake_cyl = self.telem.get("brake_cyl_bar")
                self.decider.feed_learner(
                    speed_mph=speed,
                    handle_notch=self._last_state_handle,
                    gradient_pct=self.telem.get("gradient_pct") or 0.0,
                    accel_ms2=api_accel,
                    brake_cyl_bar=brake_cyl,
                )
                if (
                    not self._pressure_warn_logged
                    and self._last_state_handle is not None
                    and self._last_state_handle <= 3
                    and brake_cyl is None
                ):
                    self._pressure_warn_logged = True
                    self._log.warning(
                        "brake_cyl_bar ausente en probe — learner/fill-time "
                        "sin presión (recarga TelemetryProbeMod / UE4SS)",
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
                cmd = self.decider.brake_command_for(final, state)
                cmd_sent = self.controller.execute(
                    final, state, self.conn, self.hwnd,
                    brake_command=cmd,
                )

            self._log_cycle(
                speed, limit, action, final, cmd_sent=cmd_sent,
                state=state, override=override,
            )
            self._control_skip_reason = "active"
        else:
            self.decider.last_action = "HOLD"
            if self.conn.mode == "searching":
                self._control_skip_reason = "skip_searching"
            elif speed is None:
                self._control_skip_reason = "skip_no_spd"
            elif limit is None:
                self._control_skip_reason = "skip_no_limit"
            else:
                self._control_skip_reason = "skip_other"

        elapsed = time.perf_counter() - t0
        self.loop_times.append(elapsed)
        if len(self.loop_times) > 20:
            self.loop_times.pop(0)
        fps = self._loop_hz_real
        self._loop_fps = fps
        self._last_tick_ms = elapsed * 1000.0
        self._heartbeat_tick_count += 1
        self._loop_metrics.record_tick(self._last_tick_ms, self._loop_hz_real)

        self._log_heartbeat()
        self._log_channel_summary()
        self._log_pause_diag()

        now = time.monotonic()
        if now - self._control_api_check_t >= 5.0:
            self._control_api_ok = self.conn.has_control_api()
            self._control_api_check_t = now

        if (not self.config.no_control
                and not self._ipc_armed
                and self.conn.has_ipc_control()):
            self.conn.arm_ipc_controls()
            self._ipc_armed = True
            self._log.info(
                "Canal IPC armado (async writer + TelemetryReader 20Hz)")
            self._log.info("Mandos vía SendCommand.txt (UE4SS IPC)")

        _stations = list(self.telem.get("stations") or [])
        (
            _nxt_name,
            _nxt_dist,
            _nxt_arr,
            _nxt_dep,
        ) = self._resolve_next_stop_snapshot(_stations)

        learn_info = self._learn_status()
        probe_st = self.conn.probe_status()

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
            doors_open=(
                self.telem.get("doors_telem") is True
                or bool(self.telem.get("doors_open"))
                or self.telem.get("doors_dmi") is True
            ),
            doors_telem=self.telem.get("doors_telem"),
            doors_dmi=self.telem.get("doors_dmi"),
            stations=_stations,
            next_stop_name=_nxt_name,
            next_stop_distance_m=_nxt_dist,
            next_stop_arrival=_nxt_arr,
            next_stop_departure=_nxt_dep,
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
            probe_live=bool(probe_st.get("live")),
            probe_hint=str(probe_st.get("hint") or ""),
            probe_dist_limit_m=self.telem.get("probe_dist_limit_m"),
            distance_units=str(self.telem.get("distance_units") or "uk_imperial"),
            brake_phase=(
                self.decider.brake_command.phase
                if self.decider.brake_command else None
            ),
            brake_target_notch=(
                self.decider.brake_command.target_notch
                if self.decider.brake_command else None
            ),
            schedule_source=self.telem.get("schedule_source"),
            hud_timetable_id=self.telem.get("hud_timetable_id"),
            learn_enabled=self.config.learn,
            schedule_slack_enabled=self.config.schedule_slack,
            learn_profile=learn_info["profile"],
            learn_done_cells=learn_info["done_cells"],
            learn_total_cells=learn_info["total_cells"],
            learn_reason=learn_info["last_reason"],
            learn_max_decel=learn_info["max_decel"],
            learn_target_decel=learn_info["target_decel"],
            learn_coast_decel=learn_info["coast_decel"],
            eff_max_decel=learn_info["eff_max_decel"],
            learn_confidence=dict(learn_info["confidence"]),
        )
        return self.snapshot

    def set_learn_enabled(self, enabled: bool) -> None:
        """Activa auto-aprendizaje en todas las muescas (estilo Dastsc)."""
        if enabled == self.config.learn:
            return
        self.config.learn = enabled
        veh = self._veh_detected.get("v")
        if enabled and veh:
            self.decider.adopt_vehicle_profile(veh)
        label = "activado" if enabled else "desactivado"
        self._log.info(
            "Auto-aprendizaje %s (%s)",
            label,
            "todas las muescas" if enabled else "solo refinado en freno",
        )

    def set_schedule_slack_enabled(self, enabled: bool) -> None:
        """Holgura de horario en frenada de estación (coast por ETA)."""
        if enabled == self.config.schedule_slack:
            return
        self.config.schedule_slack = enabled
        self.decider.set_schedule_slack_enabled(enabled)
        label = "activada" if enabled else "desactivada"
        self._log.info("Holgura de horario %s", label)

    def learn_status(self) -> LearnStatus:
        """Estado del perfil / learner para la GUI."""
        return self._learn_status()

    def _learn_status(self) -> LearnStatus:
        now = time.monotonic()
        cached = self._learn_status_cache
        if cached is not None and now - self._learn_status_t < 0.25:
            return cached
        physics = self.decider._physics
        learner = physics.learner
        vehicle = self._veh_detected.get("v") or ""
        layout = getattr(physics, "_layout", "combined")
        raw: dict = {}
        try:
            raw = learn_progress_summary(
                learner, vehicle, layout=layout,
            )
        except Exception:
            pass
        consts = raw.get("constants") or {}
        max_d = tgt_d = coast = None
        if isinstance(consts, dict):
            if consts.get("MAX_DECEL_MS2") is not None:
                max_d = float(consts["MAX_DECEL_MS2"])
            if consts.get("TARGET_DECEL_MS2") is not None:
                tgt_d = float(consts["TARGET_DECEL_MS2"])
            if consts.get("COAST_DECEL_MS2") is not None:
                coast = float(consts["COAST_DECEL_MS2"])
        conf = raw.get("confidence") or {}
        if not isinstance(conf, dict):
            conf = {}
        result: LearnStatus = {
            "profile": str(raw.get("profile") or ""),
            "done_cells": int(raw.get("done_cells") or 0),
            "total_cells": int(raw.get("total_cells") or 0),
            "last_reason": str(raw.get("last_reason") or ""),
            "max_decel": float(max_d if max_d is not None else physics.max_decel_ms2),
            "target_decel": float(tgt_d if tgt_d is not None else physics.target_decel_ms2),
            "coast_decel": float(coast if coast is not None else physics.coast_decel_ms2),
            "eff_max_decel": float(physics.eff_max_decel),
            "confidence": {str(k): int(v) for k, v in conf.items()},
        }
        self._learn_status_cache = result
        self._learn_status_t = now
        return result

    def _needs_ocr(self) -> bool:
        if self.decider.station_state in ("APPROACHING", "STOPPED", "DEPARTING"):
            return True
        for st in (self.telem.get("stations") or [])[:1]:
            if st.get("distance_m", 99999) < 1500:
                return True
        return False

    def sleep_remainder(self, elapsed: float) -> None:
        target_dt = 1.0 / self.config.loop_hz if self.conn.mode != "manual" else 1.0
        sleep_s = max(0.0, target_dt - elapsed)
        self._last_sleep_ms = sleep_s * 1000.0
        time.sleep(sleep_s)

    def _detect_vehicle(self) -> None:
        if self._vehicle_profiled or self.conn.mode != "ue4ss":
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
            self._log_learner_state("perfil cargado")
            self._vehicle_profiled = True

    def _on_ue4ss_upgraded(self) -> None:
        """Probe F7 disponible tras arrancar en HTTP — canal rápido + IPC."""
        self._probe_mod_logged = False
        self._log.info(
            "Probe UE4SS activo — cambio HTTP → UE4SS (~%d Hz telemetría)",
            int(DEFAULT_TELEM_HZ),
        )
        self._log_probe_mod()

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
        if self._telem_ready_logged or self.conn.mode != "ue4ss":
            return
        speed = self.telem.get("speed_mph")
        limit = self.telem.get("limit_mph")
        if speed is not None and limit is not None:
            self._telem_ready_logged = True
            self._log_probe_mod()
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
        next_lim = self.telem.get("next_limit_mph")
        dist = self.telem.get("distance_next_m")
        hint = (
            "max_speed HTTP inactivo — next_limit disponible"
            if next_lim is not None else
            "falta límite vía (F7 probe o DriverAid)"
        )
        self._log.warning(
            "Telemetría parcial: spd=%.1f  lim=%s  next_lim=%s  dist=%s  seq=%s  (%s)",
            float(speed),
            f"{limit:.0f}" if limit is not None else "—",
            f"{next_lim:.0f}" if next_lim is not None else "—",
            f"{dist:.0f}m" if dist is not None else "—",
            self.telem.get("probe_seq", "?"),
            hint,
        )

    def _learner_snapshot(self) -> tuple[str, str, float, int]:
        """Presión cilindro, last_reason, fill_s y fill_n para logs."""
        telem = self.telem
        p_bar = telem.get("brake_cyl_bar")
        p_txt = f"{float(p_bar):.2f}" if p_bar is not None else "—"
        physics = self.decider._physics
        learner = physics.learner
        lrn = str(getattr(learner, "last_reason", "") or "—")
        if len(lrn) > 40:
            lrn = lrn[:37] + "..."
        fill_s = float(getattr(physics, "brake_fill_s", 0.0))
        fill_n = int(getattr(learner, "_brake_fill_n", 0))
        return p_txt, lrn, fill_s, fill_n

    def _log_learner_state(self, prefix: str) -> None:
        p_txt, lrn, fill_s, fill_n = self._learner_snapshot()
        self._log.info(
            "%s — P=%s BAR  fill=%.2fs (n=%d)  lrn=%s",
            prefix, p_txt, fill_s, fill_n, lrn,
        )

    def _log_heartbeat(self) -> None:
        """Estado cada ~2 s visible en panel Depuración."""
        now = time.monotonic()
        if now - self._heartbeat_t < 2.0:
            return
        if self._heartbeat_wall_t > 0:
            dt = now - self._heartbeat_wall_t
            if dt > 0:
                self._loop_hz_real = self._heartbeat_tick_count / dt
        self._heartbeat_tick_count = 0
        self._heartbeat_wall_t = now
        self._heartbeat_t = now
        t = self.telem
        spd = t.get("speed_mph")
        lim = t.get("limit_mph")
        dist = t.get("distance_next_m")
        probe_dist = t.get("probe_dist_limit_m")
        frozen = t.get("probe_motion_frozen")
        units = str(t.get("distance_units") or "uk_imperial")
        next_lim = t.get("next_limit_mph")
        telem_age = t.get("telemetry_age_ms")
        telem_src = t.get("telemetry_source") or self.conn.mode
        telem_poll = t.get("telem_poll_hz")
        if telem_poll is None:
            telem_poll = self.conn.telem_poll_hz()
        skip = self._control_skip_reason
        if self.decider.paused:
            skip = "paused"
        p_txt, lrn, fill_s, fill_n = self._learner_snapshot()
        lever = t.get("lever_notch", t.get("handle_notch"))
        hud = t.get("hud_notch")
        cmd_st = self.conn.command_state()
        cmd_q = cmd_st.queue_depth
        ack_ms = cmd_st.last_ack_ms
        last_id = cmd_st.cmd_id
        target_n = cmd_st.target_notch
        confirmed = (
            "Y" if cmd_st.confirmed_cmd_id == last_id and last_id > 0 else
            "N" if last_id > 0 else "—"
        )
        match = (
            "Y" if cmd_st.reached_notch else
            "Y" if target_n is not None and lever is not None
            and int(lever) == int(target_n) else
            "N" if target_n is not None else "—"
        )
        ipc_err = cmd_st.last_error or "—"
        had_cmd = last_id > 0 or cmd_q > 0
        self._loop_metrics.record_heartbeat(
            cf=confirmed, match=match, had_cmd=had_cmd)
        self._log.info(
            "heartbeat modo=%s  loop_hz=%.1f  work=%.0fms  sleep=%.0fms  tgt=%.0fHz  "
            "spd=%s  lim=%s  next_lim=%s  lim2=%s  elim=%.1f  seq=%s  "
            "dist=%s  probe=%s  frozen=%s  stale=%s  mandos=%s  ctrl=%s  "
            "p1on=%s  telem=%s  age=%s  telem_poll=%s  "
            "lua=%s dmi=%s  "
            "cmd_q=%d id=%d cf=%s ack=%.0fms ret=%d err=%s via=%s match=%s "
            "lever=%s hud=%s  "
            "P=%s  fill=%.2fs/%d  lrn=%s",
            self.conn.mode,
            self._loop_hz_real,
            self._last_tick_ms,
            self._last_sleep_ms,
            self.config.loop_hz,
            f"{spd:.1f}" if spd is not None else "—",
            f"{lim:.0f}" if lim is not None else "—",
            f"{next_lim:.0f}" if next_lim is not None else "—",
            (
                f"{t.get('next_limit_2_mph'):.0f}"
                if t.get("next_limit_2_mph") is not None else "—"
            ),
            self.decider.effective_limit,
            t.get("probe_seq", "?"),
            format_distance(dist, units) if dist is not None else "—",
            format_distance(probe_dist, units) if probe_dist is not None else "—",
            "Y" if frozen else "N",
            "Y" if t.get("probe_stale") else "N",
            self.conn.control_channel(),
            skip,
            "Y" if self.decider.p1_active else "N",
            telem_src,
            f"{float(telem_age):.0f}ms" if telem_age is not None else "—",
            f"{float(telem_poll):.1f}Hz" if telem_poll else "—",
            "1" if t.get("doors_telem") is True else (
                "0" if t.get("doors_telem") is False else "—"),
            "1" if t.get("doors_dmi") is True else (
                "0" if t.get("doors_dmi") is False else "—"),
            cmd_q,
            last_id,
            confirmed,
            ack_ms,
            cmd_st.retries,
            ipc_err,
            cmd_st.last_via or "—",
            match,
            str(lever) if lever is not None else "—",
            str(hud) if hud is not None else "—",
            p_txt,
            fill_s,
            fill_n,
            lrn,
        )

    def _log_probe_mod(self) -> None:
        if self._probe_mod_logged or self.conn.mode != "ue4ss":
            return
        self._probe_mod_logged = True
        flags = probe_mod_flags(self.telem)
        rep = self.conn.channel_report()
        self._log.info(
            "Probe mod: %s  getdata=%s  "
            "lever=%s  last_cmd_id=%s  last_ack_ok=%s  brake_cyl=%s",
            probe_mod_label(flags),
            rep.get("getdata", "?"),
            self.telem.get("lever_notch", "—"),
            self.telem.get("last_cmd_id", "—"),
            self.telem.get("last_ack_ok", "—"),
            self.telem.get("brake_cyl_bar", "—"),
        )
        if not flags.get("lever_notch") or not flags.get("last_cmd_id"):
            self._log.warning(
                "Mod Lua antiguo — ejecuta install_ue4ss_probe.bat y reinicia TSW6")

    def _log_channel_summary(self) -> None:
        """Resumen canal cada ~10 s (criterios CANAL_CONTROL)."""
        now = time.monotonic()
        if now - self._channel_summary_t < 10.0:
            return
        self._channel_summary_t = now
        if self.conn.mode != "ue4ss":
            return
        rep = self.conn.channel_report()
        ctrl = self.controller.session_metrics()
        lm = self._loop_metrics
        verdict = acceptance_verdict(
            loop=lm,
            channel=rep,
            controller=ControllerMetrics(**ctrl),
            telem_poll_hz=float(rep.get("telem_poll_hz") or 0.0),
            mod_flags=rep.get("mod_flags") or probe_mod_flags(self.telem),
        )
        self._log.info(
            "canal [%s]  ipc_ok=%d/%d (%.0f%%)  http_ok=%d  via=%s  ack_p95=%.0fms  "
            "enq=%d ret=%d drop=%d err=%s  "
            "async=%d KEY=%d p1rej=%d  "
            "ticks=%d work_max=%.0fms slow=%d  "
            "loop_hz=%.1f-%.1f  telem_poll=%.1fHz  mod=%s",
            verdict,
            int(rep.get("ipc_ok", 0)),
            int(rep.get("cmd_total", 0)),
            float(rep.get("ack_ok_pct", 0.0)),
            int(rep.get("http_ok", 0)),
            rep.get("last_via", "—"),
            float(rep.get("ack_p95_ms", 0.0)),
            int(rep.get("enqueued", 0)),
            int(rep.get("retries", 0)),
            int(rep.get("drops", 0)),
            rep.get("last_error", "—"),
            ctrl.get("ipc_async", 0),
            ctrl.get("keyboard", 0),
            ctrl.get("p1_rejected", 0),
            lm.ticks,
            lm.work_max_ms,
            lm.work_over_150,
            lm.loop_hz_min if lm.loop_hz_min < 999 else 0.0,
            lm.loop_hz_max,
            float(rep.get("telem_poll_hz") or 0.0),
            rep.get("mod", "?"),
        )

    def _log_session_summary(self, label: str) -> None:
        """Resumen al cerrar — una línea con veredicto PASS/WARN/FAIL."""
        rep = self.conn.channel_report()
        ctrl = self.controller.session_metrics()
        lm = self._loop_metrics
        flags = rep.get("mod_flags") or probe_mod_flags(self.telem)
        verdict = acceptance_verdict(
            loop=lm,
            channel=rep,
            controller=ControllerMetrics(**ctrl),
            telem_poll_hz=float(rep.get("telem_poll_hz") or 0.0),
            mod_flags=flags,
        )
        cf_total = lm.heartbeats_cf_y + lm.heartbeats_cf_n
        cf_pct = (
            100.0 * lm.heartbeats_cf_y / cf_total if cf_total else 0.0
        )
        self._log.info(
            "═══ SESIÓN CANAL %s [%s] ═══  log=%s",
            label.upper(), verdict,
            self._session_log_path or "—",
        )
        self._log.info(
            "  bucle: ticks=%d  loop_hz=%.1f-%.1f  work_max=%.0fms  "
            "slow(>150ms)=%d",
            lm.ticks,
            lm.loop_hz_min if lm.loop_hz_min < 999 else 0.0,
            lm.loop_hz_max,
            lm.work_max_ms,
            lm.work_over_150,
        )
        self._log.info(
            "  mandos: ipc_ok=%d  http_ok=%d  total_ok=%d/%d (%.0f%%)  "
            "ack_p95=%.0fms  enqueued=%d  "
            "retries=%d  drops=%d  último_via=%s  último_err=%s",
            int(rep.get("ipc_ok", 0)),
            int(rep.get("http_ok", 0)),
            int(rep.get("cmd_ok", 0)),
            int(rep.get("cmd_total", 0)),
            float(rep.get("ack_ok_pct", 0.0)),
            float(rep.get("ack_p95_ms", 0.0)),
            int(rep.get("enqueued", 0)),
            int(rep.get("retries", 0)),
            int(rep.get("drops", 0)),
            rep.get("last_via", "—"),
            rep.get("last_error", "—"),
        )
        self._log.info(
            "  mandos: async=%d  sync=%d  KEY=%d  p1_rejected=%d  "
            "cf_hb=%.0f%%  match_hb=%d  mod=%s",
            ctrl.get("ipc_async", 0),
            ctrl.get("ipc_sync", 0),
            ctrl.get("keyboard", 0),
            ctrl.get("p1_rejected", 0),
            cf_pct,
            lm.heartbeats_match_y,
            rep.get("mod", "?"),
        )
        if verdict == "FAIL":
            self._log.warning(
                "Canal FAIL — revisar install_ue4ss_probe.bat, F7, "
                "y líneas IPC async en este log")
        elif verdict == "WARN":
            self._log.warning(
                "Canal WARN — ver líneas 'canal [...]' y IPC async en el log")

    def _log_pause_state(self, label: str) -> None:
        """Línea inmediata al pulsar Pausar/Reanudar (visible en panel Depuración)."""
        t = self.telem
        dist = t.get("distance_next_m")
        probe_dist = t.get("probe_dist_limit_m")
        units = str(t.get("distance_units") or "uk_imperial")
        dist_txt = format_distance(dist, units) if dist is not None else "—"
        self._log.info(
            "%s  elim=%.1f  lim=%s  dist=%s  probe=%s  next=%s  seq=%s  spd=%s",
            label,
            self.decider.effective_limit,
            f"{t.get('limit_mph'):.0f}" if t.get("limit_mph") is not None else "—",
            dist_txt,
            format_distance(probe_dist, units) if probe_dist is not None else "—",
            f"{t.get('next_limit_mph', '?')}@{dist_txt}"
            if dist is not None and t.get("next_limit_mph") is not None
            else "?",
            t.get("probe_seq", "?"),
            f"{t.get('speed_mph'):.1f}" if t.get("speed_mph") is not None else "—",
        )

    def _log_pause_diag(self) -> None:
        """Planning en pausa (autopilot o juego congelado) — comparar dist vs probe."""
        ap_pause = self.decider.paused
        game_frozen = bool(self.telem.get("probe_motion_frozen"))
        if not ap_pause and not game_frozen:
            return
        now = time.monotonic()
        if now - self._pause_diag_t < 1.0:
            return
        self._pause_diag_t = now
        t = self.telem
        dist = t.get("distance_next_m")
        probe_dist = t.get("probe_dist_limit_m")
        units = str(t.get("distance_units") or "uk_imperial")
        drift = (
            float(dist) - float(probe_dist)
            if dist is not None and probe_dist is not None
            else None
        )
        dist_txt = format_distance(dist, units) if dist is not None else "—"
        self._log.info(
            "PAUSA ap=%s game_frozen=%s  elim=%.1f  lim=%s  "
            "dist=%s  probe=%s  drift=%s  next=%s  seq=%s  spd=%s",
            "Y" if ap_pause else "N",
            "Y" if game_frozen else "N",
            self.decider.effective_limit,
            f"{t.get('limit_mph'):.0f}" if t.get("limit_mph") is not None else "—",
            dist_txt,
            format_distance(probe_dist, units) if probe_dist is not None else "—",
            f"{drift:+.1f}m" if drift is not None else "—",
            f"{t.get('next_limit_mph', '?')}@{dist_txt}"
            if dist is not None and t.get("next_limit_mph") is not None
            else "?",
            t.get("probe_seq", "?"),
            f"{t.get('speed_mph'):.1f}" if t.get("speed_mph") is not None else "—",
        )

    def _sync_handle(self) -> None:
        handle_notch = self.telem.get("handle_notch")
        if handle_notch is not None:
            self._last_state_handle = int(handle_notch)
            self._handle_synced = True
            return
        if self._handle_synced:
            return
        # No bloquear ~5s con teclado hasta que el probe/API esté conectado.
        if self.conn.mode != "ue4ss" or not self.telem:
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
                   action: str, final: str, *, cmd_sent: bool = False,
                   state: Optional[TrainState] = None,
                   override: Optional[str] = None) -> None:
        if self.decider.paused or self.telem.get("probe_motion_frozen"):
            return
        self._log_cycle_n += 1
        want_info = self._log_cycle_n <= 5
        want_debug = (
            self._log_cycle_n > 5 and self._log_cycle_n % 40 == 0
        )
        if want_info:
            if not self._log.isEnabledFor(logging.INFO):
                return
        elif want_debug:
            if not self._log.isEnabledFor(logging.DEBUG):
                return
        else:
            return
        telem = self.telem
        cmd = self.decider.brake_command
        p1_txt = "—"
        if cmd is not None:
            p1_txt = cmd.display_action()
            if cmd.target_notch is not None:
                p1_txt += f"→N{cmd.target_notch}"
        nxt_stop = telem.get("next_stop_name")
        nxt_stop_d = telem.get("next_stop_distance_m")
        parada = (
            f"{nxt_stop}@{nxt_stop_d:.0f}m"
            if nxt_stop and nxt_stop_d is not None else "—"
        )
        sched = telem.get("schedule_source") or "—"
        tid = telem.get("hud_timetable_id")
        if tid:
            sched = f"{sched}#{tid}"
        arr = telem.get("next_stop_arrival") or "—"
        dep = telem.get("next_stop_departure") or "—"
        p1_inv = self.decider.p1_investigate_suffix
        handle = telem.get("handle_notch", 4)
        if state is not None:
            thr = state.throttle_notch
        else:
            try:
                hn = int(handle)
            except (TypeError, ValueError):
                hn = 4
            thr = max(0, hn - 4) if hn > 4 else 0
        stn_d = telem.get("next_stop_distance_m")
        lim_d = telem.get("distance_next_m")
        gap_txt = "—"
        if stn_d is not None and lim_d is not None:
            try:
                gap_txt = f"{float(stn_d) - float(lim_d):.0f}m"
            except (TypeError, ValueError):
                pass
        wd_txt = override if override and override != action else "—"
        p_txt, lrn, fill_s, fill_n = self._learner_snapshot()
        line = (
            "spd=%5.1f  lim=%4.1f  elim=%5.1f  notch=%-2s  thr=%d  action=%-11s  "
            "final=%-11s  wd=%-11s  p1=%-10s  ipc=%s  fsm=%-10s  stop=%-24s  "
            "next_lim=%s@%sm  lim2=%s@%sm  parada=%s  gap=%s  p1dbg=%s  p1on=%s  %s  "
            "sched=%s  arr=%s  dep=%s  ack=%s  grad=%s  P=%s  fill=%.2fs/%d  lrn=%s"
        )
        args = (
            speed, limit,
            self.decider.effective_limit,
            telem.get("handle_notch", "?"),
            thr,
            action, final,
            wd_txt,
            p1_txt,
            "OK" if cmd_sent else "—",
            self.decider.station_state or "-",
            self.decider.station_name or "-",
            f"{telem.get('next_limit_mph', '?')}",
            f"{telem.get('distance_next_m', '?')}",
            f"{telem.get('next_limit_2_mph') or '—'}",
            f"{telem.get('distance_next_2_m') if telem.get('distance_next_2_m') is not None else '—'}",
            parada,
            gap_txt,
            self.decider.p1_debug or "—",
            "Y" if self.decider.p1_active else "N",
            p1_inv or "—",
            sched,
            arr,
            dep,
            "Y" if telem.get("ack_required") else "N",
            f"{telem.get('gradient_pct') or 0.0:+.1f}%",
            p_txt,
            fill_s,
            fill_n,
            lrn,
        )
        if self._log_cycle_n <= 5:
            self._log.info(line, *args)
        else:
            self._log.debug(line, *args)
