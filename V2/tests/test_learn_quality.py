from __future__ import annotations

import _path  # noqa: F401

from learn_helpers import feed_stable_decel

from tsw6v2.brake_air import BrakeAirTracker
from tsw6v2.learn_quality import MIN_STABLE_S
from tsw6v2.learner import LearnerProfile
from tsw6v2.learner_v1 import V1LearnerData
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S


def test_decel_window_requires_stable_duration() -> None:
    p = LearnerProfile()
    assert not p.observe_brake_decel(
        handle=3,
        speed_mph=50.0,
        gradient_pct=0.0,
        accel_ms2=-0.80,
        lever=3,
        brake_cyl_bar=2.8,
        now=0.0,
    )
    assert p.decel_observe_n == 0


def test_decel_window_commits_after_stable_window() -> None:
    p = LearnerProfile()
    assert feed_stable_decel(p)
    assert p.decel_observe_n == 1


def test_decel_window_clears_on_notch_change() -> None:
    p = LearnerProfile()
    dt = MIN_STABLE_S / 3.0 + 0.05
    for i in range(3):
        p.observe_brake_decel(
            handle=3,
            speed_mph=50.0 - i * 0.8,
            gradient_pct=0.0,
            accel_ms2=-0.80,
            lever=3,
            brake_cyl_bar=2.8,
            now=i * dt,
        )
    p.observe_brake_decel(
        handle=2,
        speed_mph=47.0,
        gradient_pct=0.0,
        accel_ms2=-0.80,
        lever=2,
        brake_cyl_bar=2.8,
        now=3 * dt,
    )
    assert p.decel_observe_n == 0
    ev = p.pop_learn_event()
    assert ev is not None and ev.reason == "notch_unstable"


def test_decel_outlier_rejected() -> None:
    v1 = V1LearnerData()
    v1.ema_bands[1][3] = -0.56
    v1.n_bands[1][3] = 10
    v1.ema[3] = -0.56
    v1.n[3] = 10
    p = LearnerProfile(v1=v1)
    ok = False
    t0 = 100.0
    dt = MIN_STABLE_S / 3.0 + 0.05
    for i in range(4):
        if p.observe_brake_decel(
            handle=3,
            speed_mph=50.0 - i * 0.8,
            gradient_pct=0.0,
            accel_ms2=-0.10,
            lever=3,
            brake_cyl_bar=2.8,
            now=t0 + i * dt,
        ):
            ok = True
    assert not ok
    assert p.decel_observe_n == 0
    ev = p.pop_learn_event()
    assert ev is not None
    assert ev.kind == "decel"
    assert ev.accepted is False
    assert ev.reason == "decel_outlier"


def test_fill_conservative_until_min_samples() -> None:
    air = BrakeAirTracker()
    t0 = 0.0
    air.observe(4, 1.0, now=t0)
    air.observe(2, 1.1, now=t0 + 0.05)
    ev = air.observe(2, 1.7, now=t0 + 0.85)
    assert ev is not None and ev.accepted
    assert air.brake_fill_n == 1
    assert air.brake_fill_s == DEFAULT_BRAKE_FILL_S


def test_fill_outlier_rejected() -> None:
    air = BrakeAirTracker()
    t0 = 0.0
    air.observe(4, 1.0, now=t0)
    air.observe(3, 1.1, now=t0 + 0.1)
    air.observe(3, 2.6, now=t0 + 2.1)
    assert air.brake_fill_n == 1
    air.observe(4, 1.0, now=t0 + 5.0)
    air.observe(3, 1.1, now=t0 + 5.1)
    ev = air.observe(3, 2.6, now=t0 + 5.3)
    assert ev is not None
    assert not ev.accepted
    assert ev.reason == "fill_outlier"
    assert air.brake_fill_n == 1


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
