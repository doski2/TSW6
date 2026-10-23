"""``autopilot_limit``: adaptador limit-only del autopilot v1 sobre ``evaluate_p1_tick``."""

from __future__ import annotations

import pytest

from tsw6v2.autopilot_limit import BrakeCoordinatorV2, LimitP1Adapter, snapshot_from_autopilot
from tsw6v2.constants import MPH_TO_MS


def _eval(adapter: LimitP1Adapter, **kw):
    args = dict(
        speed_mph=40.0,
        next_limit_mph=None,
        distance_next_m=None,
        effective_limit=40.0,
        gradient_pct=0.0,
        throttle_notch=0,
        handle_notch=4,
        base_decel_ms2=0.7,
    )
    args.update(kw)
    return adapter.evaluate(**args)


def test_snapshot_convierte_unidades() -> None:
    snap = snapshot_from_autopilot(
        speed_mph=30.0,
        effective_limit=40.0,
        next_limit_mph=20.0,
        distance_next_m=500.0,
        gradient_pct=-1.0,
        handle_notch=4,
        accel_ms2=0.1,
    )
    assert snap.speed_ms == pytest.approx(30.0 * MPH_TO_MS)
    assert snap.speed_limit_ms == pytest.approx(40.0 * MPH_TO_MS)
    assert snap.next_limit_ms == pytest.approx(20.0 * MPH_TO_MS)
    assert snap.dist_limit_cm == pytest.approx(50000.0)
    assert snap.handle_notch == 4


def test_snapshot_sin_cartel_deja_none() -> None:
    snap = snapshot_from_autopilot(
        speed_mph=30.0,
        effective_limit=40.0,
        next_limit_mph=None,
        distance_next_m=None,
        gradient_pct=0.0,
        handle_notch=4,
        accel_ms2=None,
    )
    assert snap.next_limit_ms is None
    assert snap.dist_limit_cm is None


def test_alias_historico() -> None:
    assert BrakeCoordinatorV2 is LimitP1Adapter


def test_sin_cartel_cercano_no_manda_accion() -> None:
    ad = LimitP1Adapter()
    action, eff = _eval(ad)
    assert action is None
    assert eff == 40.0
    assert ad.last_brake_command is None
    assert ad.last_debug  # motivo registrado
    assert ad.unified_stop_latched is False


def test_cartel_encima_de_la_velocidad_pide_freno_y_reset_limpia() -> None:
    ad = LimitP1Adapter()
    # 60 mph hacia un cartel de 30 a 300 m: el plan tiene que frenar ya.
    action, _ = _eval(
        ad, speed_mph=60.0, effective_limit=60.0, next_limit_mph=30.0, distance_next_m=300.0
    )
    assert action is not None
    assert ad.last_brake_command is not None
    assert ad.last_brake_command.kind == "APPLY"
    assert "p1cmd=APPLY" in ad.investigate_suffix()
    ad.reset()
    assert ad.last_target is None and ad.last_brake_command is None and ad.last_debug == ""
