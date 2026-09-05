#!/usr/bin/env python3
"""Comparar dos sesiones JSONL P1 V2 (timing APPLY vs ds=0)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_V2 = _ROOT / "V2"
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

from tsw6v2.session_report import (  # noqa: E402
    _apply_zone_m,
    _kinematic_markers,
    finalize_session_report,
    load_ticks,
    print_report,
    summarize,
)


def _stem(path: Path) -> str:
    name = path.name
    return name[: name.rfind("_")] if "_" in name else path.stem


def _first_apply_per_limit(data: dict) -> list[dict]:
    seen: set[float] = set()
    out: list[dict] = []
    for e in data.get("apply_events") or []:
        lim = e.get("lim_mph")
        if lim is None or lim in seen:
            continue
        seen.add(lim)
        out.append(e)
    return out


def _apply_row(e: dict) -> str:
    ds = e.get("dist_start_m")
    dist = e.get("lim_dist_m")
    spd = e.get("spd")
    zone = None
    if ds is not None and dist is not None and spd is not None:
        zone = round(_apply_zone_m(spd_mph=float(spd), lim_dist_m=float(dist), dist_start_m=float(ds)), 1)
    return (
        f"  lim={e.get('lim_mph')}mph  t={e.get('t_s')}s  spd={spd}  "
        f"dist={dist}m  ds={ds}  zona~±{zone}m"
    )


def compare(a_path: Path, b_path: Path) -> None:
    a = summarize(a_path)
    b = summarize(b_path)
    if "error" in a or "error" in b:
        if "error" in a:
            print(f"A: {a['error']}", file=sys.stderr)
        if "error" in b:
            print(f"B: {b['error']}", file=sys.stderr)
        raise SystemExit(1)

    _, a_ticks = load_ticks(a_path)
    _, b_ticks = load_ticks(b_path)
    a_mk = _kinematic_markers(a_ticks)
    b_mk = _kinematic_markers(b_ticks)

    print("=== Comparar sesiones P1 V2 ===")
    print(f"A  {_stem(a_path)}")
    print(f"B  {_stem(b_path)}")
    print()

    def line(label: str, va: object, vb: object) -> None:
        print(f"  {label:<22} {str(va):>14}  {str(vb):>14}")

    line("duracion (s)", a["duration_s"], b["duration_s"])
    line("ticks", a["n_ticks"], b["n_ticks"])
    line("APPLY", a["apply_ticks"], b["apply_ticks"])
    line("RELEASE", a["release_ticks"], b["release_ticks"])
    line("GAP cerca cartel", a["command_none_near"], b["command_none_near"])
    line("cruces ds=0", len(a_mk), len(b_mk))
    print()

    limits = sorted(
        {e.get("lim_mph") for e in (a.get("apply_events") or []) + (b.get("apply_events") or [])}
        - {None}
    )
    a_by = {e["lim_mph"]: e for e in _first_apply_per_limit(a)}
    b_by = {e["lim_mph"]: e for e in _first_apply_per_limit(b)}

    print("--- Primer APPLY por cartel ---")
    for lim in limits:
        print(f"Cartel {lim} mph:")
        ea, eb = a_by.get(lim), b_by.get(lim)
        print(f"  A: {_apply_row(ea) if ea else '  (sin APPLY)'}")
        print(f"  B: {_apply_row(eb) if eb else '  (sin APPLY)'}")
        if ea and eb:
            dsa = ea.get("dist_start_m")
            dsb = eb.get("dist_start_m")
            if dsa is not None and dsb is not None:
                delta = round(float(dsb) - float(dsa), 1)
                note = "mas tarde" if delta < 0 else "mas pronto" if delta > 0 else "igual"
                print(f"  -> B frena {abs(delta)}m {note} que A (ds)")
        print()

    print("--- Cruces ds=0 ---")
    for label, mk in (("A", a_mk), ("B", b_mk)):
        if not mk:
            print(f"  {label}: (ninguno)")
            continue
        for m in mk:
            print(
                f"  {label}: t={m['t']}s lim={m['lim_mph']} "
                f"spd={m['spd']} m_al_cartel={m['lim_dist_m']} zona=±{m['zone_m']}m"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description="Comparar dos JSONL de sesion P1 V2")
    ap.add_argument("jsonl_a", type=Path, help="sesion anterior (ej. 185740Z)")
    ap.add_argument("jsonl_b", type=Path, help="sesion nueva (ej. 222538Z)")
    ap.add_argument(
        "--html",
        action="store_true",
        help="genera replay HTML si falta (.html junto al jsonl)",
    )
    ap.add_argument("--open", action="store_true", help="abre ambos HTML en el navegador")
    ap.add_argument("--summary", action="store_true", help="imprime resumen completo de cada una")
    args = ap.parse_args()

    for p in (args.jsonl_a, args.jsonl_b):
        if not p.is_file():
            print(f"No existe: {p}", file=sys.stderr)
            return 1

    if args.summary:
        for p in (args.jsonl_a, args.jsonl_b):
            print()
            print_report(summarize(p))

    compare(args.jsonl_a, args.jsonl_b)

    html_paths: list[Path] = []
    if args.html or args.open:
        for p in (args.jsonl_a, args.jsonl_b):
            out = p.with_suffix(".html")
            if not out.is_file() or args.html:
                finalize_session_report(p, html_path=out, force=True)
                print(f"replay -> {out.resolve()}")
            html_paths.append(out)

    if args.open:
        import os

        for hp in html_paths:
            if hp.is_file():
                os.startfile(hp)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
