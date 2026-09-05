from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.physics import (
    DEFAULT_MAX_BRAKE_DECEL,
    MPH_TO_MS,
    brake_ctx_for_decel,
    braking_distance_m,
    decel_for_notch,
    gravity_acceleration_ms2,
)
from tsw6v2.planning import next_speed_limit
from tsw6v2.bridge.getdata import ProbeSnapshot


class TestPhysicsGradient:
    def test_downhill_s_matches_single_g(self) -> None:
        v = 60.0 * MPH_TO_MS
        u = 50.0 * MPH_TO_MS
        a_flat = decel_for_notch(0.33, DEFAULT_MAX_BRAKE_DECEL, -1.0)
        g_pct = -1.0
        s = braking_distance_m(
            v,
            u,
            a_flat,
            ctx=brake_ctx_for_decel(gradient_pct=g_pct, using_learned=False),
        )
        a_net = a_flat + gravity_acceleration_ms2(g_pct)
        s_once = (v * v - u * u) / (2.0 * a_net)
        assert abs(s - s_once) < 1e-6

    def test_learned_decel_skips_double_g(self) -> None:
        v = 60.0 * MPH_TO_MS
        u = 50.0 * MPH_TO_MS
        a_learned = 0.40
        s = braking_distance_m(
            v,
            u,
            a_learned,
            ctx=brake_ctx_for_decel(gradient_pct=-2.0, using_learned=True),
        )
        s_flat = (v * v - u * u) / (2.0 * a_learned)
        assert abs(s - s_flat) < 1e-6


class TestLimitBrake:
    def test_latches_on_new_limit(self) -> None:
        state = LimitBrakeState()
        r = evaluate_limit_brake(
            state,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=800.0,
            gradient_pct=0.0,
        )
        assert r is not None
        assert state.latch is not None
        assert state.latch.posted_limit_mph == 55.0
        assert state.latch.limit_mph == 54.0
        assert r.target_speed_mph == 54.0

    def test_60_to_55_weak_notch_far(self) -> None:
        state = LimitBrakeState()
        r = evaluate_limit_brake(
            state,
            speed_mph=60.0,
            limit_mph=55.0,
            distance_m=1200.0,
            gradient_pct=0.0,
        )
        assert r is not None
        assert r.phase in ("B1", "B2")
        assert r.dist_start > 0


class TestPlanning:
    def test_next_speed_limit_from_probe(self) -> None:
        snap = ProbeSnapshot.from_dict(
            {
                "dist_limit_cm": 40000.0,
                "next_limit_ms": 24.5872,
                "speed_ms": 10.0,
            }
        )
        dist_m, mph = next_speed_limit(snap)
        assert dist_m == 400.0
        assert mph is not None
        assert abs(mph - 55.0) < 1.0


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
