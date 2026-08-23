#!/usr/bin/env python3
"""
learn_monitor_gui.py — Monitor de aprendizaje con interfaz gráfica (tkinter).

Sin dependencias extra; evita los problemas de ANSI en consola Windows.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from tsw6.learning.learn_monitor import (
    TARGET_SAMPLES,
    LearnMonitor,
    _LOOP_SLEEP_S,
    _adopt_vehicle_profile,
    _ensure_freight_learner,
    _sync_vehicle_from_telem,
)
from tsw6.learning.control_layout import detect_control_layout
from tsw6.learning.freight_learner import FreightLearner, create_learner, resolve_feed_axis
from tsw6.learning.online_learner import MIN_SPEED, MIN_SPEED_FREIGHT, _SPEED_BANDS, path_for_vehicle
from tsw6.learning.train_labels import control_level_label, control_value_label, notch_label
from tsw6.telemetry.tsw_telemetry_source import TswTelemetrySource

_PADX = 8
_PADY = 4


class LearnMonitorApp:
    def __init__(self, root: tk.Tk, monitor: LearnMonitor, conn: TswTelemetrySource,
                 learner, vehicle: str, min_speed: float,
                 detected_name: dict[str, Optional[str]]) -> None:
        self.root = root
        self.monitor = monitor
        self.conn = conn
        self.learner = learner
        self.vehicle = vehicle
        self.min_speed = min_speed
        self._detected_name = detected_name
        self._running = True
        self._ui_tick = 0
        self.prev_controls: Optional[dict] = None
        self.capture_axis: Optional[str] = None
        self.capture_level: Optional[float] = None

        root.title("TSW6 — Monitor de aprendizaje")
        root.geometry("820x720")
        root.minsize(640, 520)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        self._build_ui()
        self._schedule_tick()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=_PADX, pady=_PADY)

        self.lbl_title = ttk.Label(
            top, text="Monitor de aprendizaje", font=("Segoe UI", 12, "bold"))
        self.lbl_title.pack(anchor=tk.W)
        self.lbl_vehicle = ttk.Label(top, text="", font=("Segoe UI", 10))
        self.lbl_vehicle.pack(anchor=tk.W)
        self.lbl_profile = ttk.Label(top, text="", foreground="#555")
        self.lbl_profile.pack(anchor=tk.W)
        self.lbl_conn = ttk.Label(top, text="", foreground="#2a7")
        self.lbl_conn.pack(anchor=tk.W)

        prog = ttk.Frame(self.root)
        prog.pack(fill=tk.X, padx=_PADX, pady=_PADY)
        ttk.Label(prog, text="Progreso global").pack(anchor=tk.W)
        self.prog_var = tk.DoubleVar(value=0.0)
        self.prog_bar = ttk.Progressbar(prog, variable=self.prog_var, maximum=100)
        self.prog_bar.pack(fill=tk.X, pady=2)
        self.lbl_prog = ttk.Label(prog, text="0/0 celdas")
        self.lbl_prog.pack(anchor=tk.W)

        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True, padx=_PADX, pady=_PADY)

        self.notebook = ttk.Notebook(mid)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_matrix = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_matrix, text="Matriz")
        self._matrix_parent = self.tab_matrix

        self.tab_hints = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_hints, text="Guía")
        self.txt_hints = tk.Text(
            self.tab_hints, wrap=tk.WORD, height=12, font=("Segoe UI", 10),
            relief=tk.FLAT, bg="#f8f8f8")
        self.txt_hints.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.txt_hints.configure(state=tk.DISABLED)

        bottom = ttk.LabelFrame(self.root, text="Estado en vivo")
        bottom.pack(fill=tk.X, padx=_PADX, pady=_PADY)
        self.lbl_live = ttk.Label(bottom, text="—", font=("Consolas", 10))
        self.lbl_live.pack(anchor=tk.W, padx=6, pady=4)
        self.lbl_learner = ttk.Label(bottom, text="", foreground="#444")
        self.lbl_learner.pack(anchor=tk.W, padx=6, pady=(0, 6))

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill=tk.X, padx=_PADX, pady=_PADY)
        ttk.Button(btn_row, text="Guardar y cerrar", command=self._on_close).pack(
            side=tk.RIGHT)

        self._trees: list[ttk.Treeview] = []

    def _clear_matrix(self) -> None:
        for w in self._matrix_parent.winfo_children():
            w.destroy()
        self._trees.clear()

    def _cell_text(self, count: int, target: int) -> str:
        mark = " ✓" if count >= target else ""
        return f"{min(count, target)}/{target}{mark}"

    def _build_combined_matrix(self) -> None:
        self._clear_matrix()
        cols = ("muesca",) + tuple(f"{lo}-{hi}" for lo, hi in _SPEED_BANDS)
        tree = ttk.Treeview(
            self._matrix_parent, columns=cols, show="headings", height=12)
        tree.heading("muesca", text="Muesca")
        tree.column("muesca", width=140, anchor=tk.W)
        for lo, hi in _SPEED_BANDS:
            cid = f"{lo}-{hi}"
            tree.heading(cid, text=f"{lo}-{hi} mph")
            tree.column(cid, width=90, anchor=tk.CENTER)
        tree.tag_configure("done", foreground="#1a7f37")
        tree.tag_configure("partial", foreground="#333")
        for n in self.monitor._notch_rows():
            cells = [notch_label(n)]
            tags: list[str] = []
            all_done = True
            for b in range(len(_SPEED_BANDS)):
                c = self.monitor._count(b, n)
                cells.append(self._cell_text(c, self.monitor.target))
                if c < self.monitor.target:
                    all_done = False
            tags.append("done" if all_done and self.monitor.target > 0 else "partial")
            tree.insert("", tk.END, values=cells, tags=tags)
        tree.pack(fill=tk.BOTH, expand=True)
        self._trees.append(tree)

    def _build_freight_matrix(self) -> None:
        self._clear_matrix()
        outer = ttk.Frame(self._matrix_parent)
        outer.pack(fill=tk.BOTH, expand=True)
        for axis, (title, rows) in self.monitor._freight_rows().items():
            lf = ttk.LabelFrame(outer, text=title)
            lf.pack(fill=tk.X, padx=2, pady=4)
            cols = ("nivel",) + tuple(f"{lo}-{hi}" for lo, hi in _SPEED_BANDS)
            tree = ttk.Treeview(lf, columns=cols, show="headings", height=min(8, len(rows) + 1))
            tree.heading("nivel", text="Nivel")
            tree.column("nivel", width=120, anchor=tk.W)
            for lo, hi in _SPEED_BANDS:
                cid = f"{lo}-{hi}"
                tree.heading(cid, text=f"{lo}-{hi} mph")
                tree.column(cid, width=80, anchor=tk.CENTER)
            tree.tag_configure("done", foreground="#1a7f37")
            for lv in rows:
                cells = [control_level_label(axis, lv)]
                all_done = True
                for b in range(len(_SPEED_BANDS)):
                    c = self.monitor._count_freight(axis, b, lv)
                    cells.append(self._cell_text(c, self.monitor.target))
                    if c < self.monitor.target:
                        all_done = False
                tag = "done" if all_done else ()
                tree.insert("", tk.END, values=cells, tags=tag)
            tree.pack(fill=tk.X, padx=4, pady=4)
            self._trees.append(tree)

    def _refresh_matrix(self) -> None:
        if self.monitor._is_freight:
            self._build_freight_matrix()
        else:
            self._build_combined_matrix()

    def _refresh_labels(self) -> None:
        m = self.monitor
        veh = m.vehicle
        if not m.vehicle_known:
            veh += "  (buscando nombre…)"
        self.lbl_vehicle.configure(text=f"Tren: {veh}")
        self.lbl_profile.configure(
            text=f"Perfil: {os.path.basename(m.learner.save_path)}  ·  "
                 f"objetivo {m.target}/celda")
        mode = self.conn.mode
        self.lbl_conn.configure(
            text=f"Conexión: {self.conn.last_probe_info}  [{mode}]")

        done, total = m._total_progress()
        pct = (100.0 * done / total) if total else 0.0
        self.prog_var.set(pct)
        self.lbl_prog.configure(text=f"{done}/{total} celdas completas ({pct:.0f}%)")

        atp = "  ⚠ ATP" if m._ack_active else ""
        lim = f"{m._cur_limit:.0f}" if m._cur_limit else "?"
        accel = (f"{m._cur_accel:+.2f}" if m._cur_accel is not None else "dv/dt")
        if m._is_freight:
            c = m._cur_controls
            mandos = (
                f"thr={control_value_label('throttle', c.get('throttle'))}  "
                f"auto={control_value_label('train_brake', c.get('train_brake'))}  "
                f"ind={control_value_label('ind_brake', c.get('ind_brake'))}  "
                f"dyn={control_value_label('dyn_brake', c.get('dyn_brake'))}"
            )
            live = (f"{mandos}   |   {m._cur_speed:.1f} mph   lím {lim} mph   "
                    f"grad {m._cur_grad:+.1f}%   a {accel} m/s²{atp}")
        else:
            live = (f"{notch_label(m._cur_notch):<14}   |   {m._cur_speed:.1f} mph   "
                    f"lím {lim} mph   grad {m._cur_grad:+.1f}%   a {accel} m/s²{atp}")
        self.lbl_live.configure(text=live)
        self.lbl_learner.configure(
            text=f"Learner: {m.learner.last_reason}   (snapshots: {m._snaps})")

        hints = "\n".join(f"• {h}" for h in m._hints())
        self.txt_hints.configure(state=tk.NORMAL)
        self.txt_hints.delete("1.0", tk.END)
        self.txt_hints.insert("1.0", hints or "—")
        self.txt_hints.configure(state=tk.DISABLED)

    def _telemetry_tick(self) -> None:
        if not self._running:
            return
        telem = self.conn.get_telemetry()
        self.monitor._snaps += 1

        speed = telem.get("speed_mph")
        notch = telem.get("handle_notch")
        grad = telem.get("gradient_pct") or 0.0
        accel = telem.get("accel_mps2")
        limit = telem.get("limit_mph")
        ack = bool(telem.get("ack_required", False))

        layout = telem.get("control_layout", "combined")
        resolved = _sync_vehicle_from_telem(
            self.vehicle, self.conn, self._detected_name["v"], telem)
        if resolved and resolved != "Desconocido":
            _adopt_vehicle_profile(self.learner, resolved)
            self.vehicle = resolved
            self.monitor.vehicle = resolved
            self.monitor.vehicle_known = True

        is_freight = isinstance(self.learner, FreightLearner) or layout == "freight_na"
        self.monitor.layout = "freight_na" if is_freight else "combined"

        if speed is not None and (is_freight or notch is not None):
            if not self.monitor.vehicle_known and self._detected_name["v"]:
                name = self._detected_name["v"]
                _adopt_vehicle_profile(self.learner, name)
                self.monitor.vehicle = name
                self.monitor.vehicle_known = True
                self.vehicle = name
                self.monitor.layout = (
                    "freight_na" if isinstance(self.learner, FreightLearner)
                    else "combined")

            if layout == "freight_na" and not isinstance(self.learner, FreightLearner):
                self.learner, veh = _ensure_freight_learner(
                    self.learner, self.vehicle, self.conn,
                    self._detected_name["v"], self.min_speed)
                self.monitor.learner = self.learner
                if veh and veh != "Desconocido":
                    self.vehicle = veh
                    self.monitor.vehicle = veh
                    self.monitor.vehicle_known = True

            if is_freight:
                controls = {
                    "throttle": float(notch if notch is not None else 0),
                    "train_brake": float(telem.get("train_brake_value") or 0.0),
                    "ind_brake": float(telem.get("ind_brake_value") or 0.0),
                    "dyn_brake": float(telem.get("dyn_brake_value") or 0.0),
                }
                axis, level, self.capture_axis, self.capture_level = resolve_feed_axis(
                    self.prev_controls, controls, self.capture_axis, self.capture_level)
                self.monitor.feed_freight(
                    speed, grad, accel, limit, ack, controls, axis, level)
                self.prev_controls = controls
            else:
                assert notch is not None
                self.monitor.feed(speed, notch, grad, accel, limit, ack)

    def _schedule_tick(self) -> None:
        if not self._running:
            return
        try:
            self._telemetry_tick()
            self._ui_tick += 1
            if self._ui_tick % 2 == 0:
                self._refresh_matrix()
                self._refresh_labels()
        except Exception as exc:
            self._running = False
            messagebox.showerror("Error", f"Error en telemetría:\n{exc}")
            return
        self.root.after(int(_LOOP_SLEEP_S * 1000), self._schedule_tick)

    def _on_close(self) -> None:
        if not self._running:
            self.root.destroy()
            return
        self._running = False
        self.learner.save()
        done, total = self.monitor._total_progress()
        consts = self.learner.get_constants()
        msg = (
            f"Vehículo: {self.vehicle}\n"
            f"Celdas: {done}/{total}\n"
            f"Guardado: {self.learner.save_path}"
        )
        if consts:
            msg += "\n\nConstantes confiables:\n"
            for k, v in consts.items():
                msg += f"  {k}: {v:.3f} m/s²\n"
        messagebox.showinfo("Sesión guardada", msg)
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor de aprendizaje — GUI")
    parser.add_argument("--vehicle", default=None)
    parser.add_argument("--target", type=int, default=TARGET_SAMPLES)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--freight", action="store_true")
    parser.add_argument("--min-speed", type=float, default=None, metavar="MPH")
    args = parser.parse_args()

    if args.min_speed is not None:
        min_speed = max(0.5, args.min_speed)
    elif args.freight:
        min_speed = MIN_SPEED_FREIGHT
    else:
        min_speed = MIN_SPEED

    conn = TswTelemetrySource()
    for _ in range(30):
        conn.probe()
        if conn.mode in ("ue4ss", "tsw_api"):
            break
        import time
        time.sleep(1.0)

    if conn.mode not in ("ue4ss", "tsw_api"):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Sin conexión",
            "No se pudo conectar a TSW6.\n\n"
            "¿TelemetryProbeMod activo o TSW6 con -HTTPAPI (en cabina)?")
        sys.exit(1)

    if args.vehicle:
        vehicle, vehicle_known = args.vehicle, True
    else:
        detected = conn.get_vehicle_name()
        vehicle = detected or "Desconocido"
        vehicle_known = detected is not None

    profile_path = path_for_vehicle(vehicle)
    if args.reset and os.path.exists(profile_path):
        os.remove(profile_path)

    init_layout = "freight_na" if args.freight else None
    if init_layout is None and vehicle_known:
        if detect_control_layout(vehicle) == "freight_na":
            init_layout = "freight_na"

    learner = create_learner(vehicle=vehicle, min_speed=min_speed, layout=init_layout)
    init_layout = "freight_na" if isinstance(learner, FreightLearner) else "combined"
    monitor = LearnMonitor(
        learner, vehicle, max(1, args.target),
        vehicle_known=vehicle_known, layout=init_layout, auto_render=False)

    detected_name: dict[str, Optional[str]] = {"v": None}
    if not vehicle_known:
        def _search() -> None:
            import time
            while detected_name["v"] is None:
                time.sleep(3.0)
                name = conn.get_vehicle_name()
                if name:
                    detected_name["v"] = name
                    return
        threading.Thread(target=_search, daemon=True).start()

    root = tk.Tk()
    LearnMonitorApp(root, monitor, conn, learner, vehicle, min_speed, detected_name)
    root.mainloop()


if __name__ == "__main__":
    main()
