"""GUI tkinter — sesiones lab + asistente L0 (v1)."""

from __future__ import annotations

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

from .assistant import (
    assistant_summary,
    do_prepare_pc,
    run_correlator,
    run_vehicles_json,
    suggest_vehicle_id,
)
from .catalog import (
    EXPORT_FILES,
    LabSession,
    list_sessions,
    load_json,
    summarize_controls,
)
from .paths import lab_exports_dir, repo_root
from .phases import first_pending_phase, format_phase_report, mark_phase_skipped


class VehicleLabApp:
    _AUTO_MS = 5000

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TSW6 — Vehicle Lab (exploración por tren)")
        self.root.geometry("1000x780")
        self._exports = lab_exports_dir()
        self._sessions: list[LabSession] = []
        self._auto_var = tk.BooleanVar(value=False)
        self._auto_job: str | None = None
        self._build()
        self._refresh_sessions()

    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text="Sesiones ApiExplorer (F5–F7 en cabina)",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(top, text=f"Exports: {self._exports}").pack(anchor=tk.W)

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(body, width=280)
        body.add(left, weight=1)
        ttk.Label(left, text="Sesiones").pack(anchor=tk.W)
        self._list = tk.Listbox(left, height=20, exportselection=False)
        self._list.pack(fill=tk.BOTH, expand=True, pady=4)
        self._list.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(left, text="Actualizar", command=self._refresh_sessions).pack(fill=tk.X)
        ttk.Button(left, text="Seguir L0", command=self._follow_l0).pack(fill=tk.X, pady=(6, 0))
        ttk.Checkbutton(
            left,
            text=f"Auto-actualizar ({self._AUTO_MS // 1000}s)",
            variable=self._auto_var,
            command=self._toggle_auto,
        ).pack(anchor=tk.W, pady=4)
        ttk.Button(left, text="Abrir plantillas…", command=self._open_templates).pack(fill=tk.X)

        right = ttk.Frame(body)
        body.add(right, weight=3)

        assist = ttk.LabelFrame(right, text="Asistente L0", padding=8)
        assist.pack(fill=tk.X, pady=(0, 6))
        self._assist_title = ttk.Label(assist, text="Elige una sesión", font=("Segoe UI", 10, "bold"))
        self._assist_title.pack(anchor=tk.W)
        self._assist_body = ttk.Label(assist, text="", wraplength=680, justify=tk.LEFT)
        self._assist_body.pack(anchor=tk.W, pady=4)
        btn_row = ttk.Frame(assist)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="Preparar PC", command=self._on_prepare_pc).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Correlator", command=self._on_correlator).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Generar G-B", command=self._on_generate_gb).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Saltar fase", command=self._on_skip_phase).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Carpeta sesión", command=self._open_session_dir).pack(side=tk.LEFT, padx=4)
        self._log = scrolledtext.ScrolledText(assist, height=5, wrap=tk.WORD, font=("Consolas", 8))
        self._log.pack(fill=tk.X, pady=(4, 0))

        self._meta = ttk.Label(right, text="", wraplength=640)
        self._meta.pack(anchor=tk.W, pady=4)

        self._nb = ttk.Notebook(right)
        self._nb.pack(fill=tk.BOTH, expand=True)
        self._texts: dict[str, scrolledtext.ScrolledText] = {}
        for label in (
            "Fases L0",
            "Resumen",
            "controls",
            "hud_batch",
            "driver_aid",
            "session",
        ):
            frame = ttk.Frame(self._nb)
            self._nb.add(frame, text=label)
            st = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=("Consolas", 9))
            st.pack(fill=tk.BOTH, expand=True)
            self._texts[label] = st

        foot = ttk.Label(
            self.root,
            text="Cabina: F5–F7 · PC: Preparar / Correlator / G-B · Doc: docs/v2/VEHICLE_LAB.md",
            foreground="#555",
        )
        foot.pack(fill=tk.X, padx=8, pady=6)

    def _log_line(self, text: str) -> None:
        self._log.insert(tk.END, text.rstrip() + "\n")
        self._log.see(tk.END)

    def _clear_log(self) -> None:
        self._log.delete("1.0", tk.END)

    def _refresh_sessions(self, keep_selection: bool = True) -> None:
        prev = self._selected()
        prev_id = prev.session_id if prev else None
        self._sessions = list_sessions(self._exports)
        self._list.delete(0, tk.END)
        select_idx = 0
        for i, s in enumerate(self._sessions):
            mark = "OK" if s.checklist_ok else ".."
            vc = s.vehicle_class or "?"
            self._list.insert(tk.END, f"{mark} {s.session_id}  ({vc})")
            if keep_selection and prev_id and s.session_id == prev_id:
                select_idx = i
        if self._sessions:
            self._list.selection_set(select_idx)
            self._list.event_generate("<<ListboxSelect>>")

    def _selected(self) -> LabSession | None:
        sel = self._list.curselection()
        if not sel:
            return None
        return self._sessions[sel[0]]

    def _update_assistant(self, s: LabSession | None) -> None:
        if s is None:
            self._assist_title.configure(text="Sin sesión")
            self._assist_body.configure(text="Selecciona una carpeta o pulsa Seguir L0.")
            return
        ph = first_pending_phase(s.path)
        if ph is None:
            self._assist_title.configure(text=f"{s.session_id} — L0 cerrado")
            self._assist_body.configure(
                text="Todas las fases automáticas OK o saltadas. Revisa package/probe y data/vehicles/."
            )
        else:
            self._assist_title.configure(text=f"{s.session_id} — {ph.id}: {ph.title}")
            self._assist_body.configure(text=assistant_summary(s.path, s.vehicle_class))

    def _on_select(self, _event: object = None) -> None:
        s = self._selected()
        if s is None:
            return
        self._update_assistant(s)
        present = ", ".join(s.files_present) or "(vacío)"
        missing = ", ".join(s.files_missing) if s.files_missing else "—"
        self._meta.configure(
            text=(
                f"{s.session_id}\n"
                f"vehicle_class: {s.vehicle_class or '?'}\n"
                f"Presentes: {present}\n"
                f"Opcionales ausentes: {missing}"
            )
        )
        self._set_tab(
            "Fases L0",
            format_phase_report(s.path, vehicle_class=s.vehicle_class),
        )
        summary_lines = [
            "Checklist mínimo nuevo tren: session + hud_batch + controls + driver_aid",
            f"notas_sesion.md: {'sí' if s.has_notas else 'no'}",
            f"railbridge/: {'sí' if s.has_railbridge else 'no'}",
            "",
            "Archivos esperados (explorer):",
        ]
        for name in EXPORT_FILES:
            ok = name in s.files_present
            summary_lines.append(f"  [{'x' if ok else ' '}] {name}")
        extra = sorted(
            p.name
            for p in s.path.iterdir()
            if p.is_file()
            and p.name not in EXPORT_FILES
            and p.suffix in (".json", ".md", ".txt")
        )
        if extra:
            summary_lines.append("")
            summary_lines.append("Otros en carpeta:")
            for name in extra[:20]:
                summary_lines.append(f"  + {name}")
        ctrl_path = s.path / "controls.json"
        if ctrl_path.is_file():
            summary_lines.append("")
            summary_lines.append("controls.json:")
            summary_lines.extend(summarize_controls(ctrl_path))
        self._set_tab("Resumen", "\n".join(summary_lines))
        self._load_tab_json("session", s.path / "session.json")
        self._load_tab_json("controls", ctrl_path)
        self._load_tab_json("hud_batch", s.path / "hud_batch.json")
        self._load_tab_json("driver_aid", s.path / "driver_aid.json")

    def _set_tab(self, key: str, text: str) -> None:
        w = self._texts[key]
        w.delete("1.0", tk.END)
        w.insert(tk.END, text)

    def _load_tab_json(self, key: str, path: Path) -> None:
        if not path.is_file():
            self._set_tab(key, f"(no existe {path.name})")
            return
        try:
            data = load_json(path)
            text = json.dumps(data, indent=2, ensure_ascii=False)
            if len(text) > 120_000:
                text = text[:120_000] + "\n… (truncado)"
        except (json.JSONDecodeError, OSError) as exc:
            text = f"Error leyendo {path.name}: {exc}"
        self._set_tab(key, text)

    def _follow_l0(self) -> None:
        if not self._sessions:
            messagebox.showinfo("Vehicle Lab", "No hay sesiones en exports/. Pulsa F5 en cabina primero.")
            return
        idx = 0
        for i, s in enumerate(self._sessions):
            if first_pending_phase(s.path) is not None:
                idx = i
                break
        self._list.selection_clear(0, tk.END)
        self._list.selection_set(idx)
        self._list.see(idx)
        self._on_select()

    def _toggle_auto(self) -> None:
        if self._auto_var.get():
            self._schedule_auto()
        elif self._auto_job is not None:
            self.root.after_cancel(self._auto_job)
            self._auto_job = None

    def _schedule_auto(self) -> None:
        if not self._auto_var.get():
            return

        def tick() -> None:
            self._refresh_sessions(keep_selection=True)
            if self._auto_var.get():
                self._auto_job = self.root.after(self._AUTO_MS, tick)

        self._auto_job = self.root.after(self._AUTO_MS, tick)

    def _run_async(self, label: str, work: Callable[[], list[str]]) -> None:
        self._log_line(f"--- {label} ---")

        def runner() -> None:
            try:
                lines = work()
            except OSError as exc:
                lines = [str(exc)]
            self.root.after(0, lambda: self._async_done(lines))

        threading.Thread(target=runner, daemon=True).start()

    def _async_done(self, lines: list[str]) -> None:
        for line in lines:
            self._log_line(line)
        self._refresh_sessions(keep_selection=True)

    def _on_prepare_pc(self) -> None:
        s = self._selected()
        if s is None:
            messagebox.showinfo("Vehicle Lab", "Selecciona una sesión.")
            return
        self._clear_log()
        path = s.path
        vc = s.vehicle_class

        def work() -> list[str]:
            return do_prepare_pc(path, vehicle_class=vc)

        self._run_async("Preparar PC", work)

    def _on_correlator(self) -> None:
        s = self._selected()
        if s is None:
            messagebox.showinfo("Vehicle Lab", "Selecciona una sesión.")
            return
        if not messagebox.askyesno(
            "Correlator",
            "Requiere TSW6 en marcha con -HTTPAPI.\n¿Continuar?",
        ):
            return
        self._clear_log()
        path = s.path

        def work() -> list[str]:
            code, out = run_correlator(path)
            return [out, f"exit {code}"]

        self._run_async("api_correlator --formation", work)

    def _on_generate_gb(self) -> None:
        s = self._selected()
        if s is None:
            messagebox.showinfo("Vehicle Lab", "Selecciona una sesión.")
            return
        vid = suggest_vehicle_id(s.vehicle_class)
        if not messagebox.askyesno("Generar G-B", f"Escribir data/vehicles/{vid}.json ?"):
            return
        self._clear_log()
        path = s.path

        def work() -> list[str]:
            code, out = run_vehicles_json(path, vid)
            lines = [out, f"exit {code}"]
            if code == 0:
                mark_phase_skipped(path, "package")
                lines.append("Fase package marcada OK")
            if "M3A" in (s.vehicle_class or "").upper() or vid == "m3a_mnr":
                lines.append(
                    "M3a: si hace falta merge RailBridge, ejecuta build_m3a_profile_from_exports.py "
                    "(o copia dumps a sesión/railbridge/ y ajusta el script)."
                )
            return lines

        self._run_async("vehicles_json_from_lab", work)

    def _on_skip_phase(self) -> None:
        s = self._selected()
        if s is None:
            return
        ph = first_pending_phase(s.path)
        if ph is None:
            messagebox.showinfo("Vehicle Lab", "No hay fase pendiente.")
            return
        if not messagebox.askyesno("Saltar", f"Marcar como hecha (saltar) la fase {ph.id}?"):
            return
        mark_phase_skipped(s.path, ph.id)
        self._log_line(f"Saltada fase {ph.id}")
        self._refresh_sessions(keep_selection=True)

    def _open_session_dir(self) -> None:
        s = self._selected()
        if s is None:
            return
        os.startfile(s.path)  # type: ignore[attr-defined]

    def _open_templates(self) -> None:
        tpl = repo_root() / "data" / "lab_exports" / "templates"
        if not tpl.is_dir():
            messagebox.showwarning("Vehicle Lab", f"No existe {tpl}")
            return
        os.startfile(tpl)  # type: ignore[attr-defined]


def run_gui() -> None:
    root = tk.Tk()
    if "vista" in ttk.Style().theme_names():
        ttk.Style().theme_use("vista")
    VehicleLabApp(root)
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Uso: python -m lab.vehicle_explorer [--gui | --list]")
        return 0
    if args and args[0] == "--list":
        exports = lab_exports_dir()
        for s in list_sessions(exports):
            print(s.session_id, s.vehicle_class, "ok" if s.checklist_ok else "partial")
        return 0
    run_gui()
    return 0
