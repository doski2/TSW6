"""Planning sidecar y dead-reckoning."""

from __future__ import annotations

import time

import pytest

from tsw6v2.planning_feed import (
    PlanningFeed,
    PlanningSnapshot,
    advance_station_distance_tick,
    apply_station_distance_reading,
    planning_distance_accept,
    tick_station_distance_m,
)
from tsw6v2.probe_seq import probe_seq_dt_s


def test_tick_station_distance_m_advances():
    assert tick_station_distance_m(1000.0, 60.0, 1.0) == 1000.0 - 60.0 * 0.44704


def test_tick_station_distance_m_skips_when_stopped():
    assert tick_station_distance_m(500.0, 0.0, 1.0) == 500.0


def test_probe_seq_dt_s_ignores_menu_pause():
    assert probe_seq_dt_s(100, 100) == 0.0
    assert probe_seq_dt_s(100, 103) == 0.15


def test_planning_feed_skips_dead_reckoning_when_probe_seq_frozen(tmp_path):
    path = tmp_path / "Planning.txt"
    path.write_text("station_dist_m=1000.0\n", encoding="utf-8")
    feed = PlanningFeed(path=path)
    feed.update(60.0, probe_seq=500)
    # seq sin cambiar > PROBE_FROZEN_S = juego en pausa: no avanza aunque pase el reloj
    feed._last_seq_change_t = time.monotonic() - 1.0
    feed._last_tick_t = time.monotonic() - 0.1
    snap = feed.update(60.0, probe_seq=500)
    assert snap.station_distance_m == 1000.0


def test_resolve_station_tick_dt_uses_wall_clock_with_fps_capped_probe():
    """Límite 50 fps: el probe repite seq (16,7 Hz) y la distancia no debe quedarse plana."""
    from tsw6v2.planning_feed import resolve_station_tick_dt

    kw = dict(last_wall_t=10.0, now=10.05)
    assert resolve_station_tick_dt(
        last_probe_seq=7, probe_seq=7, last_seq_change_t=10.0, **kw
    ) == pytest.approx(0.05)
    # un paso de seq tras 60 ms reales: dt = 0,06 (no los 0,05 de PROBE_SEQ_MS)
    assert resolve_station_tick_dt(
        last_probe_seq=7, probe_seq=8, last_wall_t=10.0, now=10.06
    ) == pytest.approx(0.06)
    # pausa: seq sin cambiar > PROBE_FROZEN_S
    assert resolve_station_tick_dt(
        last_probe_seq=7, probe_seq=7, last_seq_change_t=9.0, **kw
    ) == 0.0
    # retroceso de seq (carga)
    assert resolve_station_tick_dt(last_probe_seq=9, probe_seq=3, **kw) == 0.0
    # hueco de reloj largo con pocos pasos de seq: acotado por el juego
    assert resolve_station_tick_dt(
        last_probe_seq=7, probe_seq=8, last_wall_t=10.0, now=12.0
    ) == pytest.approx(0.1)
    # sin seq: reloj de pared
    assert resolve_station_tick_dt(last_probe_seq=None, probe_seq=None, **kw) == pytest.approx(0.05)


def test_planning_distance_rejects_jump_after_platform():
    assert not planning_distance_accept(52.0, 2211.0, 36.8)


def test_planning_distance_rejects_jump_at_creep_after_platform():
    """Sesión 20260911T152306Z: dwell creep @ 3.4 mph no debe aceptar 0→2012 m."""
    assert not planning_distance_accept(0.0, 2012.0, 3.4)


def test_planning_distance_accepts_next_stop_after_departure_session_225330():
    """Tras pasar andén @ marcha: aceptar distancia HTTP a la siguiente parada."""
    assert planning_distance_accept(0.0, 3200.0, 15.0)
    assert planning_distance_accept(0.5, 2800.0, 25.0)


def test_planning_distance_accepts_normal_update():
    assert planning_distance_accept(500.0, 480.0, 60.0)
    assert planning_distance_accept(None, 900.0, 0.0)


def test_planning_distance_rejects_http_regression_while_approaching():
    """145832Z: HTTP ~235 m con v×dt ~230 m — no resetear hacia arriba."""
    assert not planning_distance_accept(230.7, 235.4, 23.0)
    assert planning_distance_accept(230.7, 235.4, 2.0)  # parado: aceptar


