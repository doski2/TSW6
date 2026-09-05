"""Trazas JSONL e investigate para afinar P1 cartel (paso 3)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tsw6v2.loop import AgentSnapshot
from tsw6v2.p1_layers import format_layer_tag, layer_label


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

    def write_tick(
        self,
        snap: AgentSnapshot,
        *,
        t_ms: float,
        ipc_cmd_id: Optional[int] = None,
    ) -> None:
        p1: dict[str, Any] = {}
        if snap.p1_cmd or snap.p1_phase or snap.p1_detail:
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
            "grad_pct": _round_opt(snap.gradient_pct, 2),
            "eff_mph": _round_opt(snap.effective_limit_mph, 2),
            "lim_mph": _round_opt(snap.limit_mph, 2),
            "lim_dist_m": _round_opt(snap.limit_dist_m, 1),
            "vehicle": snap.vehicle,
            "p1": p1 or None,
            "ipc": {
                "sent": snap.ipc_sent,
                "ok": snap.ipc_ok,
                "cmd_id": ipc_cmd_id,
                "error": snap.ipc_error or None,
            },
        }
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
    parts = [
        f"tick={snap.tick}",
        f"spd={spd}",
        f"lim={lim}",
        f"eff={eff}",
        f"ds={ds}",
        f"apply={apply}",
    ]
    if capa:
        parts.append(f"capa={capa}")
    parts.extend([
        f"p1={p1}/{phase}",
        f"h={snap.lever_notch}",
        f"tgt={snap.target_notch}",
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
    return " ".join(parts)


def _round_opt(val: Optional[float], digits: int) -> Optional[float]:
    if val is None:
        return None
    return round(float(val), digits)
