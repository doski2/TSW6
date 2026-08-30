"""Tests for api_correlator.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tools" / "api_correlator.py"
SESSION = ROOT / "data" / "lab_exports" / "exports" / "20260830T145544Z"

_spec = importlib.util.spec_from_file_location("api_correlator", SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["api_correlator"] = _mod
_spec.loader.exec_module(_mod)

collect_http_guesses = _mod.collect_http_guesses
collect_formation_probe_defs = _mod.collect_formation_probe_defs
compare_values = _mod.compare_values
correlate_session = _mod.correlate_session
fetch_formation_snapshot = _mod.fetch_formation_snapshot
formation_lua_diagnosis = _mod.formation_lua_diagnosis
normalize_api_path_candidates = _mod.normalize_api_path_candidates


def test_normalize_hud_path():
    lab = "CurrentFormation/0/Function.HUD_GetSpeed"
    cands = normalize_api_path_candidates(lab)
    assert "CurrentFormation/0.Function.HUD_GetSpeed" in cands
    assert "CurrentDrivableActor.Function.HUD_GetSpeed" in cands


def test_normalize_driver_input():
    lab = "DriverInput/0/PowerBrakeHandle.InputValue"
    cands = normalize_api_path_candidates(lab)
    assert cands[0] == lab
    assert "DriverInput.PowerBrakeHandle.InputValue" in cands


def test_compare_values_exact_and_fuzzy():
    assert compare_values(1.0, 1.0) == "exact"
    assert compare_values(1.0, 1.0000001) == "fuzzy"
    assert compare_values({"Speed (ms)": 22.0}, {"Speed (ms)": 22.0}) == "exact"
    assert compare_values(1.0, 2.0) == "mismatch"


def test_collect_guesses_from_reference_session():
    if not SESSION.is_dir():
        pytest.skip("reference session not in tree")
    rows = collect_http_guesses(SESSION)
    hud = [r for r in rows if r.source == "hud_batch.json"]
    assert len(hud) == 16


def test_correlate_hud_mock_client():
    if not SESSION.is_dir():
        pytest.skip("reference session not in tree")
    hud_batch = json.loads((SESSION / "hud_batch.json").read_text(encoding="utf-8"))
    guesses = hud_batch["http_guess"]

    client = MagicMock()
    client.probe.return_value = True

    def fake_get_node(path: str):
        for lab_path, value in guesses.items():
            for cand in normalize_api_path_candidates(lab_path):
                if cand == path:
                    return value
        return None

    client.get_node.side_effect = fake_get_node

    summary = correlate_session(SESSION, client, hud_only=True)
    assert summary.http_alive is True
    ratio = summary.hud_exact_ratio()
    assert ratio == 1.0


def test_normalize_simulation_path():
    lab = "CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR"
    cands = normalize_api_path_candidates(lab)
    assert cands[0] == lab
    assert "CurrentFormation/0.Simulation.BrakeCylinder_2_1.Pressure_BAR" in cands


def test_collect_formation_probe_defs_fallback():
    if not SESSION.is_dir():
        pytest.skip("reference session not in tree")
    probes, meta = collect_formation_probe_defs(SESSION)
    assert len(probes) >= 10
    paths = {p["path"] for p in probes}
    assert "CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR" in paths


def test_formation_lua_diagnosis_http_only():
    FormationProbeRow = _mod.FormationProbeRow
    FormationSnapshot = _mod.FormationSnapshot

    snap = FormationSnapshot(session_id="test")
    snap.http_alive = True
    snap.rows = [
        FormationProbeRow(
            path="CurrentFormation/0/Simulation/BrakeCylinder_2_1.Pressure_BAR",
            scope="formation",
            node="BrakeCylinder_2_1",
            field="Pressure_BAR",
            status="ok",
            actual={"Pressure_BAR": 2.6},
            lua_index_ok=False,
        )
    ]
    lines = formation_lua_diagnosis(snap)
    assert any("HTTP sí, Lua no" in line for line in lines)


def test_fetch_formation_snapshot_mock():
    if not SESSION.is_dir():
        pytest.skip("reference session not in tree")
    client = MagicMock()
    client.probe.return_value = True
    client.get_node.return_value = {"Pressure_BAR": 2.61}

    snap = fetch_formation_snapshot(SESSION, client)
    assert snap.http_alive is True
    assert any(r.status == "ok" for r in snap.rows)


def test_dry_list_cli():
    if not SESSION.is_dir():
        pytest.skip("reference session not in tree")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(SESSION), "--dry-list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "hud_batch.json" in proc.stdout
    assert "HUD_GetSpeed" in proc.stdout
