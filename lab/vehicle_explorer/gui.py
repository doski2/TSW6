"""GUI tkinter — sesiones lab + vista JSON (v0)."""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from .catalog import (
    EXPORT_FILES,
    LabSession,
    list_sessions,
    load_json,
    summarize_controls,
)
from .paths import lab_exports_dir


class VehicleLabApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TSW6 — Vehicle Lab (exploración por tren)")
        self.root.geometry("960x720")
        self._exports = lab_exports_dir()
        self._sessions: list[LabSession] = []
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
        self._list = tk.Listbox(left, height=24, exportselection=False)
        self._list.pack(fill=tk.BOTH, expand=True, pady=4)
        self._list.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(left, text="Actualizar", command=self._refresh_sessions).pack(fill=tk.X)
        ttk.Button(left, text="Generar G-B (CLI)…", command=self._hint_g_b).pack(fill=tk.X, pady=4)

        right = ttk.Frame(body)
        body.add(right, weight=3)
        self._meta = ttk.Label(right, text="Elige una sesión", wraplength=640)
        self._meta.pack(anchor=tk.W, pady=4)

        self._nb = ttk.Notebook(right)
        self._nb.pack(fill=tk.BOTH, expand=True)
        self._texts: dict[str, scrolledtext.ScrolledText] = {}
        for label in ("Resumen", "controls", "hud_batch", "driver_aid", "session"):
            frame = ttk.Frame(self._nb)
            self._nb.add(frame, text=label)
            st = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=("Consolas", 9))
            st.pack(fill=tk.BOTH, expand=True)
            self._texts[label] = st

        foot = ttk.Label(
            self.root,
            text="Probe en vivo + muescas learner: v1 · Doc: docs/v2/VEHICLE_LAB.md",
            foreground="#555",
        )
        foot.pack(fill=tk.X, padx=8, pady=6)

    def _refresh_sessions(self) -> None:
        self._sessions = list_sessions(self._exports)
        self._list.delete(0, tk.END)
        for s in self._sessions:
            mark = "✓" if s.checklist_ok else "…"
            vc = s.vehicle_class or "?"
            self._list.insert(tk.END, f"{mark} {s.session_id}  ({vc})")

    def _selected(self) -> LabSession | None:
        sel = self._list.curselection()
        if not sel:
            return None
        return self._sessions[sel[0]]

    def _on_select(self, _event: object = None) -> None:
        s = self._selected()
        if s is None:
            return
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
        summary_lines = [
            "Checklist mínimo nuevo tren: session + hud_batch + controls + driver_aid",
            "",
            "Archivos esperados (explorer):",
        ]
        for name in EXPORT_FILES:
            ok = name in s.files_present
            summary_lines.append(f"  [{'x' if ok else ' '}] {name}")
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

    def _hint_g_b(self) -> None:
        s = self._selected()
        if s is None:
            messagebox.showinfo("Vehicle Lab", "Selecciona una sesión primero.")
            return
        cmd = (
            f'python scripts\\tools\\vehicles_json_from_lab.py "{s.path}" '
            f"--vehicle-id <id_tren>"
        )
        messagebox.showinfo(
            "Generar paquete G-B",
            f"Desde la raíz del repo:\n\n{cmd}\n\nSalida: data\\vehicles\\<id>.json",
        )


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
