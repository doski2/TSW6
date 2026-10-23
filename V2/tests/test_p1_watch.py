"""Registro de los tres candidatos (cartel / andén / semáforo) y vigilante de inanición (§7.11)."""

from __future__ import annotations

import _path  # noqa: F401

import json
import logging
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from tsw6v2.constants import P1_STARVED_WARN_TICKS
from tsw6v2.decision import _candidates, _starved
from tsw6v2.decision_types import LimitBrakeDecision
from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.target import BrakeTargetResult
from tsw6v2.testdata import write_getdata_line
from tsw6v2.trace import JsonlTrace, session_meta


def _target(kind: str, *, apply_now: bool, ds: float = 40.0, dist: float = 300.0) -> BrakeTargetResult:
    return BrakeTargetResult(
        target_kind=kind,  # type: ignore[arg-type]
        distance_m=dist,
        target_speed_mph=0.0,
        handle_notch=3,
        phase="B1",
        dist_start=ds,
        apply_now=apply_now,
        detail="t",
    )


def test_candidatos_registran_los_tres_objetivos_ganen_o_no() -> None:
    cands = _candidates(
        _target("SPEED_LIMIT", apply_now=False, ds=300.0, dist=900.0),
        _target("STATION", apply_now=True, ds=-20.0, dist=700.0),
        _target("SIGNAL", apply_now=False, ds=90.0, dist=500.0),
    )
    assert set(cands) == {"lim", "stn", "sig"}
    assert cands["stn"] == {"k": "STATION", "apply": True, "ds": -20.0, "d": 700.0, "h": 3}
    assert cands["lim"]["apply"] is False


def test_candidatos_omite_los_que_no_hay() -> None:
    assert _candidates(None, None, None) == {}
    assert set(_candidates(None, _target("STATION", apply_now=False), None)) == {"stn"}


def test_starved_cuando_un_candidato_pide_frenar_y_no_hay_mando() -> None:
    station = _target("STATION", apply_now=True)
    limit = _target("SPEED_LIMIT", apply_now=False)
    cands = _candidates(limit, station, None)
    idle = LimitBrakeDecision.idle(reason="command_none")
    assert _starved(cands, limit, idle) is True  # el cartel ganó el pick sin frenar (§7.6)
    assert _starved(cands, station, idle) is False  # el que pide frenar es el elegido
    assert _starved({}, None, idle) is False  # nadie pide frenar
    from tsw6v2.command import BrakeCommand

    with_cmd = LimitBrakeDecision(BrakeCommand(kind="APPLY", target_notch=3, phase="B1", reason="x"))
    assert _starved(cands, limit, with_cmd) is False  # hay mando


def test_evaluate_p1_tick_adjunta_candidatos() -> None:
    """Sobre el tramo real de Gravelly Hill (§7.6): el andén pide frenar y el cartel aún no."""
    import logging as _logging
    from dataclasses import replace

    from replay_helpers import tick_to_snap
    from tsw6v2.command import BrakeReleaseState
    from tsw6v2.decision import evaluate_p1_tick
    from tsw6v2.limits import LimitBrakeState
    from tsw6v2.physics import get_active_physics, set_active_physics

    fixture = Path(__file__).parent / "fixtures" / "class323_station_before_limit_sign_20261023.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    keys = data["keys"]
    ticks = [dict(zip(keys, row)) for row in data["rows"]]
    limit_state, release_state = LimitBrakeState(), BrakeReleaseState()
    prev = get_active_physics()
    seen: Optional[dict] = None
    _logging.disable(_logging.CRITICAL)
    try:
        for t in ticks:
            d = evaluate_p1_tick(
                limit_state,
                release_state,
                replace(tick_to_snap(t), accel_ms2=t["accel_ms2"]),
                learner=None,
                station_distance_m=t["stn_dist_m"] if (t["stn_dist_m"] or 0) > 0 else None,
                station_fsm=t["stn_fsm"],
            )
            if d.candidates and "stn" in d.candidates and d.candidates["stn"]["apply"]:
                seen = d.candidates
                break
    finally:
        _logging.disable(_logging.NOTSET)
        set_active_physics(prev)
    assert seen is not None
    assert seen["stn"]["k"] == "STATION" and seen["lim"]["k"] == "SPEED_LIMIT"
    assert seen["lim"]["apply"] is False


