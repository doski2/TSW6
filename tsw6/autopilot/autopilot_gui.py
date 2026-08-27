#!/usr/bin/env python3
"""
autopilot_gui.py — Interfaz gráfica del autopilot TSW6 (tkinter).

Muestra telemetría, planning (límites y estaciones), FSM y log de depuración.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import tkinter as tk
from tsw6.paths import LOGS_DIR
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from tsw6.autopilot.autopilot_core import AutopilotConfig, AutopilotEngine, AutopilotSnapshot
from tsw6.autopilot.distance_format import (
    distance_unit_label,
    format_distance,
    format_distance_pair,
)

_PADX = 8
_PADY = 4
_UI_MS = 50
_LOOP_HZ = 20.0

from tsw6.autopilot.control_actions import (
    BRAKE, BRAKE_FAST, COAST, EMERGENCY, HOLD, PAUSED, RELEASE,
)

_ACTION_COLORS = {
    HOLD: "#07a",
    COAST: "#a80",
    RELEASE: "#07a",
    BRAKE: "#c33",
    BRAKE_FAST: "#e00",
    EMERGENCY: "#f0f",
    PAUSED: "#888",
}


class AutopilotApp:
    def __init__(self, root: tk.Tk, engine: AutopilotEngine) -> None:
        self.root = root
        self.engine = engine
        self._running = True
        self._ui_tick = 0
        self._last_snap: Optional[AutopilotSnapshot] = None
        self._last_limits_sig: Optional[tuple] = None
        self._last_stations_sig: Optional[tuple] = None
        self._last_dist_units: Optional[str] = None
        self._snap_lock = threading.Lock()
        self._control_error: Optional[str] = None

        root.title("TSW6 — Autopilot")
        root.geometry("900x820")
        root.minsize(720, 680)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        self._build_ui()
        threading.Thread(target=self._control_loop, daemon=True,
                         name="autopilot-control").start()
        self._schedule_ui_refresh()

    def _build_ui(self) -> None:
        # Barra inferior primero (side=BOTTOM) para que no la empuje el notebook.
        bottom = ttk.LabelFrame(self.root, text="Acción")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=_PADX, pady=_PADY)

        action_row = ttk.Frame(bottom)
        action_row.pack(fill=tk.X, padx=8, pady=(6, 2))
        self.lbl_action_main = ttk.Label(
            action_row, text="—", font=("Segoe UI", 18, "bold"), width=14)
        self.lbl_action_main.pack(side=tk.LEFT, anchor=tk.NW)
        detail_col = ttk.Frame(action_row)
        detail_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
        self.lbl_action_detail = ttk.Label(
            detail_col, text="—", font=("Consolas", 10), justify=tk.LEFT)
        self.lbl_action_detail.pack(anchor=tk.W, fill=tk.X)
        self.lbl_action_cmd = ttk.Label(
            detail_col, text="", font=("Consolas", 9), foreground="#555")
        self.lbl_action_cmd.pack(anchor=tk.W, fill=tk.X)
        self.lbl_fps = ttk.Label(
            bottom, text="", font=("Consolas", 9), foreground="#666")
        self.lbl_fps.pack(anchor=tk.W, padx=8, pady=(0, 6))

        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=_PADX, pady=_PADY)

        self.lbl_title = ttk.Label(
            top, text="TSW6 Autopilot", font=("Segoe UI", 13, "bold"))
        self.lbl_title.pack(anchor=tk.W)
        self.lbl_probe = ttk.Label(
            top, text="● Probe", font=("Segoe UI", 10, "bold"), foreground="#c33")
        self.lbl_probe.pack(anchor=tk.W)
        self.lbl_conn = ttk.Label(top, text="Conectando…", foreground="#a60")
        self.lbl_conn.pack(anchor=tk.W)
        self.lbl_vehicle = ttk.Label(top, text="", foreground="#555")
        self.lbl_vehicle.pack(anchor=tk.W)

        ctrl = ttk.LabelFrame(self.root, text="Control")
        ctrl.pack(fill=tk.X, padx=_PADX, pady=_PADY)

        row1 = ttk.Frame(ctrl)
        row1.pack(fill=tk.X, padx=6, pady=4)
        self.btn_pause = ttk.Button(row1, text="Pausar", command=self._toggle_pause)
        self.btn_pause.pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Neutro (R)", command=self.engine.reset_neutral).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Sync handle (N)", command=self.engine.force_neutral).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Parada (S)", command=self._set_stop).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Sin paradas", command=self.engine.clear_stop).pack(
            side=tk.LEFT, padx=2)

        row2 = ttk.Frame(ctrl)
        row2.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(row2, text="Objetivo mph:").pack(side=tk.LEFT)
        self.var_target = tk.StringVar(
            value=str(int(self.engine.config.target_mph)))
        self.ent_target = ttk.Entry(row2, textvariable=self.var_target, width=6)
        self.ent_target.pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="Aplicar", command=self._apply_target).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(row2, text="−5", width=4,
                   command=lambda: self._bump_target(-5)).pack(side=tk.LEFT, padx=1)
        ttk.Button(row2, text="+5", width=4,
                   command=lambda: self._bump_target(5)).pack(side=tk.LEFT, padx=1)
        ttk.Label(row2, text="(0 = seguir límite de vía)").pack(side=tk.LEFT, padx=8)

        row3 = ttk.Frame(ctrl)
        row3.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.var_learn = tk.BooleanVar(value=self.engine.config.learn)
        ttk.Checkbutton(
            row3,
            text="Auto-aprender (todas las muescas, estilo Dastsc)",
            variable=self.var_learn,
            command=self._toggle_learn,
        ).pack(side=tk.LEFT)
        ttk.Label(
            row3,
            text="Desmarcar: solo refina al frenar (muescas 0–3)",
            foreground="#666",
        ).pack(side=tk.LEFT, padx=8)

        row4 = ttk.Frame(ctrl)
        row4.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.var_schedule_slack = tk.BooleanVar(
            value=self.engine.config.schedule_slack)
        ttk.Checkbutton(
            row4,
            text="Holgura de horario (coast por ETA)",
            variable=self.var_schedule_slack,
            command=self._toggle_schedule_slack,
        ).pack(side=tk.LEFT)
        ttk.Label(
            row4,
            text="Desmarcado: frenar solo por distancia/física (recomendado en pruebas)",
            foreground="#666",
        ).pack(side=tk.LEFT, padx=8)

        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True, padx=_PADX, pady=_PADY)

        self.notebook = ttk.Notebook(mid)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        tab_live = ttk.Frame(self.notebook)
        self.notebook.add(tab_live, text="Estado")
        self._build_live_tab(tab_live)

        tab_plan = ttk.Frame(self.notebook)
        self.notebook.add(tab_plan, text="Planning")
        self._build_plan_tab(tab_plan)

        tab_debug = ttk.Frame(self.notebook)
        self.notebook.add(tab_debug, text="Depuración")
        self._build_debug_tab(tab_debug)

        tab_learn = ttk.Frame(self.notebook)
        self.notebook.add(tab_learn, text="Aprendizaje")
        self._build_learn_tab(tab_learn)

        self.root.bind("<Configure>", self._on_root_configure)

    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        wrap = max(320, event.width - 220)
        self.lbl_action_detail.configure(wraplength=wrap)

    def _build_live_tab(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        rows: list[tuple[str, ttk.Label]] = []
        for title in (
            "Velocidad",
            "Límite vía",
            "Límite efectivo",
            "Próx. límite",
            "2º límite",
            "Handle (API)",
            "Aceleración",
            "Gradiente",
            "Estación FSM",
            "lua / dmi",
            "Supervisión",
            "Lluvia",
        ):
            rows.append((title, ttk.Label(grid, text="—", font=("Consolas", 10))))

        for i, (title, lbl) in enumerate(rows):
            ttk.Label(grid, text=title + ":", width=18).grid(
                row=i, column=0, sticky=tk.W, pady=2)
            lbl.grid(row=i, column=1, sticky=tk.W, pady=2)

        (
            self.lbl_speed,
            self.lbl_limit,
            self.lbl_eff_limit,
            self.lbl_next_limit,
            self.lbl_next_limit_2,
            self.lbl_handle,
            self.lbl_accel,
            self.lbl_grad,
            self.lbl_fsm,
            self.lbl_doors,
            self.lbl_ack,
            self.lbl_rain,
        ) = [lbl for _, lbl in rows]

        self.prog_speed = ttk.Progressbar(grid, length=280, maximum=130)
        self.prog_speed.grid(row=0, column=2, padx=12, pady=2, sticky=tk.W)

    def _build_plan_tab(self, parent: ttk.Frame) -> None:
        lim_frame = ttk.LabelFrame(parent, text="Próximos límites de velocidad")
        lim_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        cols = ("mph", "dist_m", "brake_m")
        self.tree_limits = ttk.Treeview(
            lim_frame, columns=cols, show="headings", height=6)
        self.tree_limits.heading("mph", text="Límite mph")
        self.tree_limits.heading("dist_m", text="Distancia m")
        self.tree_limits.heading("brake_m", text="Freno desde m")
        self.tree_limits.column("mph", width=90)
        self.tree_limits.column("dist_m", width=100)
        self.tree_limits.column("brake_m", width=110)
        self.tree_limits.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.lbl_next_brake = ttk.Label(lim_frame, text="", foreground="#a60")
        self.lbl_next_brake.pack(anchor=tk.W, padx=6, pady=2)
        self.lbl_next_brake_2 = ttk.Label(lim_frame, text="", foreground="#a60")
        self.lbl_next_brake_2.pack(anchor=tk.W, padx=6, pady=2)

        st_frame = ttk.LabelFrame(parent, text="Estaciones programadas")
        st_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.lbl_next_stop = ttk.Label(
            st_frame, text="Próxima parada: —", foreground="#07a")
        self.lbl_next_stop.pack(anchor=tk.W, padx=6, pady=(4, 0))
        cols2 = ("name", "dist_m", "arrival", "departure")
        self.tree_stations = ttk.Treeview(
            st_frame, columns=cols2, show="headings", height=6)
        self.tree_stations.heading("name", text="Estación")
        self.tree_stations.heading("dist_m", text="Distancia m")
        self.tree_stations.heading("arrival", text="Llegada")
        self.tree_stations.heading("departure", text="Salida")
        self.tree_stations.column("name", width=200)
        self.tree_stations.column("dist_m", width=90)
        self.tree_stations.column("arrival", width=72)
        self.tree_stations.column("departure", width=72)
        self.tree_stations.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _build_debug_tab(self, parent: ttk.Frame) -> None:
        info = ttk.Frame(parent)
        info.pack(fill=tk.X, padx=6, pady=4)
        self.lbl_hwnd = ttk.Label(info, text="hwnd: —", font=("Consolas", 9))
        self.lbl_hwnd.pack(anchor=tk.W)
        self.lbl_ocr = ttk.Label(info, text="OCR: —", font=("Consolas", 9))
        self.lbl_ocr.pack(anchor=tk.W)

        self.txt_log = tk.Text(
            parent, wrap=tk.WORD, height=20, font=("Consolas", 9),
            relief=tk.FLAT, bg="#1e1e1e", fg="#d4d4d4")
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.txt_log.configure(state=tk.DISABLED)

    def _build_learn_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=6, pady=6)
        self.lbl_learn_profile = ttk.Label(top, text="Perfil: —", font=("Segoe UI", 10))
        self.lbl_learn_profile.pack(anchor=tk.W)
        self.lbl_learn_state = ttk.Label(
            top, text="Estado: —", font=("Consolas", 9), foreground="#444")
        self.lbl_learn_state.pack(anchor=tk.W, pady=(2, 0))

        prog = ttk.LabelFrame(parent, text="Progreso matriz (8 muestras/celda)")
        prog.pack(fill=tk.X, padx=6, pady=4)
        self.learn_prog_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(prog, variable=self.learn_prog_var, maximum=100).pack(
            fill=tk.X, padx=6, pady=4)
        self.lbl_learn_prog = ttk.Label(prog, text="0/0 celdas")
        self.lbl_learn_prog.pack(anchor=tk.W, padx=6, pady=(0, 4))

        const = ttk.LabelFrame(parent, text="Constantes de frenado (perfil activo)")
        const.pack(fill=tk.X, padx=6, pady=4)
        grid = ttk.Frame(const)
        grid.pack(fill=tk.X, padx=6, pady=4)
        self.lbl_learn_max = ttk.Label(grid, text="MAX_DECEL: —", font=("Consolas", 9))
        self.lbl_learn_max.grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        self.lbl_learn_tgt = ttk.Label(grid, text="TARGET_DECEL: —", font=("Consolas", 9))
        self.lbl_learn_tgt.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)
        self.lbl_learn_coast = ttk.Label(grid, text="COAST: —", font=("Consolas", 9))
        self.lbl_learn_coast.grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        self.lbl_learn_eff = ttk.Label(grid, text="eff_max (lluvia): —", font=("Consolas", 9))
        self.lbl_learn_eff.grid(row=1, column=1, sticky=tk.W, padx=4, pady=2)
        self.lbl_learn_hint = ttk.Label(
            const,
            text="Si pasas de estación con parada@ bajando bien, revisa MAX_DECEL "
                 "y muestras en muesca 0–3.",
            foreground="#666", wraplength=820, justify=tk.LEFT)
        self.lbl_learn_hint.pack(anchor=tk.W, padx=6, pady=(0, 4))

        samp = ttk.LabelFrame(parent, text="Muestras por muesca")
        samp.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.tree_learn = ttk.Treeview(
            samp, columns=("notch", "samples"), show="headings", height=9)
        self.tree_learn.heading("notch", text="Muesca")
        self.tree_learn.heading("samples", text="Muestras")
        self.tree_learn.column("notch", width=200)
        self.tree_learn.column("samples", width=80)
        self.tree_learn.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._last_learn_sig: Optional[tuple] = None

    def _toggle_learn(self) -> None:
        self.engine.set_learn_enabled(bool(self.var_learn.get()))

    def _toggle_schedule_slack(self) -> None:
        self.engine.set_schedule_slack_enabled(bool(self.var_schedule_slack.get()))

    def _toggle_pause(self) -> None:
        paused = self.engine.toggle_pause()
        self.btn_pause.configure(text="Reanudar" if paused else "Pausar")

    def _apply_target(self) -> None:
        try:
            val = float(self.var_target.get().strip())
            self.engine.set_target_mph(val)
        except ValueError:
            messagebox.showwarning("Objetivo", "Introduce un número válido en mph.")

    def _bump_target(self, delta: int) -> None:
        self.engine.adjust_target(delta)
        self.var_target.set(str(int(self.engine.decider.target_mph)))

    def _set_stop(self) -> None:
        raw = simpledialog.askstring(
            "Parada manual",
            "Distancia a próxima parada en millas\n(Enter vacío = modo automático):")
        if raw is None:
            return
        raw = raw.strip()
        if raw == "":
            self.engine.clear_stop()
            return
        try:
            self.engine.set_stop_miles(float(raw))
        except ValueError:
            messagebox.showwarning("Parada", "Introduce un número válido.")

    def _control_loop(self) -> None:
        while self._running:
            t0 = time.perf_counter()
            try:
                snap = self.engine.tick()
                with self._snap_lock:
                    self._last_snap = snap
            except Exception as exc:
                self._control_error = str(exc)
                self._running = False
                self.root.after(0, self._on_control_error)
                return
            elapsed = time.perf_counter() - t0
            self.engine.sleep_remainder(elapsed)

    def _on_control_error(self) -> None:
        messagebox.showerror(
            "Error",
            f"Error en bucle de control:\n{self._control_error or 'desconocido'}")

    def _schedule_ui_refresh(self) -> None:
        if not self._running and self._control_error:
            return
        with self._snap_lock:
            snap = self._last_snap
        if snap is not None:
            self._refresh_ui(snap)
        if self._running:
            self.root.after(_UI_MS, self._schedule_ui_refresh)

    def _refresh_ui(self, s: AutopilotSnapshot) -> None:
        mode_labels = {
            "ue4ss": "UE4SS probe ✓",
            "tsw_api": "TSW API ✓",
            "manual": "Manual",
            "searching": "Buscando conexión…",
        }
        mode = mode_labels.get(s.conn_mode, s.conn_mode)
        if s.probe_live:
            probe_txt = "● PROBE F7 ON — canal rápido (~20 Hz)"
            probe_col = "#2a7"
        elif s.conn_mode == "tsw_api":
            probe_txt = f"● {s.probe_hint or 'F7 OFF — HTTP lento (~2s)'}"
            probe_col = "#c80"
        elif s.probe_hint:
            probe_txt = f"● {s.probe_hint}"
            probe_col = "#c33"
        else:
            probe_txt = "● Sin probe — pulsa F7 en cabina"
            probe_col = "#c33"
        self.lbl_probe.configure(text=probe_txt, foreground=probe_col)

        col = "#2a7" if s.conn_mode == "ue4ss" else (
            "#c80" if s.conn_mode == "tsw_api" else "#a60")
        ch = s.control_channel
        if ch == "ipc":
            ctrl_txt = "Mandos: SendCommand ✓"
            ctrl_col = "#2a7"
        elif ch == "http":
            ctrl_txt = "Mandos: HTTPAPI ✓"
            ctrl_col = "#2a7"
        else:
            ctrl_txt = "Mandos: no disponibles (probe UE4SS o -HTTPAPI)"
            ctrl_col = "#c33"
        plan_txt = ""
        if s.stations:
            plan_txt = "   ·   Estaciones: HTTP"
        elif s.next_limit_mph is not None:
            plan_txt = "   ·   Límites: probe"
        conn_ok = s.conn_mode in ("ue4ss", "tsw_api")
        self.lbl_conn.configure(
            text=f"Fuente: {mode}   ·   {ctrl_txt}{plan_txt}",
            foreground=col if conn_ok else ctrl_col)

        if s.vehicle_name:
            self.lbl_vehicle.configure(text=f"Tren: {s.vehicle_name}")

        spd = s.speed_mph
        lim = s.limit_mph
        self.lbl_speed.configure(
            text=f"{spd:.1f} mph" if spd is not None else "—")
        self.lbl_limit.configure(
            text=f"{lim:.0f} mph" if lim is not None else "—")
        self.lbl_eff_limit.configure(text=f"{s.effective_limit:.1f} mph")
        self.lbl_next_limit.configure(
            text=self._format_limit_ahead(
                s.next_limit_mph, s.distance_next_m, s.speed_mph,
                units=s.distance_units))
        self.lbl_next_limit_2.configure(
            text=self._format_limit_ahead(
                s.next_limit_2_mph, s.distance_next_2_m, s.speed_mph,
                units=s.distance_units))
        self.lbl_handle.configure(
            text=str(s.handle_notch) if s.handle_notch is not None else "?")
        if s.acceleration_ms2 is not None:
            self.lbl_accel.configure(text=f"{s.acceleration_ms2:+.3f} m/s²")
        else:
            self.lbl_accel.configure(text="calculando…")
        if s.gradient_pct is not None:
            self.lbl_grad.configure(text=f"{s.gradient_pct:+.2f} %")
        else:
            self.lbl_grad.configure(text="—")

        fsm = s.station_state or "—"
        if s.station_name:
            fsm += f" → {s.station_name}"
        elif s.next_stop_name:
            fsm += f" → próx: {s.next_stop_name}"
        self.lbl_fsm.configure(text=fsm)
        lua = s.doors_telem
        dmi = s.doors_dmi
        lua_txt = "1" if lua is True else ("0" if lua is False else "—")
        dmi_txt = "1" if dmi is True else ("0" if dmi is False else "—")
        self.lbl_doors.configure(text=f"lua={lua_txt}  dmi={dmi_txt}")
        self.lbl_ack.configure(text=s.supervision or "—")
        self.lbl_rain.configure(text=f"{s.rain_intensity:.2f}")

        if spd is not None and lim is not None and lim > 0:
            self.prog_speed.configure(value=min(130.0, (spd / lim) * 100))

        action = s.final_action
        if s.paused:
            action = "PAUSED"
        elif s.brake_phase:
            action = s.brake_phase
        elif s.final_action == "RELEASE":
            action = "RELEASE"
        color = _ACTION_COLORS.get(action, "#333")
        if action in ("B1", "B2", "B3"):
            color = "#c33"
        extra = ""
        if s.override:
            extra = f"override: {s.override}"
        notch_txt = ""
        if s.brake_target_notch is not None:
            notch_txt = f" → N{s.brake_target_notch}"
        main_txt = f"{action}{notch_txt}"
        detail_parts = [f"decider: {s.action}"]
        if extra:
            detail_parts.append(extra)
        self.lbl_action_main.configure(text=main_txt, foreground=color)
        self.lbl_action_detail.configure(
            text="   ·   ".join(detail_parts))
        self.lbl_action_cmd.configure(
            text="Mando enviado ✓" if s.last_cmd_sent else "Sin mando en este tick",
            foreground="#2a7" if s.last_cmd_sent else "#888")
        self.lbl_fps.configure(
            text=(
                f"{s.fps:.1f} Hz"
                f"   ·   probe seq={s.probe_seq if s.probe_seq is not None else '?'}"
                f"   age={s.probe_age_ms:.0f}ms"
                if s.probe_age_ms is not None
                else f"{s.fps:.1f} Hz   ·   probe seq={s.probe_seq if s.probe_seq is not None else '?'}"
            ))

        self._refresh_planning(s)
        self._refresh_learn(s)
        self._refresh_log()
        self.lbl_hwnd.configure(
            text=f"hwnd: {s.hwnd:#010x}" if s.hwnd else "hwnd: no encontrada")
        ocr = "—"
        if s.ocr_stop_dist_m is not None:
            ocr = f"dist={s.ocr_stop_dist_m:.0f}m"
        if s.ocr_task:
            ocr += f"  task={s.ocr_task}"
        self.lbl_ocr.configure(text=f"OCR: {ocr}")

    def _refresh_planning(self, s: AutopilotSnapshot) -> None:
        units = s.distance_units
        src = s.schedule_source or "—"
        if s.next_stop_name:
            extra = ""
            if s.schedule_source == "hud_db" and s.hud_timetable_id:
                extra = f"  [horario HUD #{s.hud_timetable_id}]"
            elif s.schedule_source == "timetable_json":
                extra = "  [timetable.json]"
            sched = ""
            if s.next_stop_arrival or s.next_stop_departure:
                parts = []
                if s.next_stop_arrival:
                    parts.append(f"arr {s.next_stop_arrival}")
                if s.next_stop_departure:
                    parts.append(f"dep {s.next_stop_departure}")
                sched = "  ·  " + "  ".join(parts)
            dist_txt = (
                format_distance(s.next_stop_distance_m, units)
                if isinstance(s.next_stop_distance_m, (int, float))
                else "—"
            )
            self.lbl_next_stop.configure(
                text=(f"Próxima parada: {s.next_stop_name}  @ "
                      f"{dist_txt}{sched}{extra}"))
        elif s.stations:
            if s.schedule_source == "hud_db":
                hint = "sin coincidencia TrackData ↔ horario HUD"
            elif s.schedule_source == "timetable_json":
                hint = "sin coincidencia en timetable.json"
            else:
                hint = f"sin filtro de horario (fuente: {src})"
            self.lbl_next_stop.configure(text=f"Próxima parada: — ({hint})")
        else:
            self.lbl_next_stop.configure(
                text="Próxima parada: — (requiere DriverAid.TrackData vía HTTPAPI)")

        if units != self._last_dist_units:
            self._last_dist_units = units
            tag = distance_unit_label(units)
            self.tree_limits.heading("dist_m", text=f"Distancia ({tag})")
            self.tree_limits.heading("brake_m", text=f"Freno desde ({tag})")
            self.tree_stations.heading("dist_m", text=f"Distancia ({tag})")
            self.tree_stations.heading("arrival", text="Llegada")
            self.tree_stations.heading("departure", text="Salida")

        ahead = s.speed_limits_ahead
        if not ahead and s.next_limit_mph is not None:
            ahead = [{
                "limit_mph": s.next_limit_mph,
                "distance_m": s.distance_next_m,
                "brake_marker_m": s.brake_marker_m,
            }]
        limits_sig = tuple(
            (e.get("limit_mph"), round(float(e.get("distance_m", 0)), 1))
            for e in ahead[:8]
            if isinstance(e, dict)
        )
        if limits_sig != self._last_limits_sig:
            self._last_limits_sig = limits_sig
            for item in self.tree_limits.get_children():
                self.tree_limits.delete(item)
            for entry in ahead[:8]:
                if isinstance(entry, dict):
                    mph = entry.get("limit_mph", entry.get("mph", "?"))
                    dist = entry.get("distance_m", entry.get("dist_m"))
                    brake = entry.get("brake_marker_m", entry.get("brake_m"))
                else:
                    mph, dist, brake = entry[0], entry[1] if len(entry) > 1 else None, None
                self.tree_limits.insert("", tk.END, values=(
                    f"{mph:.0f}" if isinstance(mph, (int, float)) else str(mph),
                    format_distance(dist, units)
                    if isinstance(dist, (int, float)) else "—",
                    format_distance(brake, units)
                    if isinstance(brake, (int, float)) else "—",
                ))

        stations_sig = tuple(
            (st.get("name"), round(float(st.get("distance_m", 0)), 0))
            for st in s.stations[:8]
        )
        if stations_sig != self._last_stations_sig:
            self._last_stations_sig = stations_sig
            for item in self.tree_stations.get_children():
                self.tree_stations.delete(item)
            for st in s.stations[:8]:
                dist_m = st.get("distance_m", 0)
                self.tree_stations.insert("", tk.END, values=(
                    st.get("name", "?"),
                    format_distance(float(dist_m), units),
                    st.get("arrival") or "—",
                    st.get("departure") or "—",
                ))

        if s.next_limit_mph is not None and s.distance_next_m is not None:
            self.lbl_next_brake.configure(
                **self._p1_brake_style(
                    s, s.next_limit_mph, s.distance_next_m, label="P1 #1",
                    units=units))
        else:
            self.lbl_next_brake.configure(text="Sin datos de próximo límite")

        if s.next_limit_2_mph is not None and s.distance_next_2_m is not None:
            self.lbl_next_brake_2.configure(
                **self._p1_brake_style(
                    s, s.next_limit_2_mph, s.distance_next_2_m, label="P1 #2",
                    units=units))
        else:
            self.lbl_next_brake_2.configure(text="")

    def _refresh_learn(self, s: AutopilotSnapshot) -> None:
        mode = "ON" if s.learn_enabled else "OFF (solo freno)"
        sched = "ON" if s.schedule_slack_enabled else "OFF"
        self.lbl_learn_profile.configure(
            text=(
                f"Perfil: {s.learn_profile or '—'}   ·   "
                f"Auto-aprender: {mode}   ·   Holgura horario: {sched}"
            ))
        self.lbl_learn_state.configure(text=f"Learner: {s.learn_reason or '—'}")

        total = s.learn_total_cells
        done = s.learn_done_cells
        if total > 0:
            pct = 100.0 * done / total
            self.learn_prog_var.set(pct)
            self.lbl_learn_prog.configure(
                text=f"{done}/{total} celdas completas (≥8 muestras/celda)")
        else:
            self.learn_prog_var.set(0.0)
            self.lbl_learn_prog.configure(text="0/0 celdas")

        def _fmt(v: Optional[float]) -> str:
            return f"{v:.3f} m/s²" if v is not None else "—"

        self.lbl_learn_max.configure(text=f"MAX_DECEL: {_fmt(s.learn_max_decel)}")
        self.lbl_learn_tgt.configure(text=f"TARGET_DECEL: {_fmt(s.learn_target_decel)}")
        self.lbl_learn_coast.configure(text=f"COAST: {_fmt(s.learn_coast_decel)}")
        self.lbl_learn_eff.configure(text=f"eff_max: {_fmt(s.eff_max_decel)}")

        status = s.learn_confidence
        if isinstance(status, dict):
            sig = tuple(sorted((str(k), int(v)) for k, v in status.items()))
            if sig != self._last_learn_sig:
                self._last_learn_sig = sig
                for item in self.tree_learn.get_children():
                    self.tree_learn.delete(item)
                for label, count in sorted(status.items()):
                    self.tree_learn.insert("", tk.END, values=(label, count))

    def _format_limit_ahead(
            self, mph: Optional[float], dist_m: Optional[float],
            speed_mph: Optional[float],
            *,
            probe_dist_m: Optional[float] = None,
            units: str = "uk_imperial") -> str:
        if mph is None or dist_m is None:
            return "—"
        if dist_m <= 8.0:
            return "—"
        extra = ""
        if speed_mph is not None and mph < speed_mph - 0.5:
            extra = "  ↓"
        dist_txt = format_distance_pair(dist_m, probe_dist_m, units)
        return f"{mph:.0f} mph @ {dist_txt}{extra}"

    def _p1_brake_style(
            self, s: AutopilotSnapshot, limit_mph: float, dist_m: float,
            *, label: str, units: str = "uk_imperial") -> dict:
        need = None
        if s.speed_mph is not None:
            need = self.engine.decider.braking_distance(
                s.speed_mph, limit_mph)
        if not need:
            return {"text": f"{label}: —", "foreground": "#a60"}
        ok = dist_m >= need
        return {
            "text": (f"{label}: {'OK' if ok else 'FRENAR'} — "
                     f"{limit_mph:.0f} mph @ {format_distance(dist_m, units)} "
                     f"(freno ~{format_distance(need, units)})"),
            "foreground": "#2a7" if ok else "#c33",
        }

    def _refresh_log(self) -> None:
        lines = self.engine.log_lines[-40:]
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.insert(tk.END, "\n".join(lines))
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        if not self._running:
            self.root.destroy()
            return
        self._running = False
        self.engine.stop()
        if not self.engine.config.no_control:
            self.engine.reset_neutral()
        self.root.destroy()


def launch(config: Optional[AutopilotConfig] = None) -> None:
    """Arranca la GUI con la configuración indicada (o parsea sys.argv)."""
    if config is None:
        parser = argparse.ArgumentParser(description="TSW6 Autopilot — GUI")
        parser.add_argument("--target", type=float, default=0,
                            help="Velocidad objetivo mph (0=límite vía)")
        parser.add_argument("--no-control", action="store_true",
                            help="Solo monitorizar, sin mandos")
        parser.add_argument("--manual", action="store_true",
                            help="Telemetría manual")
        parser.add_argument("--no-learn", dest="learn", action="store_false",
                            help="No actualizar perfil en vivo (por defecto: sí aprende)")
        parser.set_defaults(learn=True)
        parser.add_argument("--schedule-slack", dest="schedule_slack",
                            action="store_true",
                            help="Activar holgura de horario en frenada (por defecto: off)")
        parser.set_defaults(schedule_slack=False)
        parser.add_argument("--stop", type=float, default=None, metavar="MILLAS",
                            help="Distancia a próxima parada en millas")
        args = parser.parse_args()
        config = AutopilotConfig(
            target_mph=args.target,
            no_control=args.no_control,
            manual=args.manual,
            learn=args.learn,
            schedule_slack=args.schedule_slack,
            stop_miles=args.stop,
            loop_hz=_LOOP_HZ,
        )

    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"autopilot_{time.strftime('%Y%m%d_%H%M%S')}.log"

    engine = AutopilotEngine(config, log_path=log_path)
    logging.getLogger("tsw.autopilot").info("Autopilot GUI — log: %s", log_path)

    if not config.no_control and engine.conn.mode == "searching":
        warn = tk.Tk()
        warn.withdraw()
        messagebox.showwarning(
            "Sin canal de mandos",
            "No se detectó escritura de mandos.\n\n"
            "Opciones:\n"
            "  • TelemetryProbeMod activo (SendCommand.txt / UE4SS)\n"
            "  • TSW6 con -HTTPAPI y CommAPIKey.txt\n\n"
            "Sin uno de ellos el autopilot no puede mover el freno.",
            parent=warn)
        warn.destroy()

    if config.manual:
        def _manual_prompt() -> dict:
            root = tk.Tk()
            root.withdraw()
            try:
                speed = float(simpledialog.askstring(
                    "Manual", "Velocidad actual (mph):") or "0")
                limit = float(simpledialog.askstring(
                    "Manual", "Límite de vía (mph):") or "0")
                return {"speed_mph": speed, "limit_mph": limit}
            finally:
                root.destroy()

        engine.set_manual_prompt(_manual_prompt)

    root = tk.Tk()
    AutopilotApp(root, engine)
    root.mainloop()


def main() -> None:
    launch()


if __name__ == "__main__":
    main()
