#!/usr/bin/env python3
"""Evalúa, sobre un JSONL grabado con ``--hud-ocr``, si corregir la distancia cada N capturas compensa."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "V2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tsw6v2.hud_ocr_eval import (
    evaluate,
    extract_captures,
    format_table,
    load_ticks,
    per_station_offset,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl", type=Path, help="logs/v2/<sesión>.jsonl con campos hud_ocr_m")
    ap.add_argument("--every", default="1,2,3,5,10", help="valores de N separados por comas")
    ap.add_argument("--max-dist", type=float, default=1000.0, help="solo capturas con el marcador a menos de X m")
    args = ap.parse_args(argv)

    ticks = load_ticks(args.jsonl)
    with_ocr = sum(1 for t in ticks if t.get("hud_ocr_m") is not None)
    print(f"{args.jsonl.name}: {len(ticks)} ticks, {with_ocr} con lectura de HUD")
    if with_ocr == 0:
        print("Sin lecturas: graba con --hud-ocr (ver docs/v2/HUD_OCR_MEDICION.md).")
        return 1
    segments = extract_captures(ticks, max_dist_m=args.max_dist)
    caps = sum(len(s) for s in segments)
    print(f"{len(segments)} aproximaciones, {caps} capturas nuevas utilizables\n")
    options = [int(x) for x in args.every.split(",") if x.strip()]
    print(format_table(evaluate(segments, options)))
    print("\nDesfase app - HUD por estación (marcador a < 300 m):")
    for name, st in sorted(per_station_offset(segments).items()):
        print(f"  {name or '?':<28} n={int(st['n']):>4}  mediana={st['median_m']:>7.1f} m  desv={st['stdev_m']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
