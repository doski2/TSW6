#!/usr/bin/env python3
"""Compare ApiExplorer controls.json layout_hint with detect_control_layout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tsw6.learning.control_layout import detect_control_layout  # noqa: E402


def load_controls(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("controls_json", type=Path, help="Path to controls.json export")
    parser.add_argument(
        "--vehicle",
        help="Override vehicle class (default: vehicle_class from JSON)",
    )
    args = parser.parse_args()

    if not args.controls_json.is_file():
        print(f"ERROR: not found: {args.controls_json}", file=sys.stderr)
        return 1

    data = load_controls(args.controls_json)
    vehicle = args.vehicle or data.get("vehicle_class") or "?"
    layout_hint = data.get("layout_hint", "unknown")
    python_layout = detect_control_layout(vehicle)
    levers = data.get("lua", {}).get("levers") or []
    aliases = data.get("ipc_aliases") or {}

    print(f"vehicle_class: {vehicle}")
    print(f"layout_hint (Lua): {layout_hint}")
    print(f"detect_control_layout: {python_layout}")
    print(f"match: {layout_hint == python_layout or layout_hint == 'unknown'}")
    print(f"levers found: {len(levers)}")
    for lev in levers:
        name = lev.get("name", "?")
        scope = lev.get("scope", "?")
        cls = lev.get("class", "?")
        val = lev.get("read_value")
        print(f"  - {scope}/{name} [{cls}] read={val}")
    if aliases:
        print("ipc_aliases:")
        for k, v in sorted(aliases.items()):
            print(f"  {k} -> {v}")

    if layout_hint not in ("unknown", python_layout):
        print(
            f"\nWARN: Lua layout_hint={layout_hint!r} != Python {python_layout!r}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
