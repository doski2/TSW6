#!/usr/bin/env python3
"""Informe de amperímetro — logs probe UE4SS y (opcional) capturas F5 lab.

Uso:
  python scripts/tools/amp.py logs/ue4ss_probe_20261007_001325.txt
  python scripts/tools/amp.py logs/*.txt --write-report
  python scripts/tools/amp.py logs/foo.txt --lab data/lab_exports/exports/SESSION_ID

Clasifica muestras en reposo / tracción / frenada (regen) por signo y magnitud de `amps`,
con apoyo en `accel_ms2` y `power` cuando existen.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsw6.lab.lab_export import list_hud_batch_exports, summarize_amps_session  # noqa: E402

PROBE_CSV_HEADER = (
    "time_s,seq,hz,speed_mph,limit_mph,max_mph,handle_notch,power,"
    "train_brake,loco_brake,dyn_brake,accel_ms2,gradient_pct,"
    "amps,doors_telem,doors_dmi,mc_input,vehicle"
)

# Por debajo → reposo / ruido HUD (ajustable por tren en el futuro).
IDLE_AMPS_A = 15.0


def _f(val: str) -> Optional[float]:
    val = (val or "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _i(val: str) -> Optional[int]:
    v = _f(val)
    return int(v) if v is not None else None


@dataclass
class ProbeSample:
    time_s: float
    seq: Optional[int]
    speed_mph: Optional[float]
    power: Optional[float]
    train_brake: Optional[float]
    accel_ms2: Optional[float]
    amps: float
    vehicle: str
    brake_cyl_bar: Optional[float] = None


@dataclass
class AmpStats:
    count: int = 0
    min_a: Optional[float] = None
    max_a: Optional[float] = None
    mean_a: Optional[float] = None
    median_a: Optional[float] = None

    def add(self, values: list[float]) -> None:
        if not values:
            return
        self.count = len(values)
        self.min_a = min(values)
        self.max_a = max(values)
        self.mean_a = statistics.fmean(values)
        self.median_a = statistics.median(values)


@dataclass
class ProbeAmpReport:
    path: Path
    vehicle: str = "?"
    duration_s: Optional[float] = None
    sample_count: int = 0
    seq_range: tuple[Optional[int], Optional[int]] = (None, None)
    hz_mean: Optional[float] = None
    speed_mph_max: Optional[float] = None
    all_amps: AmpStats = field(default_factory=AmpStats)
    idle: AmpStats = field(default_factory=AmpStats)
    traction: AmpStats = field(default_factory=AmpStats)
    braking: AmpStats = field(default_factory=AmpStats)
    brake_cyl_bar: AmpStats = field(default_factory=AmpStats)

    def verdict(self) -> str:
        if self.sample_count == 0:
            return "no_samples"
        vals = [
            self.all_amps.max_a,
            self.all_amps.min_a,
        ]
        if all(v is not None and abs(v) < 1e-6 for v in vals):
            return "always_zero"
        if self.traction.count == 0 and self.braking.count == 0:
            return "idle_only"
        return "variable"


def _parse_raw_brake_cyl(raw: str) -> Optional[float]:
    m = re.search(r"brake_cyl_bar=([0-9.]+)", raw)
    return float(m.group(1)) if m else None


def _parse_raw_amps(raw: str) -> Optional[float]:
    m = re.search(r"amps=([-0-9.]+)", raw)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_probe_log(path: Path) -> list[ProbeSample]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    has_amps_col = PROBE_CSV_HEADER in text
    samples: list[ProbeSample] = []
    pending_raw: Optional[str] = None

    for line in text:
        if line.startswith("# raw:"):
            pending_raw = line[6:].strip()
            continue
        if not line or line.startswith("#"):
            pending_raw = None
            continue
        if line.startswith("time_s,"):
            continue
        parts = line.split(",")
        if len(parts) < 14:
            pending_raw = None
            continue

        amps: Optional[float] = None
        brake_cyl: Optional[float] = None
        if has_amps_col and len(parts) >= 18:
            amps = _f(parts[13])
            vehicle = parts[17].strip() or "?"
        else:
            vehicle = parts[-1].strip() if parts else "?"
        if amps is None and pending_raw:
            amps = _parse_raw_amps(pending_raw)
            brake_cyl = _parse_raw_brake_cyl(pending_raw)
        elif pending_raw:
            brake_cyl = _parse_raw_brake_cyl(pending_raw)
        pending_raw = None

        if amps is None:
            continue

        samples.append(
            ProbeSample(
                time_s=_f(parts[0]) or 0.0,
                seq=_i(parts[1]),
                speed_mph=_f(parts[3]),
                power=_f(parts[7]) if len(parts) > 7 else None,
                train_brake=_f(parts[8]) if len(parts) > 8 else None,
                accel_ms2=_f(parts[11]) if len(parts) > 11 else None,
                amps=amps,
                vehicle=vehicle,
                brake_cyl_bar=brake_cyl,
            )
        )
    return samples


def _classify_regime(s: ProbeSample, idle_threshold: float = IDLE_AMPS_A) -> str:
    a = s.amps
    if abs(a) < idle_threshold:
        return "idle"
    if a > 0:
        return "traction"
    return "braking"


def analyze_probe_log(path: Path, *, idle_threshold: float = IDLE_AMPS_A) -> ProbeAmpReport:
    samples = parse_probe_log(path)
    rep = ProbeAmpReport(path=path)
    if not samples:
        return rep

    rep.sample_count = len(samples)
    rep.vehicle = samples[-1].vehicle
    rep.duration_s = samples[-1].time_s - samples[0].time_s
    seqs = [s.seq for s in samples if s.seq is not None]
    if seqs:
        rep.seq_range = (min(seqs), max(seqs))
    speeds = [s.speed_mph for s in samples if s.speed_mph is not None]
    if speeds:
        rep.speed_mph_max = max(speeds)

    all_a = [s.amps for s in samples]
    rep.all_amps.add(all_a)

    idle_a: list[float] = []
    tract_a: list[float] = []
    brake_a: list[float] = []
    cyl: list[float] = []
    for s in samples:
        reg = _classify_regime(s, idle_threshold)
        if reg == "idle":
            idle_a.append(s.amps)
        elif reg == "traction":
            tract_a.append(s.amps)
        else:
            brake_a.append(s.amps)
        if s.brake_cyl_bar is not None:
            cyl.append(s.brake_cyl_bar)

    rep.idle.add(idle_a)
    rep.traction.add(tract_a)
    rep.braking.add(brake_a)
    rep.brake_cyl_bar.add(cyl)
    return rep


def _fmt_stats(st: AmpStats, unit: str = "A") -> str:
    if st.count == 0:
        return "—"
    return (
        f"n={st.count} min={st.min_a:.1f}{unit} max={st.max_a:.1f}{unit} "
        f"mean={st.mean_a:.1f}{unit} med={st.median_a:.1f}{unit}"
    )


def render_markdown_report(
    probe_reports: list[ProbeAmpReport],
    lab_rows: Optional[list[dict[str, Any]]] = None,
    *,
    idle_threshold: float = IDLE_AMPS_A,
) -> str:
    lines = ["# Informe amperímetro (amp.py)", ""]
    for rep in probe_reports:
        lines.extend(
            [
                f"## Probe — `{rep.path.name}`",
                "",
                f"- Vehículo: `{rep.vehicle}`",
                f"- Muestras: **{rep.sample_count}** · duración ~**{rep.duration_s:.1f}s**"
                if rep.duration_s is not None
                else f"- Muestras: **{rep.sample_count}**",
                f"- Seq: {rep.seq_range[0]} … {rep.seq_range[1]}",
                f"- Vel. máx: {rep.speed_mph_max:.1f} mph"
                if rep.speed_mph_max is not None
                else "- Vel. máx: —",
                f"- Veredicto: **{rep.verdict()}** (umbral reposo |amps| < {idle_threshold} A)",
                "",
                "| Régimen | Estadística amps |",
                "| --- | --- |",
                f"| Global | {_fmt_stats(rep.all_amps)} |",
                f"| Reposo | {_fmt_stats(rep.idle)} |",
                f"| Tracción (amps > 0) | {_fmt_stats(rep.traction)} |",
                f"| Frenada / regen (amps < 0) | {_fmt_stats(rep.braking)} |",
            ]
        )
        if rep.brake_cyl_bar.count:
            lines.append(f"| Cilindro HUD (`brake_cyl_bar` en raw) | {_fmt_stats(rep.brake_cyl_bar, ' bar')} |")
        lines.append("")

    if lab_rows:
        lines.extend(
            [
                "## Lab F5 (instantáneas `hud_batch_*.json`)",
                "",
                "| Archivo | Amps | speed_ms | power | train_brake |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in lab_rows:
            lines.append(
                f"| `{row.get('file', '?')}` | {row.get('amps', '—')} | "
                f"{row.get('speed_ms', '—')} | {row.get('power', '—')} | "
                f"{row.get('train_brake', '—')} |"
            )
        lines.append("")

    lines.append(
        "_Clasificación automática; revisar manualmente si el tren tiene offset DC en reposo._"
    )
    lines.append("")
    return "\n".join(lines)


def latest_probe_log(logs_dir: Optional[Path] = None) -> Optional[Path]:
    """Último `ue4ss_probe_*.txt` bajo `logs/` (incl. `logs/probe/<stamp>/`)."""
    base = logs_dir if logs_dir is not None else ROOT / "logs"
    if not base.is_dir():
        return None
    candidates = list(base.rglob("ue4ss_probe_*.txt"))
    if not candidates:
        return None

    def _sort_key(p: Path) -> tuple[str, float]:
        return (p.name, p.stat().st_mtime)

    return max(candidates, key=_sort_key)


def print_console_report(rep: ProbeAmpReport) -> None:
    print(f"\n=== {rep.path.name} ===")
    print(f"vehicle={rep.vehicle}  samples={rep.sample_count}  verdict={rep.verdict()}")
    print(f"  global:    {_fmt_stats(rep.all_amps)}")
    print(f"  reposo:    {_fmt_stats(rep.idle)}")
    print(f"  tracción:  {_fmt_stats(rep.traction)}")
    print(f"  frenada:   {_fmt_stats(rep.braking)}")
    if rep.brake_cyl_bar.count:
        print(f"  cilindro:  {_fmt_stats(rep.brake_cyl_bar, ' bar')}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "probe_logs",
        nargs="*",
        type=Path,
        help="Archivo(s) logs/ue4ss_probe_*.txt",
    )
    parser.add_argument(
        "--lab",
        type=Path,
        default=None,
        help="Carpeta sesión ApiExplorer (hud_batch_*.json) para anexar al informe",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Escribir amp_report.md junto al primer log",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida JSON en stdout",
    )
    parser.add_argument(
        "--idle-threshold",
        type=float,
        default=IDLE_AMPS_A,
        help=f"|amps| por debajo = reposo (default {IDLE_AMPS_A})",
    )
    args = parser.parse_args(argv)
    if not args.probe_logs:
        latest = latest_probe_log()
        if latest is None:
            parser.print_help()
            print(
                "\nERROR: no hay logs/ue4ss_probe_*.txt — graba con probe_ue4ss.bat.",
                file=sys.stderr,
            )
            return 1
        try:
            rel = latest.relative_to(ROOT)
        except ValueError:
            rel = latest
        print(f"Log mas reciente: {rel}", file=sys.stderr)
        args.probe_logs = [latest]

    idle_threshold = float(args.idle_threshold)

    reports: list[ProbeAmpReport] = []
    for p in args.probe_logs:
        path = p.resolve()
        if not path.is_file():
            print(f"ERROR: no existe {path}", file=sys.stderr)
            return 1
        rep = analyze_probe_log(path, idle_threshold=idle_threshold)
        reports.append(rep)
        if not args.json:
            print_console_report(rep)

    lab_rows: Optional[list[dict[str, Any]]] = None
    if args.lab is not None:
        lab_dir = args.lab.resolve()
        if lab_dir.is_dir() and list_hud_batch_exports(lab_dir):
            lab_rows = summarize_amps_session(lab_dir)
        else:
            print(f"AVISO: sin hud_batch en {lab_dir}", file=sys.stderr)

    if args.json:
        payload = {
            "reports": [
                {
                    "path": str(r.path),
                    "vehicle": r.vehicle,
                    "verdict": r.verdict(),
                    "sample_count": r.sample_count,
                    "all": r.all_amps.__dict__,
                    "idle": r.idle.__dict__,
                    "traction": r.traction.__dict__,
                    "braking": r.braking.__dict__,
                }
                for r in reports
            ],
            "lab": lab_rows,
        }
        print(json.dumps(payload, indent=2))

    if args.write_report and reports:
        for r in reports:
            out = r.path.parent / "amp_report.md"
            out.write_text(
                render_markdown_report(
                    [r], lab_rows, idle_threshold=idle_threshold
                ),
                encoding="utf-8",
            )
            print(f"\nWrote {out}")
        if len(reports) > 1:
            bundle = ROOT / "logs" / "probe" / "informe_combinado_amp.md"
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text(
                render_markdown_report(
                    reports, lab_rows, idle_threshold=idle_threshold
                ),
                encoding="utf-8",
            )
            print(f"\nWrote {bundle}")

    worst = "variable"
    for r in reports:
        v = r.verdict()
        if v == "no_samples":
            return 1
        if v == "always_zero":
            worst = "always_zero"
    return 0 if worst == "variable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
