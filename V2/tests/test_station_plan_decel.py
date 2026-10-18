"""Deceleración de plan de estación por vehículo (M3A: 0,5 m/s²)."""

from __future__ import annotations

import pytest

from tsw6v2.plan import UK_SERVICE_PHASES
from tsw6v2.station_plan import plan_station_service_brake
from tsw6v2.vehicle_package import clear_package_cache, resolve_vehicle_package, vehicle_physics

MPH = 0.44704


def _learned_035(handle_notch: int, speed_mph: float, gradient_pct: float) -> float:
    """Lo aprendido del M3A por escalón (203040Z: B3/B2/B1 ≈ 0,33/0,37/0,39 m/s²)."""
    return 0.35


def test_vehicle_physics_station_plan_decel_per_vehicle() -> None:
    clear_package_cache()
    m3a = resolve_vehicle_package("RVM_NYH_MNR_M3a-A_C")
    assert m3a is not None
    assert vehicle_physics(m3a).station_plan_decel_ms2 == pytest.approx(0.5)
    c323 = resolve_vehicle_package("Class323")
    assert vehicle_physics(c323).station_plan_decel_ms2 is None
    assert vehicle_physics(None).station_plan_decel_ms2 is None
    assert vehicle_physics({"physics": {"station_plan_decel_ms2": 9.0}}).station_plan_decel_ms2 is None


def _first_start_m(plan_decel: float | None) -> float:
    plan = plan_station_service_brake(
        speed_mph=30.0,
        station_distance_m=600.0,
        predict_decel=_learned_035,
        plan_decel_ms2=plan_decel,
    )
    assert plan is not None
    return min(s.dist_start for s in plan.steps)


def test_plan_decel_override_starts_braking_later_203040z() -> None:
    """Con 0,5 en vez de ~0,35 el plan arranca más tarde (menos metros de frenada)."""
    soft = _first_start_m(None)
    firm = _first_start_m(0.5)
    assert firm > soft + 20.0  # más metros de margen antes de empezar a frenar
    plan = plan_station_service_brake(
        speed_mph=30.0, station_distance_m=600.0, predict_decel=_learned_035, plan_decel_ms2=0.5
    )
    assert plan is not None
    phases = [s.decel_ms2 for s in plan.steps]
    assert phases == [pytest.approx(0.5)] * len(UK_SERVICE_PHASES)
