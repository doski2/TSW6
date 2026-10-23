"""``limit_containment``: suelo de RELEASE en bajada y contención de zona."""

from __future__ import annotations

from typing import Optional

import pytest

from tsw6v2.limit_containment import (
    downhill_brake_release_floor_mph,
    pick_downhill_containment,
)
from tsw6v2.limit_state import LimitBrakeState


def _floor(**kw: float) -> Optional[float]:
    base = dict(
        speed_mph=59.8,
        effective_limit=60.0,
        next_limit_mph=60.0,
        distance_next_m=2000.0,
        gradient_pct=-2.0,
        release_over_mph=0.4,
    )
    base.update(kw)
    return downhill_brake_release_floor_mph(**base)


def test_sin_bajada_no_hay_suelo() -> None:
    assert _floor(gradient_pct=0.0) is None
    assert _floor(gradient_pct=1.5) is None


def test_zona_vigente_lejos_del_cartel_suelta_en_el_suelo_de_la_zona() -> None:
    # 60→60 en bajada: coast ~59.5 (ops + 0.5).
    assert _floor() == pytest.approx(59.5)


def test_acercandose_al_cartel_menor_suelta_en_el_suelo_del_cartel() -> None:
    # 55→45 dentro del horizonte: soltar ~44.5.
    assert _floor(
        speed_mph=44.6, effective_limit=55.0, next_limit_mph=45.0, distance_next_m=100.0
    ) == pytest.approx(44.5)


def test_por_encima_del_cartel_aun_no_suelta() -> None:
    assert (
        _floor(speed_mph=50.0, effective_limit=55.0, next_limit_mph=45.0, distance_next_m=100.0)
        is None
    )


def test_salida_ascendente_cuenta_la_zona_vigente_no_el_cartel_nuevo() -> None:
    # 15→50: coast ~14.5 en la zona vigente (sesiones 081745Z / 142034Z).
    assert _floor(
        speed_mph=14.6, effective_limit=15.0, next_limit_mph=50.0, distance_next_m=2000.0
    ) == pytest.approx(14.5)


def test_pick_downhill_sin_bajada_no_contiene() -> None:
    assert (
        pick_downhill_containment(
            LimitBrakeState(),
            speed_mph=40.0,
            posted_limit_mph=60.0,
            gradient_pct=0.0,
        )
        is None
    )


def test_pick_downhill_salida_ascendente_no_aplica_hold() -> None:
    # 35→60 en bajada: la zona sube, no se retiene (zone_hold_suppressed_for_ascending_exit).
    assert (
        pick_downhill_containment(
            LimitBrakeState(),
            speed_mph=35.5,
            posted_limit_mph=35.0,
            gradient_pct=-2.0,
            next_limit_mph=60.0,
            next_distance_m=500.0,
        )
        is None
    )
