from __future__ import annotations

import _path  # noqa: F401

import time

from tsw6v2.brake_air import BrakeAirTracker, pressure_for_handle
from tsw6v2.learner import LearnerProfile


def test_fill_time_observed() -> None:
    air = BrakeAirTracker()
    t0 = 100.0
    air.observe(4, 1.0, now=t0)
    air.observe(3, 1.2, now=t0 + 0.1)
    air.observe(3, 2.5, now=t0 + 2.0)
    assert air.brake_fill_n == 1
    assert 1.8 < air.brake_fill_s < 2.2


def test_cap_escalation_waits_for_pressure() -> None:
    air = BrakeAirTracker()
    assert air.cap_escalation(committed=3, requested=2, brake_cyl_bar=2.0) == 3
    assert air.cap_escalation(committed=3, requested=2, brake_cyl_bar=2.6) == 2


def test_inhibit_reapply_until_idle() -> None:
    air = BrakeAirTracker()
    t0 = 50.0
    air.observe(3, 4.0, now=t0)
    air.observe(4, 3.5, now=t0 + 0.1)
    assert air.inhibit_reapply(3.5, now=t0 + 0.2) is True
    assert air.inhibit_reapply(1.4, now=t0 + 0.3) is False


def test_learner_persists_fill(tmp_path) -> None:
    p = LearnerProfile()
    p.observe_air(4, 1.0, now=0.0)
    p.observe_air(3, 1.1, now=0.1)
    p.observe_air(3, 2.6, now=2.1)
    path = tmp_path / "p.json"
    p.save_json(path)
    loaded = LearnerProfile.from_json(path)
    assert loaded.brake_fill_n == 1
    assert loaded.brake_fill_s > 1.5


def test_pressure_for_handle_b1() -> None:
    assert pressure_for_handle(3) >= 2.4


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
