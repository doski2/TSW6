#!/usr/bin/env python3
"""
analyze.py — Combina todos los archivos calibration_*.csv y calcula
             la media global de aceleración por (notch, banda de gradiente).

Uso:
    python analyze.py
    python analyze.py --dir logs/
    python analyze.py --dir logs/ --apply   # actualiza speed_governor.py
"""

import argparse
import csv
import glob
import os
import statistics
from typing import Optional

# Constantes actuales de governor_constants.py (para comparar con datos del profiler)
CURRENT_CONSTANTS = {
    "MAX_DECEL_MS2":    1.071,
    "TARGET_ACCEL_MS2": 0.298,
    "TARGET_DECEL_MS2": 0.433,
    "COAST_DECEL_MS2":  0.095,
}

NOTCH_LABELS: dict[int, str] = {
    0: "Freno-4(max)",
    1: "Freno-3",
    2: "Freno-2",
    3: "Freno-1",
    4: "Neutro",
    5: "Tracción-1",
    6: "Tracción-2",
    7: "Tracción-3",
    8: "Tracción-4(max)",
}


def load_csvs(directory: str) -> tuple[list[dict], list[str]]:
    """Lee todos los calibration_*.csv (excluye _stops_ y _limits_)."""
    pattern = os.path.join(directory, "calibration_*.csv")
    rows: list[dict] = []
    files_read = []
    for path in sorted(glob.glob(pattern)):
        basename = os.path.basename(path)
        if "_stops_" in basename or "_limits_" in basename:
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            file_rows = list(reader)
            rows.extend(file_rows)
            files_read.append(f"  {basename}  ({len(file_rows)} eventos)")
    return rows, files_read


def clean_mean(vals: list[float]) -> tuple[float, float, int, int]:
    """Media con eliminación 2σ. Devuelve (media, sigma, n_total, n_usados)."""
    n = len(vals)
    if n == 0:
        return 0.0, 0.0, 0, 0
    mean  = statistics.mean(vals)
    sigma = statistics.stdev(vals) if n > 1 else 0.0
    used  = [x for x in vals if abs(x - mean) <= 2 * sigma]
    if not used:
        used = vals
    return statistics.mean(used), sigma, n, len(used)


def group_events(rows: list[dict]) -> dict[tuple[int, str], list[float]]:
    groups: dict[tuple[int, str], list[float]] = {}
    for r in rows:
        try:
            notch    = int(r["notch"])
            grad_band = r["grad_band"]
            api_str  = r.get("accel_api_ms2", "").strip()
            dv_str   = r.get("accel_dv_ms2", "").strip()
            val = float(api_str) if api_str else (float(dv_str) if dv_str else None)
            if val is None:
                continue
            groups.setdefault((notch, grad_band), []).append(val)
        except (ValueError, KeyError):
            continue
    return groups


def flat_mean(groups: dict, notches: list[int]) -> Optional[float]:
    vals: list[float] = []
    for n in notches:
        vals += groups.get((n, "+0.0%"), [])
    if not vals:
        return None
    m, s, _, _ = clean_mean(vals)
    return m


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Análisis combinado de sesiones de calibración"
    )
    parser.add_argument("--dir",   default="logs",
                        help="Carpeta con los CSV (default: logs/)")
    parser.add_argument("--apply", action="store_true",
                        help="Actualizar governor_constants.py con los valores calculados")
    args = parser.parse_args()

    rows, files_read = load_csvs(args.dir)
    if not rows:
        print(f"No se encontraron archivos calibration_*.csv en '{args.dir}'")
        return

    print(f"\nArchivos leídos ({len(files_read)}):")
    for f in files_read:
        print(f)
    print(f"\nTotal eventos combinados: {len(rows)}\n")

    # Vehículos únicos
    vehicles = sorted({r.get("vehicle", "?") for r in rows})
    if len(vehicles) > 1:
        print("Vehículos:", ", ".join(vehicles))

    groups = group_events(rows)

    lines = [
        "=" * 64,
        "  ANÁLISIS COMBINADO — TODAS LAS SESIONES",
        "=" * 64,
        f"  Archivos  : {len(files_read)}",
        f"  Eventos   : {len(rows)}",
        "",
    ]

    def _section(title: str, notch_range: range) -> None:
        keys = sorted(k for k in groups if k[0] in notch_range)
        if not keys:
            return
        lines.append(f"── {title} {'─' * (54 - len(title))}")
        for notch, gband in keys:
            vals = groups[(notch, gband)]
            mean, sigma, n_total, n_used = clean_mean(vals)
            outlier = f"  ⚠ {n_total-n_used} outlier(s)" if n_used < n_total else ""
            label = NOTCH_LABELS.get(notch, f"Notch-{notch}")
            lines.append(
                f"  {label:20s}  {gband:>7s}  "
                f"a={mean:+.3f} m/s²  σ={sigma:.3f}  n={n_total}"
                f"{outlier}"
            )
        lines.append("")

    _section("FRENADOS",          range(0, 4))
    _section("INERCIA (neutro)",  range(4, 5))
    _section("TRACCIONES",        range(5, 9))

    lines.append("── CONSTANTES RECOMENDADAS (plano ±0.5%) " + "─" * 22)
    recs: dict[str, Optional[float]] = {
        "MAX_DECEL_MS2":    flat_mean(groups, [0]),
        "TARGET_DECEL_MS2": flat_mean(groups, [1, 2, 3]),
        "TARGET_ACCEL_MS2": flat_mean(groups, [7, 8]),
        "COAST_DECEL_MS2":  flat_mean(groups, [4]),
    }
    for const, val in recs.items():
        cur = CURRENT_CONSTANTS[const]
        if val is not None:
            val_abs = abs(val)
            delta   = val_abs - cur
            flag    = " ✓" if abs(delta) < 0.05 else f" ← Δ={delta:+.3f}"
            lines.append(f"  {const:22s} = {val_abs:.3f}  (actual {cur:.3f}){flag}")
        else:
            lines.append(f"  {const:22s} = ?  (sin datos en plano ±0.5%)")
    lines.append("=" * 64)

    report = "\n".join(lines)
    print(report)

    # Aplicar a speed_governor.py si se pide
    if args.apply:
        _apply_to_governor(recs)


def _apply_to_governor(recs: dict[str, Optional[float]]) -> None:
    path = os.path.join(os.path.dirname(__file__), "governor_constants.py")
    if not os.path.exists(path):
        print(f"\nNo se encontró {path}")
        return

    with open(path, encoding="utf-8") as f:
        src = f.read()

    import re
    changed: list[str] = []
    for const, val in recs.items():
        if val is None:
            continue
        val_abs = abs(val)
        pattern = rf"^({re.escape(const)}\s*=\s*)[\d.]+(.*)$"
        new_src, n = re.subn(pattern, rf"\g<1>{val_abs:.3f}\2", src, flags=re.MULTILINE)
        if n:
            src = new_src
            changed.append(f"  {const} = {val_abs:.3f}")

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print("\nActualizado governor_constants.py:")
        for c in changed:
            print(c)
    else:
        print("\nNo se encontraron las constantes en governor_constants.py")


if __name__ == "__main__":
    main()
