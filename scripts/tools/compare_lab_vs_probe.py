#!/usr/bin/env python3
"""Compare ApiExplorer hud_batch.json with a TelemetryProbe GetData line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tsw6.lab.lab_export import (  # noqa: E402
    PROBE_COMPARE_FIELDS,
    compare_hud_to_probe,
    derive_probe_fields_from_hud,
    load_hud_batch,
)


def read_probe_line(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty probe file: {path}")
    return text.splitlines()[-1].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hud_batch_json", type=Path, help="Path to hud_batch.json export")
    parser.add_argument(
        "probe_file",
        type=Path,
        help="GetData.txt or one-line snapshot file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )
    parser.add_argument(
        "--show-derived",
        action="store_true",
        help="Print lab-derived probe fields before compare",
    )
    args = parser.parse_args()

    if not args.hud_batch_json.is_file():
        print(f"ERROR: not found: {args.hud_batch_json}", file=sys.stderr)
        return 1
    if not args.probe_file.is_file():
        print(f"ERROR: not found: {args.probe_file}", file=sys.stderr)
        return 1

    hud = load_hud_batch(args.hud_batch_json)
    probe_line = read_probe_line(args.probe_file)
    derived = derive_probe_fields_from_hud(hud)
    rows = compare_hud_to_probe(hud, probe_line)

    if args.show_derived:
        print("lab-derived:")
        print(json.dumps(derived, indent=2, sort_keys=True))

    mismatches = [r for r in rows if r.match in ("mismatch", "missing_lab", "missing_probe")]
    okish = [r for r in rows if r.match in ("exact", "fuzzy")]

    if args.json:
        payload = {
            "session_id": hud.get("session_id"),
            "vehicle_class": hud.get("vehicle_class"),
            "derived": derived,
            "rows": [
                {
                    "field": r.field,
                    "lab": r.lab_value,
                    "probe": r.probe_value,
                    "match": r.match,
                    "note": r.note,
                }
                for r in rows
            ],
            "compared": len(rows),
            "ok": len(okish),
            "mismatches": len(mismatches),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"session_id: {hud.get('session_id', '?')}")
        print(f"vehicle_class: {hud.get('vehicle_class', '?')}")
        print(f"fields: {', '.join(PROBE_COMPARE_FIELDS)}")
        for row in rows:
            mark = row.match
            extra = f" ({row.note})" if row.note else ""
            print(f"  {row.field}: lab={row.lab_value!r} probe={row.probe_value!r} -> {mark}{extra}")
        print(f"ok: {len(okish)}/{len(rows)}")
        if mismatches:
            print(f"mismatches: {len(mismatches)}", file=sys.stderr)

    return 2 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
