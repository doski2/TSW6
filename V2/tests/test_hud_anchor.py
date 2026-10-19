"""Ancla de la distancia de parada al HUD (OCR): marco tablón, puertas y corrección acotada."""

from __future__ import annotations

import time

import pytest

from tsw6v2.hud_anchor import (
    MAX_CORRECTION_M,
    AnchorReading,
    HudAnchor,
    hud_ocr_control_enabled,
)
from tsw6v2.planning_poller import StationPlanning

MPH = 30.0


def _read(value: float, t: float) -> AnchorReading:
    return AnchorReading(value_m=value, t=t)


def _locked(offset: float = 100.0, est: float = 800.0) -> tuple[HudAnchor, float]:
    """Ancla ya en marco tablón: dos capturas coherentes con desfase ``offset``."""
    anchor = HudAnchor()
    assert anchor.apply(est, _read(est - offset, 10.0), now=10.0, speed_mph=MPH) is None
    out = anchor.apply(est, _read(est - offset, 10.5), now=10.5, speed_mph=MPH)
    assert out is not None and anchor.board_frame
    return anchor, out


def test_frame_switch_needs_two_consistent_captures() -> None:
    anchor = HudAnchor()
    assert anchor.apply(900.0, _read(800.0, 10.0), now=10.0, speed_mph=MPH) is None
    assert not anchor.board_frame and anchor.last_reason == "confirming"
    out = anchor.apply(900.0, _read(801.0, 10.5), now=10.5, speed_mph=MPH)
    assert anchor.board_frame
    assert out == pytest.approx(801.0 - MPH * 0.44704 * 0.0)
    assert anchor.offset_m == pytest.approx(99.5)


def test_frame_switch_rejects_broken_reading_and_inconsistent_pair() -> None:
    """104709Z: «0 m» con el tablón a 1,5 km, y lecturas lejos del fin de andén."""
    anchor = HudAnchor()
    assert anchor.apply(1571.0, _read(0.8, 10.0), now=10.0, speed_mph=MPH) is None
    assert anchor.last_reason == "on_marker"
    assert anchor.apply(1571.0, _read(2910.0, 10.5), now=10.5, speed_mph=MPH) is None
    assert anchor.last_reason == "frame_gate" and not anchor.board_frame
    # dos lecturas válidas pero con desfases distintos: no confirman
    assert anchor.apply(900.0, _read(800.0, 11.0), now=11.0, speed_mph=MPH) is None
    assert anchor.apply(900.0, _read(700.0, 11.5), now=11.5, speed_mph=MPH) is None
    assert not anchor.board_frame


def test_tracking_clips_correction_and_gates_outliers() -> None:
    anchor, est = _locked()
    out = anchor.apply(est, _read(est - 30.0, 11.0), now=11.0, speed_mph=MPH)
    assert out == pytest.approx(est - MAX_CORRECTION_M)  # acotada por captura
    # una lectura rota lejos de la estimación no mueve nada
    assert anchor.apply(est, _read(est + 500.0, 11.5), now=11.5, speed_mph=MPH) is None
    assert anchor.last_reason == "track_gate"
    # pequeña diferencia: se aplica entera
    out = anchor.apply(est, _read(est - 2.0, 12.0), now=12.0, speed_mph=MPH)
    assert out == pytest.approx(est - 2.0)


def test_age_compensation_and_dedupe() -> None:
    anchor, est = _locked()
    reading = _read(est, 11.0)  # captura de hace 1 s a 30 mph: ya se recorrieron ~13,4 m
    out = anchor.apply(est, reading, now=12.0, speed_mph=MPH)
    assert out == pytest.approx(est - MPH * 0.44704 * 1.0)
    assert anchor.apply(est, reading, now=12.05, speed_mph=MPH) is None  # misma captura


def test_http_converted_to_board_frame_and_offset_refined() -> None:
    anchor, est = _locked(offset=100.0)
    assert anchor.to_board(900.0) == pytest.approx(800.0)
    anchor.note_http_end(est + 110.0, est, now=10.6)
    assert anchor.offset_m is not None
    assert 100.0 < anchor.offset_m < 110.0
    before = HudAnchor()
    assert before.to_board(900.0) == 900.0  # sin ancla: marco fin de andén


def test_reset_and_control_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    anchor, _ = _locked()
    anchor.reset()
    assert not anchor.board_frame and anchor.offset_m is None
    monkeypatch.delenv("TSW6_HUD_OCR_CONTROL", raising=False)
    assert not hud_ocr_control_enabled()
    monkeypatch.setenv("TSW6_HUD_OCR_CONTROL", "1")
    assert hud_ocr_control_enabled()


def _planning(dist: float) -> StationPlanning:
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._source = "http"
    src._startup_invalidate_pending = False
    src._last_probe_seq = 100
    src._snap.station_distance_m = dist
    src._snap.station_name = "Fleetwood"
    src.set_hud_anchor(HudAnchor())
    return src


