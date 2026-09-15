"""Trazas JSONL e investigate para afinar P1 cartel (paso 3)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tsw6v2.probe_seq import probe_seq_delta_ms
from tsw6v2.loop import AgentSnapshot
from tsw6v2.p1_layers import format_layer_tag, layer_label


def advance_probe_active_ms(
    active_ms: float,
    last_seq: int | None,
    seq: int | None,
) -> tuple[float, int | None]:
    """Avanza tiempo activo según ``seq`` del probe (~``PROBE_SEQ_MS`` por paso)."""
    if seq is not None:
        delta_ms = probe_seq_delta_ms(last_seq, seq)
        if delta_ms is not None:
            active_ms += delta_ms
        last_seq = int(seq)
    return active_ms, last_seq


def _git_head() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def default_log_path(*, mode: str = "session", route: str = "session") -> Path:
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in route.lower())
    mode_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in mode.lower())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("logs/v2") / f"{stamp}_{slug}_{mode_slug}.jsonl"


def resolve_session_log_path(
    log_arg: Optional[str],
    *,
    trace_mode: str,
    route: str,
    default_route: str = "session",
) -> Optional[Path]:
    """``None`` = sin log; ``""`` = ``default_log_path`` con ``trace_mode``."""
    if log_arg is None:
        return None
    route_slug = route or default_route
    if log_arg == "":
        return default_log_path(mode=trace_mode, route=route_slug)
    return Path(log_arg)


class JsonlTrace:
    """Una línea JSON por evento; primera línea = metadatos de sesión."""

    def __init__(self, path: Path, session: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fp = path.open("w", encoding="utf-8")
        self.write({"type": "session", **session})

    def write(self, row: dict[str, Any]) -> None:
        self._fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fp.flush()

    def write_session_detect(self, **fields: Any) -> None:
        """Ruta/servicio detectados por HTTP (línea aparte; se fusiona al leer JSONL)."""
        row = {"type": "session_detect"}
        for key, val in fields.items():
            if val is not None and val != "":
                row[key] = val
        if len(row) > 1:
            self.write(row)

    def write_tick(
        self,
        snap: AgentSnapshot,
        *,
        t_ms: float,
        active_t_ms: Optional[float] = None,
        ipc_cmd_id: Optional[int] = None,
    ) -> None:
        p1: dict[str, Any] = {}
        if snap.p1_cmd or snap.p1_phase or snap.p1_detail or snap.p1_reason:
            p1 = {
                "cmd": snap.p1_cmd or None,
                "phase": snap.p1_phase or None,
                "handle": snap.p1_handle,
                "apply_now": snap.p1_apply_now,
                "dist_start_m": _round_opt(snap.p1_dist_start_m, 1),
                "detail": snap.p1_detail or None,
                "reason": snap.p1_reason or None,
                "layer": snap.p1_layer or None,
                "layer_label": layer_label(snap.p1_layer) if snap.p1_layer else None,
            }
        fb: dict[str, Any] = {}
        if snap.fb_a_pred_ms2 is not None:
            fb["a_pred_ms2"] = _round_opt(snap.fb_a_pred_ms2, 3)
        if snap.fb_a_obs_ms2 is not None:
            fb["a_obs_ms2"] = _round_opt(snap.fb_a_obs_ms2, 3)
        if snap.fb_shortfall:
            fb["shortfall"] = True
        if snap.fb_escalated:
            fb["escalated"] = True
        row: dict[str, Any] = {
            "type": "tick",
            "tick": snap.tick,
            "seq": snap.seq,
            "t_ms": round(t_ms, 1),
            "spd_mph": _round_opt(snap.speed_mph, 2),
            "lever": snap.lever_notch,
            "target": snap.target_notch,
            "train_brake": _round_opt(snap.train_brake, 3),
            "brake_cyl_bar": _round_opt(snap.brake_cyl_bar, 2),
            "brake_fill_s": _round_opt(snap.brake_fill_s, 2),
            "brake_fill_n": snap.brake_fill_n,
            "decel_observe_n": snap.decel_observe_n,
            "grad_pct": _round_opt(snap.gradient_pct, 2),
            "eff_mph": _round_opt(snap.effective_limit_mph, 2),
            "lim_mph": _round_opt(snap.limit_mph, 2),
            "lim_dist_m": _round_opt(snap.limit_dist_m, 1),
            "stn_dist_m": _round_opt(snap.station_dist_m, 1),
            "station_name": snap.station_name or None,
            "service_name": snap.service_name or None,
            "schedule_source": snap.schedule_source or None,
            "stn_fsm": snap.station_fsm or None,
            "doors_telem": snap.doors_telem,
            "doors_dmi": snap.doors_dmi,
            "doors_open": snap.doors_open,
            "signal_red": snap.signal_red,
            "signal_dist_m": _round_opt(snap.signal_dist_m, 1),
            "p1_tgt": snap.p1_target_kind or None,
            "vehicle": snap.vehicle,
            "p1": p1 or None,
            "fb": fb or None,
            "ipc": {
                "sent": snap.ipc_sent,
                "ok": snap.ipc_ok,
                "cmd_id": ipc_cmd_id,
                "error": snap.ipc_error or None,
            },
        }
        if active_t_ms is not None:
            row["active_t_ms"] = round(active_t_ms, 1)
        if snap.driver_override_s > 0:
            row["manual_s"] = round(snap.driver_override_s, 1)
        if snap.learn_kind is not None:
            row["learn_kind"] = snap.learn_kind
            row["learn_accepted"] = snap.learn_accepted
            if snap.learn_reject_reason:
                row["learn_reject_reason"] = snap.learn_reject_reason
        self.write(row)

    def close(self) -> None:
        self._fp.close()


def session_meta(
    *,
    mode: str,
    route: str = "",
    profile: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "route": route or None,
        "profile": profile,
        "git": _git_head(),
    }


def format_investigate(snap: AgentSnapshot) -> str:
    """Línea compacta estilo v1 ``investigate_suffix``."""
    spd = f"{snap.speed_mph:.1f}" if snap.speed_mph is not None else "?"
    lim = "—"
    if snap.limit_mph is not None and snap.limit_dist_m is not None:
        lim = f"{snap.limit_mph:.0f}@{snap.limit_dist_m:.0f}"
    eff = (
        f"{snap.effective_limit_mph:.0f}"
        if snap.effective_limit_mph is not None
        else "?"
    )
    ds = (
        f"{snap.p1_dist_start_m:.0f}"
        if snap.p1_dist_start_m is not None
        else "—"
    )
    apply = "Y" if snap.p1_apply_now else ("N" if snap.p1_apply_now is not None else "—")
    p1 = snap.p1_cmd or "—"
    phase = snap.p1_phase or "—"
    capa = format_layer_tag(snap.p1_layer) if snap.p1_layer else ""
    det = (snap.p1_detail or "")[:48]
    stn = (
        f"{snap.station_dist_m:.0f}"
        if snap.station_dist_m is not None
        else "—"
    )
    if snap.station_name:
        stn = f"{stn}({snap.station_name})"
    parts = [
        f"tick={snap.tick}",
        f"spd={spd}",
        f"lim={lim}",
        f"stn={stn}",
        f"eff={eff}",
        f"ds={ds}",
        f"apply={apply}",
    ]
    if snap.schedule_source:
        parts.append(f"sched={snap.schedule_source}")
    if snap.service_name:
        parts.append(f"svc={snap.service_name}")
    if snap.station_fsm:
        parts.append(f"fsm={snap.station_fsm}")
    if snap.signal_red is True:
        sig_d = (
            f"{snap.signal_dist_m:.0f}"
            if snap.signal_dist_m is not None
            else "?"
        )
        parts.append(f"sig=ROJO@{sig_d}m")
    if snap.doors_telem is not None or snap.doors_dmi is not None or snap.doors_open is not None:
        telem = "1" if snap.doors_telem else ("0" if snap.doors_telem is False else "—")
        dmi = "1" if snap.doors_dmi else ("0" if snap.doors_dmi is False else "—")
        parts.append(f"doors={telem}/{dmi}")
    if snap.p1_target_kind:
        parts.append(f"p1tgt={snap.p1_target_kind}")
    if capa:
        parts.append(f"capa={capa}")
    parts.extend([
        f"p1={p1}/{phase}",
        f"h={snap.lever_notch}",
        f"ipc_tgt={snap.target_notch}",
        f"ipc={1 if snap.ipc_sent else 0}",
    ])
    if snap.p1_reason:
        parts.append(f"why={snap.p1_reason}")
    if det:
        parts.append(f"det={det}")
    if snap.brake_cyl_bar is not None:
        parts.append(f"P={snap.brake_cyl_bar:.1f}bar")
    if snap.brake_fill_s is not None:
        parts.append(f"fill={snap.brake_fill_s:.1f}s")
    if snap.fb_a_pred_ms2 is not None and snap.fb_a_obs_ms2 is not None:
        parts.append(f"a={snap.fb_a_obs_ms2:.2f}/{snap.fb_a_pred_ms2:.2f}")
    if snap.learn_kind:
        tag = "ok" if snap.learn_accepted else (snap.learn_reject_reason or "rej")
        parts.append(f"learn={snap.learn_kind}:{tag}")
    if snap.driver_override_s > 0:
        parts.append(f"manual={snap.driver_override_s:.0f}s")
    return str(" ".join(parts))


def _round_opt(val: Optional[float], digits: int) -> Optional[float]:
    if val is None:
        return None
    return round(float(val), digits)
