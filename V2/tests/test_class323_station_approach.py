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
from tsw6v2.physics import get_active_physics, set_active_physics
from tsw6v2.vehicle_package import (
    resolve_brake_air_profile,
    resolve_vehicle_package,
    vehicle_physics,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_FIXTURE = _FIXTURES / "class323_station_approach_20261023.json"
_FIXTURE_EARLY = _FIXTURES / "class323_early_brake_20261023.json"
_B_CAB = "RVM_BCC_WRM_Class323_DMS_B_C"
# Velocidad y FSM de cada tick de la última ``_replay`` (los tests de abajo los cruzan con ``seq``).
speeds: list[float] = []
fsms: list[str | None] = []


def _replay(fixture: Path = _FIXTURE) -> list[tuple[str | None, str, int | None]]:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    keys = data["keys"]
    ticks = [dict(zip(keys, row)) for row in data["rows"]]
    pkg = resolve_vehicle_package(_B_CAB)
    limit_state, release_state, learner = LimitBrakeState(), BrakeReleaseState(), LearnerProfile()
    learner.apply_vehicle_brake_profile(pkg)
    out: list[tuple[str | None, str, int | None]] = []
    speeds.clear()
    fsms.clear()
    logging.disable(logging.CRITICAL)
    prev_physics = get_active_physics()
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
            speeds.append(t["spd_mph"])
            fsms.append(t["stn_fsm"])
    finally:
        logging.disable(logging.NOTSET)
        set_active_physics(prev_physics)  # ``evaluate_p1_tick`` lo fija: no contaminar otros tests
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


def test_plan_usa_la_decel_de_b1_del_vehiculo() -> None:
    """``resolve_phase_decel`` ignoraba ``physics.service_decel_frac`` (tabla fija 0,33)."""
    from tsw6v2.plan import UK_SERVICE_PHASES, resolve_phase_decel

    phys = vehicle_physics(resolve_vehicle_package(_B_CAB))
    b1 = next(p for p in UK_SERVICE_PHASES if p.handle_notch == 3)
    prev = get_active_physics()
    set_active_physics(phys)
    try:
        decel, learned = resolve_phase_decel(b1, 30.0, 0.0, phys.max_decel_ms2)
    finally:
        set_active_physics(prev)
    assert learned is False
    assert abs(decel - phys.max_decel_ms2 * phys.service_decel_frac[3]) < 1e-6
    assert decel > 0.5  # antes 0,353


def test_plan_de_estacion_no_empieza_a_560_m_a_35_mph_en_bajada() -> None:
    """20261023T214704Z: B1 a 560 m con 35 mph y −1 % → parada a 285 m del tablón."""
    from tsw6v2.station_brake import evaluate_station_brake

    phys = vehicle_physics(resolve_vehicle_package(_B_CAB))
    prev = get_active_physics()
    set_active_physics(phys)
    try:
        for dist in (560.0, 500.0, 450.0, 400.0):
            r = evaluate_station_brake(
                speed_mph=35.0,
                station_distance_m=dist,
                gradient_pct=-1.0,
                base_decel=phys.max_decel_ms2,
                allow_watch=True,
                plan_decel_ms2=phys.station_plan_decel_ms2,
            )
            assert r is None or not r.apply_now, f"frena ya a {dist} m"
    finally:
        set_active_physics(prev)


def test_freno_de_estacion_se_suelta_si_el_plan_ya_no_lo_pide() -> None:
    """Con B1 puesto y el plan sin pedir freno se suelta (antes se retenía hasta parar)."""
    seq = _replay(_FIXTURE_EARLY)
    release_speeds = [v for (kind, _, _), v in zip(seq, speeds) if kind == "RELEASE"]
    assert release_speeds, "nunca soltó"
    assert release_speeds[0] >= 20.0, f"soltó tarde, a {release_speeds[0]} mph"


def test_parado_en_anden_no_suelta_por_el_cartel_ni_alterna() -> None:
    """APPLY de puertas (bucle) ↔ RELEASE de ``evaluate_p1_tick`` cada tick estando parado."""
    seq = _replay(_FIXTURE_EARLY)
    stopped = [kind for (kind, _, _), f in zip(seq, fsms) if f == "STOPPED"]
    assert stopped, "el fixture debe tener ticks STOPPED"
    assert "RELEASE" not in stopped


def test_propiedad_del_freno_de_estacion_caduca_tras_20_ticks_sin_plan() -> None:
    """Con la parada propia en curso y el plan sin pedir freno: retiene un tiempo y luego suelta.

    20261023T214704Z: sin esta caducidad el freno se retenía hasta parar (285 m corto).
    """
    from tsw6v2.constants import STATION_PLAN_LOST_RELEASE_TICKS

    data = json.loads(_FIXTURE_EARLY.read_text(encoding="utf-8"))
    keys = data["keys"]
    ticks = [dict(zip(keys, row)) for row in data["rows"]]
    start = next(i for i, t in enumerate(ticks) if t["lever"] == 3 and t["spd_mph"] < 27)
    limit_state, release_state, learner = LimitBrakeState(), BrakeReleaseState(), LearnerProfile()
    learner.apply_vehicle_brake_profile(resolve_vehicle_package(_B_CAB))
    kinds: list[str | None] = []
    owned: list[bool] = []
    prev = get_active_physics()
    logging.disable(logging.CRITICAL)
    try:
        for n, t in enumerate(ticks[start : start + STATION_PLAN_LOST_RELEASE_TICKS + 80]):
            if n == 0:
                limit_state.station_stop_m = float(t["stn_dist_m"]) + 10.0  # APPLY de estación previo
            d = evaluate_p1_tick(
                limit_state,
                release_state,
                tick_to_snap(t),
                learner=learner,
                station_distance_m=t["stn_dist_m"],
                station_fsm=t["stn_fsm"],
            )
            kinds.append(d.command.kind if d.command else None)
            owned.append(limit_state.station_stop_m is not None)
    finally:
        logging.disable(logging.NOTSET)
        set_active_physics(prev)
    k = STATION_PLAN_LOST_RELEASE_TICKS
    assert all(owned[: k - 1]), "debe retener mientras dura la histéresis"
    assert "RELEASE" not in kinds[: k - 1]
    assert not owned[k - 1], "la propiedad debe caducar a los 20 ticks sin plan"
    assert "RELEASE" in kinds[k - 1 :], "tras caducar debe poder soltar"
