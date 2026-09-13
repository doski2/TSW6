"""Planning sidecar y dead-reckoning."""

from __future__ import annotations

from tsw6v2.planning_feed import planning_distance_accept, tick_station_distance_m


def test_tick_station_distance_m_advances():
    assert tick_station_distance_m(1000.0, 60.0, 1.0) == 1000.0 - 60.0 * 0.44704


def test_tick_station_distance_m_skips_when_stopped():
    assert tick_station_distance_m(500.0, 0.0, 1.0) == 500.0


def test_planning_distance_rejects_jump_after_platform():
    assert not planning_distance_accept(52.0, 2211.0, 36.8)


def test_planning_distance_rejects_jump_at_creep_after_platform():
    """Sesión 20260911T152306Z: dwell creep @ 3.4 mph no debe aceptar 0→2012 m."""
    assert not planning_distance_accept(0.0, 2012.0, 3.4)


def test_planning_distance_accepts_normal_update():
    assert planning_distance_accept(500.0, 480.0, 60.0)
    assert planning_distance_accept(None, 900.0, 0.0)


def test_planning_distance_rejects_http_regression_while_approaching():
    """145832Z: HTTP ~235 m con v×dt ~230 m — no resetear hacia arriba."""
    assert not planning_distance_accept(230.7, 235.4, 23.0)
    assert planning_distance_accept(230.7, 235.4, 2.0)  # parado: aceptar


def test_planning_distance_accepts_large_jump_after_save_load():
    """Tras cargar partida: salto legítimo a otra posición en ruta."""
    assert planning_distance_accept(235.0, 1800.0, 45.0)


def test_planning_distance_rejects_large_yoyo_at_speed():
    """Sesión 211414Z: yo-yo TrackData hacia atrás o adelante en marcha."""
    assert not planning_distance_accept(22184.0, 120.8, 45.0)
    assert not planning_distance_accept(24000.0, 2000.0, 30.0)
    assert not planning_distance_accept(2000.0, 24000.0, 45.0)
    # Tras invalidate (prev None) o parado: aceptar primera lectura.
    assert planning_distance_accept(None, 120.8, 45.0)
    assert planning_distance_accept(None, 24000.0, 45.0)
    assert planning_distance_accept(22184.0, 120.8, 2.0)
