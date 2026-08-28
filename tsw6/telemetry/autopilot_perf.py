"""Rendimiento del hilo de control del autopilot (logs heartbeat / canal).

CPU de un núcleo ≈ work / (work+sleep) en cada tick (objetivo 50 ms @ 20 Hz).
El hilo GUI (tk) no entra en ``work=``. Lua va aparte (UE4SS).

Uso:
  python -m tsw6.telemetry.autopilot_perf
  python -m tsw6.telemetry.autopilot_perf logs\\autopilot_20260828_023813.log
"""
from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path
from typing import Any, Optional

_HB = re.compile(
    r"heartbeat modo=\S+\s+loop_hz=([\d.]+)\s+work=([\d.]+)ms\s+"
    r"sleep=([\d.]+)ms\s+tgt=([\d.]+)Hz"
    r".*?telem_poll=([\d.]+)Hz",
)
_CANAL = re.compile(
    r"canal \[PASS\].*?work_max=([\d.]+)ms slow=(\d+)\s+"
    r"loop_hz=([\d.]+)-([\d.]+)\s+telem_poll=([\d.]+)Hz",
)
_CYCLE_DEBUG = re.compile(r"\[tsw\.autopilot\s*\]\s+DEBUG\s+spd=")
_CYCLE_INFO = re.compile(r"\[tsw\.autopilot\s*\]\s+INFO\s+spd=")

MIN_LOOP_HZ = 16.0
MAX_WORK_MED_MS = 45.0
TARGET_DT_MS = 50.0  # 20 Hz

LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"


