"""Tests brake_physics_monitor / brake lab."""

from pathlib import Path

import pytest

from tsw6.learning.brake_physics_monitor import (
    BrakeLabSample,
    CSV_FIELDS,
    is_brake_effort_valid,
    summarize_csv,
)


def test_brake_effort_valid():
    assert not is_brake_effort_valid(None)
    assert not is_brake_effort_valid(0.0)
    assert is_brake_effort_valid(5921.0)
    assert not is_brake_effort_valid(4.8e20)


def test_lab_sample_csv_row_dual_source():
    s = BrakeLabSample(
        t=1000.0,
        phase="stopped_b1",
        pressure_http_bar=2.6,
        pressure_probe_bar=2.55,
        brake_effort_n=5921.0,
        http_ok=True,
        probe_ok=True,
    )
    row = s.to_csv_row()
    assert row["pressure_http_bar"] == "2.6"
    assert row["pressure_probe_bar"] == "2.55"
    assert row["effort_valid"] == "1"
    assert "P_http!=probe" not in row["quality_flags"]


def test_summarize_csv_phases(tmp_path: Path):
    p = tmp_path / "sample.csv"
    header = ",".join(CSV_FIELDS)
    p.write_text(
        header + "\n"
        "2026-01-01T00:00:00,0,stopped_b1,,,,,,,,,,2.6,2.5,0.1,5921,0,1,,1,1\n"
        "2026-01-01T00:00:01,1,stopped_b2,,,,,,,,,,3.5,3.4,0.1,9347,0,1,,1,1\n"
        "2026-01-01T00:00:02,2,moving_b2,,,,,,,,,,4.0,3.9,0.1,0,0,0,effort_0_marcha,1,1\n",
        encoding="utf-8",
    )
    out = summarize_csv(p)
    assert "stopped_b1" in out
    assert "BrakeEffort=0 en marcha" in out


def test_sample_effort_invalid_flags():
    s = BrakeLabSample(t=0.0, phase="t", brake_effort_n=1e20, http_ok=True)
    assert "effort_basura" in s.quality_flags()