def test_station_planning_anchors_distance_to_hud() -> None:
    src = _planning(900.0)
    now = time.monotonic()
    src._last_tick_t = now - 0.05
    src.update(MPH, probe_seq=101, hud_ocr=_read(800.0, now))
    snap = src.update(MPH, probe_seq=102, hud_ocr=_read(800.5, time.monotonic()))
    assert src._anchor is not None and src._anchor.board_frame
    assert snap.station_distance_m == pytest.approx(800.0, abs=3.0)
    status = src.anchor_status()
    assert status is not None and status.startswith("board")


def test_station_planning_without_anchor_is_unchanged() -> None:
    src = StationPlanning(http_enabled=False)
    src._http_ok = True
    src._startup_invalidate_pending = False
    src._last_probe_seq = 100
    src._snap.station_distance_m = 900.0
    src._last_tick_t = time.monotonic() - 0.05
    snap = src.update(MPH, probe_seq=101, hud_ocr=_read(800.0, time.monotonic()))
    assert snap.station_distance_m is not None and snap.station_distance_m > 890.0
    assert src.anchor_status() is None


def test_http_reading_uses_board_frame_and_station_change_resets(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_poll(exclude_bases=None, hud_db_path=None, **_):
        calls["n"] += 1
        name = "Fleetwood" if calls["n"] == 1 else "Bronxville"
        dist = 905.0 if calls["n"] == 1 else 3000.0
        return {"next_stop": {"distance_m": dist, "name": name}, "service_name": "5P06"}

    monkeypatch.setattr("tsw6v2.planning_poller.poll_station_planning", fake_poll)
    src = _planning(800.0)
    src._last_speed_mph = 0.0  # sin compensación v×lag
    anchor = src._anchor
    assert anchor is not None
    anchor.board_frame = True
    anchor.offset_m = 100.0
    src._poll_once()
    assert src._snap.station_distance_m == pytest.approx(805.0)  # 905 − 100 (marco tablón)
    src._poll_once()  # otra estación: el desfase aprendido se descarta
    assert not anchor.board_frame
    assert src._snap.station_distance_m == pytest.approx(3000.0)


def test_marker_passed_not_triggered_when_arriving_at_board_181008z() -> None:
    """Fleetwood 181008Z: stn=1,0 m a 1,1 mph con ancla = llegada al tablón, no salida."""
    from tsw6v2.hud_anchor import set_board_frame
    from tsw6v2.p1_station_gate import _left_platform

    try:
        set_board_frame(False)
        assert _left_platform(speed_mph=1.1, station_dist_m=1.0)  # marco fin de andén: marcador pasado
        set_board_frame(True)
        assert not _left_platform(speed_mph=1.1, station_dist_m=1.0)
        assert _left_platform(speed_mph=6.0, station_dist_m=0.5)  # pasa el tablón a marcha clara
    finally:
        set_board_frame(False)


def test_anchor_resyncs_after_consistent_gated_captures() -> None:
    """162907Z: estimación 47 m por encima del OCR; track_gate no puede bloquear para siempre."""
    anchor, _ = _locked(offset=50.0, est=130.0)
    est = 130.0
    for i, t in enumerate((11.0, 11.5)):
        assert anchor.apply(est, _read(est - 47.0 - i * 0.2, t), now=t, speed_mph=MPH) is None
        assert anchor.last_reason == "track_gate"
    out = anchor.apply(est, _read(est - 47.4, 12.0), now=12.0, speed_mph=MPH)
    assert out == pytest.approx(est - 47.4, abs=0.1)
    assert anchor.last_reason == "resync"


def test_anchor_gate_streak_resets_on_inconsistent_captures() -> None:
    anchor, _ = _locked(offset=50.0, est=130.0)
    assert anchor.apply(130.0, _read(60.0, 11.0), now=11.0, speed_mph=MPH) is None
    assert anchor.apply(130.0, _read(20.0, 11.5), now=11.5, speed_mph=MPH) is None
    assert anchor.apply(130.0, _read(60.0, 12.0), now=12.0, speed_mph=MPH) is None
    assert anchor.last_reason == "track_gate"


def test_rejected_http_does_not_move_offset(monkeypatch) -> None:
    """Una lectura HTTP rechazada no debe contaminar el desfase del ancla."""
    src = _planning(80.0)
    assert src._anchor is not None
    src._anchor.board_frame = True
    src._anchor.offset_m = 52.0
    src._anchor._last_accept_t = time.monotonic()
    src._last_speed_mph = 8.0
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda **_: {"next_stop": {"distance_m": 195.1, "name": "Fleetwood"}},
    )
    src._poll_once()
    assert src._anchor.offset_m == pytest.approx(52.0)
    assert src._snap.station_distance_m == pytest.approx(80.0)


def test_http_contradicting_ocr_is_ignored(monkeypatch) -> None:
    """162907Z: HTTP daba 3 m con el OCR en 34 m."""
    src = _planning(36.0)
    assert src._anchor is not None
    src._anchor.board_frame = True
    src._anchor.offset_m = 83.0
    src._last_speed_mph = 7.8
    src._last_ocr = _read(34.1, time.monotonic())
    monkeypatch.setattr(
        "tsw6v2.planning_poller.poll_station_planning",
        lambda **_: {"next_stop": {"distance_m": 93.4, "name": "Fleetwood"}},
    )
    src._poll_once()
    assert src._snap.station_distance_m == pytest.approx(36.0)
    assert src._snap.planning_rejected_n >= 1
