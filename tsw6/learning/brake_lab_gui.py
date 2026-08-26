#!/usr/bin/env python3
"""
brake_lab_gui.py — GUI laboratorio de frenos (Lua probe + HTTPAPI + CSV).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar este archivo directo desde el IDE (Run Python File).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from tsw6.learning.brake_physics_monitor import (
    PHASES,
    BrakeLabSample,
    BrakePhysicsSampler,
    SessionWriter,
    brake_notch_label,
    build_sampler,
    copy_latest,
    default_out_path,
    summarize_csv,
)
from tsw6.paths import LOGS_DIR

_PADX = 8
_PADY = 4
_POLL_S = 0.25
_UI_MS = 100


class BrakeLabApp:
    def __init__(
        self,
        root: tk.Tk,
        sampler: BrakePhysicsSampler,
        vehicle: str,
        csv_path: Path,
    ) -> None:
        self.root = root
        self.sampler = sampler
        self.vehicle = vehicle
        self.csv_path = csv_path
        self.writer: Optional[SessionWriter] = None
        self._recording = False
        self._running = True
        self._lock = threading.Lock()
        self._last_sample: Optional[BrakeLabSample] = None
        self._pending_tree: list[BrakeLabSample] = []
        self._row_count = 0
        self._phase_id = PHASES[0][0]
        self._note_pending = ""

        root.title("TSW6 — Laboratorio de frenos")
        root.geometry("960x720")
        root.minsize(800, 600)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        self._build_ui()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self._schedule_ui_tick()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=_PADX, pady=_PADY)

        ttk.Label(top, text="Laboratorio de frenos", font=("Segoe UI", 12, "bold")).pack(
            anchor=tk.W)
        self.lbl_csv = ttk.Label(top, text="", foreground="#555", font=("Segoe UI", 9))
        self.lbl_csv.pack(anchor=tk.W)
        self.lbl_conn = ttk.Label(top, text="", font=("Segoe UI", 9))
        self.lbl_conn.pack(anchor=tk.W)

        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=_PADX, pady=_PADY)

        tab_live = ttk.Frame(nb)
        nb.add(tab_live, text="En vivo")
        self._build_live_tab(tab_live)

        tab_log = ttk.Frame(nb)
        nb.add(tab_log, text="Log CSV")
        self._build_log_tab(tab_log)

        tab_report = ttk.Frame(nb)
        nb.add(tab_report, text="Informe")
        self.txt_report = tk.Text(
            tab_report, wrap=tk.WORD, font=("Consolas", 10), relief=tk.FLAT, bg="#f8f8f8")
        self.txt_report.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill=tk.X, padx=_PADX, pady=_PADY)
        ttk.Button(btn_row, text="Abrir carpeta logs", command=self._open_logs).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Generar informe", command=self._refresh_report).pack(
            side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Cerrar", command=self._on_close).pack(side=tk.RIGHT)

        self.lbl_csv.config(text=str(self.csv_path))

    def _build_live_tab(self, parent: ttk.Frame) -> None:
        left = ttk.LabelFrame(parent, text="Sesion")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6), pady=4)

        self.var_rec = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            left, text="Grabar CSV", variable=self.var_rec,
            command=self._toggle_recording).pack(anchor=tk.W, padx=6, pady=4)

        ttk.Label(left, text="Fase:").pack(anchor=tk.W, padx=6)
        self.cmb_phase = ttk.Combobox(
            left, width=36, state="readonly",
            values=[f"{i + 1}. {d}" for i, (_, d) in enumerate(PHASES)])
        self.cmb_phase.current(0)
        self.cmb_phase.pack(padx=6, pady=2)
        self.cmb_phase.bind("<<ComboboxSelected>>", self._on_phase_selected)
        ttk.Button(left, text="Siguiente fase", command=self._next_phase).pack(
            fill=tk.X, padx=6, pady=4)
        ttk.Button(left, text="Marcar evento", command=self._mark_event).pack(
            fill=tk.X, padx=6, pady=2)

        self.lbl_phase_hint = ttk.Label(
            left, text=PHASES[0][1], wraplength=260, justify=tk.LEFT)
        self.lbl_phase_hint.pack(anchor=tk.W, padx=6, pady=8)

        ttk.Label(left, text="Nota manual:").pack(anchor=tk.W, padx=6)
        self.ent_note = ttk.Entry(left, width=34)
        self.ent_note.pack(padx=6, pady=2)

        right = ttk.LabelFrame(parent, text="Telemetria dual (probe Lua | HTTPAPI)")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        grid = ttk.Frame(right)
        grid.pack(fill=tk.X, padx=8, pady=8)

        rows = [
            ("Velocidad mph", "lbl_spd_probe", "lbl_spd_http"),
            ("Muesca freno", "lbl_brk_probe", "lbl_brk_http"),
            ("Acel m/s2", "lbl_acc_probe", "lbl_acc_http"),
            ("Presion BAR", "lbl_p_probe", "lbl_p_http"),
        ]
        ttk.Label(grid, text="", width=14).grid(row=0, column=0)
        ttk.Label(grid, text="Probe Lua", font=("Segoe UI", 9, "bold")).grid(row=0, column=1)
        ttk.Label(grid, text="HTTP API", font=("Segoe UI", 9, "bold")).grid(row=0, column=2)

        self._value_labels: dict[str, ttk.Label] = {}
        for i, (title, k_probe, k_http) in enumerate(rows, start=1):
            ttk.Label(grid, text=title).grid(row=i, column=0, sticky=tk.W, pady=2)
            lp = ttk.Label(grid, text="—", font=("Consolas", 11), width=14)
            lh = ttk.Label(grid, text="—", font=("Consolas", 11), width=14)
            lp.grid(row=i, column=1, sticky=tk.W)
            lh.grid(row=i, column=2, sticky=tk.W)
            self._value_labels[k_probe] = lp
            self._value_labels[k_http] = lh

        eff = ttk.Frame(right)
        eff.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(eff, text="BrakeEffort (N):").pack(side=tk.LEFT)
        self.lbl_be = ttk.Label(eff, text="—", font=("Consolas", 11))
        self.lbl_be.pack(side=tk.LEFT, padx=8)
        ttk.Label(eff, text="TractEffort:").pack(side=tk.LEFT, padx=(16, 0))
        self.lbl_te = ttk.Label(eff, text="—", font=("Consolas", 11))
        self.lbl_te.pack(side=tk.LEFT, padx=8)

        self.lbl_flags = ttk.Label(right, text="", foreground="#a40")
        self.lbl_flags.pack(anchor=tk.W, padx=8, pady=4)

        self.lbl_vehicle = ttk.Label(right, text="Vehiculo: —")
        self.lbl_vehicle.pack(anchor=tk.W, padx=8, pady=2)
        self.lbl_rows = ttk.Label(right, text="Filas CSV: 0")
        self.lbl_rows.pack(anchor=tk.W, padx=8, pady=2)

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        cols = (
            "t_rel", "phase", "spd", "brk", "P_h", "P_p", "BE", "flags")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", height=20)
        headings = {
            "t_rel": "t(s)", "phase": "Fase", "spd": "mph", "brk": "muesca",
            "P_h": "P HTTP", "P_p": "P probe", "BE": "N", "flags": "calidad",
        }
        widths = {"t_rel": 55, "phase": 90, "spd": 50, "brk": 50,
                  "P_h": 60, "P_p": 60, "BE": 70, "flags": 180}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor=tk.CENTER)
        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _fmt(self, v: Optional[float], prec: int = 2) -> str:
        if v is None:
            return "—"
        return f"{v:.{prec}f}"

    def _toggle_recording(self) -> None:
        if self.var_rec.get():
            with self._lock:
                if self.writer is None:
                    self.writer = SessionWriter(self.csv_path)
                    self.sampler.session_t0 = time.time()
                self._recording = True
        else:
            with self._lock:
                self._recording = False

    def _current_phase_id(self) -> str:
        idx = self.cmb_phase.current()
        if idx < 0:
            idx = 0
        return PHASES[idx][0]

    def _on_phase_selected(self, _event: object = None) -> None:
        with self._lock:
            self._phase_id = self._current_phase_id()
        idx = self.cmb_phase.current()
        if idx >= 0:
            self.lbl_phase_hint.config(text=PHASES[idx][1])

    def _next_phase(self) -> None:
        idx = min(self.cmb_phase.current() + 1, len(PHASES) - 1)
        self.cmb_phase.current(idx)
        self.lbl_phase_hint.config(text=PHASES[idx][1])
        with self._lock:
            self._phase_id = PHASES[idx][0]

    def _mark_event(self) -> None:
        note = self.ent_note.get().strip() or "marcador"
        with self._lock:
            self._note_pending = note

    def _open_logs(self) -> None:
        folder = str(LOGS_DIR / "brake_physics")
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", folder])

    def _refresh_report(self) -> None:
        if not self.csv_path.is_file():
            messagebox.showinfo("Informe", "Aun no hay CSV grabado.")
            return
        text = summarize_csv(self.csv_path)
        self.txt_report.configure(state=tk.NORMAL)
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, text)
        self.txt_report.configure(state=tk.DISABLED)

    def _append_tree(self, s: BrakeLabSample) -> None:
        flags = "|".join(s.quality_flags())
        self.tree.insert(
            "", 0,
            values=(
                f"{s.t_rel_s:.1f}",
                s.phase,
                self._fmt(s.speed_mph, 1),
                self._fmt(s.train_brake, 2),
                self._fmt(s.pressure_http_bar, 2),
                self._fmt(s.pressure_probe_bar, 2),
                self._fmt(s.brake_effort_n, 0),
                flags[:80],
            ),
        )
        children = self.tree.get_children()
        if len(children) > 200:
            self.tree.delete(children[-1])

    def _update_live(self, s: BrakeLabSample, row_count: int) -> None:
        self._value_labels["lbl_spd_probe"].config(
            text=self._fmt(s.speed_mph_probe, 1))
        self._value_labels["lbl_spd_http"].config(
            text=self._fmt(s.speed_mph_http, 1))
        self._value_labels["lbl_brk_probe"].config(
            text=self._fmt(s.train_brake_probe, 2))
        self._value_labels["lbl_brk_http"].config(
            text=self._fmt(s.train_brake_http, 2))
        self._value_labels["lbl_acc_probe"].config(
            text=self._fmt(s.accel_ms2_probe, 3))
        self._value_labels["lbl_acc_http"].config(
            text=self._fmt(s.accel_ms2_http, 3))
        self._value_labels["lbl_p_probe"].config(
            text=self._fmt(s.pressure_probe_bar, 2))
        self._value_labels["lbl_p_http"].config(
            text=self._fmt(s.pressure_http_bar, 2))

        be = s.brake_effort_n
        be_txt = self._fmt(be, 0) if be is not None else "—"
        if be is not None and not s.effort_valid:
            be_txt += " !"
        self.lbl_be.config(text=be_txt)
        self.lbl_te.config(text=self._fmt(s.tractive_effort_n, 0))

        flags = s.quality_flags()
        self.lbl_flags.config(
            text=("OK" if not flags else "⚠ " + ", ".join(flags)))
        veh = s.vehicle or self.vehicle
        notch = brake_notch_label(s.train_brake)
        self.lbl_vehicle.config(text=f"Vehiculo: {veh}  |  {notch}")
        self.lbl_rows.config(text=f"Filas CSV: {row_count}")

        http_s = "HTTP OK" if s.http_ok else "HTTP —"
        pr_s = "Probe OK" if s.probe_ok else "Probe —"
        self.lbl_conn.config(text=f"{http_s}  |  {pr_s}")

    def _poll_loop(self) -> None:
        """Muestreo I/O en segundo plano (HTTP + probe); no tocar Tk aquí."""
        while self._running:
            t0 = time.perf_counter()
            with self._lock:
                phase = self._phase_id
                note = self._note_pending
                if note:
                    self._note_pending = ""
                recording = self._recording
                writer = self.writer

            s = self.sampler.sample(phase, note=note)
            if s.vehicle and s.vehicle != "?":
                with self._lock:
                    self.vehicle = s.vehicle

            pending: Optional[BrakeLabSample] = None
            with self._lock:
                self._last_sample = s
                if recording and writer is not None:
                    writer.write(s)
                    self._row_count += 1
                    pending = s

            if pending is not None:
                with self._lock:
                    self._pending_tree.append(pending)

            elapsed = time.perf_counter() - t0
            time.sleep(max(0.0, _POLL_S - elapsed))

    def _schedule_ui_tick(self) -> None:
        if not self._running:
            return
        with self._lock:
            sample = self._last_sample
            row_count = self._row_count
            pending = self._pending_tree[:]
            self._pending_tree.clear()
            vehicle = self.vehicle

        if sample is not None:
            if sample.vehicle and sample.vehicle != "?":
                vehicle = sample.vehicle
            self.vehicle = vehicle
            self._update_live(sample, row_count)

        for s in pending:
            self._append_tree(s)

        self.root.after(_UI_MS, self._schedule_ui_tick)

    def _on_close(self) -> None:
        self._running = False
        if self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        if self.writer is not None:
            self.writer.close()
            copy_latest(self.csv_path)
            self._refresh_report()
        self.root.destroy()


def main(
    vehicle: str = "Class323",
    probe_path: Optional[Path] = None,
    use_http: bool = True,
) -> None:
    sampler = build_sampler(probe=probe_path, use_http=use_http)
    csv_path = default_out_path(vehicle)
    root = tk.Tk()
    BrakeLabApp(root, sampler, vehicle, csv_path)
    if not sampler.probe_alive() and not sampler.http_alive():
        messagebox.showwarning(
            "Sin conexion aun",
            "No hay probe Lua ni HTTPAPI en este momento.\n\n"
            "La ventana seguira abierta — arranca TSW en cabina con:\n"
            "- UE4SS TelemetryProbeMod (GetData.txt)\n"
            "- -HTTPAPI (presion y BrakeEffort)\n\n"
            "Los valores apareceran al conectar.",
        )
    root.mainloop()


if __name__ == "__main__":
    main()
