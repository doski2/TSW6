"""Criterios del test IPC B1 (diagnostic)."""

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.diagnostic import _b1_brake_evidence, _mc_b1_ipc_pass


def test_b1_evidence_train_brake_323() -> None:
    snap = ProbeSnapshot(train_brake=0.3, lever_notch=3)
    assert _b1_brake_evidence(snap, 3) is True


def test_b1_evidence_m3a_cyl_rise() -> None:
    base = ProbeSnapshot(brake_cyl_bar=9.93)
    after = ProbeSnapshot(brake_cyl_bar=10.30, train_brake=0.0, lever_notch=3)
    assert _b1_brake_evidence(after, 3, baseline=base) is True


def test_mc_b1_pass_fraction_and_cylinder() -> None:
    base = ProbeSnapshot(brake_cyl_bar=9.27)
    after = ProbeSnapshot(
        brake_cyl_bar=10.78,
        train_brake=0.0,
        lever_notch=3,
        power=-0.85,
        power_neg=True,
    )
    pkg = {
        "layout": "master_controller",
        "brake_input": {"neutral": 0.72, "B3": 0.27},
    }
    expected = 0.72 - (0.72 - 0.27) / 3.0
    last = {"ok": True, "value": expected}
    assert _mc_b1_ipc_pass(base, after, last, pkg) is True
    assert _mc_b1_ipc_pass(base, after, {"ok": True, "value": 0.95}, pkg) is False
