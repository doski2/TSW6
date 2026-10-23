"""``vehicle_adapter``: mismas respuestas que las ramas ``uses_mc_analog_ipc`` que sustituye."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from tsw6v2.constants import NEUTRAL_NOTCH
from tsw6v2.vehicle_adapter import McAnalogAdapter, NotchAdapter, adapter_for_package
from tsw6v2.vehicle_package import (
    clear_package_cache,
    combined_notch_to_ipc_value,
    profile_neutral_fraction,
    resolve_vehicle_package,
)

M3A = "RVM_NYH_MNR_M3a-A_C"
C323 = "RVM_BCC_WRM_Class323_DMS_A_C"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    clear_package_cache()


class _Snap(SimpleNamespace):
    def combined_handle_notch(self) -> Optional[int]:
        return getattr(self, "lever_notch", None)


def _snap(**kw: Any) -> Any:
    base = dict(lever_notch=None, power=None, power_neg=False, mc_input=None, train_brake=None)
    base.update(kw)
    return _Snap(**base)


def test_seleccion_de_adaptador() -> None:
    assert isinstance(adapter_for_package(None), NotchAdapter)
    assert isinstance(adapter_for_package(resolve_vehicle_package(C323)), NotchAdapter)
    assert isinstance(adapter_for_package(resolve_vehicle_package(M3A)), McAnalogAdapter)


def test_banderas_por_layout() -> None:
    assert not adapter_for_package(resolve_vehicle_package(C323)).analog_lever
    assert not adapter_for_package(resolve_vehicle_package(C323)).single_step
    mc = adapter_for_package(resolve_vehicle_package(M3A))
    assert mc.analog_lever and mc.single_step


def test_muescas_throttle_y_station_lever() -> None:
    a = NotchAdapter()
    assert a.throttle_notch(_snap(lever_notch=NEUTRAL_NOTCH + 2)) == 2
    assert a.throttle_notch(_snap(lever_notch=2)) == 0
    assert a.throttle_notch(_snap()) == 0
    assert a.station_lever(_snap(), 2) == 2
    assert a.station_lever(_snap(), None) == NEUTRAL_NOTCH


def test_mc_ignora_la_muesca_y_usa_mc_input() -> None:
    pkg = resolve_vehicle_package(M3A)
    a = adapter_for_package(pkg)
    neu = profile_neutral_fraction(pkg)
    assert neu is not None
    # Muesca UK dice tracción, pero la palanca analógica está en el neutro.
    assert a.throttle_notch(_snap(lever_notch=NEUTRAL_NOTCH + 3, mc_input=neu)) == 0
    assert a.station_lever(_snap(mc_input=neu), 1) == NEUTRAL_NOTCH
    assert a.throttle_notch(_snap(mc_input=min(1.0, neu + 0.2))) == 1
    assert a.station_lever(_snap(mc_input=min(1.0, neu + 0.2)), 1) == NEUTRAL_NOTCH + 1


def test_wire_fraction() -> None:
    assert NotchAdapter().wire_fraction(NEUTRAL_NOTCH) is None
    pkg = resolve_vehicle_package(M3A)
    a = adapter_for_package(pkg)
    assert a.wire_fraction(NEUTRAL_NOTCH) == pytest.approx(combined_notch_to_ipc_value(NEUTRAL_NOTCH, pkg))
    assert a.wire_fraction(NEUTRAL_NOTCH) == pytest.approx(profile_neutral_fraction(pkg))


def test_lever_says_brake() -> None:
    n = NotchAdapter()
    assert n.lever_says_brake(None, 3) is True
    assert n.lever_says_brake(None, NEUTRAL_NOTCH) is False
    pkg = resolve_vehicle_package(M3A)
    a = adapter_for_package(pkg)
    neu = profile_neutral_fraction(pkg)
    assert neu is not None
    assert a.lever_says_brake(_snap(mc_input=neu - 0.2), None) is True
    assert a.lever_says_brake(_snap(mc_input=neu), None) is False
    assert a.lever_says_brake(None, None) is None


def test_fraction_feedback() -> None:
    assert NotchAdapter().fraction_feedback(_snap(train_brake=0.4)) == pytest.approx(0.4)
    assert NotchAdapter().fraction_feedback(_snap()) is None
    pkg = resolve_vehicle_package(M3A)
    assert adapter_for_package(pkg).fraction_feedback(_snap(mc_input=0.64)) == pytest.approx(0.64)


_STOP: dict[str, Any] = dict(speed_mph=30.0, distance_m=300.0, gradient_pct=0.0, decel_table=None)
_LIMIT: dict[str, Any] = dict(speed_mph=60.0, target_mph=35.0, distance_m=400.0, gradient_pct=0.0, decel_table=None)


def test_fracciones_notch_adapter_no_aplica() -> None:
    ad = NotchAdapter(resolve_vehicle_package(C323))
    assert ad.station_stop_fraction(**_STOP) is None
    assert ad.limit_fraction(**_LIMIT) is None
    assert ad.roll_until_click(
        speed_mph=10.0, distance_m=50.0, gradient_pct=0.0, click_decel_ms2=None, running=False, latch=None
    ) is False


def test_fracciones_mc_adapter_delega_en_el_paquete() -> None:
    from tsw6v2.vehicle_package import mc_limit_brake_fraction, mc_stop_brake_fraction

    pkg = resolve_vehicle_package(M3A)
    ad = adapter_for_package(pkg)
    assert ad.station_stop_fraction(**_STOP) == mc_stop_brake_fraction(pkg, **_STOP)
    assert ad.limit_fraction(**_LIMIT) == mc_limit_brake_fraction(pkg, **_LIMIT)


def test_bleed_notch_adapter_siempre_falso() -> None:
    ad = NotchAdapter(resolve_vehicle_package(C323))
    snap = _snap(mc_input=0.64)
    assert not ad.bleed_b1_latched(snap)
    assert not ad.bleed_neutral_reached(snap)
    assert not ad.bleed_should_reapply_b1(snap)


def test_bleed_mc_adapter_delega_en_el_paquete() -> None:
    from tsw6v2.vehicle_package import (
        mc_platform_bleed_b1_latched,
        mc_platform_bleed_neutral_ipc,
        mc_platform_bleed_should_reapply_b1,
    )

    pkg = resolve_vehicle_package(M3A)
    ad = adapter_for_package(pkg)
    for frac in (0.55, 0.64, 0.72):
        snap = _snap(mc_input=frac)
        assert ad.bleed_b1_latched(snap) == mc_platform_bleed_b1_latched(snap, pkg)
        assert ad.bleed_neutral_reached(snap) == mc_platform_bleed_neutral_ipc(snap, pkg)
        assert ad.bleed_should_reapply_b1(snap) == mc_platform_bleed_should_reapply_b1(snap, pkg)
