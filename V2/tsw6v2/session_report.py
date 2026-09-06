"""Informe de sesión P1 — resumen JSONL + replay HTML."""

from __future__ import annotations
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

# V2 en PYTHONPATH (V2/run_p1_session.bat lo configura)
from tsw6v2.constants import MPH_TO_MS
from tsw6v2.p1_layers import LAYERS, classify_from_p1, layer_label
from tsw6v2.physics import apply_zone_margin_m


def load_ticks(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    session = None
    ticks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") == "session":
            session = row
        elif row.get("type") == "tick":
            ticks.append(row)
    return session, ticks


def summarize(path: Path) -> dict[str, Any]:
    session, ticks = load_ticks(path)
    if not ticks:
        return {"session": session, "error": "sin ticks"}

    reasons: Counter[str] = Counter()
    cmds: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    for t in ticks:
        p1 = t.get("p1") or {}
        if p1:
            reasons[p1.get("reason") or "null"] += 1
            cmds[p1.get("cmd") or "null"] += 1
        layers[classify_from_p1(p1 if p1 else None)] += 1

    limits: list[dict[str, Any]] = []
    prev_lim: tuple[Any, ...] | None = None
    for t in ticks:
        lim_mph = t.get("lim_mph")
        if lim_mph is None:
            continue
        key = (lim_mph, round(float(t.get("lim_dist_m") or 0)))
        if key != prev_lim:
            limits.append(
                {
                    "tick": t["tick"],
                    "t_s": round(t["t_ms"] / 1000, 1),
                    "spd": t.get("spd_mph"),
                    "lim_mph": lim_mph,
                    "lim_dist_m": t.get("lim_dist_m"),
                    "eff_mph": t.get("eff_mph"),
                    "lever": t.get("lever"),
                    "p1_reason": (t.get("p1") or {}).get("reason"),
                }
            )
            prev_lim = key

    ipc_sent = sum(1 for t in ticks if (t.get("ipc") or {}).get("sent"))
    spds = [float(t["spd_mph"]) for t in ticks if t.get("spd_mph") is not None]

    apply_events = [
        t
        for t in ticks
        if (t.get("p1") or {}).get("cmd") == "APPLY"
    ]
    release_events = [
        t
        for t in ticks
        if (t.get("p1") or {}).get("cmd") == "RELEASE"
    ]

    def _event_row(t: dict[str, Any]) -> dict[str, Any]:
        p1 = t.get("p1") or {}
        return {
            "tick": t["tick"],
            "t_s": round(t["t_ms"] / 1000, 1),
            "spd": t.get("spd_mph"),
            "lever": t.get("lever"),
            "lim_mph": t.get("lim_mph"),
            "lim_dist_m": t.get("lim_dist_m"),
            "cmd": p1.get("cmd"),
            "phase": p1.get("phase"),
            "dist_start_m": p1.get("dist_start_m"),
            "apply_now": p1.get("apply_now"),
            "reason": p1.get("reason"),
            "ipc": (t.get("ipc") or {}).get("sent"),
        }

    return {
        "session": session,
        "n_ticks": len(ticks),
        "duration_s": round(ticks[-1]["t_ms"] / 1000, 1),
        "speed_min_max": (round(min(spds), 1), round(max(spds), 1)) if spds else None,
        "ipc_sent": ipc_sent,
        "p1_reasons": dict(reasons.most_common()),
        "p1_cmds": dict(cmds.most_common()),
        "p1_layers": {k: layers[k] for k in sorted(layers.keys())},
        "apply_ticks": len(apply_events),
        "release_ticks": len(release_events),
        "apply_events": [_event_row(t) for t in apply_events],
        "release_events": [_event_row(t) for t in release_events],
        "limit_transitions": len(limits),
        "limit_events": limits[:20],
        "traction_ticks": sum(1 for t in ticks if (t.get("lever") or 0) > 4),
        "command_none_near": sum(
            1
            for t in ticks
            if (t.get("p1") or {}).get("reason") == "command_none"
            and (t.get("p1") or {}).get("dist_start_m", 999) < 50
        ),
        "apply_now_true": sum(
            1 for t in ticks if (t.get("p1") or {}).get("apply_now") is True
        ),
    }


def _apply_zone_m(*, spd_mph: float, lim_dist_m: float, dist_start_m: float) -> float:
    apply_at = max(0.0, float(lim_dist_m) - float(dist_start_m))
    return apply_zone_margin_m(float(spd_mph) * MPH_TO_MS, apply_at)


def _append_kinematic_marker(
    markers: list[dict[str, Any]],
    *,
    t_s: float,
    lim_mph: Any,
    spd: float,
    lim_dist_m: float,
    ds: float,
    kind: str,
) -> None:
    apply_at = max(0.0, lim_dist_m - ds)
    zone = _apply_zone_m(
        spd_mph=spd,
        lim_dist_m=lim_dist_m,
        dist_start_m=ds,
    )
    markers.append(
        {
            "t": round(t_s, 2),
            "kind": kind,
            "lim_mph": lim_mph,
            "spd": round(spd, 1),
            "lim_dist_m": round(lim_dist_m, 1),
            "dist_start_m": round(ds, 1),
            "apply_at_m": round(apply_at, 1),
            "zone_m": round(zone, 1),
        }
    )


def _kinematic_markers(ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cruces ds=0 y primer APPLY por cartel (ideal vs real)."""
    markers: list[dict[str, Any]] = []
    prev_ds: float | None = None
    prev_t_s: float | None = None
    prev_lim_dist: float | None = None
    prev_spd: float | None = None
    seen_apply: set[str] = set()

    for t in ticks:
        p1 = t.get("p1") or {}
        ds = p1.get("dist_start_m")
        lim_dist = t.get("lim_dist_m")
        spd = t.get("spd_mph")
        if ds is None or lim_dist is None or spd is None:
            prev_ds = None
            prev_t_s = None
            prev_lim_dist = None
            prev_spd = None
            continue

        ds_f = float(ds)
        lim_f = float(lim_dist)
        spd_f = float(spd)
        t_s = float(t["t_ms"]) / 1000.0
        detail = str(p1.get("detail") or "")

        if prev_ds is not None and prev_ds > 0 and ds_f <= 0:
            if prev_ds != ds_f and prev_t_s is not None:
                frac = prev_ds / (prev_ds - ds_f)
                cross_t = prev_t_s + frac * (t_s - prev_t_s)
                lim_cross = lim_f
                if prev_lim_dist is not None:
                    lim_cross = prev_lim_dist + frac * (lim_f - prev_lim_dist)
                spd_cross = spd_f
                if prev_spd is not None:
                    spd_cross = prev_spd + frac * (spd_f - prev_spd)
                ds_cross = 0.0
            else:
                cross_t = t_s
                lim_cross = lim_f
                spd_cross = spd_f
                ds_cross = ds_f
            _append_kinematic_marker(
                markers,
                t_s=cross_t,
                lim_mph=t.get("lim_mph"),
                spd=spd_cross,
                lim_dist_m=lim_cross,
                ds=ds_cross,
                kind="ds0",
            )

        if p1.get("apply_now") is True and detail and detail not in seen_apply:
            seen_apply.add(detail)
            _append_kinematic_marker(
                markers,
                t_s=t_s,
                lim_mph=t.get("lim_mph"),
                spd=spd_f,
                lim_dist_m=lim_f,
                ds=ds_f,
                kind="apply",
            )

        prev_ds = ds_f
        prev_t_s = t_s
        prev_lim_dist = lim_f
        prev_spd = spd_f

    return markers


def _ds_chart_bounds(series: list[dict[str, Any]]) -> tuple[float, float]:
    """Escala legible para dist_start (evita aplastar por valores lejanos al cartel)."""
    raw = [float(p["ds"]) for p in series if p.get("ds") is not None]
    if not raw:
        return -50.0, 120.0
    core = [v for v in raw if -120.0 <= v <= 200.0]
    pool = core or raw
    lo = min(pool)
    hi = max(pool)
    pad = max(12.0, (hi - lo) * 0.12)
    return min(-50.0, lo - pad), max(120.0, hi + pad)


def _dist_chart_bounds(series: list[dict[str, Any]]) -> tuple[float, float]:
    raw = [float(p["dist"]) for p in series if p.get("dist") is not None]
    if not raw:
        return 0.0, 500.0
    hi = max(raw)
    return 0.0, max(200.0, hi * 1.05)


_CHART_LAYER_COL: dict[str, str] = {
    "WATCH": "#64748b",
    "WAIT": "#ca8a04",
    "COAST_PWR": "#a78bfa",
    "HOLD_DH": "#38bdf8",
    "BRAKE": "#ef4444",
    "RELEASE": "#22c55e",
    "HOLD": "#4ade80",
    "OK": "#334155",
    "NONE": "#1e293b",
    "GAP": "#fb7185",
    "IDLE": "#0f1115",
}

_CHART_W = 1100
_CHART_PAD_L = 76
_CHART_PAD_R = 14
_CHART_PAD_TOP = 10


def _nice_axis_ticks(lo: float, hi: float, *, max_ticks: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    span = hi - lo
    raw = span / max(1, max_ticks - 1)
    if raw <= 0:
        return [lo, hi]
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step = max(mag, math.ceil(raw / mag) * mag)
    start = math.floor(lo / step) * step
    ticks: list[float] = []
    v = start
    while v <= hi + step * 0.01:
        if v >= lo - step * 0.01:
            ticks.append(v)
        v += step
    if not ticks:
        return [lo, hi]
    return ticks[: max_ticks + 2]


def _fmt_axis(v: float) -> str:
    av = abs(v)
    if av >= 100:
        return f"{v:.0f}"
    if av >= 10:
        return f"{v:.0f}"
    return f"{v:.1f}"


def _marker_badge_slots(
    markers: list[dict[str, Any]],
    x_t,
    *,
    min_gap: float = 26.0,
) -> dict[int, int]:
    """Asigna carril vertical (0..2) por marcador para evitar solapar números."""
    lanes: dict[int, int] = {}
    last_x: list[float] = [-999.0, -999.0, -999.0]
    for idx, m in enumerate(sorted(markers, key=lambda row: float(row["t"]))):
        if m.get("kind") != "apply":
            continue
        cx = x_t(float(m["t"]))
        lane = 0
        for try_lane in range(3):
            if cx - last_x[try_lane] >= min_gap:
                lane = try_lane
                break
        else:
            lane = int(idx % 3)
        last_x[lane] = cx
        lanes[idx] = lane
    return lanes


def _render_chart_svg(
    series: list[dict[str, Any]],
    markers: list[dict[str, Any]],
) -> str:
    """SVG embebido: 4 paneles apilados con ejes y sin texto superpuesto."""
    if not series:
        return '<text x="40" y="40" fill="#94a3b8" font-size="12">Sin datos</text>'

    w = _CHART_W
    pad_l = _CHART_PAD_L
    pad_r = _CHART_PAD_R
    plot_w = w - pad_l - pad_r

    h_spd = 168
    h_dist = 108
    h_ds = 88
    h_layers = 34
    gap = 10
    y_spd = _CHART_PAD_TOP
    y_dist = y_spd + h_spd + gap
    y_ds = y_dist + h_dist + gap
    y_layers = y_ds + h_ds + gap
    total_h = y_layers + h_layers + 8

    t0 = float(series[0]["t"])
    t1 = float(series[-1]["t"])
    t_span = max(0.1, t1 - t0)

    def x_t(t: float) -> float:
        return pad_l + (float(t) - t0) / t_span * plot_w

    def y_in_panel(v: float, lo: float, hi: float, y_top: float, height: float) -> float:
        span = max(hi - lo, 1e-6)
        inner = height - 16
        return y_top + 8 + (1.0 - (float(v) - lo) / span) * inner

    y_max = max(max(p.get("spd") or 0, p.get("eff") or 0, p.get("lim") or 0) for p in series) + 5
    y_min = min(p.get("spd") or 0 for p in series) - 2
    ds_min, ds_max = _ds_chart_bounds(series)
    dist_min, dist_max = _dist_chart_bounds(series)

    def line_path(key: str, yfn) -> str:
        parts: list[str] = []
        for p in series:
            if p.get(key) is None:
                continue
            cmd = "M" if not parts else "L"
            parts.append(f"{cmd}{x_t(p['t']):.1f},{yfn(p[key]):.1f}")
        if not parts:
            return ""
        return f'<path d="{" ".join(parts)}" fill="none" stroke-width="1.5"/>'

    out: list[str] = [
        f'<rect x="0" y="0" width="{w}" height="{total_h}" fill="#1a1f28" rx="8"/>',
    ]

    def panel_frame(y: float, height: float, title: str, bg: str = "#151a22") -> None:
        out.append(
            f'<rect x="{pad_l - 4}" y="{y:.1f}" width="{plot_w + 8}" height="{height:.1f}" '
            f'fill="{bg}" stroke="#2a3140" stroke-width="1" rx="4"/>'
        )
        out.append(
            f'<text x="8" y="{y + 14:.1f}" fill="#94a3b8" font-size="11" font-weight="600">{title}</text>'
        )

    def draw_axis(
        y_top: float,
        height: float,
        lo: float,
        hi: float,
        unit: str,
        *,
        zero_line: bool = False,
    ) -> None:
        ticks = _nice_axis_ticks(lo, hi)
        for tick in ticks:
            yy = y_in_panel(tick, lo, hi, y_top, height)
            out.append(
                f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + plot_w}" y2="{yy:.1f}" '
                f'stroke="#2a3140" stroke-width="1"/>'
            )
            out.append(
                f'<text x="{pad_l - 8}" y="{yy + 3:.1f}" fill="#cbd5e1" font-size="10" '
                f'text-anchor="end">{_fmt_axis(tick)}{unit}</text>'
            )
        if zero_line and lo < 0 < hi:
            yz = y_in_panel(0.0, lo, hi, y_top, height)
            out.append(
                f'<line x1="{pad_l}" y1="{yz:.1f}" x2="{pad_l + plot_w}" y2="{yz:.1f}" '
                f'stroke="#cbd5e1" stroke-width="1" stroke-dasharray="5,4" opacity="0.7"/>'
            )

    panel_frame(y_spd, h_spd, "Velocidad (mph)")
    draw_axis(y_spd, h_spd, y_min, y_max, "")
    for key, color in (("spd", "#7eb6ff"), ("eff", "#6bcf7f"), ("lim", "#e8a87c")):
        path = line_path(
            key,
            lambda v, lo=y_min, hi=y_max, yt=y_spd, ht=h_spd: y_in_panel(v, lo, hi, yt, ht),
        )
        if path:
            out.append(path.replace('stroke-width="1.5"', f'stroke="{color}" stroke-width="1.5"'))

    panel_frame(y_dist, h_dist, "Distancia al cartel (m)", bg="#121820")
    draw_axis(y_dist, h_dist, dist_min, dist_max, "m")
    dist_path = line_path(
        "dist",
        lambda v, lo=dist_min, hi=dist_max, yt=y_dist, ht=h_dist: y_in_panel(v, lo, hi, yt, ht),
    )
    if dist_path:
        out.append(dist_path.replace('stroke-width="1.5"', 'stroke="#38bdf8" stroke-width="2"'))

    panel_frame(y_ds, h_ds, "Margen cinemático ds (m)")
    draw_axis(y_ds, h_ds, ds_min, ds_max, "m", zero_line=True)
    for i in range(len(series) - 1):
        a, b = series[i], series[i + 1]
        if a.get("zone") is None or a.get("ds") is None:
            continue
        z = float(a["zone"])
        y_top = y_in_panel(z, ds_min, ds_max, y_ds, h_ds)
        y_bot = y_in_panel(-z, ds_min, ds_max, y_ds, h_ds)
        width = max(1.0, x_t(b["t"]) - x_t(a["t"]))
        out.append(
            f'<rect x="{x_t(a["t"]):.1f}" y="{y_top:.1f}" width="{width:.1f}" '
            f'height="{(y_bot - y_top):.1f}" fill="#22c55e" opacity="0.12"/>'
        )
    ds_path = line_path(
        "ds",
        lambda v, lo=ds_min, hi=ds_max, yt=y_ds, ht=h_ds: y_in_panel(v, lo, hi, yt, ht),
    )
    if ds_path:
        out.append(ds_path.replace('stroke-width="1.5"', 'stroke="#c9a0ff" stroke-width="1.5"'))

    panel_frame(y_layers, h_layers, "Capa P1", bg="#12151b")
    for i in range(len(series) - 1):
        a, b = series[i], series[i + 1]
        lay = a.get("layer") or "IDLE"
        if lay == "IDLE":
            continue
        col = _CHART_LAYER_COL.get(lay, "#444")
        width = max(1.0, x_t(b["t"]) - x_t(a["t"]))
        out.append(
            f'<rect x="{x_t(a["t"]):.1f}" y="{y_layers + 6:.1f}" width="{width:.1f}" '
            f'height="{h_layers - 12:.1f}" fill="{col}" opacity="0.9" rx="2"/>'
        )

    apply_markers = [m for m in markers if m.get("kind") == "apply"]
    badge_lanes = _marker_badge_slots(apply_markers, x_t)
    for idx, m in enumerate(sorted(apply_markers, key=lambda row: float(row["t"]))):
        cx = x_t(float(m["t"]))
        lane = badge_lanes.get(idx, 0)
        badge_y = y_spd + 16 + lane * 16
        lim_m = m.get("lim_dist_m")
        out.append(
            f'<line x1="{cx:.1f}" y1="{y_spd}" x2="{cx:.1f}" y2="{y_layers + h_layers}" '
            f'stroke="#38bdf8" stroke-width="1" stroke-dasharray="3,4" opacity="0.45"/>'
        )
        out.append(f'<circle cx="{cx:.1f}" cy="{badge_y:.1f}" r="9" fill="#0ea5e9" opacity="0.95"/>')
        out.append(
            f'<text x="{cx:.1f}" y="{badge_y + 4:.1f}" fill="#0f172a" font-size="10" '
            f'font-weight="700" text-anchor="middle">{idx + 1}</text>'
        )
        if lim_m is not None:
            lim_label = f"{int(round(float(lim_m)))}m"
            out.append(
                f'<text x="{cx:.1f}" y="{badge_y + 22:.1f}" fill="#38bdf8" font-size="9" '
                f'font-weight="600" text-anchor="middle">{lim_label}</text>'
            )
            dist_start_m = m.get("dist_start_m")
            if dist_start_m is not None:
                ds_lbl = f"ds {int(round(float(dist_start_m)))}m"
                out.append(
                    f'<text x="{cx:.1f}" y="{y_ds + h_ds - 4:.1f}" fill="#c9a0ff" font-size="9" '
                    f'text-anchor="middle">{ds_lbl}</text>'
                )
            dist_y = y_in_panel(
                float(lim_m),
                dist_min,
                dist_max,
                y_dist,
                h_dist,
            )
            out.append(
                f'<circle cx="{cx:.1f}" cy="{dist_y:.1f}" r="4" fill="#38bdf8" stroke="#0f172a" '
                f'stroke-width="1"/>'
            )

    for m in markers:
        if m.get("kind") == "apply":
            continue
        cx = x_t(float(m["t"]))
        out.append(
            f'<line x1="{cx:.1f}" y1="{y_ds}" x2="{cx:.1f}" y2="{y_ds + h_ds}" '
            f'stroke="#67e8f9" stroke-width="1.5" stroke-dasharray="2,3" opacity="0.65"/>'
        )

    for p in series:
        if p.get("cmd") not in ("APPLY", "RELEASE"):
            continue
        col = "#ef4444" if p.get("cmd") == "APPLY" else "#eab308"
        cx = x_t(p["t"])
        out.append(
            f'<line x1="{cx:.1f}" y1="{y_spd}" x2="{cx:.1f}" y2="{y_layers + h_layers}" '
            f'stroke="{col}" stroke-width="1.25" opacity="0.22"/>'
        )

    out.append(
        f'<text x="{pad_l + plot_w - 4}" y="{y_spd + 14:.1f}" fill="#7eb6ff" font-size="10" '
        f'text-anchor="end">spd</text>'
    )
    out.append(
        f'<text x="{pad_l + plot_w - 4}" y="{y_spd + 26:.1f}" fill="#6bcf7f" font-size="10" '
        f'text-anchor="end">eff</text>'
    )
    out.append(
        f'<text x="{pad_l + plot_w - 4}" y="{y_spd + 38:.1f}" fill="#e8a87c" font-size="10" '
        f'text-anchor="end">lim</text>'
    )

    return "".join(out)


def _chart_view_height() -> int:
    return _CHART_PAD_TOP + 168 + 10 + 108 + 10 + 88 + 10 + 34 + 16


def _apply_marker_numbers(markers: list[dict[str, Any]]) -> dict[float, int]:
    out: dict[float, int] = {}
    for idx, m in enumerate(sorted(
        [row for row in markers if row.get("kind") == "apply"],
        key=lambda row: float(row["t"]),
    )):
        out[float(m["t"])] = idx + 1
    return out


def _session_warning_html(summary: dict[str, Any]) -> str:
    dur = float(summary.get("duration_s") or 0)
    n = int(summary.get("n_ticks") or 0)
    if dur >= 15.0 and n >= 50:
        return ""
    return (
        f'<p class="warn"><b>Sesión muy corta</b> ({dur:g}s, {n} ticks). '
        f"El gráfico se verá plano; para debatir P1 usa "
        f"<code>run_p1_session.bat limit cross-city</code> y conduce 2–5 min antes de Ctrl+C.</p>"
    )


def _meta_line(summary: dict[str, Any]) -> str:
    sess = summary.get("session") or {}
    return (
        f"modo={sess.get('mode')} ruta={sess.get('route')} git={sess.get('git')} "
        f"· {summary.get('n_ticks')} ticks · {summary.get('duration_s')}s"
    )


def _stats_html(summary: dict[str, Any], layers_meta: dict[str, dict[str, str]]) -> tuple[str, str]:
    layers = summary.get("p1_layers") or {}
    blocks = [
        ("Frenar", summary.get("apply_ticks", 0)),
        ("Soltar", summary.get("release_ticks", 0)),
        ("IPC", summary.get("ipc_sent", 0)),
        ("Vigilar", layers.get("WATCH", 0)),
        ("Revisar GAP", layers.get("GAP", 0)),
    ]
    stats = "".join(f'<div class="stat"><b>{v}</b>{k}</div>' for k, v in blocks)
    layer_stats = "".join(
        f'<div class="stat"><b>{v}</b>{layers_meta.get(k, {}).get("label", k)}</div>'
        for k, v in sorted(layers.items())
        if v > 0 and k != "IDLE"
    )
    return stats, layer_stats


MIN_HTML_TICKS = 15
MIN_HTML_DURATION_S = 5.0
MIN_BROWSER_TICKS = 40
MIN_BROWSER_DURATION_S = 12.0


def session_ready_for_html(data: dict[str, Any]) -> bool:
    if "error" in data:
        return False
    return (
        int(data.get("n_ticks") or 0) >= MIN_HTML_TICKS
        and float(data.get("duration_s") or 0) >= MIN_HTML_DURATION_S
    )


def session_ready_for_browser(data: dict[str, Any]) -> bool:
    if not session_ready_for_html(data):
        return False
    return (
        int(data.get("n_ticks") or 0) >= MIN_BROWSER_TICKS
        and float(data.get("duration_s") or 0) >= MIN_BROWSER_DURATION_S
    )


def _render_ds0_rows(markers: list[dict[str, Any]]) -> str:
    if not markers:
        return '<tr><td colspan="7">Sin marcas cinemáticas en sesión</td></tr>'
    badge = _apply_marker_numbers(markers)
    rows: list[str] = []
    for m in sorted(markers, key=lambda row: float(row["t"])):
        dist = round(float(m.get("lim_dist_m") or m.get("apply_at_m") or 0))
        zone = round(float(m.get("zone_m") or 0))
        spd = m.get("spd")
        spd_s = f"{float(spd):.1f}" if isinstance(spd, (int, float)) else str(spd)
        ds = m.get("dist_start_m")
        ds_s = f"{float(ds):.0f}" if isinstance(ds, (int, float)) else ""
        kind = "APPLY real" if m.get("kind") == "apply" else "ds=0 ideal"
        num = badge.get(float(m["t"]), "")
        num_s = f'<b>{num}</b>' if num else "—"
        rows.append(
            f'<tr><td>{num_s}</td><td>{kind}</td><td>{m["t"]}</td><td>{spd_s}</td>'
            f'<td>{m.get("lim_mph")} mph</td><td>{dist} m</td>'
            f'<td>{ds_s} / ±{zone} m</td></tr>'
        )
    return "".join(rows)


def _downsample_series(ticks: list[dict[str, Any]], max_pts: int = 800) -> list[dict[str, Any]]:
    if len(ticks) <= max_pts:
        step = 1
    else:
        step = max(1, len(ticks) // max_pts)
    out: list[dict[str, Any]] = []
    for i, t in enumerate(ticks):
        if i % step != 0 and i != len(ticks) - 1:
            continue
        p1 = t.get("p1") or {}
        layer = p1.get("layer") or classify_from_p1(p1 if p1 else None)
        ds = p1.get("dist_start_m")
        zone = None
        if (
            ds is not None
            and t.get("lim_dist_m") is not None
            and t.get("spd_mph") is not None
        ):
            zone = round(
                _apply_zone_m(
                    spd_mph=float(t["spd_mph"]),
                    lim_dist_m=float(t["lim_dist_m"]),
                    dist_start_m=float(ds),
                ),
                1,
            )
        out.append(
            {
                "t": round(t["t_ms"] / 1000, 1),
                "spd": t.get("spd_mph"),
                "eff": t.get("eff_mph"),
                "lim": t.get("lim_mph"),
                "dist": t.get("lim_dist_m"),
                "ds": ds,
                "zone": zone,
                "lev": t.get("lever"),
                "tgt": t.get("target"),
                "cmd": p1.get("cmd"),
                "why": p1.get("reason"),
                "layer": layer,
            }
        )
    return out


def write_html_replay(path: Path, out: Path) -> None:
    """Replay visual (HTML estático) para debatir sesión sin TSW."""
    session, ticks = load_ticks(path)
    if not ticks:
        raise ValueError("sin ticks")
    summary = summarize(path)
    series = _downsample_series(ticks)
    markers = _kinematic_markers(ticks)
    layers_meta = {
        lid: {"label": info[0], "help": info[1]}
        for lid, info in LAYERS.items()
    }
    payload = {
        "session": session,
        "summary": summary,
        "series": series,
        "markers": markers,
        "layers_meta": layers_meta,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    ds0_rows = _render_ds0_rows(markers)
    chart_svg = _render_chart_svg(series, markers)
    warn_html = _session_warning_html(summary)
    meta_html = _meta_line(summary)
    stats_html, layer_stats_html = _stats_html(summary, layers_meta)
    chart_h = _chart_view_height()
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>P1 replay — {session.get('route', '?') if session else path.name}</title>
<style>
  body {{ font: 14px/1.4 system-ui, sans-serif; margin: 1rem 1.5rem; background: #0f1115; color: #e6e8ec; }}
  h1 {{ font-size: 1.1rem; font-weight: 600; }}
  .meta {{ color: #9aa3b2; margin-bottom: 1rem; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }}
  .stat {{ background: #1a1f28; padding: 0.5rem 0.75rem; border-radius: 6px; min-width: 8rem; }}
  .stat b {{ display: block; font-size: 1.25rem; color: #7eb6ff; }}
  svg {{ background: #1a1f28; border-radius: 8px; width: 100%; max-width: 1100px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 1100px; font-size: 12px; }}
  th, td {{ border: 1px solid #2a3140; padding: 4px 8px; text-align: left; }}
  th {{ background: #1a1f28; }}
  .leg {{ font-size: 12px; color: #9aa3b2; margin: 0.25rem 0 0.75rem; }}
  .note {{ max-width: 800px; color: #b8c0cc; margin-top: 1rem; }}
  a {{ color: #7eb6ff; }}
  .gloss {{ font-size: 12px; max-width: 1100px; }}
  .warn {{ background: #422006; border: 1px solid #b45309; color: #fcd34d; padding: 0.6rem 0.75rem; border-radius: 6px; max-width: 1100px; }}
</style>
</head>
<body>
<h1>Replay P1 — cartel (capas)</h1>
<p class="leg"><a href="../../docs/v2/p1_limit_capas.html">Diagrama concepto</a> — franja inferior = capa de decisión cada momento</p>
{warn_html}
<div class="meta" id="meta">{meta_html}</div>
<div class="stats" id="stats">{stats_html}</div>
<p class="leg">Cuatro paneles: <b>velocidad</b> · <b>m al cartel</b> (cian) · <b>ds</b> (violeta, línea punteada = 0) · <b>capa</b>.</p>
<p class="leg">Círculos numerados = primer APPLY por cartel; debajo <b>Xm</b> = metros al cartel en ese momento. Punto cian en panel distancia = misma marca.</p>
<svg id="chart" viewBox="0 0 {_CHART_W} {chart_h}" height="{chart_h}" xmlns="http://www.w3.org/2000/svg">{chart_svg}</svg>
<h2>Capas (tiempo en sesión)</h2>
<div class="stats" id="layer-stats">{layer_stats_html}</div>
<h2>Marcas cinemáticas (ideal vs APPLY)</h2>
<table id="ds0"><thead><tr>
<th>#</th><th>tipo</th><th>t(s)</th><th>spd</th><th>cartel</th><th>m al cartel</th><th>ds / zona</th>
</tr></thead><tbody id="ds0-body">{ds0_rows}</tbody></table>
<p class="leg">El <b>#</b> coincide con el círculo en el gráfico. <b>m al cartel</b> = probe. <b>ds</b> = margen al punto cinemático (0 = ideal).</p>
<h2>Eventos Frenar / Soltar</h2>
<table id="events"><thead><tr>
<th>t(s)</th><th>spd</th><th>capa</th><th>cmd</th><th>lim@dist</th><th>ds</th><th>apply</th><th>ipc</th>
</tr></thead><tbody></tbody></table>
<h2>Glosario capas</h2>
<table class="gloss" id="gloss"><thead><tr><th>Capa</th><th>Código</th><th>Significado</th></tr></thead><tbody></tbody></table>
<p class="note" id="note"></p>
<script>
const LAYER_COL = {{
  WATCH:'#64748b', WAIT:'#ca8a04', COAST_PWR:'#a78bfa', HOLD_DH:'#38bdf8', BRAKE:'#ef4444',
  RELEASE:'#22c55e', HOLD:'#4ade80', OK:'#334155', NONE:'#1e293b', GAP:'#fb7185', IDLE:'#0f1115'
}};
const DATA = {data_json};
const s = DATA.summary;
const meta = document.getElementById('meta');
meta.textContent = `modo=${{s.session?.mode}} ruta=${{s.session?.route}} git=${{s.session?.git}} · ${{s.n_ticks}} ticks · ${{s.duration_s}}s`;

const stats = [
  ['Frenar', s.apply_ticks], ['Soltar', s.release_ticks], ['IPC', s.ipc_sent],
  ['Vigilar', s.p1_layers?.WATCH||0], ['Revisar GAP', s.p1_layers?.GAP||0],
];
document.getElementById('stats').innerHTML = stats.map(([k,v]) =>
  `<div class="stat"><b>${{v}}</b>${{k}}</div>`).join('');

const ls = s.p1_layers || {{}};
document.getElementById('layer-stats').innerHTML = Object.entries(ls)
  .filter(([k,v])=>v>0 && k!=='IDLE')
  .map(([k,v])=>`<div class="stat"><b>${{v}}</b>${{DATA.layers_meta[k]?.label||k}}</div>`).join('');

document.querySelector('#gloss tbody').innerHTML = Object.entries(DATA.layers_meta||{{}})
  .filter(([k])=>k!=='IDLE')
  .map(([k,v])=>`<tr><td>${{v.label}}</td><td>${{k}}</td><td>${{v.help}}</td></tr>`).join('');

const rows = [...(s.apply_events||[]), ...(s.release_events||[])].sort((a,b)=>a.t_s-b.t_s);
document.querySelector('#events tbody').innerHTML = rows.map(e =>
  `<tr><td>${{e.t_s}}</td><td>${{e.spd?.toFixed?.(1)??e.spd}}</td>`+
  `<td>${{e.reason==='plan'?'Frenar':e.reason==='release'?'Soltar':e.reason||''}}</td>`+
  `<td>${{e.cmd||''}}</td><td>${{e.lim_mph}}@${{Math.round(e.lim_dist_m||0)}}m</td>`+
  `<td>${{e.dist_start_m?.toFixed?.(0)??''}}</td><td>${{e.apply_now?'Y':'N'}}</td><td>${{e.ipc?'Y':''}}</td></tr>`).join('');

const mk = DATA.markers||[];
const applyN = mk.filter(m=>m.kind==='apply').length;
document.getElementById('note').innerHTML =
  '<b>Debate:</b> panel distancia baja hacia el cartel; ds cruza 0 = ideal. '+
  'Si el círculo APPLY va antes de ds=0, el margen de zona adelanta el freno. '+
  (applyN ? `Marcas APPLY numeradas: ${{applyN}}.` : 'Sin APPLY en sesión.') +
  ' <a href="../../docs/v2/p1_limit_capas.html">Diagrama concepto</a>.';
</script>
</body>
</html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def finalize_session_report(
    jsonl_path: Path,
    *,
    html_path: Path | None = None,
    summary: dict[str, Any] | None = None,
    force: bool = False,
) -> Path | None:
    """Al cerrar sesión: genera replay HTML junto al JSONL (si hay datos suficientes)."""
    data = summary or summarize(jsonl_path)
    if not force and not session_ready_for_html(data):
        return None
    out = html_path or jsonl_path.with_suffix(".html")
    tmp = out.with_suffix(".html.part")
    write_html_replay(jsonl_path, tmp)
    tmp.replace(out)
    return out


def format_summary_line(data: dict[str, Any]) -> str:
    if "error" in data:
        return f"resumen: {data['error']}"
    layers = data.get("p1_layers") or {}
    return (
        f"resumen: {data['duration_s']}s · "
        f"Frenar={data.get('apply_ticks', 0)} Soltar={data.get('release_ticks', 0)} · "
        f"Vigilar={layers.get('WATCH', 0)} GAP={layers.get('GAP', 0)} · "
        f"IPC={data.get('ipc_sent', 0)}"
    )


def print_report(data: dict[str, Any]) -> None:
    if "error" in data:
        print(data["error"])
        return
    s = data["session"] or {}
    print("=== Sesión P1 V2 ===")
    print(f"  modo={s.get('mode')}  ruta={s.get('route')}  git={s.get('git')}")
    print(f"  ticks={data['n_ticks']}  duración={data['duration_s']}s")
    if data["speed_min_max"]:
        print(f"  velocidad {data['speed_min_max'][0]}–{data['speed_min_max'][1]} mph")
    print(f"  IPC enviados: {data['ipc_sent']}")
    print(f"  APPLY: {data['apply_ticks']}  RELEASE: {data['release_ticks']}")
    print(f"  tracción (lever>4): {data['traction_ticks']} ticks")
    print()
    print(format_summary_line(data))
    print()
    print("=== Capas ===")
    for k, v in sorted((data.get("p1_layers") or {}).items()):
        if v > 0 and k != "IDLE":
            print(f"  {k}: {v}")
    print()
    print(f"GAP (revisar): {data.get('command_none_near', 0)} ticks cerca cartel sin cmd")
