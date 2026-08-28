"""Rendimiento del probe Lua a partir de UE4SS.log (líneas seq=).

No corre dentro del juego: mide el ritmo de ``[TelemetryProbe] seq=``
(cadencia ~LOG_INTERVAL, Hz = Δseq/Δt) y el hitch seq 1→2.

Uso:
  python -m tsw6.telemetry.lua_probe_perf
  python -m tsw6.telemetry.lua_probe_perf "C:\\...\\UE4SS.log"
"""
from __future__ import annotations

import argparse
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_SEQ_LINE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]"
    r".*\[TelemetryProbe\] seq=(\d+)\b"
)
_PERF_LINE = re.compile(
    r"\[TelemetryProbe\] perf writes=(\d+) avg_ms=([\d.]+) hz=([\d.]+)"
)

TARGET_HZ = 20.0
MIN_STEADY_HZ = 15.0
MAX_AVG_MS = 8.0
WARMUP_SEQ = 10

DEFAULT_UE4SS_LOG = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Train Sim World 6\WindowsNoEditor\TS2Prototype\Binaries\Win64\UE4SS.log"
)


def _parse_ts(raw: str) -> datetime:
    if len(raw) > 26:
        raw = raw[:26]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f",):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(raw)


def parse_probe_seq_events(text: str) -> list[tuple[datetime, int]]:
    events: list[tuple[datetime, int]] = []
    for m in _SEQ_LINE.finditer(text):
        events.append((_parse_ts(m.group(1)), int(m.group(2))))
    return events


def parse_perf_lines(text: str) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for m in _PERF_LINE.finditer(text):
        out.append({
            "writes": float(m.group(1)),
            "avg_ms": float(m.group(2)),
            "hz": float(m.group(3)),
        })
    return out


def summarize_seq_events(
    events: list[tuple[datetime, int]],
) -> dict[str, Any]:
    if len(events) < 2:
        return {
            "n_log_lines": len(events),
            "steady_hz": None,
            "hitch_s": None,
            "max_dt_s": None,
            "median_dt_s": None,
        }

    hitch_s: Optional[float] = None
    by_seq = {seq: ts for ts, seq in events}
    if 1 in by_seq and 2 in by_seq:
        hitch_s = (by_seq[2] - by_seq[1]).total_seconds()

    dts: list[float] = []
    hz_chunks: list[float] = []
    for (t0, s0), (t1, s1) in zip(events, events[1:]):
        dt = (t1 - t0).total_seconds()
        if dt <= 0:
            continue
        dseq = s1 - s0
        dts.append(dt)
        if s0 >= WARMUP_SEQ and dseq > 0:
            hz_chunks.append(dseq / dt)

    steady = statistics.median(hz_chunks) if hz_chunks else None
    return {
        "n_log_lines": len(events),
        "seq_first": events[0][1],
        "seq_last": events[-1][1],
        "steady_hz": steady,
        "hitch_s": hitch_s,
        "max_dt_s": max(dts) if dts else None,
        "median_dt_s": statistics.median(dts) if dts else None,
        "n_steady_chunks": len(hz_chunks),
    }


def evaluate_lua_perf(
    stats: dict[str, Any],
    perf_rows: Optional[list[dict[str, float]]] = None,
    *,
    min_hz: float = MIN_STEADY_HZ,
    max_avg_ms: float = MAX_AVG_MS,
) -> list[str]:
    """Falla régimen (Hz / avg_ms). El hueco seq1→2 no cuenta: ReceiveTick
    se para ~2.7 s tras el primer GetDriverAid; Lua avg_ms sigue ~1 ms.
    """
    fails: list[str] = []
    hz = stats.get("steady_hz")
    if hz is None:
        fails.append("sin tramo estable (pocas líneas seq= tras warmup)")
    elif hz < min_hz:
        fails.append(f"Hz estable {hz:.1f} < {min_hz:.0f}")
    if perf_rows:
        avgs = [r["avg_ms"] for r in perf_rows if r.get("writes", 0) >= 8]
        if avgs:
            med = statistics.median(avgs)
            if med > max_avg_ms:
                fails.append(f"avg_ms Lua {med:.2f} > {max_avg_ms:.0f}")
    return fails


def format_report(
    stats: dict[str, Any],
    perf_rows: Optional[list[dict[str, float]]] = None,
) -> str:
    lines = [
        f"líneas seq= {stats.get('n_log_lines')}",
        f"seq {stats.get('seq_first')} → {stats.get('seq_last')}",
    ]
    hitch = stats.get("hitch_s")
    if hitch is not None and hitch > 1.0:
        lines.append(
            f"hitch seq1→2 {hitch:.3f}s  (aviso arranque; no es avg_ms Lua)"
        )
    elif hitch is not None:
        lines.append(f"hitch seq1→2 {hitch:.3f}s")
    else:
        lines.append("hitch seq1→2 —")
    hz = stats.get("steady_hz")
    lines.append(
        f"Hz estable (mediana Δseq/Δt) {hz:.1f}" if hz is not None else "Hz estable —"
    )
    md = stats.get("median_dt_s")
    mx = stats.get("max_dt_s")
    if md is not None:
        lines.append(f"Δt entre logs mediana {md:.2f}s  máx {mx:.2f}s")
    fails = evaluate_lua_perf(stats, perf_rows)
    lines.append("OK" if not fails else "FALLA: " + "; ".join(fails))
    if perf_rows:
        avgs = [r["avg_ms"] for r in perf_rows]
        hzs = [r["hz"] for r in perf_rows]
        lines.append(
            f"perf Lua n={len(perf_rows)}  avg_ms med={statistics.median(avgs):.2f}  "
            f"hz med={statistics.median(hzs):.1f}"
        )
    return "\n".join(lines)


def analyze_log_text(text: str) -> tuple[dict[str, Any], list[dict[str, float]]]:
    return summarize_seq_events(parse_probe_seq_events(text)), parse_perf_lines(text)


def analyze_log_file(path: Path) -> tuple[dict[str, Any], list[dict[str, float]]]:
    return analyze_log_text(path.read_text(encoding="utf-8", errors="replace"))


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Rendimiento probe Lua vía UE4SS.log")
    p.add_argument(
        "log",
        nargs="?",
        type=Path,
        default=DEFAULT_UE4SS_LOG,
        help="UE4SS.log (por defecto instalación Steam TSW6)",
    )
    args = p.parse_args(argv)
    if not args.log.is_file():
        print(f"No existe {args.log}")
        return 2
    stats, perf = analyze_log_file(args.log)
    print(format_report(stats, perf))
    return 1 if evaluate_lua_perf(stats, perf) else 0


if __name__ == "__main__":
    raise SystemExit(main())
