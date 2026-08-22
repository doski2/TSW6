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
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from autopilot_core import AutopilotConfig, AutopilotEngine, AutopilotSnapshot

_PADX = 8
_PADY = 4
_UI_MS = 50
_LOOP_HZ = 20.0

_ACTION_COLORS = {
    "ACCELERATE": "#2a7",
    "HOLD": "#07a",
    "COAST": "#a80",
    "BRAKE": "#c33",
    "HARDBRAKE": "#e00",
    "FULLSTOP": "#90c",
    "PAUSED": "#888",
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
        self._snap_lock = threading.Lock()
        self._control_error: Optional[str] = None

        root.title("TSW6 — Autopilot")
        root.geometry("900x780")
        root.minsize(720, 600)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        self._build_ui()
        threading.Thread(target=self._control_loop, daemon=True,
                         name="autopilot-control").start()
        self._schedule_ui_refresh()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=_PADX, pady=_PADY)

        self.lbl_title = ttk.Label(
            top, text="TSW6 Autopilot", font=("Segoe UI", 13, "bold"))
        self.lbl_title.pack(anchor=tk.W)
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

        bottom = ttk.LabelFrame(self.root, text="Acción")
        bottom.pack(fill=tk.X, padx=_PADX, pady=_PADY)
        self.lbl_action = ttk.Label(
            bottom, text="—", font=("Consolas", 14, "bold"))
        self.lbl_action.pack(anchor=tk.W, padx=8, pady=6)
        self.lbl_fps = ttk.Label(bottom, text="", foreground="#666")
        self.lbl_fps.pack(anchor=tk.W, padx=8, pady=(0, 6))

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
            "Puertas",
            "ACK / supervisión",
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
        cols2 = ("name", "dist_m", "platform_m")
        self.tree_stations = ttk.Treeview(
            st_frame, columns=cols2, show="headings", height=6)
        self.tree_stations.heading("name", text="Estación")
        self.tree_stations.heading("dist_m", text="Distancia m")
        self.tree_stations.heading("platform_m", text="Andén m")
        self.tree_stations.column("name", width=220)
        self.tree_stations.column("dist_m", width=100)
        self.tree_stations.column("platform_m", width=90)
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
        col = "#2a7" if s.conn_mode in ("ue4ss", "tsw_api") else "#a60"
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
                s.next_limit_mph, s.distance_next_m, s.speed_mph))
        self.lbl_next_limit_2.configure(
            text=self._format_limit_ahead(
                s.next_limit_2_mph, s.distance_next_2_m, s.speed_mph))
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
        self.lbl_fsm.configure(text=fsm)
        self.lbl_doors.configure(text="ABIERTAS" if s.doors_open else "cerradas")
        self.lbl_ack.configure(
            text=f"ACK={'Sí' if s.ack_required else 'No'}  {s.supervision}")
        self.lbl_rain.configure(text=f"{s.rain_intensity:.2f}")

        if spd is not None and lim is not None and lim > 0:
            self.prog_speed.configure(value=min(130.0, (spd / lim) * 100))

        action = s.final_action
        if s.paused:
            action = "PAUSED"
        color = _ACTION_COLORS.get(action, "#333")
        extra = ""
        if s.override:
            extra = f"  (override: {s.override})"
        self.lbl_action.configure(
            text=f"{action}{extra}  ← decider: {s.action}"
                 f"  {'[cmd OK]' if s.last_cmd_sent else '[sin cmd]'}",
            foreground=color)
        self.lbl_fps.configure(
            text=(
                f"{s.fps:.1f} Hz"
                f"   ·   probe seq={s.probe_seq if s.probe_seq is not None else '?'}"
                f"   age={s.probe_age_ms:.0f}ms"
                if s.probe_age_ms is not None
                else f"{s.fps:.1f} Hz   ·   probe seq={s.probe_seq if s.probe_seq is not None else '?'}"
            ))

        self._refresh_planning(s)
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
                    f"{dist:.1f}" if isinstance(dist, (int, float)) else "—",
                    f"{brake:.0f}" if isinstance(brake, (int, float)) else "—",
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
                self.tree_stations.insert("", tk.END, values=(
                    st.get("name", "?"),
                    f"{st.get('distance_m', 0):.0f}",
                    f"{st.get('platform_length_m', st.get('platform_m', 0)):.0f}"
                    if st.get("platform_length_m") or st.get("platform_m") else "—",
                ))

        if s.next_limit_mph is not None and s.distance_next_m is not None:
            self.lbl_next_brake.configure(
                **self._p1_brake_style(
                    s, s.next_limit_mph, s.distance_next_m, label="P1 #1"))
        else:
            self.lbl_next_brake.configure(text="Sin datos de próximo límite")

        if s.next_limit_2_mph is not None and s.distance_next_2_m is not None:
            self.lbl_next_brake_2.configure(
                **self._p1_brake_style(
                    s, s.next_limit_2_mph, s.distance_next_2_m, label="P1 #2"))
        else:
            self.lbl_next_brake_2.configure(text="")

    def _format_limit_ahead(
            self, mph: Optional[float], dist_m: Optional[float],
            speed_mph: Optional[float]) -> str:
        if mph is None or dist_m is None:
            return "—"
        extra = ""
        if speed_mph is not None and mph < speed_mph - 0.5:
            extra = "  ↓"
        return f"{mph:.0f} mph @ {dist_m:.1f} m{extra}"

    def _p1_brake_style(
            self, s: AutopilotSnapshot, limit_mph: float, dist_m: float,
            *, label: str) -> dict:
        need = None
        if s.speed_mph is not None:
            need = self.engine.decider.braking_distance(
                s.speed_mph, limit_mph)
        if not need:
            return {"text": f"{label}: —", "foreground": "#a60"}
        ok = dist_m >= need
        return {
            "text": (f"{label}: {'OK' if ok else 'FRENAR'} — "
                     f"{limit_mph:.0f} mph @ {dist_m:.0f}m "
                     f"(freno ~{need:.0f}m)"),
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
        parser.add_argument("--learn", action="store_true",
                            help="Re-aprender calibración en vivo")
        parser.add_argument("--stop", type=float, default=None, metavar="MILLAS",
                            help="Distancia a próxima parada en millas")
        args = parser.parse_args()
        config = AutopilotConfig(
            target_mph=args.target,
            no_control=args.no_control,
            manual=args.manual,
            learn=args.learn,
            stop_miles=args.stop,
            loop_hz=_LOOP_HZ,
        )

    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"autopilot_{time.strftime('%Y%m%d_%H%M%S')}.log"

    engine = AutopilotEngine(config, log_path=log_path)
    logging.getLogger("tsw.autopilot").info("Autopilot GUI — log: %s", log_path)

    if not config.no_control and not engine.conn.has_control_api():
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
