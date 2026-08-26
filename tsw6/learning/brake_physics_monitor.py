#!/usr/bin/env python3
"""
brake_physics_monitor.py — Laboratorio de frenos: muestreo dual Lua + HTTPAPI.

Recopila CSV detallado para validar presion de aire y BrakeEffort antes de
integrar senales en OnlineLearner.

Uso consola:
    python -m tsw6.learning.brake_physics_monitor
    python -m tsw6.learning.brake_physics_monitor --review logs/brake_physics/latest.csv

GUI:
    validar_freno.bat  (opcion 1)
    python validar_freno.py --gui
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

from tsw6.paths import LOGS_DIR
from tsw6.telemetry.tsw_api_client import TswApiClient, client_from_key_file
from tsw6.telemetry.tsw_ue4ss_reader import default_getdata_path, parse_probe_line

from tsw6.braking.v2.physics import PRESSURE_BRAKING_MIN_BAR

BRAKE_EFFORT_MAX_VALID_N = 50_000.0
MPH_TO_MS = 0.44704

PHASES: list[tuple[str, str]] = [
    ("baseline", "Neutro — tren parado (~5 s)"),
    ("stopped_b1", "Parado — B1 (1/3), mantener ~5 s"),
    ("stopped_b2", "Parado — B2 (2/3), mantener ~5 s"),
    ("stopped_b3", "Parado — B3 (max), mantener ~5 s"),
    ("moving_neutral", "30-50 mph — neutro, ~5 s"),
    ("moving_b2", "30-50 mph — B2 sostenido ~8 s (transitorio aire)"),
    ("release", "Soltar freno — presion vuelve a ~1 BAR"),
    ("free", "Grabacion libre / manual"),
]

CSV_FIELDS: list[str] = [
    "t_iso",
    "t_rel_s",
    "phase",
    "note",
    "vehicle",
    "probe_seq",
    "gradient_pct",
    "speed_mph_probe",
    "speed_mph_http",
    "train_brake_probe",
    "train_brake_http",
    "accel_ms2_probe",
    "accel_ms2_http",
    "pressure_http_bar",
    "pressure_probe_bar",
    "pressure_delta_bar",
    "brake_effort_n",
    "tractive_effort_n",
    "effort_valid",
    "quality_flags",
    "http_ok",
    "probe_ok",
]

_LOOP_SLEEP_S = 0.25


def is_brake_effort_valid(value: Optional[float]) -> bool:
    if value is None:
        return False
    if value != value:
        return False
    return 0.0 < value <= BRAKE_EFFORT_MAX_VALID_N


def brake_notch_label(handle: Optional[float]) -> str:
    if handle is None:
        return "?"
    h = float(handle)
    if h < 0.05:
        return "NEU"
    if h < 0.45:
        return "B1"
    if h < 0.85:
        return "B2"
    return "B3"


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return ""
    return f"{v:.6g}"


def _float_val(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


@dataclass
class BrakeLabSample:
    """Muestra con fuentes Lua (probe) y HTTP separadas."""

    t: float
    phase: str
    t_rel_s: float = 0.0
    note: str = ""
    vehicle: str = ""
    probe_seq: Optional[int] = None
    gradient_pct: Optional[float] = None
    speed_mph_probe: Optional[float] = None
    speed_mph_http: Optional[float] = None
    train_brake_probe: Optional[float] = None
    train_brake_http: Optional[float] = None
    accel_ms2_probe: Optional[float] = None
    accel_ms2_http: Optional[float] = None
    pressure_http_bar: Optional[float] = None
    pressure_probe_bar: Optional[float] = None
    brake_effort_n: Optional[float] = None
    tractive_effort_n: Optional[float] = None
    http_ok: bool = False
    probe_ok: bool = False

    @property
    def effort_valid(self) -> bool:
        return is_brake_effort_valid(self.brake_effort_n)

    @property
    def pressure_delta_bar(self) -> Optional[float]:
        if self.pressure_http_bar is None or self.pressure_probe_bar is None:
            return None
        return self.pressure_http_bar - self.pressure_probe_bar

    @property
    def speed_mph(self) -> Optional[float]:
        return self.speed_mph_probe if self.speed_mph_probe is not None else self.speed_mph_http

    @property
    def train_brake(self) -> Optional[float]:
        if self.train_brake_probe is not None:
            return self.train_brake_probe
        return self.train_brake_http

    @property
    def accel_ms2(self) -> Optional[float]:
        if self.accel_ms2_probe is not None:
            return self.accel_ms2_probe
        return self.accel_ms2_http

    @property
    def pressure_bar(self) -> Optional[float]:
        if self.pressure_http_bar is not None:
            return self.pressure_http_bar
        return self.pressure_probe_bar

    def quality_flags(self) -> list[str]:
        flags: list[str] = []
        if not self.probe_ok:
            flags.append("sin_probe")
        if not self.http_ok:
            flags.append("sin_http")
        if self.pressure_http_bar is None and self.pressure_probe_bar is None:
            flags.append("sin_presion")
        brk = self.train_brake
        p = self.pressure_bar
        if brk is not None and brk > 0.1 and p is not None and p < PRESSURE_BRAKING_MIN_BAR:
            flags.append("freno_sin_aire")
        if self.brake_effort_n is not None and not self.effort_valid:
            flags.append("effort_basura")
        spd = self.speed_mph
        if spd is not None and spd > 5 and self.brake_effort_n == 0:
            flags.append("effort_0_marcha")
        d = self.pressure_delta_bar
        if d is not None and abs(d) > 0.5:
            flags.append("P_http!=probe")
        return flags

    def to_csv_row(self) -> dict[str, str]:
        flags = self.quality_flags()
        return {
            "t_iso": datetime.fromtimestamp(self.t).isoformat(timespec="milliseconds"),
            "t_rel_s": _fmt(self.t_rel_s),
            "phase": self.phase,
            "note": self.note,
            "vehicle": self.vehicle,
            "probe_seq": str(self.probe_seq) if self.probe_seq is not None else "",
            "gradient_pct": _fmt(self.gradient_pct),
            "speed_mph_probe": _fmt(self.speed_mph_probe),
            "speed_mph_http": _fmt(self.speed_mph_http),
            "train_brake_probe": _fmt(self.train_brake_probe),
            "train_brake_http": _fmt(self.train_brake_http),
            "accel_ms2_probe": _fmt(self.accel_ms2_probe),
            "accel_ms2_http": _fmt(self.accel_ms2_http),
            "pressure_http_bar": _fmt(self.pressure_http_bar),
            "pressure_probe_bar": _fmt(self.pressure_probe_bar),
            "pressure_delta_bar": _fmt(self.pressure_delta_bar),
            "brake_effort_n": _fmt(self.brake_effort_n),
            "tractive_effort_n": _fmt(self.tractive_effort_n),
            "effort_valid": "1" if self.effort_valid else "0",
            "quality_flags": "|".join(flags),
            "http_ok": "1" if self.http_ok else "0",
            "probe_ok": "1" if self.probe_ok else "0",
        }


# Alias retrocompatible con tests/consola antigua
BrakePhysicsSample = BrakeLabSample


@dataclass
class BrakePhysicsSampler:
    api: Optional[TswApiClient] = None
    probe_path: Optional[Path] = None
    session_t0: float = field(default_factory=time.time)
    _api_paths: dict[str, str] = field(default_factory=lambda: {
        "effort": "CurrentFormation/0.Function.HUD_GetTractiveEffort",
        "pressure": "CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR",
        "brake": "CurrentFormation/0.Function.HUD_GetTrainBrakeHandle",
        "accel": "CurrentFormation/0.Function.HUD_GetAcceleration",
        "speed": "CurrentFormation/0.Function.HUD_GetSpeed",
    })

    def read_probe(self) -> dict[str, Any]:
        path = self.probe_path or default_getdata_path()
        if not path.is_file():
            return {}
        try:
            line = path.read_text(encoding="utf-8", errors="replace").strip()
            if not line:
                return {}
            return parse_probe_line(line)
        except OSError:
            return {}

    def probe_alive(self) -> bool:
        p = self.read_probe()
        return bool(p.get("speed_ms") is not None or p.get("seq") is not None)

    def http_alive(self) -> bool:
        return self.api is not None and self.api.probe()

    def sample(self, phase: str, note: str = "") -> BrakeLabSample:
        now = time.time()
        out = BrakeLabSample(
            t=now,
            phase=phase,
            note=note,
            t_rel_s=now - self.session_t0,
        )
        probe = self.read_probe()
        if probe:
            out.probe_ok = True
            if probe.get("seq") is not None:
                out.probe_seq = int(probe["seq"])
            if probe.get("vehicle"):
                out.vehicle = str(probe["vehicle"])
            if probe.get("gradient_pct") is not None:
                out.gradient_pct = float(probe["gradient_pct"])
            if probe.get("speed_ms") is not None:
                out.speed_mph_probe = float(probe["speed_ms"]) * 2.236936
            if probe.get("train_brake") is not None:
                out.train_brake_probe = float(probe["train_brake"])
            if probe.get("accel_ms2") is not None:
                out.accel_ms2_probe = float(probe["accel_ms2"])
            if probe.get("brake_cyl_bar") is not None:
                out.pressure_probe_bar = float(probe["brake_cyl_bar"])

        if self.api is not None:
            out.http_ok = True
            effort = self.api.get_node(self._api_paths["effort"]) or {}
            out.brake_effort_n = _float_val(effort.get("BrakeEffort (N)"))
            out.tractive_effort_n = _float_val(effort.get("TractiveEffort (N)"))

            pres = self.api.get_node(self._api_paths["pressure"]) or {}
            out.pressure_http_bar = _float_val(pres.get("Pressure_BAR"))

            brk = self.api.get_node(self._api_paths["brake"]) or {}
            out.train_brake_http = _float_val(brk.get("HandlePosition"))

            acc = self.api.get_node(self._api_paths["accel"]) or {}
            out.accel_ms2_http = _float_val(acc.get("Acceleration (ms2)"))

            spd = self.api.get_json(f"/get/{self._api_paths['speed']}")
            if isinstance(spd, dict):
                vals = spd.get("Values") or {}
                ms = _float_val(vals.get("Speed (ms)"))
                if ms is not None:
                    out.speed_mph_http = ms * 2.236936

        return out


@dataclass
class SessionWriter:
    path: Path
    _file: Any = field(default=None, repr=False)
    _flush_every: int = 4
    _since_flush: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
        self._w.writeheader()

    def write(self, sample: BrakeLabSample) -> None:
        self._w.writerow(sample.to_csv_row())
        self._since_flush += 1
        if self._since_flush >= self._flush_every:
            self._file.flush()
            self._since_flush = 0

    def close(self) -> None:
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None


def _quality_flags(sample: BrakeLabSample) -> list[str]:
    return sample.quality_flags()


def _parse_f(s: Optional[str]) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _col(rows: list[dict[str, str]], name: str, *fallbacks: str) -> list[float]:
    out: list[float] = []
    for r in rows:
        v = _parse_f(r.get(name))
        if v is None:
            for fb in fallbacks:
                v = _parse_f(r.get(fb))
                if v is not None:
                    break
        if v is not None:
            out.append(v)
    return out


def _avg(vals: list[float]) -> str:
    if not vals:
        return "-"
    return f"{mean(vals):.2f}"


def summarize_csv(path: Path) -> str:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return f"Sin filas en {path}"

    lines: list[str] = [
        "",
        "=" * 62,
        f"  INFORME CALIDAD — {path.name}",
        "=" * 62,
        f"  Muestras: {len(rows)}",
        f"  HTTP ok: {sum(1 for r in rows if r.get('http_ok') == '1')}",
        f"  Probe ok: {sum(1 for r in rows if r.get('probe_ok') == '1')}",
        "",
        f"  {'Fase':<16} {'n':>4} {'Phttp':>7} {'Pprobe':>7} {'BE':>8} {'acc':>8}",
    ]

    by_phase: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_phase.setdefault(r.get("phase") or "?", []).append(r)

    for phase_id, _ in PHASES:
        chunk = by_phase.get(phase_id, [])
        if not chunk:
            continue
        ph = _col(chunk, "pressure_http_bar")
        pp = _col(chunk, "pressure_probe_bar")
        be = [
            e for e in _col(chunk, "brake_effort_n")
            if is_brake_effort_valid(e)
        ]
        acc = _col(chunk, "accel_ms2_probe", "accel_ms2_http")
        lines.append(
            f"  {phase_id:<16} {len(chunk):>4} {_avg(ph):>7} {_avg(pp):>7} "
            f"{_avg(be):>8} {_avg(acc):>8}"
        )

    stopped: list[float] = []
    for pid in ("stopped_b1", "stopped_b2", "stopped_b3"):
        for r in by_phase.get(pid, []):
            p = _parse_f(r.get("pressure_http_bar")) or _parse_f(r.get("pressure_probe_bar"))
            if p is not None:
                stopped.append(p)
    if len(stopped) >= 2:
        mono = all(stopped[i] <= stopped[i + 1] for i in range(len(stopped) - 1))
        lines.append("")
        lines.append(f"  Presion B1->B3 (parado): {'OK' if mono else 'no claro'}")

    moving = by_phase.get("moving_b2", []) + by_phase.get("moving_neutral", [])
    if moving:
        z = sum(1 for r in moving if _parse_f(r.get("brake_effort_n")) == 0.0)
        lines.append(f"  BrakeEffort=0 en marcha: {z}/{len(moving)}")

    deltas = [_parse_f(r.get("pressure_delta_bar")) for r in rows]
    deltas = [d for d in deltas if d is not None]
    if deltas:
        close = sum(1 for d in deltas if abs(d) < 0.35)
        lines.append(f"  |Phttp-Pprobe| < 0.35 BAR: {close}/{len(deltas)}")

    bad_flags = sum(1 for r in rows if "effort_basura" in (r.get("quality_flags") or ""))
    if bad_flags:
        lines.append(f"  Muestras effort_basura: {bad_flags}")

    lines.extend([
        "",
        "  Recomendacion:",
        "  - Presion: integrar si escala con muesca y transitorio estable.",
        "  - BrakeEffort: solo parado B1-B2; filtrar B3 y marcha.",
        "",
        f"  CSV: {path}",
        "=" * 62,
        "",
    ])
    return "\n".join(lines)


def default_out_path(vehicle: str = "Class323") -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in vehicle)[:48]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOGS_DIR / "brake_physics" / f"{safe}_{stamp}.csv"


def copy_latest(path: Path) -> None:
    latest = LOGS_DIR / "brake_physics" / "latest.csv"
    try:
        shutil.copy2(path, latest)
    except OSError:
        pass


def build_sampler(
    *,
    probe: Optional[Path] = None,
    use_http: bool = True,
    http_timeout: float = 0.8,
) -> BrakePhysicsSampler:
    api = None
    if use_http:
        api = client_from_key_file()
        if api is not None:
            api.timeout = http_timeout
            if not api.probe():
                api = None
    return BrakePhysicsSampler(api=api, probe_path=probe)


def _enable_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _render(sample: BrakeLabSample, phase_idx: int, n_rows: int,
            hint: str, flags: list[str]) -> None:
    _clear()
    phase_id, phase_desc = PHASES[phase_idx] if phase_idx < len(PHASES) else ("?", "?")
    print("=" * 62)
    print("  TSW6 - LABORATORIO FRENOS (consola)")
    print("=" * 62)
    print(f"  Fase {phase_idx + 1}: {phase_desc}")
    print(f"  Muestras: {n_rows}")
    print("-" * 62)
    spd = sample.speed_mph
    print(f"  Vel {spd:.1f} mph" if spd is not None else "  Vel ?")
    print(f"  Muesca {sample.train_brake} ({brake_notch_label(sample.train_brake)})")
    print(f"  P HTTP {sample.pressure_http_bar}  P probe {sample.pressure_probe_bar}")
    print(f"  BE {sample.brake_effort_n}  valid={sample.effort_valid}")
    if flags:
        print(f"  ! {', '.join(flags)}")
    print("-" * 62)
    print(hint)


def run_guided_session(sampler: BrakePhysicsSampler, out_path: Path) -> Path:
    writer = SessionWriter(out_path)
    phase_idx = 0
    n_rows = 0
    try:
        while phase_idx < len(PHASES) - 1:  # exclude 'free'
            phase_id = PHASES[phase_idx][0]
            sample = sampler.sample(phase_id)
            writer.write(sample)
            n_rows += 1
            if n_rows % 4 == 0:
                _render(sample, phase_idx, n_rows, "Enter=siguiente fase", _quality_flags(sample))
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        phase_idx += 1
                    elif ch.lower() == "q":
                        break
            time.sleep(_LOOP_SLEEP_S)
    except KeyboardInterrupt:
        pass
    finally:
        writer.close()
    return out_path


def run_free_session(sampler: BrakePhysicsSampler, out_path: Path, seconds: float) -> Path:
    writer = SessionWriter(out_path)
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            writer.write(sampler.sample("free"))
            time.sleep(_LOOP_SLEEP_S)
    except KeyboardInterrupt:
        pass
    finally:
        writer.close()
    return out_path


def main() -> None:
    _enable_utf8()
    if len(sys.argv) == 1:
        sys.argv.append("--gui")
    parser = argparse.ArgumentParser(description="Laboratorio frenos TSW6")
    parser.add_argument("--gui", action="store_true", help="Interfaz grafica (defecto en .bat)")
    parser.add_argument("--console", action="store_true", help="Modo consola guiado")
    parser.add_argument("--free", type=float, metavar="SEC", help="Grabacion libre N segundos")
    parser.add_argument("--review", metavar="CSV", help="Informe CSV")
    parser.add_argument("--vehicle", default="Class323", help="Nombre archivo CSV")
    parser.add_argument("--probe", type=Path, default=None, help="Ruta GetData.txt")
    parser.add_argument("--no-http", action="store_true", help="Solo probe Lua")
    args = parser.parse_args()

    if args.review:
        path = Path(args.review)
        if not path.is_file():
            print(f"No existe: {path}")
            sys.exit(1)
        print(summarize_csv(path))
        return

    if args.gui and not args.console and args.free is None:
        from tsw6.learning.brake_lab_gui import main as gui_main
        gui_main(vehicle=args.vehicle, probe_path=args.probe, use_http=not args.no_http)
        return

    sampler = build_sampler(probe=args.probe, use_http=not args.no_http)
    out_path = default_out_path(args.vehicle)
    print(f"Guardando: {out_path}")

    if args.free:
        run_free_session(sampler, out_path, args.free)
    else:
        run_guided_session(sampler, out_path)

    print(summarize_csv(out_path))
    copy_latest(out_path)


if __name__ == "__main__":
    main()
