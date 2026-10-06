"""Paquetes ``data/vehicles`` y mapeo IPC MC."""

from __future__ import annotations

import json
from pathlib import Path

from tsw6v2.bridge.commands import combined_notch_to_value, master_controller_input_value
from tsw6v2.constants import B1_NOTCH, NEUTRAL_NOTCH
from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand, brake_applied_from_probe
from tsw6v2.vehicle_package import (
    apply_vehicle_brake_actuator,
    clear_package_cache,
    combined_notch_to_ipc_value,
    enrich_brake_command_actuator,
    profile_brake_fraction,
    resolve_vehicle_package,
    session_route_cli_slug_for_probe,
    station_planning_trusted,
    uses_mc_analog_ipc,
    vehicle_class_matches,
)


def test_station_planning_trusted_m3a_vs_cross_city() -> None:
    m3a = "RVM_NYH_MNR_M3a-A_C"
    assert station_planning_trusted(m3a, "Grand Central Corridor (MNR)")
    assert not station_planning_trusted(m3a, "Birmingham Cross-City")
    assert station_planning_trusted(m3a, None)


def test_vehicle_class_matches_m3a() -> None:
    klass = "RVM_NYH_MNR_M3a"
    assert vehicle_class_matches("RVM_NYH_MNR_M3a-A_C", klass)
    assert vehicle_class_matches("RVM_NYH_MNR_M3a-B_C_2147478415", klass)


def test_resolve_m3a_package_from_repo() -> None:
    clear_package_cache()
    for probe in ("RVM_NYH_MNR_M3a-B_C", "RVM_NYH_MNR_M3a-A_C"):
        pkg = resolve_vehicle_package(probe)
        assert pkg is not None
        assert pkg["vehicle_id"] == "m3a_mnr"
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert session_route_cli_slug_for_probe("RVM_NYH_MNR_M3a-B_C") == "gct-mnr"
    assert uses_mc_analog_ipc(pkg)
    from tsw6v2.vehicle_package import station_platform_tail_m

    assert station_platform_tail_m(pkg) == 85.0
    assert profile_brake_fraction(pkg, "neutral") == 0.72
    b1 = profile_brake_fraction(pkg, "B1")
    assert b1 is not None and b1 < 0.72
    assert abs(b1 - 0.64) < 0.01


def test_brake_input_overrides_legacy_uk_map(tmp_path: Path) -> None:
    clear_package_cache()
    pkg = {
        "schema": "tsw6-vehicle-package/1",
        "vehicle_id": "test_mc",
        "match": {"vehicle_class": "Test_MC_Train"},
        "layout": "master_controller",
        "brake_input": {"neutral": 0.5, "B1": 0.6, "B3": 0.2},
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
    assert b1_mc is not None and b1_mc < neutral_mc
    assert abs(b1_mc - 0.64) < 0.01
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
    assert cmd.target_fraction is not None
    assert cmd.target_fraction < 0.72


def test_mc_service_brake_fraction_interpolates_session_215905() -> None:
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    neu = profile_brake_fraction(pkg, "neutral")
    b3 = profile_brake_fraction(pkg, "B3")
    assert neu is not None and b3 is not None
    from tsw6v2.vehicle_package import mc_service_brake_fraction

    b1 = mc_service_brake_fraction(pkg, handle_notch=3, phase="B1")
    mid = mc_service_brake_fraction(pkg, handle_notch=2, phase="B2")
    full = mc_service_brake_fraction(pkg, handle_notch=1, phase="B3")
    assert b1 is not None and mid is not None and full is not None
    assert neu > b1 > mid > full == b3
    assert abs(b1 - (neu - (neu - b3) / 3.0)) < 0.02


def test_mc_ipc_neutral_hold_and_traction_helpers_m3a() -> None:
    from tsw6v2.vehicle_package import (
        mc_has_traction_above_neutral,
        mc_ipc_target_is_neutral_hold,
    )

    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    assert mc_ipc_target_is_neutral_hold(pkg, 0.72)
    assert not mc_ipc_target_is_neutral_hold(pkg, 0.64)
    snap_pwr = ProbeSnapshot.from_dict(
        {"power": 1.0, "mc_input": 0.85, "vehicle": "RVM_NYH_MNR_M3a-B_C"}
    )
    snap_idle = ProbeSnapshot.from_dict(
        {"power": 0.0, "mc_input": 0.72, "vehicle": "RVM_NYH_MNR_M3a-B_C"}
    )
    assert mc_has_traction_above_neutral(snap_pwr, pkg)
    assert not mc_has_traction_above_neutral(snap_idle, pkg)


def test_apply_actuator_coast_throttle_neutral_fraction_m3a() -> None:
    from tsw6v2.command import BrakeCommand

    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    cmd = apply_vehicle_brake_actuator(
        BrakeCommand(kind="COAST_THROTTLE", target_notch=4),
        pkg,
    )
    assert cmd.target_fraction == 0.72


def test_m3a_brake_input_below_neutral_not_power_side_session_215007() -> None:
    """Regresión: B* < neutro (0.72); valores > neutro aceleran (IPC 0.95 → power 1)."""
    clear_package_cache()
    pkg = resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")
    assert pkg is not None
    neu = profile_brake_fraction(pkg, "neutral")
    assert neu is not None
    assert neu == 0.72
    for slot in ("B1", "B2", "B3"):
        frac = profile_brake_fraction(pkg, slot)
        assert frac is not None and frac < neu
    b1 = profile_brake_fraction(pkg, "B1")
    b2 = profile_brake_fraction(pkg, "B2")
    b3 = profile_brake_fraction(pkg, "B3")
    assert b1 is not None and b2 is not None and b3 is not None
    assert b3 < b2 < b1


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
    assert out.target_fraction is not None and out.target_fraction < 0.72
    b2 = enrich_brake_command_actuator(
        BrakeCommand(kind="APPLY", target_notch=2, phase="B2"),
        pkg,
    )
    assert b2.target_fraction is not None
    assert b2.target_fraction < out.target_fraction
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
        lever_notch=B1_NOTCH,
    )
    assert brake_applied_from_probe(snap_b1, B1_NOTCH, pkg)
    snap_cyl = ProbeSnapshot(
        vehicle="RVM_NYH_MNR_M3a-B_C",
        train_brake=0.0,
        brake_cyl_bar=2.0,
        lever_notch=NEUTRAL_NOTCH,
    )
    assert brake_applied_from_probe(snap_cyl, NEUTRAL_NOTCH, pkg)
