from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_limit_tick
from tsw6v2.limits import LimitBrakeState, evaluate_limit_brake
from tsw6v2.limit_horizon import next_limit_brake_horizon_m, within_next_brake_horizon
from tsw6v2.p1_layers import classify_layer


def test_h1_horizon_positive():
    h = next_limit_brake_horizon_m(60.0, 55.0, -1.0)
    assert 100 < h < 900
    assert within_next_brake_horizon(
        speed_mph=60.0,
        next_limit_mph=55.0,
        next_distance_m=h - 10.0,
        gradient_pct=-1.0,
    )
    assert not within_next_brake_horizon(
        speed_mph=60.0,
        next_limit_mph=55.0,
        next_distance_m=h + 10.0,
        gradient_pct=-1.0,
    )


def test_h1_no_hold_on_descending_zone_60_to_55():
    """60→55 @ −1%%: bajo techo HOLD (60.2); solo WATCH/BRAKE_LIMIT en horizonte."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.1,
        limit_mph=55.0,
        distance_m=474.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.downhill_hold
    assert not r.apply_now


def test_zone_hold_ceiling_scales_with_gradient():
    from tsw6v2.constants import posted_zone_hold_ceiling_mph, zone_hold_over_mph

    assert zone_hold_over_mph(0.0) == 0.5
    assert abs(zone_hold_over_mph(-1.0) - 0.2) < 0.01
    assert posted_zone_hold_ceiling_mph(60.0, -1.0) == 60.2
    assert posted_zone_hold_ceiling_mph(60.0, -0.2) == 60.5


def test_h1_zone_contain_far_when_over_scoring_ceiling_on_60_to_55():
    """60→55 lejos: > techo HOLD (60.2 @ −1%%) → B1 suave, no al 55 todavía."""
    state = LimitBrakeState()
    r = evaluate_limit_brake(
        state,
        speed_mph=62.5,
        limit_mph=55.0,
        distance_m=520.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert r.apply_now
    assert r.target_speed_mph == 60.2
    assert r.handle_notch == 3
    assert r.phase == "B1"
    assert state.latch is None
    assert state.committed_handle == 3


def test_flat_zone_contain_60_to_50_session_204031() -> None:
    """60→50 lejos @ +0.36 %%: >60.5 → HOLD zona vigente (sesión 204031Z)."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.53,
        limit_mph=50.0,
        distance_m=3516.0,
        gradient_pct=0.36,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert r.apply_now
    assert r.target_speed_mph == 60.5
    assert r.handle_notch == 3


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


def test_h1_hold_same_zone_uses_scoring_ceiling():
    """Zona 60→60 @ −1%%: HOLD_DH si superas 60.2 (techo HOLD fuerte)."""
    under = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=60.1,
        limit_mph=60.0,
        distance_m=2000.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert under is None or not under.downhill_hold

    over = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=61.2,
        limit_mph=60.0,
        distance_m=2000.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert over is not None
    assert over.downhill_hold
    assert over.target_speed_mph == 60.2
    assert "posted 60" in over.detail
    assert "@60.2" in over.detail


def test_h1_no_hold_on_ascending_exit():
    """35→60 en bajada: no contener zona vigente; dejar subir."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=36.5,
        limit_mph=60.0,
        distance_m=2000.0,
        gradient_pct=-1.0,
        posted_limit_mph=35.0,
    )
    assert r is None or not getattr(r, "downhill_hold", False)


def test_h1_zone_contain_on_moderate_ascending_10_to_30():
    """10→30 lejos: HOLD zona 10 aunque suba el cartel (sesión 142034Z)."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=12.8,
        limit_mph=30.0,
        distance_m=123.0,
        gradient_pct=-1.74,
        posted_limit_mph=10.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert r.apply_now
    assert abs(r.target_speed_mph - 9.88) < 0.05


def test_h1_posted_hold_far_from_next_sign():
    """Misma zona 60→60: HOLD_DH solo sobre 60.5, sin latch."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=61.0,
        limit_mph=60.0,
        distance_m=700.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert "@60.2" in r.detail
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


def test_h1_no_hold_when_next_limit_rises():
    """35→60: sin HOLD_DH al salir de zona lenta."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=34.3,
        limit_mph=60.0,
        distance_m=520.0,
        gradient_pct=-1.0,
        posted_limit_mph=35.0,
    )
    assert r is None or not r.downhill_hold


def test_h1_hold_escalates_via_hysteresis_when_overspeed():
    """HOLD_DH: B1 al entrar; B2 si sigue > techo + 0.65 mph."""
    state = LimitBrakeState()
    first = evaluate_limit_brake(
        state,
        speed_mph=61.8,
        limit_mph=60.0,
        distance_m=2000.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert first is not None
    assert first.downhill_hold
    assert first.handle_notch == 3
    assert first.phase == "B1"

    second = evaluate_limit_brake(
        state,
        speed_mph=61.8,
        limit_mph=60.0,
        distance_m=1990.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert second is not None
    assert second.downhill_hold
    assert second.handle_notch == 2
    assert second.phase == "B2"


def test_h1_downhill_coast_trim_defers_b1_near_target():
    """Bajada: +1.5 mph sobre techo → Vigilar, sin comprometer B1."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=55.5,
        limit_mph=55.0,
        distance_m=800.0,
        gradient_pct=-1.0,
        posted_limit_mph=60.0,
    )
    assert r is not None
    assert not r.apply_now
    assert r.handle_notch == 3
    assert r.phase == "B1"


def test_h1_hold_zone_15_to_50_session_152129() -> None:
    """15→50: zona 15 obligatoria en bajada aunque el cartel siguiente suba mucho."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=16.0,
        limit_mph=50.0,
        distance_m=800.0,
        gradient_pct=-1.74,
        posted_limit_mph=15.0,
    )
    assert r is not None
    assert r.downhill_hold
    assert r.apply_now
    assert abs(r.target_speed_mph - 14.88) < 0.05


def test_h1_coast_watch_below_hold_ceiling_session_150916() -> None:
    """30→50 @ −0.92 %%: vigilar y soltar P6 antes del techo 30.2 (150916Z)."""
    r = evaluate_limit_brake(
        LimitBrakeState(),
        speed_mph=28.09,
        limit_mph=50.0,
        distance_m=533.3,
        gradient_pct=-0.92,
        posted_limit_mph=30.0,
    )
    assert r is not None
    assert not r.downhill_hold
    assert r.phase == "WATCH"
    assert not r.apply_now
    assert abs(r.target_speed_mph - 30.2) < 0.05

    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 12.55,  # ~28.09 mph
            "lever_notch": 6,
            "dist_limit_cm": 53330.0,
            "next_limit_ms": 22.352,  # 50 mph
            "speed_limit_ms": 13.4112,  # 30 mph
            "gradient_pct": -0.92,
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


def test_h1_coast_pwr_before_hold_with_power():
    snap = ProbeSnapshot.from_dict(
        {
            "seq": 1,
            "speed_ms": 27.38,  # ~61.2 mph — sobre 60.9, con tracción
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
            "speed_ms": 27.38,  # ~61.2 mph
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
