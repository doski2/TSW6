#!/usr/bin/env python3
"""Comprueba si tsw_hud.db está lista para el autopilot."""

from __future__ import annotations

import sys

from tsw6.hud.hud_timetable import HudTimetableStore, default_hud_db_paths


def main() -> int:
    print("=== Verificación tsw_hud.db ===\n")
    print("Rutas buscadas:")
    for p in default_hud_db_paths():
        mark = "OK" if p.is_file() else "—"
        print(f"  [{mark}] {p}")

    store = HudTimetableStore()
    if not store.available:
        print("\n[NO] No se encontro tsw_hud.db.")
        print("     Sigue extraer_horario_hud.bat o copia la BD manualmente.")
        return 1

    print(f"\n[OK] BD encontrada: {store.db_path}")
    found = False
    for svc in ("2R17", "2R17 Cross-City"):
        match = store.find_active_timetable(svc, lat=52.676, lng=-1.830)
        if match is None:
            match = store.find_active_timetable(svc)
        if match is None:
            continue
        stops = store.scheduled_stop_names(match.id)
        print(f"\nServicio '{svc}' -> timetable #{match.id} ({match.route_name})")
        print(f"  Paradas STOP: {len(stops)}")
        if stops:
            print(f"  Primeras: {', '.join(stops[:5])}")
        found = True
        if "cross" in match.route_name.lower():
            break
    if not found:
        print("\n[AVISO] No hay horario 2R17 usable. Extrajiste Cross-City en hud.exe?")
        print("   En hud.exe > Timetables, busca 'Cross-City' o '2R17'.")

    store.close()
    print("\nListo. Con TSW en -HTTPAPI el autopilot usará schedule_source=hud_db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
