"""Modelo de vista GUI V2 — cartel, bajada, estación + payload IA (sin tkinter)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from tsw6v2.constants import LIMIT_DOWNHILL_GRADIENT_PCT, posted_zone_hold_ceiling_mph
from tsw6v2.loop import AgentSnapshot
from tsw6v2.p1_layers import LAYERS, layer_help, layer_label

from tsw6v2.p1_mode import resolve_gui_p1_mode

_LAYER_COLORS: dict[str, str] = {
    "BRAKE": "#ef4444",
    "WAIT": "#f59e0b",
    "WATCH": "#64748b",
    "HOLD_DH": "#a78bfa",
    "COAST_PWR": "#38bdf8",
    "RELEASE": "#3b82f6",
    "HOLD": "#06b6d4",
    "OK": "#22c55e",
    "NONE": "#475569",
    "GAP": "#dc2626",
    "IDLE": "#334155",
}


def _dash(val: Optional[float], *, digits: int = 1, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{val:.{digits}f}{suffix}"


def _is_downhill(gradient_pct: Optional[float]) -> bool:
    if gradient_pct is None:
        return False
    return float(gradient_pct) < LIMIT_DOWNHILL_GRADIENT_PCT


@dataclass(frozen=True)
class LimitView:
    mph: Optional[float]
    dist_m: Optional[float]
    effective_mph: Optional[float]
    ds_m: Optional[float]
    apply_now: Optional[bool]
    enabled: bool
    is_target: bool

    @property
    def dist_label(self) -> str:
        if self.mph is None or self.dist_m is None:
            return "—"
        return f"{self.mph:.0f} mph @ {self.dist_m:.0f} m"

    @property
    def bar_ratio(self) -> float:
        if self.dist_m is None or self.dist_m <= 0:
            return 0.0
        return min(1.0, self.dist_m / 2000.0)


@dataclass(frozen=True)
class DownhillView:
    gradient_pct: Optional[float]
    zone_ceiling_mph: Optional[float]
    hold_active: bool
    enabled: bool

    @property
    def is_downhill(self) -> bool:
        return _is_downhill(self.gradient_pct)

    @property
    def gradient_label(self) -> str:
        return _dash(self.gradient_pct, digits=2, suffix=" %")

    @property
    def ceiling_label(self) -> str:
        if self.zone_ceiling_mph is None:
            return "—"
        return f"{self.zone_ceiling_mph:.1f} mph"

    @property
    def status_label(self) -> str:
        if not self.enabled:
            return "Inactivo (modo probe)"
        if self.hold_active:
            return "Mantener bajada (HOLD_DH)"
        if self.is_downhill:
            return "Bajada — vigilancia"
        return "Llano / subida"


@dataclass(frozen=True)
class StationView:
    dist_m: Optional[float]
    eta: Optional[str]
    fsm: str
    planning_source: str
    enabled: bool
    is_target: bool

    @property
    def dist_label(self) -> str:
        base = _dash(self.dist_m, digits=0, suffix=" m")
        if self.eta:
            return f"{base}  ETA {self.eta}"
        return base

    @property
    def bar_ratio(self) -> float:
        if self.dist_m is None or self.dist_m <= 0:
            return 0.0
        return min(1.0, self.dist_m / 3000.0)


@dataclass(frozen=True)
class P1View:
    target: str
    layer: str
    layer_label: str
    layer_help: str
    layer_color: str
    cmd: str
    phase: str
    reason: str
    detail: str
    apply_now: str
    handle: Optional[int]


@dataclass(frozen=True)
class TelemetryView:
    tick: int
    seq: Optional[int]
    loop_hz: float
    p1_mode: str
    speed_mph: Optional[float]
    lever: Optional[int]
    ipc_target: Optional[int]
    ipc_status: str
    vehicle: str
    brake_air: str
    signal: str
    profile: str


@dataclass(frozen=True)
class GuiDashboard:
    """Estado completo para pintar la GUI y exportar a IA."""

    telemetry: TelemetryView
    limit: LimitView
    downhill: DownhillView
    station: StationView
    p1: P1View
    headline: str
    connected: bool


@dataclass(frozen=True)
class GuiFields:
    """Compat Fase A — derivado de ``GuiDashboard``."""

    headline: str
    speed: str
    lever: str
    ipc_target: str
    ipc_status: str
    vehicle: str
    signal: str
    limit: str
    station: str
    fsm: str
    p1_target: str
    p1_eff: str
    p1_ds: str
    p1_apply: str
    p1_action: str
    p1_layer: str
    p1_reason: str
    p1_detail: str
    brake_air: str
    planning: str


def build_dashboard(
    snap: Optional[AgentSnapshot],
    *,
    loop_hz: float = 0.0,
    p1_mode: str = "off",
    planning_source: str = "",
    profile_path: str = "",
) -> GuiDashboard:
    mode = resolve_gui_p1_mode(p1_mode or "off")
    limit_on = mode == "p1"
    station_on = mode == "p1"

    if snap is None:
        empty_p1 = P1View("—", "IDLE", "—", "", _LAYER_COLORS["IDLE"], "—", "—", "—", "—", "—", None)
        return GuiDashboard(
            telemetry=TelemetryView(
                0, None, loop_hz, mode, None, None, None, "—", "—", "—", "—", profile_path or "—"
            ),
            limit=LimitView(None, None, None, None, None, limit_on, False),
            downhill=DownhillView(None, None, False, limit_on),
            station=StationView(None, None, "—", planning_source or "—", station_on, False),
            p1=empty_p1,
            headline="(sin GetData — probe F7?)",
            connected=False,
        )

    grad = snap.gradient_pct
    zone_ceiling: Optional[float] = None
    if snap.limit_mph is not None and grad is not None:
        zone_ceiling = posted_zone_hold_ceiling_mph(snap.limit_mph, grad)

    layer = snap.p1_layer or "IDLE"
    if snap.p1_apply_now is True:
        apply_s = "Y"
    elif snap.p1_apply_now is False:
        apply_s = "N"
    else:
        apply_s = "—"

    ipc = "—"
    if snap.ipc_sent:
        ipc = "OK" if snap.ipc_ok else f"FAIL {snap.ipc_error or '?'}"

    sig = "—"
    if snap.signal_red is True:
        sig = f"ROJO @ {_dash(snap.signal_dist_m, digits=0, suffix=' m')}"

    air = "—"
    if snap.brake_cyl_bar is not None:
        air = f"P {snap.brake_cyl_bar:.1f} bar  fill {_dash(snap.brake_fill_s, digits=1, suffix=' s')}"

    tgt = snap.p1_target_kind or ""
    mode_label = mode if mode != "off" else "probe"
    if snap and snap.driver_override_s > 0:
        mode_label = f"{mode_label} · MANUAL {snap.driver_override_s:.0f}s"

    return GuiDashboard(
        telemetry=TelemetryView(
            tick=snap.tick,
            seq=snap.seq,
            loop_hz=loop_hz,
            p1_mode=mode_label,
            speed_mph=snap.speed_mph,
            lever=snap.lever_notch,
            ipc_target=snap.target_notch,
            ipc_status=ipc,
            vehicle=snap.vehicle or "?",
            brake_air=air,
            signal=sig,
            profile=profile_path or "auto",
        ),
        limit=LimitView(
            mph=snap.limit_mph,
            dist_m=snap.limit_dist_m,
            effective_mph=snap.effective_limit_mph,
            ds_m=snap.p1_dist_start_m,
            apply_now=snap.p1_apply_now,
            enabled=limit_on,
            is_target=tgt in ("SPEED_LIMIT", "LIMIT"),
        ),
        downhill=DownhillView(
            gradient_pct=grad,
            zone_ceiling_mph=zone_ceiling,
            hold_active=layer == "HOLD_DH" or snap.p1_reason == "downhill_hold",
            enabled=limit_on,
        ),
        station=StationView(
            dist_m=snap.station_dist_m,
            eta=snap.station_eta,
            fsm=snap.station_fsm or "—",
            planning_source=planning_source or "—",
            enabled=station_on,
            is_target=tgt == "STATION",
        ),
        p1=P1View(
            target=tgt or "—",
            layer=layer,
            layer_label=layer_label(layer) if layer else "—",
            layer_help=layer_help(layer),
            layer_color=_LAYER_COLORS.get(layer, "#94a3b8"),
            cmd=snap.p1_cmd or "—",
            phase=snap.p1_phase or "—",
            reason=snap.p1_reason or "—",
            detail=(snap.p1_detail or "—")[:120],
            apply_now=apply_s,
            handle=snap.p1_handle,
        ),
        headline=f"seq {snap.seq or '?'}  tick {snap.tick}  {loop_hz:.1f} Hz  modo {mode_label}",
        connected=True,
    )


def dashboard_to_fields(d: GuiDashboard) -> GuiFields:
    t, l, s, p = d.telemetry, d.limit, d.station, d.p1
    return GuiFields(
        headline=d.headline,
        speed=_dash(t.speed_mph, suffix=" mph"),
        lever=str(t.lever if t.lever is not None else "—"),
        ipc_target=str(t.ipc_target if t.ipc_target is not None else "—"),
        ipc_status=t.ipc_status,
        vehicle=t.vehicle,
        signal=t.signal,
        limit=l.dist_label,
        station=s.dist_label,
        fsm=s.fsm,
        p1_target=p.target,
        p1_eff=_dash(l.effective_mph, digits=0, suffix=" mph"),
        p1_ds=_dash(l.ds_m, digits=0, suffix=" m"),
        p1_apply=p.apply_now,
        p1_action=f"{p.cmd} / {p.phase}",
        p1_layer=p.layer_label,
        p1_reason=p.reason,
        p1_detail=p.detail[:72],
        brake_air=t.brake_air,
        planning=s.planning_source if s.enabled else "—",
    )


def snapshot_to_fields(
    snap: Optional[AgentSnapshot],
    *,
    loop_hz: float = 0.0,
    p1_mode: str = "off",
    planning_source: str = "",
) -> GuiFields:
    return dashboard_to_fields(
        build_dashboard(snap, loop_hz=loop_hz, p1_mode=p1_mode, planning_source=planning_source)
    )


def snapshot_ai_payload(
    snap: Optional[AgentSnapshot],
    *,
    loop_hz: float = 0.0,
    p1_mode: str = "off",
    planning_source: str = "",
    profile_path: str = "",
    dashboard: Optional[GuiDashboard] = None,
) -> dict[str, Any]:
    """JSON estructurado para copiar a un agente IA / depuración."""
    d = dashboard or build_dashboard(
        snap,
        loop_hz=loop_hz,
        p1_mode=p1_mode,
        planning_source=planning_source,
        profile_path=profile_path,
    )
    t, l, dh, st, p = d.telemetry, d.limit, d.downhill, d.station, d.p1
    out: dict[str, Any] = {
        "connected": d.connected,
        "tick": t.tick,
        "seq": t.seq,
        "mode": t.p1_mode,
        "loop_hz": round(t.loop_hz, 1),
        "telemetry": {
            "speed_mph": t.speed_mph,
            "gradient_pct": dh.gradient_pct,
            "lever": t.lever,
            "ipc_target": t.ipc_target,
            "ipc_status": t.ipc_status,
            "vehicle": t.vehicle,
            "brake_cyl_bar": snap.brake_cyl_bar if snap else None,
            "brake_fill_s": snap.brake_fill_s if snap else None,
            "profile": t.profile,
        },
        "cartel": {
            "enabled": l.enabled,
            "active_target": l.is_target,
            "limit_mph": l.mph,
            "limit_dist_m": l.dist_m,
            "effective_mph": l.effective_mph,
            "ds_m": l.ds_m,
            "apply_now": l.apply_now,
        },
        "bajada": {
            "enabled": dh.enabled,
            "is_downhill": dh.is_downhill,
            "hold_dh_active": dh.hold_active,
            "zone_ceiling_mph": dh.zone_ceiling_mph,
            "status": dh.status_label,
        },
        "estacion": {
            "enabled": st.enabled,
            "active_target": st.is_target,
            "dist_m": st.dist_m,
            "eta": st.eta,
            "fsm": st.fsm if st.fsm != "—" else None,
            "planning_source": st.planning_source if st.planning_source != "—" else None,
        },
        "p1": {
            "target": p.target if p.target != "—" else None,
            "layer": p.layer,
            "layer_label": p.layer_label,
            "cmd": p.cmd if p.cmd != "—" else None,
            "phase": p.phase if p.phase != "—" else None,
            "reason": p.reason if p.reason != "—" else None,
            "detail": p.detail if p.detail != "—" else None,
            "apply_now": p.apply_now if p.apply_now != "—" else None,
            "handle": p.handle,
        },
    }
    if snap and snap.fb_a_obs_ms2 is not None:
        out["feedback"] = {
            "a_obs_ms2": snap.fb_a_obs_ms2,
            "a_pred_ms2": snap.fb_a_pred_ms2,
            "shortfall": snap.fb_shortfall,
            "escalated": snap.fb_escalated,
        }
    return out


def snapshot_ai_json(
    snap: Optional[AgentSnapshot],
    *,
    loop_hz: float = 0.0,
    p1_mode: str = "off",
    planning_source: str = "",
    profile_path: str = "",
    dashboard: Optional[GuiDashboard] = None,
) -> str:
    return json.dumps(
        snapshot_ai_payload(
            snap,
            loop_hz=loop_hz,
            p1_mode=p1_mode,
            planning_source=planning_source,
            profile_path=profile_path,
            dashboard=dashboard,
        ),
        ensure_ascii=False,
        indent=2,
    )


def format_viewer_lines(snap: Optional[AgentSnapshot], *, loop_hz: float = 0.0) -> list[str]:
    f = snapshot_to_fields(snap, loop_hz=loop_hz)
    return [f.headline, f"vel={f.speed}  lever={f.lever}  ipc_tgt={f.ipc_target}", f"veh={f.vehicle}"]


def layer_catalog() -> dict[str, tuple[str, str]]:
    return dict(LAYERS)
