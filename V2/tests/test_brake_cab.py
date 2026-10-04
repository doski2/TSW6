from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.brake_cab import BrakeCabState, brake_state_from_probe, service_brake_held_from_probe
from tsw6v2.command import brake_applied_from_probe
from tsw6v2.constants import NEUTRAL_NOTCH
from tsw6v2.vehicle_package import probe_mc_input_fraction, resolve_vehicle_package


def _m3a_pkg():
    return resolve_vehicle_package("RVM_NYH_MNR_M3a-B_C")


def test_brake_state_mc_uses_mc_input_over_lever_estimate() -> None:
    pkg = _m3a_pkg()
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "lever_notch": NEUTRAL_NOTCH,
            "mc_input": 0.45,
            "vehicle": "RVM_NYH_MNR_M3a-B_C",
        }
    )
    assert brake_state_from_probe(snap, NEUTRAL_NOTCH, pkg) == BrakeCabState.HELD_SERVICE
    assert probe_mc_input_fraction(snap, pkg) == 0.45
    snap_neu = ProbeSnapshot.from_dict(
        {
            "seq": 2,
            "lever_notch": 0,
            "mc_input": 0.72,
            "brake_cyl_bar": 1.0,
            "vehicle": "RVM_NYH_MNR_M3a-B_C",
        }
    )
    assert brake_state_from_probe(snap_neu, 0, pkg) == BrakeCabState.RELEASED


def test_brake_applied_from_probe_delegates_to_brake_cab() -> None:
    pkg = _m3a_pkg()
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "lever_notch": NEUTRAL_NOTCH,
            "mc_input": 0.27,
            "vehicle": "RVM_NYH_MNR_M3a-B_C",
        }
    )
    assert service_brake_held_from_probe(snap, NEUTRAL_NOTCH, pkg)
    assert brake_applied_from_probe(snap, NEUTRAL_NOTCH, pkg)


def test_brake_state_uk_lever() -> None:
    snap = ProbeSnapshot.from_dict({"seq": 1, "lever_notch": 3, "vehicle": "Class323"})
    assert brake_state_from_probe(snap, 3, None) == BrakeCabState.HELD_SERVICE
    assert brake_state_from_probe(snap, NEUTRAL_NOTCH, None) == BrakeCabState.RELEASED
