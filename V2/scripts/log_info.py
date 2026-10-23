#!/usr/bin/env python3
"""Ficha de un log de sesión: qué tren es, con qué paquete y a qué hora (local y UTC).

Uso::

    python V2/scripts/log_info.py logs/v2/20261023T223846Z_cross-city_station.jsonl
    python V2/scripts/log_info.py <log> --at 1110      # hora local del segundo 1110 de la sesión

Sirve igual con logs antiguos: lo que no está en la cabecera se deduce de los ticks (``vehicle``) y
del paquete de ``data/vehicles``. El nombre del log y ``ts`` van en UTC; ``--at`` convierte a la hora
local del equipo (la que muestra el reloj de Windows y las capturas de pantalla).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2))

from tsw6v2.vehicle_adapter import adapter_for_package  # noqa: E402
from tsw6v2.vehicle_package import resolve_vehicle_package  # noqa: E402


def read(path: Path) -> tuple[dict, list[dict], list[dict]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    header = next((r for r in rows if r.get("type") == "session"), {})
    detect = [r for r in rows if r.get("type") == "session_detect"]
    ticks = [r for r in rows if r.get("type") == "tick"]
    return header, detect, ticks


def start_time(header: dict) -> datetime | None:
    ts = header.get("ts")
    return datetime.fromisoformat(ts) if ts else None


def local(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def describe(path: Path) -> list[str]:
    header, detect, ticks = read(path)
    merged: dict = {}
    for row in detect:
        merged.update({k: v for k, v in row.items() if k != "type"})
    vehicle = merged.get("vehicle") or (
        collections.Counter(t.get("vehicle") for t in ticks if t.get("vehicle") not in (None, "?")).most_common(1) or [(None,)]
    )[0][0]
    package = resolve_vehicle_package(vehicle) if vehicle else None
    layout = merged.get("layout") or ("analogico" if adapter_for_package(package).analog_lever else "muescas")
    t0 = start_time(header)
    lines = [f"log:        {path.name}"]
    lines.append(f"tren:       {vehicle or '(sin dato)'}")
    lines.append(
        f"paquete:    {merged.get('vehicle_package') or (package or {}).get('vehicle_id') or 'sin_paquete'}"
        f"   layout: {layout}   flota: {merged.get('fleet') or (package or {}).get('fleet') or '?'}"
    )
    lines.append(f"ruta:       {header.get('route')}   servicio: {merged.get('service_name') or '?'}   horario: {merged.get('schedule_source') or '?'}")
    if t0 is not None and ticks:
        dur = ticks[-1]["t_ms"] / 1000.0
        t1 = t0 + timedelta(seconds=dur)
        lines.append(f"inicio:     {local(t0)}   (UTC {t0.astimezone(timezone.utc):%H:%M:%S})")
        lines.append(f"fin:        {local(t1)}   duración {dur:.0f} s, {len(ticks)} ticks")
    lines.append(f"commit:     {header.get('git')}   perfil: {header.get('profile')}")
    if not merged.get("vehicle"):
        lines.append("nota:       log anterior al registro de tren/paquete en la cabecera; deducido de los ticks.")
    if package is None and vehicle:
        lines.append("AVISO:      este tren NO resuelve ningún paquete de data/vehicles (corre con los valores por defecto).")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path)
    parser.add_argument("--at", type=float, help="segundo de la sesión (t_ms/1000) a convertir a hora local")
    args = parser.parse_args()
    print("\n".join(describe(args.log)))
    if args.at is not None:
        header, _, _ = read(args.log)
        t0 = start_time(header)
        if t0 is not None:
            print(f"t = {args.at:g} s  ->  {local(t0 + timedelta(seconds=args.at))}")


if __name__ == "__main__":
    main()
