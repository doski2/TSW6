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
            "speed_ms": 21.99,  # ~49.2 mph — banda @49 (posted 50)
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


def test_release_clears_committed_handle_to_avoid_reapply_chatter():
    """60→55 bajada: RELEASE no debe re-comprometer B1 al tick siguiente."""
    state = LimitBrakeState()
    state.committed_handle = 3
    state.committed_phase = "B1"
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.59,  # ~59.5 mph — banda coast zona 60
            "lever_notch": 3,
            "dist_limit_cm": 150000.0,
            "next_limit_ms": 24.5872,  # 55 mph
            "speed_limit_ms": 26.8224,  # 60 mph vigente
            "gradient_pct": -1.0,
        }
    )
    release = BrakeReleaseState()
    rel = evaluate_limit_tick(state, release, snap)
    assert rel.command is not None
    assert rel.command.kind == "RELEASE"
    assert state.committed_handle is None

    snap2 = ProbeSnapshot.from_dict(
        {
            "seq": 2,
            "speed_ms": 26.59,
            "lever_notch": 4,
            "dist_limit_cm": 150000.0,
            "next_limit_ms": 24.5872,
            "speed_limit_ms": 26.8224,
            "gradient_pct": -1.0,
        }
    )
    follow = evaluate_limit_tick(state, release, snap2)
    assert follow.command is None
    assert follow.reason in ("apply_deferred", "command_none")


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

    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.8,
            "lever_notch": 3,
            "dist_limit_cm": 400.0,
            "next_limit_ms": 24.5872,
            "brake_cyl_bar": 1.2,
        }
    )
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        learner=LearnerProfile(),
    )
    assert decision.command is None
    assert decision.reason == "air_fill"
    assert "presión" in (decision.detail or "").lower()


def test_air_fill_allows_apply_from_coast_idle_gauge():
    from tsw6v2.learner import LearnerProfile

    snap = _over_limit_snap(brake_cyl_bar=1.03)
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
        learner=LearnerProfile(),
    )
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
    assert decision.reason == "plan"


def test_air_fill_allows_apply_when_pressure_ready():
    from tsw6v2.learner import LearnerProfile

    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.8,
            "lever_notch": 3,
            "dist_limit_cm": 400.0,
            "next_limit_ms": 24.5872,
            "brake_cyl_bar": 2.6,
        }
    )
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