def test_jsonl_trace_escribe_candidatos_y_starved(tmp_path: Path) -> None:
    path = tmp_path / "w.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    cands = {"stn": {"k": "STATION", "apply": True, "ds": -5.0, "d": 300.0, "h": 3}}
    trace.write_tick(AgentSnapshot(tick=1, p1_cands=cands, p1_starved_ticks=7), t_ms=10.0)
    trace.write_tick(AgentSnapshot(tick=2), t_ms=20.0)
    trace.close()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()][1:]
    assert rows[0]["p1_cands"] == cands
    assert rows[0]["p1_starved"] == 7
    assert rows[1]["p1_cands"] is None and rows[1]["p1_starved"] is None


def test_el_bucle_cuenta_ticks_sin_mando_y_avisa_una_vez(tmp_path: Path, caplog) -> None:
    gd = tmp_path / "GetData.txt"
    write_getdata_line(gd, seq=1, lever=4)
    loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
    starving = LimitBrakeDecision.idle(reason="command_none")
    starving.candidates = {"stn": {"k": "STATION", "apply": True, "ds": -5.0, "d": 300.0, "h": 3}}
    starving.starved = True
    counts: list[int] = []
    with caplog.at_level(logging.WARNING, logger="tsw6v2.loop"):
        with patch("tsw6v2.loop.evaluate_p1_tick", return_value=starving):
            for i in range(P1_STARVED_WARN_TICKS + 5):
                write_getdata_line(gd, seq=i + 2, lever=4)
                out = loop.step()
                counts.append(out.p1_starved_ticks)
    assert counts[:3] == [1, 2, 3]
    assert counts[P1_STARVED_WARN_TICKS - 1] == P1_STARVED_WARN_TICKS
    assert out.p1_cands == starving.candidates
    avisos = [r for r in caplog.records if "sin mando" in r.getMessage()]
    assert len(avisos) == 1, "debe avisar una sola vez por racha"
    # una decisión con mando reinicia la racha
    ok = LimitBrakeDecision.idle(reason="no_plan")
    with patch("tsw6v2.loop.evaluate_p1_tick", return_value=ok):
        write_getdata_line(gd, seq=999, lever=4)
        assert loop.step().p1_starved_ticks == 0


def test_linea_de_traza_y_resumen_marcan_la_inanicion(tmp_path: Path) -> None:
    from tsw6v2.session_report import summarize
    from tsw6v2.trace import format_investigate

    ok = AgentSnapshot(tick=1, speed_mph=30.0, p1_starved_ticks=P1_STARVED_WARN_TICKS - 1)
    bad = AgentSnapshot(tick=2, speed_mph=30.0, p1_starved_ticks=P1_STARVED_WARN_TICKS)
    assert "SIN_MANDO" not in format_investigate(ok)
    assert f"SIN_MANDO={P1_STARVED_WARN_TICKS}" in format_investigate(bad)

    path = tmp_path / "s.jsonl"
    trace = JsonlTrace(path, session_meta(mode="station", route="test"))
    for n in (0, 5, P1_STARVED_WARN_TICKS, P1_STARVED_WARN_TICKS + 3):
        trace.write_tick(AgentSnapshot(tick=n + 1, speed_mph=20.0, p1_starved_ticks=n), t_ms=float(n))
    trace.close()
    assert summarize(path)["p1_starved_ticks"] == 2


