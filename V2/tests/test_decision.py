from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_limit_tick
from tsw6v2.limits import LimitBrakeState


def test_release_via_decision_tick():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 22.35,
            "lever_notch": 2,
            "dist_limit_cm": 20000.0,
            "next_limit_ms": 22.352,
            "speed_limit_ms": 22.352,
        }
    )
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
    )
    assert decision.command is not None
    assert decision.command.kind == "RELEASE"


def test_apply_when_over_limit_close():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.8,
            "lever_notch": 4,
            "dist_limit_cm": 400.0,
            "next_limit_ms": 24.5872,
        }
    )
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
    )
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
    assert decision.command.target_notch is not None
    assert decision.command.target_notch < 4


def _over_limit_snap(*, brake_cyl_bar: float | None = None) -> ProbeSnapshot:
    data: dict = {
        "seq": 1,
        "speed_ms": 26.8,
        "lever_notch": 4,
        "dist_limit_cm": 400.0,
        "next_limit_ms": 24.5872,
    }
    if brake_cyl_bar is not None:
        data["brake_cyl_bar"] = brake_cyl_bar
    return ProbeSnapshot.from_dict(data)


def test_air_fill_blocks_apply_without_pressure():
    from tsw6v2.learner import LearnerProfile

    snap = _over_limit_snap(brake_cyl_bar=1.2)
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        learner=LearnerProfile(),
    )
    assert decision.command is None
    assert decision.reason == "air_fill"
    assert "presión" in (decision.detail or "").lower()


def test_air_fill_allows_apply_when_pressure_ready():
    from tsw6v2.learner import LearnerProfile

    snap = _over_limit_snap(brake_cyl_bar=2.6)
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        learner=LearnerProfile(),
    )
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
    assert decision.reason == "plan"


def test_air_recharge_after_release():
    import time

    from tsw6v2.learner import LearnerProfile

    learner = LearnerProfile()
    t0 = time.monotonic()
    learner.observe_air(3, 4.0, now=t0)
    learner.observe_air(4, 3.5, now=t0 + 0.05)

    snap = _over_limit_snap(brake_cyl_bar=3.5)
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        learner=learner,
    )
    assert decision.command is None
    assert decision.reason == "air_recharge"


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
