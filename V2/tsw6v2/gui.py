"""GUI V2 — visor moderno: cartel, bajada, estación + export IA (PLAN §4.7)."""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional

from tsw6v2.gui_view import (
    GuiDashboard,
    build_dashboard,
    format_viewer_lines,
    snapshot_ai_json,
    snapshot_to_fields,
)
from tsw6v2.learner import LearnerProfile
from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.p1_mode import (
    GUI_P1_MODES,
    apply_p1_mode,
    gui_mode_to_loop_mode,
    resolve_gui_p1_mode,
    session_trace_mode,
)
from tsw6v2.session_log import (
    SessionCloseResult,
    SessionRecorder,
    make_session_recorder,
    save_learner_if_dirty,
    session_profile_note,
)

_UI_MS = 50
_AI_JSON_MS = 500
_AGENT_HZ = 20.0
_EVENT_MAX = 80
_BAR_RATIO_EPS = 0.001


def _secondary_monitor_workarea() -> Optional[tuple[int, int, int, int]]:
    """Área útil (x, y, ancho, alto) del primer monitor no primario (Windows)."""
    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
        ]

    MONITORINFOF_PRIMARY = 0x00000001
    found: list[tuple[int, int, int, int]] = []

    def _callback(hmon, _hdc, _rect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return True
        if info.dwFlags & MONITORINFOF_PRIMARY:
            return True
        r = info.rcWork
        found.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        ctypes.c_long,
    )(_callback)
    user32.EnumDisplayMonitors(0, 0, enum_proc, 0)
    return found[0] if found else None


def _gui_secondary_enabled() -> bool:
    """``V2/run_gui.bat`` define ``TSW6_GUI_SECONDARY=1``; CLI directo = monitor primario."""
    return os.environ.get("TSW6_GUI_SECONDARY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _place_on_secondary_monitor(root: tk.Tk) -> None:
    """Monitor secundario maximizado si ``_gui_secondary_enabled()``."""
    if not _gui_secondary_enabled():
        return

    area = _secondary_monitor_workarea()
    if area is None:
        return
    x, y, w, h = area
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.update_idletasks()
    try:
        root.state("zoomed")
    except tk.TclError:
        pass


# Tema oscuro (alineado con replay HTML)
_C = {
    "bg": "#0f1115",
    "panel": "#1a1f28",
    "panel2": "#151a22",
    "border": "#2a3140",
    "text": "#e6e8ec",
    "muted": "#94a3b8",
    "accent": "#7eb6ff",
    "cartel": "#38bdf8",
    "bajada": "#a78bfa",
    "estacion": "#34d399",
    "warn": "#fcd34d",
}


class _DistanceBar(tk.Canvas):
    def __init__(self, master: tk.Misc, *, color: str, height: int = 10) -> None:
        super().__init__(
            master,
            height=height,
            bg=_C["panel2"],
            highlightthickness=0,
            borderwidth=0,
        )
        self._color = color
        self._ratio = 0.0
        self.bind("<Configure>", lambda _e: self._redraw())

    def set_ratio(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        if abs(ratio - self._ratio) < _BAR_RATIO_EPS:
            return
        self._ratio = ratio
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self.create_rectangle(0, 0, w, h, fill="#0f1115", outline=_C["border"])
        fill_w = int(w * self._ratio)
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, h, fill=self._color, outline="")


class _DomainCard(ttk.Frame):
    """Tarjeta de dominio (cartel / bajada / estación)."""

    def __init__(self, master: tk.Misc, title: str, accent: str) -> None:
        super().__init__(master, style="Card.TFrame", padding=10)
        self._accent = accent
        head = ttk.Frame(self, style="Card.TFrame")
        head.pack(fill=tk.X)
        self._pill = tk.Label(
            head,
            text="OFF",
            font=("Segoe UI", 8, "bold"),
            fg="#0f1115",
            bg="#475569",
            padx=6,
            pady=1,
        )
        self._pill.pack(side=tk.RIGHT)
        ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side=tk.LEFT)
        self._primary = tk.Label(
            self, text="—", font=("Segoe UI", 16, "bold"), fg=_C["text"], bg=_C["panel"]
        )
        self._primary.pack(anchor=tk.W, pady=(6, 2))
        self._secondary = tk.Label(
            self, text="—", font=("Consolas", 10), fg=_C["muted"], bg=_C["panel"]
        )
        self._secondary.pack(anchor=tk.W)
        self._bar = _DistanceBar(self, color=accent)
        self._bar.pack(fill=tk.X, pady=(8, 0))
        self._bar_visible = True
        self._target = tk.Label(
            self, text="", font=("Segoe UI", 8, "bold"), fg=accent, bg=_C["panel"]
        )
        self._target.pack(anchor=tk.W, pady=(4, 0))

    def update(
        self,
        *,
        active: bool,
        is_target: bool,
        primary: str,
        secondary: str,
        bar_ratio: float = 0.0,
        show_bar: bool = True,
    ) -> None:
        self._primary.configure(text=primary)
        self._secondary.configure(text=secondary)
        if active:
            self._pill.configure(text="ON", bg=self._accent)
        else:
            self._pill.configure(text="OFF", bg="#475569")
        if is_target:
            self._target.configure(text="● objetivo P1")
        else:
            self._target.configure(text="")
        if show_bar:
            if not self._bar_visible:
                self._bar.pack(fill=tk.X, pady=(8, 0))
                self._bar_visible = True
            self._bar.set_ratio(bar_ratio)
        elif self._bar_visible:
            self._bar.pack_forget()
            self._bar_visible = False


