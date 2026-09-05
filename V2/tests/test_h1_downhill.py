from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_limit_tick
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.limit_containment import next_limit_brake_horizon_m
from tsw6v2.p1_layers import classify_layer


def test_h1_horizon_positive():
    h = next_limit_brake_horizon_m(60.0, 55.0, -1.0)
    assert 100 < h < 900


def test_h1_no_hold_on_descending_zone_60_to_55():
    """60→55: sin HOLD_DH; solo WATCH/BRAKE_LIMIT dentro del horizonte."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.22,
        limit_mph=55.0,
        distance_m=474.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is None or not r.downhill_hold


def test_h1_brake_limit_inside_horizon_60_to_55():
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.0,
        limit_mph=55.0,
        distance_m=280.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.downhill_hold
    assert r.target_speed_mph == 54.0
    assert "55" in r.detail
    assert "@54" in r.detail


def test_h1_60_to_55_downhill_distance_profile():
    """Perfil 60→55 bajada: WATCH lejos, BRAKE dentro del horizonte."""
    horizon = next_limit_brake_horizon_m(60.0, 55.0, -1.0)
    far = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.0,
        limit_mph=55.0,
        distance_m=horizon + 120.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert far is not None
    assert not far.apply_now

    near = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.0,
        limit_mph=55.0,
        distance_m=max(120.0, horizon - 40.0),
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert near is not None
    assert near.target_speed_mph == 54.0
    assert near.apply_now


def test_h1_hold_same_zone_uses_ops_59():
    """Zona 60→60 en bajada: HOLD_DH al techo 59 (posted 60)."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=59.5,
        limit_mph=60.0,
        distance_m=2000.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert "posted 60" in r.detail
    assert "@59" in r.detail


def test_h1_posted_hold_far_from_next_sign():
    """Misma zona 60→60: HOLD_DH con techo 59, no latch."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=59.5,
        limit_mph=60.0,
        distance_m=700.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert "@59" in r.detail
    assert "latched" not in r.detail


def test_h1_no_hold_under_trigger_same_zone():
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=59.2,
        limit_mph=60.0,
        distance_m=700.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is None or not getattr(r, "downhill_hold", False)


def test_h1_inside_horizon_uses_latch_not_legacy_containment():
    """Paso 2: dentro horizonte → latch BRAKE_LIMIT, nunca Contención bajada."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=56.0,
        limit_mph=55.0,
        distance_m=150.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.downhill_hold
    assert "Contención" not in (r.detail or "")
    assert "Límite" in (r.detail or "")


def test_h1_inside_horizon_uses_next_plan_not_posted():
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=56.0,
        limit_mph=55.0,
        distance_m=150.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.downhill_hold


def test_h1_coast_pwr_before_hold_with_power():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.6,  # ~59.5 mph
            "lever_notch": 6,
            "dist_limit_cm": 200000.0,
            "next_limit_ms": 26.8224,  # 60 mph
            "speed_limit_ms": 26.8224,
            "gradient_pct": -1.0,
        }
    )
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
    )
    assert decision.command is not None
    assert decision.command.kind == "COAST_THROTTLE"
    assert decision.reason == "coast_throttle"


def test_h1_hold_dh_layer_on_neutral():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 26.6,
            "lever_notch": 4,
            "dist_limit_cm": 200000.0,
            "next_limit_ms": 26.8224,
            "speed_limit_ms": 26.8224,
            "gradient_pct": -1.0,
        }
    )
    decision = evaluate_limit_tick(
        LimitBrakeState(),
        BrakeReleaseState(),
        snap,
    )
    assert decision.command is not None
    assert decision.command.kind == "APPLY"
    assert decision.reason == "downhill_hold"
    assert (
        classify_layer(
            reason=decision.reason,
            cmd="APPLY",
            apply_now=decision.apply_now,
        )
        == "HOLD_DH"
    )


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
