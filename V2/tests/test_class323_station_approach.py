"""Class 323 (cabina B): aproximación a andén sin ping-pong APPLY/RELEASE ni esperas de aire.

Fixture: ``20261023T211407Z``, 476-502 s (Wylde Green). En esa sesión el agente alternaba
``APPLY B1`` / ``RELEASE «Objetivo alcanzado»`` cada tick (26 pares) y esperaba presión de cilindro
(104 ticks ``air_fill`` / ``air_recharge``); el tren se quedó a 63 m del tablón.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from replay_helpers import tick_to_snap  # tests/_path: scripts/replay_jsonl
from tsw6v2.brake_air import BrakeAirTracker
from tsw6v2.brake_air_profile import BrakeAirProfile
from tsw6v2.command import BrakeReleaseState
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState
from tsw6v2.vehicle_package import (
    resolve_brake_air_profile,
    resolve_vehicle_package,
    vehicle_physics,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "class323_station_approach_20261023.json"
_B_CAB = "RVM_BCC_WRM_Class323_DMS_B_C"


def _replay() -> list[tuple[str | None, str, int | None]]:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    keys = data["keys"]
    ticks = [dict(zip(keys, row)) for row in data["rows"]]
    pkg = resolve_vehicle_package(_B_CAB)
    limit_state, release_state, learner = LimitBrakeState(), BrakeReleaseState(), LearnerProfile()
    learner.apply_vehicle_brake_profile(pkg)
    out = []
    logging.disable(logging.CRITICAL)
    try:
        for t in ticks:
            d = evaluate_p1_tick(
                limit_state,
                release_state,
                tick_to_snap(t),
                learner=learner,
                station_distance_m=t["stn_dist_m"] if (t["stn_dist_m"] or 0) > 0 else None,
                station_fsm=t["stn_fsm"],
            )
            c = d.command
            out.append((c.kind if c else None, d.reason, c.target_notch if c else None))
    finally:
        logging.disable(logging.NOTSET)
    return out


def test_323_cabina_b_resuelve_el_paquete() -> None:
    """La cabina B no resolvía (el JSON solo declaraba la A): sin física ni perfil de aire."""
    for veh in ("RVM_BCC_WRM_Class323_DMS_A_C", _B_CAB):
        pkg = resolve_vehicle_package(veh)
        assert pkg is not None and pkg["vehicle_id"] == "class_323"


def test_323_no_espera_aire_ni_recarga() -> None:
    profile = resolve_brake_air_profile(resolve_vehicle_package(_B_CAB))
    assert profile.gate_apply is False
    air = BrakeAirTracker()
    air.set_profile(profile)
    air.observe(3, 2.5, now=0.0)
    air.observe(4, 2.4, now=0.1)  # soltó con el cilindro aún cargado
    assert air.inhibit_reapply(2.4, now=0.2) is False
    assert air.air_ready(1.0, lever=3) is True  # sin presión todavía: no bloquea


def test_gate_apply_por_defecto_sigue_activo() -> None:
    """Sin el flag (otros vehículos, p. ej. mercancías) el bloqueo por aire se conserva."""
    assert BrakeAirProfile.uk_emu().gate_apply is True
    air = BrakeAirTracker()
    air.observe(3, 2.5, now=0.0)
    air.observe(4, 2.4, now=0.1)
    assert air.inhibit_reapply(2.4, now=0.2) is True


def test_323_b1_medido_es_mayor_que_la_constante_antigua() -> None:
    """B1 real 0,57-0,69 m/s² (paradas 45 y 63 m cortas con 0,35)."""
    phys = vehicle_physics(resolve_vehicle_package(_B_CAB))
    b1 = phys.max_decel_ms2 * phys.service_decel_frac[3]
    b2 = phys.max_decel_ms2 * phys.service_decel_frac[2]
    b3 = phys.max_decel_ms2 * phys.service_decel_frac[1]
    assert 0.5 <= b1 <= 0.6
    assert b1 < b2 < b3


def test_aproximacion_a_anden_sin_ping_pong_ni_espera_de_aire() -> None:
    seq = _replay()
    pares = [
        i
        for i, (a, b) in enumerate(zip(seq, seq[1:]))
        if a[0] == "APPLY" and b[0] == "RELEASE"
    ]
    assert pares == [], f"APPLY→RELEASE en ticks consecutivos: {pares[:5]}"
    assert not any(r in ("air_fill", "air_recharge") for _, r, _ in seq)
