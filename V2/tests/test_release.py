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


def test_limit_release_over_flat_vs_steep_downhill():
    from tsw6v2.command import limit_release_over_mph

    assert limit_release_over_mph(0.0) == 0.4
    assert limit_release_over_mph(-0.2) == 0.4  # no bajada (< −0.3)
    mild = limit_release_over_mph(-0.35)
    steep = limit_release_over_mph(-1.0)
    assert mild > 0.4
    assert steep > mild
    assert abs(steep - 0.55) < 0.01


def test_resolve_release_when_at_target():
    cmd = resolve_release_command(
        speed_mph=49.2,
        handle_notch=2,
        effective_limit=75.0,
        next_limit_mph=50.0,
        distance_next_m=200.0,
        gradient_pct=0.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"
    assert cmd.target_notch == 4


def test_release_after_slow_zone_when_next_limit_rises():
    """35→60: en banda @34 soltar aunque el next sea 60."""
    cmd = resolve_release_command(
        speed_mph=34.2,
        handle_notch=3,
        effective_limit=35.0,
        next_limit_mph=60.0,
        distance_next_m=520.0,
        gradient_pct=-1.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


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
    # Aún por encima del suelo coast 44.5 + banda bajada fuerte
    cmd = resolve_release_command(
        speed_mph=48.0,
        handle_notch=1,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=200.0,
        gradient_pct=-1.0,
    )
    assert cmd is None
    cmd_near = resolve_release_command(
        speed_mph=44.5,
        handle_notch=3,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=120.0,
        gradient_pct=-1.0,
        latch_ops_target=44.0,
    )
    assert cmd_near is not None
    assert cmd_near.kind == "RELEASE"


def test_release_downhill_55_to_45_at_coast_floor():
    """55→45 bajada: soltar ~44.5 en horizonte, no arrastrar B1 hasta 40."""
    cmd = resolve_release_command(
        speed_mph=44.5,
        handle_notch=3,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=120.0,
        gradient_pct=-1.0,
        latch_ops_target=44.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_release_in_zone_45_after_sign():
    """Zona 45: con B1 puesto @44, soltar hacia banda 44.5."""
    cmd = resolve_release_command(
        speed_mph=44.0,
        handle_notch=3,
        effective_limit=45.0,
        next_limit_mph=35.0,
        distance_next_m=800.0,
        gradient_pct=-1.0,
        latch_ops_target=44.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_no_release_55_zone_still_approaching_45():
    cmd = resolve_release_command(
        speed_mph=50.0,
        handle_notch=3,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=400.0,
        gradient_pct=-1.0,
        latch_ops_target=44.0,
    )
    assert cmd is None


def test_no_release_60_to_55_braking_inside_horizon():
    """Sesión 205020Z: no soltar en suelo zona 60 con cartel 55 a 216 m."""
    cmd = resolve_release_command(
        speed_mph=59.91,
        handle_notch=3,
        effective_limit=60.0,
        next_limit_mph=55.0,
        distance_next_m=216.2,
        gradient_pct=-1.0,
    )
    assert cmd is None


def test_no_release_55_to_45_chatter_inside_horizon():
    """Sesión 205020Z: APPLY→RELEASE a 54.77 mph / 324 m al cartel 45."""
    cmd = resolve_release_command(
        speed_mph=54.77,
        handle_notch=3,
        effective_limit=55.0,
        next_limit_mph=45.0,
        distance_next_m=323.7,
        gradient_pct=-1.0,
    )
    assert cmd is None


def test_release_downhill_zone_coast_far_from_next_sign():
    """60→55 lejos: tras contener zona, soltar en banda ~59.5 (no hasta @54)."""
    cmd = resolve_release_command(
        speed_mph=59.5,
        handle_notch=3,
        effective_limit=60.0,
        next_limit_mph=55.0,
        distance_next_m=650.0,
        gradient_pct=-1.0,
        latch_ops_target=54.0,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_no_zone_release_downhill_when_still_over_ceiling():
    cmd = resolve_release_command(
        speed_mph=60.8,
        handle_notch=3,
        effective_limit=60.0,
        next_limit_mph=55.0,
        distance_next_m=650.0,
        gradient_pct=-1.0,
        latch_ops_target=54.0,
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
    assert state.should_inhibit_limit_rebrake(
        speed_mph=50.5,
        next_limit_mph=50.0,
        handle_notch=4,
        plan=None,
        gradient_pct=0.0,
        distance_next_m=300.0,
        effective_limit=75.0,
    )
    assert not state.should_inhibit_limit_rebrake(
        speed_mph=52.0,
        next_limit_mph=50.0,
        handle_notch=4,
        plan=None,
        gradient_pct=0.0,
        distance_next_m=300.0,
        effective_limit=75.0,
    )


def test_kinematic_release_before_target_on_brake_limit():
    """60→55: soltar antes de 54 si el fill seguiría frenando (evita undershoot)."""
    cmd = resolve_release_command(
        speed_mph=55.2,
        handle_notch=3,
        effective_limit=60.0,
        next_limit_mph=55.0,
        distance_next_m=120.0,
        gradient_pct=-1.0,
        latch_ops_target=54.0,
        accel_ms2=-0.35,
        brake_fill_s=2.5,
    )
    assert cmd is not None
    assert cmd.kind == "RELEASE"


def test_kinematic_no_release_when_projected_above_target():
    """Aún lejos del objetivo: no soltar aunque la banda fija lo permitiría."""
    cmd = resolve_release_command(
        speed_mph=56.0,
        handle_notch=3,
        effective_limit=60.0,
        next_limit_mph=55.0,
        distance_next_m=180.0,
        gradient_pct=-1.0,
        latch_ops_target=54.0,
        brake_fill_s=2.5,
        predict_decel=lambda h, s, g: 0.35,
    )
    assert cmd is None


def test_projected_speed_after_brake_fill():
    from tsw6v2.physics import projected_speed_mph_after_brake_fill

    v = projected_speed_mph_after_brake_fill(
        55.0,
        accel_ms2=-0.40,
        decel_ms2=None,
        gradient_pct=-1.0,
        brake_fill_s=2.5,
    )
    assert v is not None
    assert v < 54.5
    assert v > 52.0


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
