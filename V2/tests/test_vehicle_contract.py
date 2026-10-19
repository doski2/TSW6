"""Contrato común: todo paquete de ``data/vehicles`` debe cumplir estas pruebas.

Un vehículo nuevo se da por soportado solo si pasa este conjunto (ANALISIS §2.4 paso 4).
Las pruebas se parametrizan con cada JSON del directorio; no nombran ningún vehículo.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from tsw6v2.brake_air_profile import MODEL_MASTER_CONTROLLER, MODEL_UK_EMU
from tsw6v2.command import BrakeCommand
from tsw6v2.constants import B1_NOTCH, NEUTRAL_NOTCH
from tsw6v2.vehicle_package import (
    apply_vehicle_brake_actuator,
    clear_package_cache,
    combined_notch_to_ipc_value,
    default_vehicles_dir,
    resolve_brake_air_profile,
    resolve_vehicle_package,
    uses_mc_analog_ipc,
    vehicle_physics,
)

_PACKAGE_SCHEMA = "tsw6-vehicle-package/1"
_KNOWN_LAYOUTS = frozenset({"combined", "master_controller"})
_KNOWN_FLEETS = frozenset({"uk", "ny"})
_PATHS = sorted(default_vehicles_dir().glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    clear_package_cache()


@pytest.fixture(params=_PATHS, ids=[p.stem for p in _PATHS])
def package(request: pytest.FixtureRequest) -> dict[str, Any]:
    return _load(request.param)


def test_hay_paquetes() -> None:
    assert _PATHS, "data/vehicles sin paquetes"


def test_vehicle_ids_unicos_y_coherentes_con_el_fichero() -> None:
    ids = [_load(p)["vehicle_id"] for p in _PATHS]
    assert len(ids) == len(set(ids))
    classes = [_load(p)["match"]["vehicle_class"] for p in _PATHS]
    assert len(classes) == len(set(classes))


def test_cabecera_del_paquete(package: dict[str, Any]) -> None:
    assert package["schema"] == _PACKAGE_SCHEMA
    assert str(package["vehicle_id"]).strip()
    assert str(package["match"]["vehicle_class"]).strip()
    assert package["layout"] in _KNOWN_LAYOUTS
    assert package["fleet"] in _KNOWN_FLEETS
    assert isinstance(package["controls"], dict) and package["controls"]


def test_se_resuelve_por_su_clase(package: dict[str, Any]) -> None:
    klass = package["match"]["vehicle_class"]
    resolved = resolve_vehicle_package(f"{klass}_C_2147480000")
    assert resolved is not None
    assert resolved["vehicle_id"] == package["vehicle_id"]


def test_perfil_de_aire_conocido(package: dict[str, Any]) -> None:
    profile = resolve_brake_air_profile(package)
    expected = MODEL_MASTER_CONTROLLER if uses_mc_analog_ipc(package) else MODEL_UK_EMU
    assert profile.model == expected


def test_fisica_valida(package: dict[str, Any]) -> None:
    phys = vehicle_physics(package)
    assert 0.2 <= phys.max_decel_ms2 <= 1.5
    assert 0.0 < phys.coast_decel_ms2 < phys.max_decel_ms2
    assert phys.safety_margin >= 1.0
    assert phys.brake_transition_s > 0.0
    if phys.station_plan_decel_ms2 is not None:
        assert phys.station_plan_decel_ms2 <= phys.max_decel_ms2
    frac = phys.service_decel_frac
    assert all(h in frac for h in (1, 2, 3))
    # B3 (muesca 1) es el freno de servicio más fuerte; B1 (muesca 3) el más suave.
    assert 0.0 < frac[3] <= frac[2] <= frac[1] <= 1.0


def test_valor_ipc_por_muesca_finito_y_monotono(package: dict[str, Any]) -> None:
    values = [combined_notch_to_ipc_value(n, package) for n in range(1, NEUTRAL_NOTCH + 1)]
    assert all(math.isfinite(v) for v in values)
    assert values == sorted(values), "más cerca del neutro no puede dar más freno"


@pytest.mark.parametrize("phase,notch", [("B1", B1_NOTCH), ("B2", 2), ("B3", 1)])
def test_apply_en_layout_mc_lleva_fraccion_valida(
    package: dict[str, Any], phase: str, notch: int
) -> None:
    if not uses_mc_analog_ipc(package):
        pytest.skip("layout con muescas: no usa target_fraction")
    cmd = apply_vehicle_brake_actuator(
        BrakeCommand(kind="APPLY", target_notch=notch, phase=phase), package
    )
    neutral = apply_vehicle_brake_actuator(
        BrakeCommand(kind="RELEASE", target_notch=NEUTRAL_NOTCH), package
    )
    assert cmd.target_fraction is not None and neutral.target_fraction is not None
    assert 0.0 <= cmd.target_fraction <= 1.0
    assert cmd.target_fraction < neutral.target_fraction, "freno aplicado debe quedar bajo el neutro"


def test_apply_en_layout_muescas_no_inventa_fraccion(package: dict[str, Any]) -> None:
    if uses_mc_analog_ipc(package):
        pytest.skip("layout MC")
    cmd = BrakeCommand(kind="APPLY", target_notch=B1_NOTCH, phase="B1")
    assert apply_vehicle_brake_actuator(cmd, package).target_fraction is None
