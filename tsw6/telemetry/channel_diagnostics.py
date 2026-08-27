#!/usr/bin/env python3
"""Métricas de canal IPC para logs de autopilot (Fase 0/A/B)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


@dataclass
class LoopMetrics:
    """Contadores del bucle de control (autopilot)."""

    ticks: int = 0
    work_max_ms: float = 0.0
    work_over_150: int = 0
    loop_hz_min: float = 999.0
    loop_hz_max: float = 0.0
    heartbeats_cf_y: int = 0
    heartbeats_cf_n: int = 0
    heartbeats_match_y: int = 0

    def record_tick(self, work_ms: float, loop_hz: float) -> None:
        self.ticks += 1
        self.work_max_ms = max(self.work_max_ms, work_ms)
        if work_ms > 150.0:
            self.work_over_150 += 1
        if loop_hz > 0:
            self.loop_hz_min = min(self.loop_hz_min, loop_hz)
            self.loop_hz_max = max(self.loop_hz_max, loop_hz)

    def record_heartbeat(self, *, cf: str, match: str, had_cmd: bool) -> None:
        if not had_cmd:
            return
        if cf == "Y":
            self.heartbeats_cf_y += 1
        elif cf == "N":
            self.heartbeats_cf_n += 1
        if match == "Y":
            self.heartbeats_match_y += 1


@dataclass
class ControllerMetrics:
  ipc_async: int = 0
  ipc_sync: int = 0
  keyboard: int = 0
  p1_rejected: int = 0


def probe_mod_flags(telem: dict[str, Any]) -> dict[str, bool]:
    """Campos GetData que indican versión del mod Lua."""
    return {
        "lever_notch": telem.get("lever_notch") is not None,
        "last_cmd_id": telem.get("last_cmd_id") is not None,
        "last_ack_ok": telem.get("last_ack_ok") is not None,
        "brake_cyl_bar": telem.get("brake_cyl_bar") is not None,
    }


def probe_mod_label(flags: dict[str, bool]) -> str:
    if not any(flags.values()):
        return "LEGACY (reinstalar install_ue4ss_probe.bat)"
    parts = [k for k, v in flags.items() if v]
    missing = [k for k, v in flags.items() if not v]
    txt = "+".join(parts) if parts else "?"
    if missing:
        txt += f" falta={','.join(missing)}"
    return txt


def channel_stats_from_state(state: Any, recent_acks: list[float]) -> dict[str, Any]:
    total = int(getattr(state, "successes", 0)) + int(getattr(state, "failures", 0))
    ok = int(getattr(state, "successes", 0))
    ack_ok_pct = (100.0 * ok / total) if total else 0.0
    return {
        "cmd_total": total,
        "cmd_ok": ok,
        "cmd_fail": int(getattr(state, "failures", 0)),
        "ack_ok_pct": ack_ok_pct,
        "ack_p95_ms": percentile(recent_acks, 95),
        "ack_last_ms": float(getattr(state, "last_ack_ms", 0.0)),
        "retries": int(getattr(state, "retries", 0)),
        "drops": int(getattr(state, "drops", 0)),
        "last_error": str(getattr(state, "last_error", "") or "—"),
        "ack_timeout_s": float(getattr(state, "ack_timeout_s", 0.0)),
        "confirmed_id": getattr(state, "confirmed_cmd_id", None),
        "telem_cmd_id": getattr(state, "telem_cmd_id", None),
        "last_via": str(getattr(state, "last_via", "") or "—"),
        "ipc_ok": int(getattr(state, "ipc_ok", 0)),
        "http_ok": int(getattr(state, "http_ok", 0)),
    }


def acceptance_verdict(
    *,
    loop: LoopMetrics,
    channel: dict[str, Any],
    controller: ControllerMetrics,
    telem_poll_hz: float,
    mod_flags: dict[str, bool],
) -> str:
    """PASS / WARN / FAIL según criterios CANAL_CONTROL."""
    issues: list[str] = []
    if loop.work_over_150 > 0:
        issues.append(f"work>150ms×{loop.work_over_150}")
    if 0 < loop.loop_hz_min < 18.0:
        issues.append(f"loop_hz_min={loop.loop_hz_min:.1f}")
    if 0 < telem_poll_hz < 15.0:
        issues.append(f"telem_poll={telem_poll_hz:.1f}Hz")
    if not mod_flags.get("lever_notch") or not mod_flags.get("last_cmd_id"):
        issues.append("mod_lua_viejo")
    cmd_total = int(channel.get("cmd_total", 0))
    ack_ok_pct = float(channel.get("ack_ok_pct", 0.0))
    ack_p95 = float(channel.get("ack_p95_ms", 0.0))
    if cmd_total > 0 and ack_ok_pct < 95.0:
        issues.append(f"ack_ok={ack_ok_pct:.0f}%")
    hb_total = loop.heartbeats_cf_y + loop.heartbeats_cf_n
    if cmd_total > 0 and hb_total > 0:
        match_pct = 100.0 * loop.heartbeats_match_y / hb_total
        if match_pct < 50.0:
            issues.append(f"match={match_pct:.0f}%")
    if cmd_total > 0 and ack_p95 > 200.0:
        issues.append(f"ack_p95={ack_p95:.0f}ms")
    if controller.keyboard > 0:
        issues.append(f"KEY×{controller.keyboard}")
    if not issues:
        return "PASS"
    if cmd_total > 0 and (
        ack_ok_pct < 50.0
        or (hb_total > 0 and loop.heartbeats_match_y == 0)
    ):
        return "FAIL"
    return "WARN"
