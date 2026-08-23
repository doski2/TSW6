"""Tests de esquemas Fase 0 (control_schema.py)."""

import json
import os
import tempfile

from tsw6.learning.control_layout import detect_control_layout
from tsw6.learning.control_schema import (
    build_observed_notches,
    build_vehicle_schema,
    combined_notch_rows,
    freight_axis_rows,
    infer_layout_from_stats,
    load_vehicle_schema,
    save_vehicle_schema,
    schema_path_for_vehicle,
)


def test_infer_freight_na_with_brakes():
    minmax = {"throttle": (0, 8), "train_brake_pct": (0.0, 1.0)}
    seen = {"throttle": {0, 4, 8}, "train_brake_pct": {0.0, 0.5, 1.0}}
    assert infer_layout_from_stats(minmax, seen) == "freight_na"


def test_infer_combined_handle_only():
    minmax = {"throttle": (0, 8)}
    seen = {"throttle": {0, 4, 8}}
    assert infer_layout_from_stats(minmax, seen) == "combined"


def test_build_observed_notches_freight():
    seen = {
        "throttle": {0, 1, 8},
        "train_brake_pct": {0.0, 0.5, 1.0},
        "dyn_brake": {0.0, 0.25, 1.0},
    }
    obs = build_observed_notches("freight_na", seen)
    assert obs["throttle"] == [0, 1, 8]
    assert 5 in obs["train_brake"]
    assert 2 in obs["dyn_brake"]


def test_build_observed_notches_combined():
    seen = {"throttle": {0, 4, 8}}
    obs = build_observed_notches("combined", seen)
    assert obs == {"handle": [0, 4, 8]}


def test_build_vehicle_schema_rejects_whitespace_name():
    schema = build_vehicle_schema(
        "   ",
        {"throttle": (0, 8)},
        {"throttle": {0, 4, 8}},
        "logs/control_diag_test.txt",
    )
    assert schema is None


def test_save_and_load_vehicle_schema():
    schema = build_vehicle_schema(
        "Test SD70M",
        {"throttle": (0, 8), "train_brake_pct": (0.0, 1.0)},
        {"throttle": {0, 8}, "train_brake_pct": {0.0, 1.0}},
        "logs/control_diag_test.txt",
    )
    assert schema is not None
    assert schema["layout"] == "freight_na"

    with tempfile.TemporaryDirectory() as tmp:
        import tsw6.learning.control_schema as cs
        old_dir = cs.SCHEMAS_DIR
        cs.SCHEMAS_DIR = tmp
        try:
            path = save_vehicle_schema(schema)
            assert os.path.isfile(path)
            loaded = load_vehicle_schema("Test SD70M")
            assert loaded is not None
            assert loaded["observed_notches"]["throttle"] == [0, 8]
        finally:
            cs.SCHEMAS_DIR = old_dir


def test_detect_layout_from_saved_schema(tmp_path, monkeypatch):
    import tsw6.learning.control_schema as cs

    schema = {
        "schema_version": 1,
        "vehicle": "Mystery Freight X",
        "layout": "freight_na",
        "observed_notches": {"throttle": [1, 2, 3]},
    }
    path = tmp_path / "Mystery_Freight_X.json"
    path.write_text(json.dumps(schema), encoding="utf-8")

    monkeypatch.setattr(cs, "SCHEMAS_DIR", str(tmp_path))

    assert detect_control_layout("Mystery Freight X") == "freight_na"


def test_freight_axis_rows_from_schema(tmp_path, monkeypatch):
    import tsw6.learning.control_schema as cs

    schema = {
        "vehicle": "UP SD70M",
        "layout": "freight_na",
        "observed_notches": {
            "throttle": [2, 4, 6],
            "train_brake": [4, 6],
        },
    }
    path = tmp_path / "UP_SD70M.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(cs, "SCHEMAS_DIR", str(tmp_path))

    rows = freight_axis_rows("UP SD70M")
    assert rows["throttle"][1] == (2, 4, 6)
    assert rows["train_brake"][1] == (4, 6)


def test_combined_notch_rows_from_schema(tmp_path, monkeypatch):
    import tsw6.learning.control_schema as cs

    schema = {
        "vehicle": "Class 350",
        "layout": "combined",
        "observed_notches": {"handle": [0, 4, 8]},
    }
    (tmp_path / "Class_350.json").write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(cs, "SCHEMAS_DIR", str(tmp_path))

    assert combined_notch_rows("Class 350", (0, 1, 2, 3, 4, 5, 6, 7, 8)) == (0, 4, 8)
