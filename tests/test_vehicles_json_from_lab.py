"""Tests for vehicles_json_from_lab.py (L0.7)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tools.vehicles_json_from_lab import (
    build_vehicle_package,
    infer_vehicle_id,
    resolve_controls_path,
    write_vehicle_package,
)

from tsw6.lab.lab_export import FIXTURES_LAB

ROOT = Path(__file__).resolve().parents[1]
REF_CONTROLS = FIXTURES_LAB / "20260830T213100Z" / "controls.json"


def test_infer_vehicle_id_class323() -> None:
    assert infer_vehicle_id("RVM_BCC_WRM_Class323_DMS_A_C") == "class_323"


def test_build_minimal_combined_package() -> None:
    controls = {
        "schema": "tsw6-lab-export/1",
        "session_id": "test",
        "vehicle_class": "RVM_BCC_WRM_Class323_DMS_A_C",
        "layout_hint": "combined",
        "ipc_aliases": {"DynamicBrake": "RegenBrakes"},
        "lua": {
            "levers": [
                {
                    "name": "PowerBrakeHandle",
                    "class": "IrregularLeverComponent",
                    "scope": "actor",
                    "read_kind": "scalar",
                    "read_value": -0.6,
                    "notches": [
                        {"index": 1, "MinimumInputValue": -1, "MaximumInputValue": -1},
                    ],
                }
            ]
        },
    }
    pkg = build_vehicle_package(controls)
    assert pkg["schema"] == "tsw6-vehicle-package/1"
    assert pkg["vehicle_id"] == "class_323"
    assert pkg["layout"] == "combined"
    assert pkg["combined"]["primary_lever"] == "PowerBrakeHandle"
    assert "PowerBrakeHandle" in pkg["controls"]
    assert pkg["ipc_aliases"]["DynamicBrake"] == "RegenBrakes"


@pytest.mark.parametrize("controls_path", [REF_CONTROLS])
def test_reference_session_213100z(controls_path: Path) -> None:
    controls = json.loads(controls_path.read_text(encoding="utf-8"))
    pkg = build_vehicle_package(controls, source_path=REF_CONTROLS)
    assert pkg["vehicle_id"] == "class_323"
    assert pkg["layout"] == "combined"
    assert len(pkg["controls"]) == 7
    pbh = pkg["controls"]["PowerBrakeHandle"]
    assert len(pbh["notches"]) == 8


def test_resolve_session_directory(tmp_path: Path) -> None:
    session = tmp_path / "sess"
    session.mkdir()
    controls = session / "controls.json"
    controls.write_text("{}", encoding="utf-8")
    assert resolve_controls_path(session) == controls


def test_write_vehicle_package(tmp_path: Path) -> None:
    pkg = {
        "schema": "tsw6-vehicle-package/1",
        "vehicle_id": "test_unit",
        "match": {"vehicle_class": "X"},
        "layout": "combined",
        "controls": {},
        "source": {},
    }
    out = write_vehicle_package(pkg, tmp_path / "out.json")
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["vehicle_id"] == "test_unit"