def test_planning_distance_rejects_big_rise_when_slow_in_approach_session_20261012_155138():
    """155138Z: HTTP salta de 101 a 234 m a ~1 mph en aproximación; no debe resetear."""
    assert not planning_distance_accept(101.0, 234.6, 1.0)
    # Ajuste pequeño parado: sigue aceptado (test de arriba).
    assert planning_distance_accept(230.7, 235.4, 2.0)


def test_planning_distance_accepts_large_jump_after_save_load():
    """Tras cargar partida: salto legítimo a otra posición en ruta."""
    assert planning_distance_accept(235.0, 1800.0, 45.0)


def test_planning_distance_rejects_next_stop_jump_in_final_approach():
    """Sesión 20260917T211417Z: HTTP salta a la siguiente parada @ 91 m en marcha."""
    assert not planning_distance_accept(90.9, 1229.0, 21.5)
    assert not planning_distance_accept(120.0, 900.0, 30.0)
    # Borde superior: save/load y v×dt consolidado quedan fuera de la zona.
    assert planning_distance_accept(201.0, 1800.0, 45.0)


def test_apply_rejects_served_stop_name_session_215036():
    """215036Z: no aceptar Five Ways fantasma tras pasar el andén."""
    snap = PlanningSnapshot(
        station_distance_m=1699.0,
        station_name="University, andén 2",
    )
    assert not apply_station_distance_reading(
        snap,
        1200.0,
        47.6,
        new_name="Five Ways",
        exclude_bases={"five ways"},
    )
    assert snap.station_distance_m == 1699.0
    assert snap.station_name == "University, andén 2"


def test_planning_distance_rejects_large_yoyo_at_speed():
    """Sesión 211414Z: yo-yo TrackData hacia atrás o adelante en marcha."""
    assert not planning_distance_accept(22184.0, 120.8, 45.0)
    assert not planning_distance_accept(24000.0, 2000.0, 30.0)
    assert not planning_distance_accept(2000.0, 24000.0, 45.0)
    # Tras invalidate (prev None) o parado: aceptar primera lectura.
    assert planning_distance_accept(None, 120.8, 45.0)
    assert planning_distance_accept(None, 24000.0, 45.0)
    assert planning_distance_accept(22184.0, 120.8, 2.0)


def test_resync_after_two_rejects_in_final_approach_session_214350Z():
    """Estimación 148 m con lectura real 198.7 m: la 1.ª se rechaza, la 2.ª re-sincroniza."""
    snap = PlanningSnapshot(station_distance_m=148.0)
    assert apply_station_distance_reading(snap, 198.7, 29.5) is False
    assert snap.planning_reject_streak == 1
    assert apply_station_distance_reading(snap, 198.7, 29.5) is True
    assert snap.station_distance_m == 198.7
    assert snap.planning_reject_streak == 0



def test_stall_freezes_estimate_above_marker_session_220924Z():
    """Feed obsoleto a 157.6 m: no se resta distancia hasta 0 m."""
    snap = PlanningSnapshot(station_distance_m=157.6)
    for _ in range(50):
        advance_station_distance_tick(snap, 11.0, 0.2, freeze=True)
    assert snap.station_distance_m == 157.6


def test_freeze_still_reaches_marker_passed_zero():
    """Cerca del andén (<= marker) sigue el dead-reckoning normal."""
    snap = PlanningSnapshot(station_distance_m=3.0)
    advance_station_distance_tick(snap, 11.0, 1.0, freeze=True)
    assert snap.station_distance_m == 0.0

def test_station_reading_stale_threshold_allows_poll_cycle():
    """Ciclo ~4 s, ~8 s con un poll fallido (103432Z): no congelar antes de 13 s sin lectura."""
    import time

    from tsw6v2.planning_poller import PLANNING_STALE_AFTER_S, StationPlanning

    sp = StationPlanning(http_enabled=False)
    assert PLANNING_STALE_AFTER_S == 13.0
    sp._last_reading_t = time.monotonic() - 8.3
    assert sp._reading_stale() is False
    sp._last_reading_t = time.monotonic() - 14.0
    assert sp._reading_stale() is True


def test_planning_reject_last_records_slow_rise_reason_session_20261015() -> None:
    """20261015T123018Z: HTTP 200 m tras integrar a 64 m; el motivo queda en el snapshot."""
    from tsw6v2.planning_feed import PlanningSnapshot, apply_station_distance_reading

    snap = PlanningSnapshot(station_distance_m=64.0)
    assert not apply_station_distance_reading(snap, 200.0, 14.0)
    assert snap.planning_reject_last == "slow_rise@200"
    assert apply_station_distance_reading(snap, 60.0, 14.0)
    assert snap.planning_reject_last is None
