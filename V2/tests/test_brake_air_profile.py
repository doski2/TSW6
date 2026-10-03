"""Perfil L4 ``brake_air`` en paquete G-B (MC US)."""

from __future__ import annotations

from tsw6v2.brake_air import BrakeAirTracker
from tsw6v2.brake_air_profile import BrakeAirProfile, MODEL_MASTER_CONTROLLER
from tsw6v2.learner import LearnerProfile
from tsw6v2.vehicle_package import resolve_brake_air_profile


def test_profile_from_m3a_package() -> None:
    pkg = {
        "layout": "master_controller",
        "brake_air": {"model": "master_controller"},
    }
    assert resolve_brake_air_profile(pkg).is_master_controller()
    assert BrakeAirProfile.from_vehicle_package(pkg).is_master_controller()


def test_profile_inferred_from_layout_without_block() -> None:
    pkg = {"layout": "master_controller", "ipc_aliases": {"PowerBrakeHandle": "MasterController"}}
    assert BrakeAirProfile.from_vehicle_package(pkg).is_master_controller()


def test_mc_air_ready_with_elevated_cylinder() -> None:
    air = BrakeAirTracker()
    air.set_profile(BrakeAirProfile(model=MODEL_MASTER_CONTROLLER))
    assert air.air_ready(11.18, lever=4) is True
    assert air.air_ready(11.18, lever=3) is True


def test_mc_no_inhibit_reapply_on_high_pressure() -> None:
    air = BrakeAirTracker()
    air.set_profile(BrakeAirProfile(model=MODEL_MASTER_CONTROLLER))
    air.observe(3, 11.0, now=0.0)
    air.observe(4, 11.0, now=0.1)
    assert air.inhibit_reapply(11.0, now=0.2) is False


def test_learner_apply_vehicle_profile() -> None:
    learner = LearnerProfile()
    learner.apply_vehicle_brake_profile(
        {"layout": "master_controller", "brake_air": {"model": "master_controller"}}
    )
    assert learner.air_ready(10.5, lever=4) is True
