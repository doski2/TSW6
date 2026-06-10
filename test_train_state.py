"""
test_train_state.py — Tests unitarios para train_state.py

Verifica construcción, propiedades derivadas y conversión desde telemetría.
"""

import time

import pytest

from train_state import TrainState, build_train_state


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> TrainState:
    """Construye un TrainState con valores sensatos por defecto."""
    defaults = dict(
        speed_mph=40.0, limit_mph=50.0, target_mph=0.0,
        handle_notch=4, acceleration_ms2=None, gradient_pct=0.0,
        rain_intensity=0.0, next_limit_mph=None, distance_next_m=None,
        brake_marker_m=None, speed_limits_ahead=None, supervision="csm",
        ack_required=False, stations=None, doors_open=False, doors_dmi=None,
        ocr_stop_dist_m=None, ocr_task=None, station_state=None,
        station_name=None, paused=False, timestamp=time.time(),
    )
    defaults.update(overrides)
    return TrainState(**defaults)


# ── Tests de construcción ─────────────────────────────────────────────────────

class TestTrainStateConstruction:
    def test_basic_fields(self):
        s = _state(speed_mph=55.0, limit_mph=60.0)
        assert s.speed_mph == 55.0
        assert s.limit_mph == 60.0

    def test_frozen(self):
        s = _state()
        with pytest.raises((AttributeError, TypeError)):
            s.speed_mph = 999.0  # type: ignore[misc]

    def test_timestamp_recent(self):
        before = time.time()
        s = _state()
        after = time.time()
        assert before <= s.timestamp <= after


# ── Tests de propiedades derivadas ────────────────────────────────────────────

class TestHandleZones:
    def test_neutral(self):
        s = _state(handle_notch=4)
        assert s.throttle_notch == 0
        assert s.brake_notch == 0
        assert not s.throttle_active
        assert not s.brake_active

    def test_full_throttle(self):
        s = _state(handle_notch=8)
        assert s.throttle_notch == 4
        assert s.brake_notch == 0
        assert s.throttle_active
        assert not s.brake_active

    def test_max_brake(self):
        s = _state(handle_notch=0)
        assert s.throttle_notch == 0
        assert s.brake_notch == 4
        assert not s.throttle_active
        assert s.brake_active

    def test_mid_throttle(self):
        s = _state(handle_notch=6)
        assert s.throttle_notch == 2
        assert s.brake_notch == 0
        assert s.throttle_active

    def test_mid_brake(self):
        s = _state(handle_notch=2)
        assert s.throttle_notch == 0
        assert s.brake_notch == 2
        assert s.brake_active


class TestEffectiveTarget:
    def test_target_zero_follows_limit(self):
        s = _state(speed_mph=0, limit_mph=50.0, target_mph=0.0)
        assert s.effective_target == 50.0

    def test_target_below_limit(self):
        s = _state(speed_mph=0, limit_mph=60.0, target_mph=45.0)
        assert s.effective_target == 45.0

    def test_target_above_limit(self):
        s = _state(speed_mph=0, limit_mph=50.0, target_mph=70.0)
        assert s.effective_target == 50.0

    def test_target_equals_limit(self):
        s = _state(speed_mph=0, limit_mph=50.0, target_mph=50.0)
        assert s.effective_target == 50.0


# ── Tests de build_train_state ────────────────────────────────────────────────

class TestBuildTrainState:
    def test_from_complete_telem(self):
        telem = {
            "speed_mph": 45.5,
            "limit_mph": 50.0,
            "handle_notch": 6,
            "gradient_pct": 1.2,
            "rain_intensity": 0.3,
            "next_limit_mph": 30.0,
            "distance_next_m": 500.0,
            "supervision": "tsm",
            "ack_required": True,
            "doors_open": False,
        }
        s = build_train_state(telem, target_mph=40.0)
        assert s.speed_mph == 45.5
        assert s.limit_mph == 50.0
        assert s.handle_notch == 6
        assert s.gradient_pct == 1.2
        assert s.rain_intensity == 0.3
        assert s.next_limit_mph == 30.0
        assert s.distance_next_m == 500.0
        assert s.supervision == "tsm"
        assert s.ack_required is True
        assert s.target_mph == 40.0

    def test_defaults_on_empty_telem(self):
        s = build_train_state({})
        assert s.speed_mph == 0.0
        assert s.limit_mph == 0.0
        assert s.handle_notch == 4        # neutral por defecto
        assert s.gradient_pct == 0.0
        assert s.rain_intensity == 0.0
        assert s.supervision == "csm"
        assert s.ack_required is False
        assert s.paused is False

    def test_stations_converted_to_tuple(self):
        stations = [{"name": "Birmingham", "distance_m": 800}]
        s = build_train_state({"stations": stations})
        assert isinstance(s.stations, tuple)
        assert s.stations[0]["name"] == "Birmingham"

    def test_speed_limits_ahead_converted_to_tuple(self):
        limits = [{"limit_mph": 25.0, "distance_m": 300.0}]
        s = build_train_state({"speed_limits_ahead": limits})
        assert isinstance(s.speed_limits_ahead, tuple)

    def test_stations_none_when_empty(self):
        s = build_train_state({})
        assert s.stations is None

    def test_optional_kwargs(self):
        s = build_train_state(
            {},
            acceleration_ms2=0.5,
            station_state="APPROACHING",
            station_name="London Euston",
            ocr_stop_dist_m=350.0,
            ocr_task="stop_here",
        )
        assert s.acceleration_ms2 == 0.5
        assert s.station_state == "APPROACHING"
        assert s.station_name == "London Euston"
        assert s.ocr_stop_dist_m == 350.0
        assert s.ocr_task == "stop_here"

    def test_none_values_in_telem(self):
        """None values no deben romper la conversión."""
        telem = {"gradient_pct": None, "rain_intensity": None, "supervision": None}
        s = build_train_state(telem)
        assert s.gradient_pct == 0.0
        assert s.rain_intensity == 0.0
        assert s.supervision == "csm"
