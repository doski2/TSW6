"""Paquetes ``data/vehicles`` y mapeo IPC MC."""

from __future__ import annotations

import json
from pathlib import Path

from tsw6v2.bridge.commands import combined_notch_to_value, master_controller_input_value
from tsw6v2.constants import B1_NOTCH, NEUTRAL_NOTCH
from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand, brake_applied_from_probe
from tsw6v2.vehicle_package import (
    clear_package_cache,
    combined_notch_to_ipc_value,
    enrich_brake_command_actuator,
    profile_brake_fraction,
    resolve_vehicle_package,
    uses_mc_analog_ipc,
    vehicle_class_matches,
)


def test_vehicle_class_matches_m3a() -> None:
    klass = "RVM_NYH_MNR_M3a-B_C"
    probe = f"{klass}_2147478415"
    assert vehicle_class_matches(probe, klass)


def test_resolve_m3a_package_from_repo() -> None:
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    assert pkg["vehicle_id"] == "m3a_mnr"
    assert uses_mc_analog_ipc(pkg)
    assert profile_brake_fraction(pkg, "neutral") == 0.72
    assert profile_brake_fraction(pkg, "B1") == 0.85


def test_brake_input_overrides_legacy_uk_map(tmp_path: Path) -> None:
    clear_package_cache()
    pkg = {
        "schema": "tsw6-vehicle-package/1",
        "vehicle_id": "test_mc",
        "match": {"vehicle_class": "Test_MC_Train"},
        "layout": "master_controller",
        "brake_input": {"neutral": 0.5, "B1": 0.6},
        "uk_combined_notch_ipc": {"3": 0.99, "4": 0.88},
    }
    (tmp_path / "test_mc.json").write_text(json.dumps(pkg), encoding="utf-8")
    loaded = resolve_vehicle_package("Test_MC_Train_x", vehicles_dir=tmp_path)
    assert loaded is not None
    assert profile_brake_fraction(loaded, "B1") == 0.6
    assert combined_notch_to_ipc_value(B1_NOTCH, loaded) == 0.6


def test_combined_notch_ipc_value_mc_vs_323() -> None:
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    b1_323 = combined_notch_to_value(B1_NOTCH)
    neutral_mc = combined_notch_to_ipc_value(NEUTRAL_NOTCH, pkg)
    b1_mc = combined_notch_to_ipc_value(B1_NOTCH, pkg)
    assert b1_323 == 0.375
    assert neutral_mc == 0.72
    assert b1_mc == 0.85
    assert b1_323 != neutral_mc
    assert b1_323 != b1_mc


def test_m3a_neutral_not_same_as_uk_b1_wire_value() -> None:
    """Regresión: 0.375 en línea ≠ neutro M3a 0.72 (semánticas distintas)."""
    assert combined_notch_to_value(3) == 0.375
    assert master_controller_input_value(0.72) == 0.72
    assert combined_notch_to_value(3) != master_controller_input_value(0.72)


def test_plan_to_brake_command_sets_mc_fraction() -> None:
    from tsw6v2.command import plan_to_brake_command
    from tsw6v2.plan import BrakePlan, BrakePlanStep

    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    dist = 800.0
    dist_start = 10.0
    step = BrakePlanStep(
        notch="B1",
        handle_notch=B1_NOTCH,
        phase="1",
        distance_m=200.0,
        apply_at_remaining_m=dist - dist_start,
        dist_start=dist_start,
        meters_until_action_m=dist_start,
        apply_now=True,
    )
    plan = BrakePlan(
        target_kind="SPEED_LIMIT",
        distance_to_target_m=dist,
        target_speed_mph=50.0,
        reaction_margin_m=40.0,
        steps=[step],
        active_step=step,
    )
    cmd, _ = plan_to_brake_command(
        plan,
        speed_mph=55.0,
        throttle_notch=0,
        effective_limit=75.0,
        current_notch=NEUTRAL_NOTCH,
        vehicle_package=pkg,
    )
    assert cmd is not None
    assert cmd.target_fraction == 0.85


def test_mc_combined_lever_for_gate_neutral_when_brake_lever() -> None:
    from tsw6v2.bridge.getdata import ProbeSnapshot
    from tsw6v2.command import combined_lever_for_station_gate
    from tsw6v2.constants import NEUTRAL_NOTCH

    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    snap = ProbeSnapshot.from_dict(
        {"lever_notch": 5, "power": 0.0, "vehicle": "RVM_NYH_MNR_M3a-B_C"}
    )
    assert combined_lever_for_station_gate(snap, 5, pkg) == NEUTRAL_NOTCH


def test_mc_brake_lever_not_counted_as_throttle() -> None:
    from tsw6v2.bridge.getdata import ProbeSnapshot
    from tsw6v2.command import throttle_notch_from_lever, throttle_notch_from_probe

    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    snap = ProbeSnapshot.from_dict(
        {
            "lever_notch": 5,
            "handle_notch": 5,
            "power": 0.0,
            "vehicle": "RVM_NYH_MNR_M3a-B_C",
        }
    )
    assert throttle_notch_from_lever(5) == 1
    assert throttle_notch_from_probe(snap, pkg) == 0


