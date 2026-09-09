#!/usr/bin/env python3
"""Escribe Planning.txt para modo ``station`` sin HTTP (pruebas manuales)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_V2 = _REPO / "V2"
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

from tsw6v2.planning_feed import default_planning_path, write_planning_snapshot


def main() -> int:
    p = argparse.ArgumentParser(description="Escribe %TEMP%\\TSW6Bridge\\Planning.txt")
    p.add_argument("distance_m", type=float, help="Distancia al andén (m)")
    p.add_argument("--stop", default=None, help="Nombre parada")
    p.add_argument("--path", type=Path, default=None)
    args = p.parse_args()
    dest = args.path or default_planning_path()
    ok = write_planning_snapshot(
        station_distance_m=args.distance_m,
        station_name=args.stop,
        path=dest,
        min_interval_s=0.0,
    )
    if not ok:
        print("No se pudo escribir (distancia <= 0)", file=sys.stderr)
        return 1
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
