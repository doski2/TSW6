#!/usr/bin/env python3
"""
vehicles_json_from_lab.py — L0.7: borrador paquete G-B desde export ApiExplorer.

Lee ``controls.json`` (o carpeta de sesión lab) y escribe ``data/vehicles/<id>.json``.

Ejemplo::

  python scripts/tools/vehicles_json_from_lab.py data/lab_exports/exports/20260830T213100Z
  python scripts/tools/vehicles_json_from_lab.py path/to/controls.json --vehicle-id class_323
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsw6.learning.control_layout import LAYOUT_COMBINED, LAYOUT_FREIGHT_NA  # noqa: E402
from tsw6.paths import DATA_DIR  # noqa: E402

SCHEMA = "tsw6-vehicle-package/1"
VEHICLES_DIR = DATA_DIR / "vehicles"


def resolve_controls_path(arg: Path) -> Path:
    arg = arg.resolve()
    if arg.is_file():
        return arg
    if arg.is_dir():
        candidate = arg / "controls.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"controls.json not found under {arg}")


def infer_vehicle_id(vehicle_class: str) -> str:
    """Slug estable para ``data/vehicles/<id>.json`` (p. ej. class_323)."""
    text = (vehicle_class or "").strip()
    match = re.search(r"class[_\s-]*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"class_{match.group(1)}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug or "unknown"


def _normalize_notches(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        if item.get("index") is not None:
            entry["index"] = int(item["index"])
        for key in ("MinimumInputValue", "MaximumInputValue"):
            if item.get(key) is not None:
                entry[key] = float(item[key])
        if entry:
            out.append(entry)
    return out


def _lever_entry(lever: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ue_name": str(lever.get("name") or ""),
        "component_class": str(lever.get("class") or ""),
        "scope": str(lever.get("scope") or "actor"),
        "read_kind": str(lever.get("read_kind") or "scalar"),
    }
    if lever.get("read_value") is not None:
        entry["read_value_at_capture"] = float(lever["read_value"])
    if lever.get("CurrentNotchID") is not None:
        entry["current_notch_id_at_capture"] = int(lever["CurrentNotchID"])
    notches = _normalize_notches(lever.get("notches"))
    if notches:
        entry["notches"] = notches
    if lever.get("number_of_notches") is not None:
        entry["number_of_notches"] = int(lever["number_of_notches"])
    if lever.get("ue_path"):
        entry["ue_path"] = str(lever["ue_path"])
    return entry


def build_vehicle_package(
    controls: dict[str, Any],
    *,
    vehicle_id: Optional[str] = None,
    source_path: Optional[Path] = None,
) -> dict[str, Any]:
    vehicle_class = str(controls.get("vehicle_class") or "").strip()
    if not vehicle_class:
        raise ValueError("controls.json missing vehicle_class")

    layout = str(controls.get("layout_hint") or LAYOUT_COMBINED)
    if layout not in (LAYOUT_COMBINED, LAYOUT_FREIGHT_NA):
        layout = LAYOUT_COMBINED

    vid = (vehicle_id or infer_vehicle_id(vehicle_class)).strip()
    levers = controls.get("lua", {}).get("levers") or []
    if not isinstance(levers, list) or not levers:
        raise ValueError("controls.json has no lua.levers[]")

    controls_map: dict[str, Any] = {}
    for lever in levers:
        if not isinstance(lever, dict):
            continue
        name = str(lever.get("name") or "").strip()
        if not name:
            continue
        controls_map[name] = _lever_entry(lever)

    if not controls_map:
        raise ValueError("no named levers in export")

    package: dict[str, Any] = {
        "schema": SCHEMA,
        "vehicle_id": vid,
        "match": {
            "vehicle_class": vehicle_class,
        },
        "layout": layout,
        "controls": controls_map,
        "source": {
            "lab_schema": str(controls.get("schema") or ""),
            "session_id": str(controls.get("session_id") or ""),
            "captured_at": str(controls.get("captured_at") or ""),
            "build": str(controls.get("build") or ""),
        },
    }

    aliases = controls.get("ipc_aliases")
    if isinstance(aliases, dict) and aliases:
        package["ipc_aliases"] = {str(k): str(v) for k, v in aliases.items()}

    if layout == LAYOUT_COMBINED and "PowerBrakeHandle" in controls_map:
        package["combined"] = {
            "primary_lever": "PowerBrakeHandle",
            "notch_min": 0,
            "notch_max": 8,
            "neutral_notch": 4,
        }

    if source_path is not None:
        package["source"]["controls_path"] = str(source_path).replace("\\", "/")

    return package


def write_vehicle_package(
    package: dict[str, Any],
    out_path: Optional[Path] = None,
) -> Path:
    vid = str(package.get("vehicle_id") or "unknown")
    path = out_path or (VEHICLES_DIR / f"{vid}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        help="controls.json or lab session directory",
    )
    parser.add_argument(
        "--vehicle-id",
        help="Override output id (default: infer from vehicle_class)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=f"Output JSON (default: {VEHICLES_DIR}/<id>.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout, do not write file",
    )
    args = parser.parse_args(argv)

    try:
        controls_path = resolve_controls_path(args.path)
        controls = json.loads(controls_path.read_text(encoding="utf-8"))
        package = build_vehicle_package(
            controls,
            vehicle_id=args.vehicle_id,
            source_path=controls_path,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(package, indent=2, ensure_ascii=False))
        return 0

    out = write_vehicle_package(package, args.out)
    print(f"Wrote {out}")
    print(f"vehicle_id={package['vehicle_id']} layout={package['layout']} "
          f"controls={len(package['controls'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