class AgentGuiApp:
    """Hilo ``AgentLoop.step()`` + dashboard (cartel · bajada · estación · IA)."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        loop: Optional[AgentLoop] = None,
        p1_mode: str = "p1",
        log_path: Optional[Path] = None,
        session_trace_mode: str = "station",
        session_route: str = "gui",
        profile_path: Optional[Path] = None,
        open_html_on_close: bool = False,
    ) -> None:
        self.root = root
        self.loop = loop or AgentLoop()
        self._log_path = log_path
        self._session_trace_mode = session_trace_mode
        self._session_route = session_route
        self._session: Optional[SessionRecorder] = None
        self._profile_path_override = profile_path
        self._open_html_on_close = open_html_on_close
        self._close_result: Optional[SessionCloseResult] = None
        self._learner_save_msg: Optional[str] = None
        self.loop.post_ipc_sleep_s = 0.0
        self._p1_mode = self._normalize_mode(p1_mode)
        self._running = True
        self._lock = threading.Lock()
        self._last: Optional[AgentSnapshot] = None
        self._last_dash: Optional[GuiDashboard] = None
        self._agent_hz = 0.0
        self._agent_reads = 0
        self._agent_window = time.monotonic()
        self._events: list[str] = []
        self._events_rev = 0
        self._events_text_rev = -1
        self._ai_json_last_t = 0.0
        self._ai_json_last_seq: Optional[int] = None
        self._status = tk.StringVar(value="")
        self._mode_var = tk.StringVar(value=self._p1_mode)
        self._speed_var = tk.StringVar(value="—")
        self._layer_var = tk.StringVar(value="—")
        self._target_var = tk.StringVar(value="—")
        self._p1_line_var = tk.StringVar(value="—")
        self._headline_var = tk.StringVar(value="—")

        root.title("TSW6 V2 — Agente")
        if not _gui_secondary_enabled():
            root.geometry("1040x720")
        root.minsize(880, 600)
        _place_on_secondary_monitor(root)
        root.configure(bg=_C["bg"])
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_theme()
        self._build_ui()
        self._apply_mode(self._p1_mode)

        threading.Thread(target=self._agent_loop, name="tsw6v2-agent", daemon=True).start()
        self._schedule_ui()

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        return resolve_gui_p1_mode(mode)

    def _setup_theme(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=_C["bg"])
        style.configure("Card.TFrame", background=_C["panel"], relief="flat")
        style.configure("CardTitle.TLabel", background=_C["panel"], foreground=_C["muted"], font=("Segoe UI", 9))
        style.configure("TLabel", background=_C["bg"], foreground=_C["text"])
        style.configure("TCombobox", fieldbackground=_C["panel2"], background=_C["panel"])
        style.configure("Header.TLabel", background=_C["bg"], foreground=_C["muted"], font=("Segoe UI", 9))
        style.configure("TLabelframe", background=_C["bg"], foreground=_C["muted"])
        style.configure("TLabelframe.Label", background=_C["bg"], foreground=_C["accent"])

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # —— Cabecera ——
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            header,
            text="TSW6 V2",
            font=("Segoe UI", 14, "bold"),
            fg=_C["accent"],
            bg=_C["bg"],
        ).pack(side=tk.LEFT)
        cfg = ttk.Frame(header)
        cfg.pack(side=tk.RIGHT)
        ttk.Label(cfg, text="Modo", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        combo = ttk.Combobox(
            cfg,
            textvariable=self._mode_var,
            values=GUI_P1_MODES,
            state="readonly",
            width=6,
        )
        combo.pack(side=tk.LEFT)
        combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        ttk.Label(
            cfg,
            text="off=probe · p1=cartel+andén+bajada",
            style="Header.TLabel",
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(outer, textvariable=self._status, style="Header.TLabel").pack(anchor=tk.W)

        # —— Hero: velocidad + capa + objetivo ——
        hero = tk.Frame(outer, bg=_C["panel"], highlightbackground=_C["border"], highlightthickness=1)
        hero.pack(fill=tk.X, pady=(0, 10))
        hero_inner = tk.Frame(hero, bg=_C["panel"], padx=14, pady=12)
        hero_inner.pack(fill=tk.X)
        tk.Label(hero_inner, textvariable=self._speed_var, font=("Segoe UI", 28, "bold"), fg=_C["text"], bg=_C["panel"]).pack(
            side=tk.LEFT
        )
        mid = tk.Frame(hero_inner, bg=_C["panel"], padx=20)
        mid.pack(side=tk.LEFT, fill=tk.Y)
        self._layer_badge = tk.Label(
            mid, textvariable=self._layer_var, font=("Segoe UI", 11, "bold"), fg="#0f1115", bg="#475569", padx=10, pady=4
        )
        self._layer_badge.pack(anchor=tk.W)
        tk.Label(
            mid, textvariable=self._target_var, font=("Consolas", 10), fg=_C["muted"], bg=_C["panel"]
        ).pack(anchor=tk.W, pady=(4, 0))
        tk.Label(
            hero_inner, textvariable=self._headline_var, font=("Consolas", 9), fg=_C["muted"], bg=_C["panel"]
        ).pack(side=tk.RIGHT)

        # —— Tres dominios ——
        domains = ttk.Frame(outer)
        domains.pack(fill=tk.X, pady=(0, 10))
        domains.columnconfigure(0, weight=1)
        domains.columnconfigure(1, weight=1)
        domains.columnconfigure(2, weight=1)

        self._card_limit = _DomainCard(domains, "Cartel (límite)", _C["cartel"])
        self._card_limit.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._card_downhill = _DomainCard(domains, "Bajada (HOLD_DH)", _C["bajada"])
        self._card_downhill.grid(row=0, column=1, sticky="nsew", padx=3)
        self._card_station = _DomainCard(domains, "Estación (andén)", _C["estacion"])
        self._card_station.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        # —— Fila auxiliar: aire + IPC + señal ——
        aux = tk.Frame(outer, bg=_C["panel"], highlightbackground=_C["border"], highlightthickness=1)
        aux.pack(fill=tk.X, pady=(0, 10))
        aux_inner = tk.Frame(aux, bg=_C["panel"], padx=12, pady=8)
        aux_inner.pack(fill=tk.X)
        self._air_lbl = tk.Label(aux_inner, text="Aire: —", font=("Consolas", 10), fg=_C["text"], bg=_C["panel"])
        self._air_lbl.pack(side=tk.LEFT, padx=(0, 20))
        self._ipc_lbl = tk.Label(aux_inner, text="IPC: —", font=("Consolas", 10), fg=_C["text"], bg=_C["panel"])
        self._ipc_lbl.pack(side=tk.LEFT, padx=(0, 20))
        self._sig_lbl = tk.Label(aux_inner, text="Señal: —", font=("Consolas", 10), fg=_C["text"], bg=_C["panel"])
        self._sig_lbl.pack(side=tk.LEFT, padx=(0, 20))
        self._veh_lbl = tk.Label(aux_inner, text="Tren: —", font=("Consolas", 10), fg=_C["muted"], bg=_C["panel"])
        self._veh_lbl.pack(side=tk.RIGHT)

        # —— Barra P1 ——
        p1bar = tk.Frame(outer, bg=_C["panel2"], highlightbackground=_C["border"], highlightthickness=1)
        p1bar.pack(fill=tk.X, pady=(0, 10))
        tk.Label(p1bar, textvariable=self._p1_line_var, font=("Consolas", 10), fg=_C["text"], bg=_C["panel2"], padx=12, pady=8).pack(
            anchor=tk.W
        )

        # —— Inferior: eventos + JSON IA ——
        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.BOTH, expand=True)
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=2)

        ev_frame = ttk.LabelFrame(bottom, text="Eventos", padding=6)
        ev_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._event_text = tk.Text(
            ev_frame,
            height=12,
            font=("Consolas", 9),
            bg=_C["panel2"],
            fg=_C["text"],
            insertbackground=_C["text"],
            relief=tk.FLAT,
            wrap=tk.WORD,
        )
        self._event_text.pack(fill=tk.BOTH, expand=True)
        self._event_text.configure(state=tk.DISABLED)

        ai_frame = ttk.LabelFrame(bottom, text="Contexto IA (JSON)", padding=6)
        ai_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ai_tool = ttk.Frame(ai_frame)
        ai_tool.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(ai_tool, text="Copiar", command=self._copy_ai_json).pack(side=tk.RIGHT)
        self._ai_text = tk.Text(
            ai_frame,
            height=12,
            font=("Consolas", 9),
            bg=_C["panel2"],
            fg=_C["muted"],
            insertbackground=_C["text"],
            relief=tk.FLAT,
            wrap=tk.NONE,
        )
        self._ai_text.pack(fill=tk.BOTH, expand=True)
        self._ai_text.configure(state=tk.DISABLED)

        tk.Label(
            outer,
            text="Visor — el agente manda vía IPC; la GUI solo configura modo P1 (sin policy).",
            font=("Segoe UI", 8),
            fg="#666",
            bg=_C["bg"],
        ).pack(anchor=tk.W, pady=(6, 0))

    def _on_mode_change(self, _event: object = None) -> None:
        self._apply_mode(self._mode_var.get())

    def _apply_mode(self, mode: str) -> None:
        mode = self._normalize_mode(mode)
        self._p1_mode = mode
        if mode == "off":
            self.loop.clear_target()
        loop_mode = gui_mode_to_loop_mode(mode)
        warnings = apply_p1_mode(self.loop, loop_mode)
        note = "probe" if mode == "off" else "P1 servicio (cartel + andén)"
        if warnings:
            note += " — " + "; ".join(warnings)
        self._status.set(note)
        self._push_event(f"modo → {mode}")

    def _planning_source(self) -> str:
        if not self.loop.station_brake_enabled:
            return ""
        if self.loop.station_planning_source == "none":
            return ""
        return self.loop.station_planning_channel

    def _ensure_session_recorder(self) -> Optional[SessionRecorder]:
        if self._log_path is None:
            return None
        if self._session is None:
            self._session = make_session_recorder(
                self._log_path,
                self.loop,
                trace_mode=self._session_trace_mode,
                route=self._session_route,
                profile_path=self._profile_path_override,
            )
        return self._session

    def _agent_loop(self) -> None:
        interval = 1.0 / _AGENT_HZ
        while self._running:
            t0 = time.perf_counter()
            snap = self.loop.step()
            recorder = self._ensure_session_recorder()
            if recorder is not None:
                recorder.record(snap)
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

    def _push_event(self, line: str) -> None:
        self._events.append(line)
        if len(self._events) > _EVENT_MAX:
            self._events = self._events[-_EVENT_MAX:]
        self._events_rev += 1

    def _detect_events(self, prev: Optional[GuiDashboard], cur: GuiDashboard) -> None:
        if prev is None:
            if cur.connected:
                self._push_event(f"tick {cur.telemetry.tick}: probe conectado")
            return
        pt, ct = prev.p1, cur.p1
        if pt.layer != ct.layer or pt.reason != ct.reason:
            self._push_event(
                f"tick {cur.telemetry.tick}: capa {pt.layer}→{ct.layer} ({ct.layer_label}) why={ct.reason}"
            )
        if pt.target != ct.target:
            self._push_event(f"tick {cur.telemetry.tick}: objetivo {pt.target}→{ct.target}")
        if prev.station.fsm != cur.station.fsm:
            self._push_event(f"tick {cur.telemetry.tick}: FSM {prev.station.fsm}→{cur.station.fsm}")
        if pt.cmd != ct.cmd and ct.cmd not in ("—", "", None):
            self._push_event(f"tick {cur.telemetry.tick}: cmd {ct.cmd} phase={ct.phase}")
        if not prev.downhill.hold_active and cur.downhill.hold_active:
            self._push_event(f"tick {cur.telemetry.tick}: HOLD_DH bajada activo")
        if prev.station.dist_m is None and cur.station.dist_m is not None and cur.station.enabled:
            self._push_event(f"tick {cur.telemetry.tick}: planning andén {cur.station.dist_m:.0f} m")

    def _render_dashboard(self, d: GuiDashboard) -> None:
        t, l, dh, st, p = d.telemetry, d.limit, d.downhill, d.station, d.p1

        if t.speed_mph is not None:
            self._speed_var.set(f"{t.speed_mph:.1f} mph")
        else:
            self._speed_var.set("— mph")

        self._layer_var.set(f"  {p.layer_label}  ")
        self._layer_badge.configure(bg=p.layer_color)
        self._target_var.set(f"objetivo P1: {p.target}  ·  apply={p.apply_now}  ·  ds={l.ds_m or '—'} m")
        self._headline_var.set(d.headline)

        eff = f"eff {l.effective_mph:.0f} mph" if l.effective_mph is not None else "eff —"
        ds = f"ds {l.ds_m:.0f} m" if l.ds_m is not None else "ds —"
        self._card_limit.update(
            active=l.enabled,
            is_target=l.is_target,
            primary=l.dist_label,
            secondary=f"{eff}  ·  {ds}",
            bar_ratio=l.bar_ratio,
            show_bar=l.dist_m is not None,
        )

        self._card_downhill.update(
            active=dh.enabled,
            is_target=dh.hold_active,
            primary=dh.gradient_label,
            secondary=f"techo zona {dh.ceiling_label}  ·  {dh.status_label}",
            bar_ratio=min(1.0, abs(dh.gradient_pct or 0) / 2.0) if dh.is_downhill else 0.0,
            show_bar=dh.is_downhill,
        )

        plan = st.planning_source if st.planning_source != "—" else "sin planning"
        self._card_station.update(
            active=st.enabled,
            is_target=st.is_target,
            primary=st.dist_label,
            secondary=f"FSM {st.fsm}  ·  {plan}",
            bar_ratio=st.bar_ratio,
            show_bar=st.dist_m is not None and st.enabled,
        )

        lever = t.lever if t.lever is not None else "—"
        ipc_tgt = t.ipc_target if t.ipc_target is not None else "—"
        self._air_lbl.configure(text=f"Aire: {t.brake_air}")
        self._ipc_lbl.configure(text=f"IPC: {t.ipc_status}  ·  palanca {lever} → {ipc_tgt}")
        self._sig_lbl.configure(text=f"Señal: {t.signal}")
        self._veh_lbl.configure(text=f"{t.vehicle}  ·  {t.profile}")

        handle = f" h={p.handle}" if p.handle is not None else ""
        self._p1_line_var.set(
            f"P1  {p.cmd} / {p.phase}{handle}  ·  {p.reason}  ·  {p.detail}"
        )

        if self._events_text_rev != self._events_rev:
            self._events_text_rev = self._events_rev
            self._event_text.configure(state=tk.NORMAL)
            self._event_text.delete("1.0", tk.END)
            self._event_text.insert(tk.END, "\n".join(self._events[-40:]) or "(sin eventos)")
            self._event_text.configure(state=tk.DISABLED)

    def _refresh_ai_json(self, snap: Optional[AgentSnapshot], dash: GuiDashboard) -> None:
        now = time.monotonic()
        seq = snap.seq if snap is not None else None
        due = (
            now - self._ai_json_last_t >= _AI_JSON_MS / 1000.0
            or seq != self._ai_json_last_seq
        )
        if not due:
            return
        ai = snapshot_ai_json(snap, dashboard=dash)
        self._ai_json_last_t = now
        self._ai_json_last_seq = seq
        self._ai_text.configure(state=tk.NORMAL)
        self._ai_text.delete("1.0", tk.END)
        self._ai_text.insert(tk.END, ai)
        self._ai_text.configure(state=tk.DISABLED)

    def _schedule_ui(self) -> None:
        if not self._running:
            return
        with self._lock:
            snap = self._last
            hz = self._agent_hz

        plan_src = self._planning_source()
        profile = session_profile_note(self.loop, self._profile_path_override) or ""
        dash = build_dashboard(
            snap,
            loop_hz=hz,
            p1_mode=self._p1_mode,
            planning_source=plan_src,
            profile_path=profile,
        )
        self._detect_events(self._last_dash, dash)
        self._last_dash = dash
        self._render_dashboard(dash)
        self._refresh_ai_json(snap, dash)

        self.root.after(_UI_MS, self._schedule_ui)

    def _copy_ai_json(self) -> None:
        with self._lock:
            snap = self._last
            dash = self._last_dash
        text = snapshot_ai_json(snap, dashboard=dash)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._push_event("JSON IA copiado al portapapeles")

    def _on_close(self) -> None:
        self._running = False
        self.loop.shutdown()
        recorder = self._ensure_session_recorder()
        if recorder is not None:
            self._close_result = recorder.finish(open_html=self._open_html_on_close)
        self._learner_save_msg = save_learner_if_dirty(
            self.loop,
            self._profile_path_override,
        )
        self.root.destroy()

    @property
    def close_result(self) -> Optional[SessionCloseResult]:
        return self._close_result


def run_gui(
    *,
    mode: str = "p1",
    profile_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
    route: str = "cross-city",
    open_html: bool = True,
    no_log: bool = False,
) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"GUI no disponible: {exc}", file=sys.stderr)
        return 1

    mode = resolve_gui_p1_mode(mode)
    learner = None
    if profile_path:
        learner = LearnerProfile.from_json(profile_path)
    loop = AgentLoop(learner=learner, auto_profile=profile_path is None)

    trace_mode = session_trace_mode(gui_mode_to_loop_mode(mode))
    if log_path is not None:
        print(f"log GUI -> {log_path.resolve()}", file=sys.stderr)

    app = AgentGuiApp(
        root,
        loop=loop,
        p1_mode=mode,
        log_path=log_path,
        session_trace_mode=trace_mode,
        session_route=route,
        profile_path=profile_path,
        open_html_on_close=open_html,
    )
    root.mainloop()

    result = app.close_result
    if app._learner_save_msg is not None:
        print(app._learner_save_msg, file=sys.stderr)
    if result is not None:
        print(result.message, file=sys.stderr)
        if result.html_path is not None:
            try:
                from tkinter import messagebox

                messagebox.showinfo(
                    "Sesión guardada",
                    result.message.replace("\n", "\n"),
                )
            except tk.TclError:
                pass
    return 0


# Re-export compat
__all__ = [
    "AgentGuiApp",
    "GUI_P1_MODES",
    "format_viewer_lines",
    "run_gui",
    "snapshot_to_fields",
]
