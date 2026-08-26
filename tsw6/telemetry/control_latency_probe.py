#!/usr/bin/env python3
"""
control_latency_probe.py — Fase 0: medir latencia mando IPC ↔ telemetría.

Mide por cada mando:
  - ack_ms: tiempo hasta ACK Lua (o timeout)
  - telem_ms: tiempo hasta ``handle_notch`` en GetData == objetivo
  - roundtrip_ms: desde envío hasta confirmación en probe

Uso (juego en cabina, F7 probe activo, autopilot cerrado o sin mandos):
    python -m tsw6.telemetry.control_latency_probe
    python -m tsw6.telemetry.control_latency_probe --sequence 4,3,2,1,4 --rounds 5
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Optional

from tsw6.paths import LOGS_DIR
from tsw6.telemetry.tsw_ipc_bus import (
    dispatch_ipc_combined_notch,
    enable_lua_commands,
    purge_lua_commands,
)
from tsw6.telemetry.tsw_ue4ss_reader import (
    default_getdata_path,
    read_probe_file,
)


@dataclass
class LatencyRow:
    cmd_id: int
    target_notch: int
    notch_before: Optional[int]
    ack_ok: bool
    ack_error: str
    ack_ms: float
    telem_notch: Optional[int]
    telem_seq: Optional[int]
    telem_ms: Optional[float]
    roundtrip_ms: Optional[float]
    getdata_age_ms: Optional[float]


def percentile(values: list[float], pct: float) -> float:
    """Percentil simple (pct 0–100)."""
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


def summarize_rows(rows: list[LatencyRow]) -> dict[str, Any]:
    """Estadísticas agregadas para informe en consola."""
    ack_ok = [r.ack_ms for r in rows if r.ack_ok]
    telem = [r.telem_ms for r in rows if r.telem_ms is not None]
    roundtrip = [r.roundtrip_ms for r in rows if r.roundtrip_ms is not None]
    matched = sum(
        1 for r in rows
        if r.telem_notch is not None and r.telem_notch == r.target_notch
    )
    return {
        "n_cmds": len(rows),
        "ack_ok_pct": 100.0 * sum(1 for r in rows if r.ack_ok) / len(rows) if rows else 0.0,
        "telem_match_pct": 100.0 * matched / len(rows) if rows else 0.0,
        "ack_ms": _stat_block(ack_ok),
        "telem_ms": _stat_block(telem),
        "roundtrip_ms": _stat_block(roundtrip),
    }


def _stat_block(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "p50": median(values),
        "p95": percentile(values, 95),
        "max": max(values),
        "mean": mean(values),
    }


def _read_notch(path: Path) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """Devuelve (handle_notch, seq, age_ms) desde GetData."""
    snap = read_probe_file(path)
    if snap is None:
        return None, None, None
    notch = snap.combined_handle_notch()
    age_ms: Optional[float] = None
    try:
        age_ms = max(0.0, (time.time() - path.stat().st_mtime) * 1000.0)
    except OSError:
        pass
    return notch, snap.seq, age_ms


def wait_telem_notch(
    path: Path,
    target: int,
    *,
    timeout_s: float,
    poll_s: float,
    t0: float,
) -> tuple[Optional[int], Optional[int], Optional[float], Optional[float]]:
    """
    Espera hasta que handle_notch == target o timeout.
    Devuelve (notch, seq, telem_ms desde t0, getdata_age_ms).
    """
    deadline = time.perf_counter() + timeout_s
    last_age: Optional[float] = None
    while time.perf_counter() < deadline:
        notch, seq, age_ms = _read_notch(path)
        last_age = age_ms
        if notch == target:
            telem_ms = (time.perf_counter() - t0) * 1000.0
            return notch, seq, telem_ms, age_ms
        time.sleep(poll_s)
    notch, seq, _ = _read_notch(path)
    return notch, seq, None, last_age


def run_probe(
    *,
    sequence: list[int],
    rounds: int,
    telem_timeout_s: float,
    poll_s: float,
    settle_s: float,
    getdata_path: Optional[Path] = None,
) -> list[LatencyRow]:
    """Ejecuta la secuencia de mandos y devuelve filas de latencia."""
    path = getdata_path or default_getdata_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"GetData no encontrado: {path}\n"
            "Activa el probe (F7) en cabina con TelemetryProbeMod.")

    purge_lua_commands()
    enable_lua_commands()

    rows: list[LatencyRow] = []
    cmd_id = 0

    for round_i in range(rounds):
        for target in sequence:
            cmd_id += 1
            notch_before, seq_before, _ = _read_notch(path)
            t0 = time.perf_counter()
            result = dispatch_ipc_combined_notch(target)
            ack_ms = float(result.get("ack_ms") or 0.0)
            ack_ok = bool(result.get("ok"))
            ack_error = str(result.get("error") or "")

            telem_notch, telem_seq, telem_ms, age_ms = wait_telem_notch(
                path,
                target,
                timeout_s=telem_timeout_s,
                poll_s=poll_s,
                t0=t0,
            )
            roundtrip_ms = telem_ms
            rows.append(LatencyRow(
                cmd_id=cmd_id,
                target_notch=target,
                notch_before=notch_before,
                ack_ok=ack_ok,
                ack_error=ack_error,
                ack_ms=ack_ms,
                telem_notch=telem_notch,
                telem_seq=telem_seq,
                telem_ms=telem_ms,
                roundtrip_ms=roundtrip_ms,
                getdata_age_ms=age_ms,
            ))
            if settle_s > 0:
                time.sleep(settle_s)

        if round_i + 1 < rounds:
            print(f"  ronda {round_i + 1}/{rounds} completada")

    return rows


def write_csv(rows: list[LatencyRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(LatencyRow.__dataclass_fields__.keys())
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def print_report(summary: dict[str, Any], out_path: Path) -> None:
    print("\n=== Control latency probe ===")
    print(f"CSV: {out_path}")
    print(f"Mandos: {summary['n_cmds']}  "
          f"ACK OK: {summary['ack_ok_pct']:.0f}%  "
          f"Telem match: {summary['telem_match_pct']:.0f}%")
    for label in ("ack_ms", "telem_ms", "roundtrip_ms"):
        block = summary[label]
        if block["n"] == 0:
            print(f"  {label}: sin datos")
            continue
        print(
            f"  {label}: n={block['n']}  "
            f"p50={block['p50']:.0f}ms  p95={block['p95']:.0f}ms  "
            f"max={block['max']:.0f}ms"
        )
    telem = summary["roundtrip_ms"]
    if telem["n"] and telem["p95"] > 300:
        print("\n  ⚠ p95 round-trip > 300 ms — canal NO listo para P1")
    elif telem["n"] and telem["p95"] <= 200:
        print("\n  ✓ p95 round-trip ≤ 200 ms — canal aceptable")


def _parse_sequence(raw: str) -> list[int]:
    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
    for n in parts:
        if not 0 <= n <= 8:
            raise ValueError(f"muesca fuera de rango 0–8: {n}")
    return parts


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Medir latencia IPC mando ↔ telemetría GetData")
    parser.add_argument(
        "--sequence", default="4,3,2,1,4",
        help="Muescas objetivo separadas por coma (default: 4,3,2,1,4)",
    )
    parser.add_argument("--rounds", type=int, default=3,
                        help="Repeticiones de la secuencia")
    parser.add_argument(
        "--telem-timeout-ms", type=float, default=500.0,
        help="Timeout esperando notch en GetData",
    )
    parser.add_argument(
        "--poll-ms", type=float, default=5.0,
        help="Intervalo de lectura GetData",
    )
    parser.add_argument(
        "--settle-ms", type=float, default=150.0,
        help="Pausa entre mandos",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="CSV salida (default: logs/control_latency/<stamp>.csv)",
    )
    args = parser.parse_args(argv)

    try:
        sequence = _parse_sequence(args.sequence)
    except ValueError as exc:
        print(f"Error secuencia: {exc}", file=sys.stderr)
        return 2

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = LOGS_DIR / "control_latency"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out or (out_dir / f"probe_{stamp}.csv")
    latest = out_dir / "latest.csv"

    print("Control latency probe — juego en cabina, probe F7 ON")
    print(f"  secuencia={sequence}  rondas={args.rounds}")
    print(f"  GetData={default_getdata_path()}")
    print(f"  CSV → {out.resolve()}")
    print("  Enviando mandos en 3 s…")
    time.sleep(3.0)

    try:
        rows = run_probe(
            sequence=sequence,
            rounds=args.rounds,
            telem_timeout_s=args.telem_timeout_ms / 1000.0,
            poll_s=args.poll_ms / 1000.0,
            settle_s=args.settle_ms / 1000.0,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    write_csv(rows, out)
    write_csv(rows, latest)
    summary = summarize_rows(rows)
    print_report(summary, out)
    return 0 if summary["ack_ok_pct"] >= 90.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