# ----------------------------------------------------------------------------- identificación del tren
def _record_vehicle(tmp_path: Path, vehicle: str) -> tuple[dict, list[dict]]:
    from tsw6v2.session_log import SessionRecorder

    path = tmp_path / f"{abs(hash(vehicle))}.jsonl"
    rec = SessionRecorder(path, trace_mode="station", route="test")
    for n in (1, 2):
        rec.record(AgentSnapshot(tick=n, seq=n, vehicle=vehicle, speed_mph=10.0))
    rec.finish(generate_html=False)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows[0], [r for r in rows if r.get("type") == "session_detect"]


def test_la_cabecera_lleva_la_hora_local(tmp_path: Path) -> None:
    header, _ = _record_vehicle(tmp_path, "RVM_BCC_WRM_Class323_DMS_B_C")
    assert header["ts"].endswith("+00:00")
    # ISO con desfase, p. ej. 2026-10-24T00:38:51+02:00
    assert len(header["ts_local"]) == 25 and header["ts_local"][-6] in "+-"


def test_el_log_dice_que_tren_es_y_con_que_paquete(tmp_path: Path) -> None:
    _, det = _record_vehicle(tmp_path, "RVM_BCC_WRM_Class323_DMS_B_C")
    assert len(det) == 1, "una sola fila aunque haya varios ticks"
    assert det[0]["vehicle"] == "RVM_BCC_WRM_Class323_DMS_B_C"
    assert det[0]["vehicle_package"] == "class_323" and det[0]["layout"] == "muescas"
    _, det = _record_vehicle(tmp_path, "RVM_NYH_MNR_M3a-B_C")
    assert det[0]["vehicle_package"] == "m3a_mnr" and det[0]["layout"] == "analogico"


def test_un_tren_sin_paquete_se_ve_en_el_log(tmp_path: Path) -> None:
    """La cabina B de la 323 corrió sin paquete y no se notó (ANALISIS §7.4)."""
    _, det = _record_vehicle(tmp_path, "RVM_XXX_Tren_Nuevo_A_C")
    assert det[0]["vehicle_package"] == "sin_paquete"


def test_el_informe_hereda_el_tren_y_el_paquete(tmp_path: Path) -> None:
    from tsw6v2.session_report import load_ticks

    path = tmp_path / "r.jsonl"
    from tsw6v2.session_log import SessionRecorder

    rec = SessionRecorder(path, trace_mode="station", route="test")
    rec.record(AgentSnapshot(tick=1, seq=1, vehicle="RVM_BCC_WRM_Class323_DMS_B_C", speed_mph=5.0))
    rec.finish(generate_html=False)
    session, _ = load_ticks(path)
    assert session is not None
    assert session["vehicle"] == "RVM_BCC_WRM_Class323_DMS_B_C"
    assert session["vehicle_package"] == "class_323" and session["layout"] == "muescas"


def test_log_info_describe_un_log_antiguo_y_uno_nuevo(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "log_info", Path(__file__).resolve().parents[1] / "scripts" / "log_info.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # antiguo: sin session_detect de vehículo (como los logs del 23-oct)
    old = tmp_path / "old.jsonl"
    old.write_text(
        json.dumps({"type": "session", "ts": "2026-10-23T22:38:51+00:00", "route": "cross-city", "git": "c5cf5b6"})
        + "\n"
        + json.dumps({"type": "tick", "t_ms": 1000.0, "vehicle": "RVM_BCC_WRM_Class323_DMS_B_C"})
        + "\n",
        encoding="utf-8",
    )
    text = "\n".join(module.describe(old))
    assert "RVM_BCC_WRM_Class323_DMS_B_C" in text and "class_323" in text and "muescas" in text
    assert "anterior al registro" in text and "inicio:" in text

    path = tmp_path / "n.jsonl"
    from tsw6v2.session_log import SessionRecorder

    rec = SessionRecorder(path, trace_mode="station", route="gct-mnr")
    rec.record(AgentSnapshot(tick=1, seq=1, vehicle="RVM_NYH_MNR_M3a-B_C", speed_mph=3.0))
    rec.finish(generate_html=False)
    text = "\n".join(module.describe(path))
    assert "m3a_mnr" in text and "analogico" in text and "anterior al registro" not in text
