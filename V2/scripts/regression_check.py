#!/usr/bin/env python3
"""Regresión entre trenes: re-evalúa los logs de referencia de CADA vehículo y compara con lo aceptado.

Cada vez que se toca la decisión (P1) hay que saber qué tren cambia. Esto lo hace de una vez::

    python V2/scripts/regression_check.py            # compara y resume por tren
    python V2/scripts/regression_check.py --update   # acepta el comportamiento actual como referencia
    python V2/scripts/regression_check.py --vehicle m3a      # solo un tren

Los logs de referencia se listan en ``V2/tests/golden/reference_logs.json`` (nombre del log → tren).
Las salidas aceptadas se guardan en ``logs/golden/<tren>/`` (junto a los logs; ``logs/`` no se versiona).
Una diferencia no es un error por sí misma: es la lista de ticks cuya decisión cambió. Si el cambio es
el buscado, ``--update``; si afecta a un tren que no se quería tocar, es una regresión.

Es lazo abierto (ver ``parity_jsonl.py``): demuestra qué decide el código con las mismas entradas,
no que el tren se comporte igual.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))

from parity_jsonl import dump  # noqa: E402

REFERENCE = _REPO / "V2" / "tests" / "golden" / "reference_logs.json"
LOGS = _REPO / "logs" / "v2"
GOLDEN = _REPO / "logs" / "golden"


def _load_reference() -> dict[str, list[str]]:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def _golden_path(vehicle: str, log: str) -> Path:
    return GOLDEN / vehicle / f"{log}.parity.jsonl"


def _compare(old: Path, new: Path) -> tuple[int, int, str]:
    a = old.read_text(encoding="utf-8").splitlines()
    b = new.read_text(encoding="utf-8").splitlines()
    n = min(len(a), len(b))
    diff = [i for i in range(n) if a[i] != b[i]]
    first = ""
    if diff:
        i = diff[0]
        first = f"línea {i + 1}: antes {a[i]}  ahora {b[i]}"
    return len(diff) + abs(len(a) - len(b)), len(a), first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="aceptar el comportamiento actual")
    parser.add_argument("--vehicle", help="solo este tren (clave de reference_logs.json)")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # las emergencias escriben mucho al log

    reference = _load_reference()
    vehicles = [args.vehicle] if args.vehicle else sorted(reference)
    changed_vehicles: list[str] = []
    tmp_dir = GOLDEN / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for vehicle in vehicles:
        if vehicle not in reference:
            print(f"tren desconocido: {vehicle} (hay: {', '.join(sorted(reference))})")
            return 2
        total_changed = total_ticks = missing = 0
        print(f"== {vehicle}")
        for log in reference[vehicle]:
            src = LOGS / f"{log}_cross-city_station.jsonl"
            if not src.exists():
                src = next(iter(LOGS.glob(f"{log}*_station.jsonl")), src)
            if not src.exists():
                print(f"   {log}: no se encuentra el log")
                missing += 1
                continue
            new = tmp_dir / f"{vehicle}_{log}.jsonl"
            ticks = dump(new, [src])
            gold = _golden_path(vehicle, log)
            if args.update or not gold.exists():
                gold.parent.mkdir(parents=True, exist_ok=True)
                gold.write_text(new.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"   {log}: {ticks} ticks -> referencia {'actualizada' if args.update else 'creada'}")
                total_ticks += ticks
                continue
            n_diff, n_ref, first = _compare(gold, new)
            total_ticks += n_ref
            total_changed += n_diff
            state = "igual" if n_diff == 0 else f"CAMBIA en {n_diff} ticks"
            print(f"   {log}: {n_ref} ticks, {state}")
            if n_diff:
                print(f"      primera diferencia, {first[:300]}")
        if total_changed:
            changed_vehicles.append(vehicle)
        verdict = "sin cambios" if not total_changed else f"{total_changed} ticks distintos de {total_ticks}"
        print(f"   -> {vehicle}: {verdict}" + (f" ({missing} logs ausentes)" if missing else ""))

    for f in tmp_dir.glob("*.jsonl"):
        f.unlink()
    if changed_vehicles and not args.update:
        print(f"\nCambian: {', '.join(changed_vehicles)}. Si es lo buscado: --update.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
