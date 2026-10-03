"""Criterios del test IPC B1 (diagnostic)."""

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.diagnostic import _b1_brake_evidence


def test_b1_evidence_train_brake_323() -> None:
    snap = ProbeSnapshot(train_brake=0.3, lever_notch=3)
    assert _b1_brake_evidence(snap, 3) is True


def test_b1_evidence_m3a_cyl_rise() -> None:
    base = ProbeSnapshot(brake_cyl_bar=9.93)
    after = ProbeSnapshot(brake_cyl_bar=10.30, train_brake=0.0, lever_notch=3)
    assert _b1_brake_evidence(after, 3, baseline=base) is True
