"""GUI visor — muestra snapshot del agente; no policy ni mandos (paso 2)."""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

from tsw6v2.constants import MS_TO_MPH
from tsw6v2.loop import AgentLoop, AgentSnapshot

_UI_MS = 50
_AGENT_HZ = 20.0


def format_viewer_lines(snap: Optional[AgentSnapshot], *, loop_hz: float = 0.0) -> list[str]:
    if snap is None:
        return ["(sin GetData)"]
    mph = f"{snap.speed_mph:.1f}" if snap.speed_mph is not None else "?"
    lever = snap.lever_notch if snap.lever_notch is not None else "?"
    target = snap.target_notch if snap.target_notch is not None else "—"
    ipc = "—"
    if snap.ipc_sent:
        ipc = "ok" if snap.ipc_ok else f"fail:{snap.ipc_error or '?'}"
    signal = ""
    if snap.signal_red is True:
        dist = f"{snap.signal_dist_m:.0f}m" if snap.signal_dist_m is not None else "?"
        signal = f"  signal_red @ {dist}"
    return [
        f"seq={snap.seq or '?'}  tick={snap.tick}  hz={loop_hz:.1f}",
        f"vel={mph} mph  lever={lever}  target={target}  ipc={ipc}",
        f"train_brk={snap.train_brake if snap.train_brake is not None else '?'}  "
        f"vehicle={snap.vehicle}{signal}",
    ]


class ViewerApp:
    """Un proceso: hilo agente ``step()`` + ventana visor (D1 paso 2)."""

    def __init__(self, root: tk.Tk, loop: Optional[AgentLoop] = None) -> None:
        self.root = root
        self.loop = loop or AgentLoop()
        self.loop.post_ipc_sleep_s = 0.0
        self._running = True
        self._lock = threading.Lock()
        self._last: Optional[AgentSnapshot] = None
        self._agent_hz = 0.0
        self._agent_reads = 0
        self._agent_window = time.monotonic()

        root.title("TSW6 V2 — visor")
        root.geometry("520x220")
        root.minsize(420, 180)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        self._lines = [
            ttk.Label(frame, text="—", font=("Consolas", 11), anchor=tk.W)
            for _ in range(3)
        ]
        for lbl in self._lines:
            lbl.pack(fill=tk.X, pady=2)
        ttk.Label(
            frame,
            text="Solo lectura — mandos vía agente/policy (paso 3)",
            font=("Segoe UI", 9),
            foreground="#666",
        ).pack(anchor=tk.W, pady=(8, 0))

        threading.Thread(target=self._agent_loop, name="tsw6v2-agent", daemon=True).start()
        self._schedule_ui()

    def _agent_loop(self) -> None:
        interval = 1.0 / _AGENT_HZ
        while self._running:
            t0 = time.perf_counter()
            snap = self.loop.step()
            with self._lock:
                self._last = snap
                self._agent_reads += 1
                elapsed = time.monotonic() - self._agent_window
                if elapsed >= 2.0:
                    self._agent_hz = self._agent_reads / elapsed
                    self._agent_reads = 0
                    self._agent_window = time.monotonic()
            wait = interval - (time.perf_counter() - t0)
            if wait > 0:
                time.sleep(wait)

    def _schedule_ui(self) -> None:
        if not self._running:
            return
        with self._lock:
            snap = self._last
            hz = self._agent_hz
        for lbl, line in zip(self._lines, format_viewer_lines(snap, loop_hz=hz)):
            lbl.config(text=line)
        self.root.after(_UI_MS, self._schedule_ui)

    def _on_close(self) -> None:
        self._running = False
        self.root.destroy()


def run_gui() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"GUI no disponible: {exc}", file=sys.stderr)
        return 1
    ViewerApp(root)
    root.mainloop()
    return 0
