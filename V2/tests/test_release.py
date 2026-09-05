from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.command import (
    BrakeReleaseState,
    is_brake_applied,
    resolve_release_command,
    should_hold_limit_brake_downhill,
)
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake


def test_is_brake_applied():
    assert is_brake_applied(3)
    assert not is_brake_applied(4)


def test_resolve_release_when_at_target():
    cmd = resolve_release_command(
        speed_mph=50.2,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


def test_no_release_when_slightly_above_limit():
    cmd = resolve_release_command(
        speed_mph=51.0,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is None


def test_no_release_parked_at_scenario_start():
    cmd = resolve_release_command(
        speed_mph=0.0,
        handle_notch=1,
        effective_limit=20.0,
        next_limit_mph=45.0,
        distance_next_m=271.0,
        gradient_pct=0.2,
    )
    assert cmd is None


def test_release_at_limit_speed_on_downhill():
    assert should_hold_limit_brake_downhill(
        gradient_pct=-1.0,
        distance_next_m=200.0,
        speed_mph=45.0,
        target_mph=45.0,
    ) is True
    cmd = resolve_release_command(
        speed_mph=45.0,
        handle_notch=1,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=200.0,
        gradient_pct=-1.0,
    )
    assert cmd is None


def test_brake_limit_latch_on_downhill_close():
    """Cerca del cartel en bajada → BRAKE_LIMIT (latch), no contención legacy."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=55.4,
        limit_mph=55.0,
        distance_m=80.0,
        gradient_pct=-1.0,
    )
    assert r is not None
    assert r.apply_now
    assert r.phase == "B1"
    assert "Límite" in r.detail
    assert "Contención" not in r.detail
    assert not r.downhill_hold


def test_coast_latch_inhibits_rebrake():
    state = BrakeReleaseState()
    state.latch(50.0)
    assert not state.should_inhibit_limit_rebrake(
        speed_mph=50.5,
        next_limit_mph=50.0,
        handle_notch=4,
        plan=None,
        gradient_pct=0.0,
        distance_next_m=300.0,
        effective_limit=75.0,
    )


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