def test_mc_station_apply_not_coast_ping_pong_session_20261003() -> None:
    from tsw6v2.bridge.getdata import ProbeSnapshot
    from tsw6v2.command import BrakeReleaseState
    from tsw6v2.constants import MS_TO_MPH
    from tsw6v2.decision import evaluate_p1_tick
    from tsw6v2.limits import LimitBrakeState

    snap = ProbeSnapshot.from_dict(
        {
            "seq": 5913,
            "speed_ms": 2.97 / MS_TO_MPH,
            "lever_notch": 5,
            "handle_notch": 5,
            "power": 0.0,
            "signal_red": True,
            "signal_dist_cm": 22260.0,
            "dist_limit_cm": 47020.0,
            "next_limit_ms": 13.4112,
            "gradient_pct": 0.0,
            "vehicle": "RVM_NYH_MNR_M3a-B_C",
            "brake_cyl_bar": 9.71,
        }
    )
    d = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        station_distance_m=26.2,
    )
    assert d.target_kind == "STATION"
    assert d.command is not None
    assert d.command.kind == "APPLY"
    assert d.reason == "plan"


def test_class323_decision_keeps_notch_only() -> None:
    from tsw6v2.bridge.getdata import ProbeSnapshot
    from tsw6v2.decision import BrakeReleaseState, evaluate_p1_tick
    from tsw6v2.limits import LimitBrakeState

    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 24.6,
            "handle_notch": 6,
            "lever_notch": 6,
            "vehicle": "Class323",
            "dist_limit_cm": 120000.0,
            "next_limit_ms": 13.4,
            "gradient_pct": 0.0,
        }
    )
    decision = evaluate_p1_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        limit_brake_enabled=True,
        station_brake_enabled=False,
        signal_brake_enabled=False,
    )
    if decision.command is not None and decision.command.kind == "APPLY":
        assert decision.command.target_fraction is None
        assert decision.command.target_notch is not None


def test_enrich_brake_command_sets_mc_fraction() -> None:
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    cmd = BrakeCommand(kind="APPLY", target_notch=B1_NOTCH, phase="B1")
    out = enrich_brake_command_actuator(cmd, pkg)
    assert out.target_fraction == 0.85
    b2 = enrich_brake_command_actuator(
        BrakeCommand(kind="APPLY", target_notch=2, phase="B2"),
        pkg,
    )
    assert b2.target_fraction is not None
    assert b2.target_fraction != 0.85
    assert out.target_notch == B1_NOTCH
    plain = enrich_brake_command_actuator(cmd, None)
    assert plain.target_fraction is None


def test_resolve_from_custom_dir(tmp_path: Path) -> None:
    clear_package_cache()
    pkg = {
        "schema": "tsw6-vehicle-package/1",
        "vehicle_id": "test_mc",
        "match": {"vehicle_class": "Test_MC_Train"},
        "layout": "master_controller",
    }
    (tmp_path / "test_mc.json").write_text(json.dumps(pkg), encoding="utf-8")
    loaded = resolve_vehicle_package("Test_MC_Train_xyz", vehicles_dir=tmp_path)
    assert loaded is not None
    assert uses_mc_analog_ipc(loaded)


def test_brake_applied_from_probe_uk_lever() -> None:
    snap_b1 = ProbeSnapshot(lever_notch=B1_NOTCH)
    assert brake_applied_from_probe(snap_b1, B1_NOTCH)
    snap_neu = ProbeSnapshot(lever_notch=NEUTRAL_NOTCH)
    assert not brake_applied_from_probe(snap_neu, NEUTRAL_NOTCH)


def test_brake_applied_from_probe_mc_input_value() -> None:
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    neutral = combined_notch_to_ipc_value(NEUTRAL_NOTCH, pkg)
    snap_neu = ProbeSnapshot(
        vehicle="RVM_NYH_MNR_M3a-B_C",
        train_brake=neutral,
        lever_notch=5,
    )
    assert not brake_applied_from_probe(snap_neu, 5, pkg)
    snap_b1 = ProbeSnapshot(
        vehicle="RVM_NYH_MNR_M3a-B_C",
        train_brake=combined_notch_to_ipc_value(B1_NOTCH, pkg),
        lever_notch=5,
    )
    assert brake_applied_from_probe(snap_b1, 5, pkg)
    snap_cyl = ProbeSnapshot(
        vehicle="RVM_NYH_MNR_M3a-B_C",
        train_brake=0.0,
        brake_cyl_bar=2.0,
        lever_notch=NEUTRAL_NOTCH,
    )
    assert brake_applied_from_probe(snap_cyl, NEUTRAL_NOTCH, pkg)