def latest_autopilot_log(logs_dir: Path = LOGS_DIR) -> Optional[Path]:
    files = sorted(
        logs_dir.glob("autopilot_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def parse_heartbeats(text: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for m in _HB.finditer(text):
        rows.append({
            "loop_hz": float(m.group(1)),
            "work_ms": float(m.group(2)),
            "sleep_ms": float(m.group(3)),
            "tgt_hz": float(m.group(4)),
            "telem_poll_hz": float(m.group(5)),
        })
    return rows


def parse_canal(text: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for m in _CANAL.finditer(text):
        rows.append({
            "work_max_ms": float(m.group(1)),
            "slow": float(m.group(2)),
            "loop_hz_min": float(m.group(3)),
            "loop_hz_max": float(m.group(4)),
            "telem_poll_hz": float(m.group(5)),
        })
    return rows


def summarize(text: str) -> dict[str, Any]:
    hb = parse_heartbeats(text)
    canal = parse_canal(text)
    n_dbg = len(_CYCLE_DEBUG.findall(text))
    n_info_spd = len(_CYCLE_INFO.findall(text))
    out: dict[str, Any] = {
        "n_heartbeat": len(hb),
        "n_canal": len(canal),
        "n_cycle_debug": n_dbg,
        "n_cycle_info_spd": n_info_spd,
    }
    if hb:
        works = [r["work_ms"] for r in hb]
        sleeps = [r["sleep_ms"] for r in hb]
        hz = [r["loop_hz"] for r in hb if r["loop_hz"] > 0.5]
        poll = [r["telem_poll_hz"] for r in hb]
        duties = []
        for r in hb:
            tot = r["work_ms"] + r["sleep_ms"]
            if tot > 1:
                duties.append(r["work_ms"] / tot)
        out["work_med_ms"] = statistics.median(works)
        out["work_p95_ms"] = sorted(works)[int(0.95 * (len(works) - 1))]
        out["sleep_med_ms"] = statistics.median(sleeps)
        out["loop_hz_med"] = statistics.median(hz) if hz else None
        out["telem_poll_med"] = statistics.median(poll)
        out["cpu_core_pct"] = (
            statistics.median(duties) * 100.0 if duties else None
        )
    if canal:
        out["work_max_ms"] = max(r["work_max_ms"] for r in canal)
        out["slow_ticks"] = int(sum(r["slow"] for r in canal))
    return out


def why_cpu(stats: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    w = stats.get("work_med_ms")
    sl = stats.get("sleep_med_ms")
    cpu = stats.get("cpu_core_pct")
    if w is not None and sl is not None:
        notes.append(
            f"Cada tick: ~{w:.0f} ms trabajo + ~{sl:.0f} ms sleep "
            f"(presupuesto {TARGET_DT_MS:.0f} ms @ 20 Hz)."
        )
    if cpu is not None:
        notes.append(
            f"CPU estimada del hilo de control: ~{cpu:.0f} % de un núcleo "
            f"(work/(work+sleep); tkinter/GUI y UE4SS no entran)."
        )
    if w is not None and w >= 36:
        notes.append(
            "work alto: get_telemetry (GetData.txt) + decider + IPC + "
            "_log_cycle. OCR se enciende cerca de estación (<1500 m)."
        )
    poll = stats.get("telem_poll_med")
    hz = stats.get("loop_hz_med")
    if poll is not None and hz is not None and poll + 1.5 < hz:
        notes.append(
            f"telem_poll {poll:.1f} Hz < loop {hz:.1f} Hz: Python lee más "
            f"rápido que Lua escribe GetData (probe ~17 Hz)."
        )
    n_dbg = int(stats.get("n_cycle_debug") or 0)
    n_hb = max(int(stats.get("n_heartbeat") or 1), 1)
    if n_dbg > n_hb * 4:
        notes.append(
            f"Muchas líneas DEBUG spd= ({n_dbg}): I/O de log; el ciclo "
            "completo no se imprime cada tick (1/20 tras los 5 primeros)."
        )
    mx = stats.get("work_max_ms")
    if mx is not None and mx > 80:
        notes.append(f"work_max {mx:.0f} ms: picos (HTTP planning, learner, disco).")
    return notes


def evaluate(stats: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    if not stats.get("n_heartbeat"):
        fails.append("sin líneas heartbeat (log corto o autopilot no arrancó)")
        return fails
    hz = stats.get("loop_hz_med")
    if hz is not None and hz < MIN_LOOP_HZ:
        fails.append(f"loop_hz {hz:.1f} < {MIN_LOOP_HZ:.0f}")
    w = stats.get("work_med_ms")
    if w is not None and w > MAX_WORK_MED_MS:
        fails.append(f"work mediana {w:.0f} ms > {MAX_WORK_MED_MS:.0f} ms (no llega a 20 Hz)")
    return fails


def format_report(stats: dict[str, Any]) -> str:
    lines = [
        f"heartbeats {stats.get('n_heartbeat')}  canal {stats.get('n_canal')}",
        f"DEBUG spd= {stats.get('n_cycle_debug')}  INFO spd= {stats.get('n_cycle_info_spd')}",
    ]
    if stats.get("loop_hz_med") is not None:
        lines.append(
            f"loop_hz med {stats['loop_hz_med']:.1f}  "
            f"telem_poll med {stats.get('telem_poll_med', 0):.1f}"
        )
    if stats.get("work_med_ms") is not None:
        lines.append(
            f"work med {stats['work_med_ms']:.0f} ms  "
            f"p95 {stats.get('work_p95_ms', 0):.0f} ms  "
            f"sleep med {stats['sleep_med_ms']:.0f} ms"
        )
    if stats.get("cpu_core_pct") is not None:
        lines.append(f"CPU hilo control ~{stats['cpu_core_pct']:.0f} % de 1 núcleo")
    if stats.get("work_max_ms") is not None:
        lines.append(
            f"canal work_max {stats['work_max_ms']:.0f} ms  "
            f"slow {stats.get('slow_ticks', 0)}"
        )
    lines.append("")
    lines.append("Por qué gasta CPU:")
    for n in why_cpu(stats):
        lines.append(f"  · {n}")
    fails = evaluate(stats)
    lines.append("")
    lines.append("OK" if not fails else "FALLA: " + "; ".join(fails))
    return "\n".join(lines)


def analyze_log_text(text: str) -> dict[str, Any]:
    return summarize(text)


def analyze_log_file(path: Path) -> dict[str, Any]:
    return summarize(path.read_text(encoding="utf-8", errors="replace"))


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Rendimiento CPU del bucle autopilot")
    p.add_argument(
        "log",
        nargs="?",
        type=Path,
        default=None,
        help="logs/autopilot_*.log (por defecto el más reciente)",
    )
    args = p.parse_args(argv)
    path = args.log or latest_autopilot_log()
    if path is None or not path.is_file():
        print("No hay logs/autopilot_*.log")
        return 2
    print(f"Log: {path}")
    print()
    stats = analyze_log_file(path)
    print(format_report(stats))
    return 1 if evaluate(stats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
