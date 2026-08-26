#!/usr/bin/env python3
"""
test_station_fsm.py — Tests para la FSM de estación (governor_station.py).

Verifica:
  - Transiciones None → APPROACHING → STOPPED → DEPARTING → None
  - Cooldown post-salida
  - Selección de parada manual
"""

import time
import unittest
from unittest.mock import patch

from tsw6.governor.governor_station import StationFSM


def _braking_dist_fn(speed_mph, target_mph, **kwargs):
    """Mock simplificado de braking_distance."""
    v1 = speed_mph * 0.44704
    v2 = target_mph * 0.44704
    if v1 <= v2:
        return 0.0
    return (v1 ** 2 - v2 ** 2) / (2 * 0.9)


class TestFSMTransitions(unittest.TestCase):
    """Tests de transiciones básicas de la FSM."""

    def setUp(self):
        self.fsm = StationFSM()

    def test_none_to_approaching(self):
        """Entra en APPROACHING cuando hay estación cercana."""
        stations = [{"name": "Test Station", "distance_m": 300.0,
                     "platform_length_m": 100.0}]
        action, lim = self.fsm.update_state_transitions(
            speed_mph=40.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=None,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertEqual(self.fsm.state, "APPROACHING")
        self.assertEqual(self.fsm.name, "Test Station")

    def test_approaching_to_stopped(self):
        """Transiciona a STOPPED cuando velocidad ≈ 0 y cerca del andén."""
        self.fsm.state = "APPROACHING"
        self.fsm.name = "Test Station"
        stations = [{"name": "Test Station", "distance_m": 20.0,
                     "platform_length_m": 100.0}]
        action, lim = self.fsm.update_state_transitions(
            speed_mph=0.3, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=None,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertEqual(self.fsm.state, "STOPPED")
        self.assertEqual(action, "HOLD")

    def test_stopped_to_departing_doors_close(self):
        """Transiciona a DEPARTING cuando puertas se cierran."""
        self.fsm.state = "STOPPED"
        self.fsm.name = "Test Station"
        self.fsm._doors_opened = True
        self.fsm._stopped_at = time.time()
        self.fsm._we_stopped = True
        stations = [{"name": "Test Station", "distance_m": 10.0,
                     "platform_length_m": 100.0}]
        action, lim = self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=False,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertEqual(self.fsm.state, "DEPARTING")
        self.assertIn("test station", self.fsm._served_bases)

    def test_approaching_door_close_marks_served_far_from_marker(self):
        """Parado lejos del tablón: puertas abrir/cerrar → servida y DEPARTING."""
        self.fsm.state = "APPROACHING"
        self.fsm.name = "Four Oaks, andén 2"
        stations = [
            {"name": "Four Oaks, andén 2", "distance_m": 480.0, "scheduled": True},
            {"name": "Sutton Coldfield, andén 2", "distance_m": 2200.0, "scheduled": True},
        ]
        self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=55.0, stations=stations,
            doors_open=False, doors_dmi=True,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5,
        )
        self.assertTrue(self.fsm._doors_opened)
        self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=55.0, stations=stations,
            doors_open=False, doors_dmi=False,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5,
        )
        self.assertEqual(self.fsm.state, "DEPARTING")
        self.assertIn("four oaks", self.fsm._served_bases)
        nxt = self.fsm.select_next_stop(stations)
        self.assertIsNotNone(nxt)
        if nxt is not None:
            self.assertIn("Sutton", nxt["name"])

    def test_stopped_dmi_open_when_telem_closed(self):
        """DMI abierto cuenta aunque la telemetría de cabina diga cerrado."""
        self.fsm.state = "STOPPED"
        self.fsm.name = "Test Station"
        self.fsm._doors_opened = False
        self.fsm._stopped_at = time.time()
        self.fsm._we_stopped = True
        stations = [{"name": "Test Station", "distance_m": 10.0,
                     "platform_length_m": 100.0}]
        action, lim = self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=True,
            doors_telem=False,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertEqual(self.fsm.state, "STOPPED")
        self.assertTrue(self.fsm._doors_opened)
        self.assertEqual(action, "HOLD")

    def test_departing_to_none(self):
        """Transiciona a None cuando se aleja de la estación."""
        self.fsm.state = "DEPARTING"
        self.fsm.name = "Test Station"
        stations = [{"name": "Next Station", "distance_m": 5000.0,
                     "platform_length_m": 100.0}]
        action, lim = self.fsm.update_state_transitions(
            speed_mph=30.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=None,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertIsNone(self.fsm.state)

    def test_departing_to_none_next_station_immediate(self):
        """Al cerrar puertas, la siguiente parada distinta libera DEPARTING."""
        self.fsm.state = "DEPARTING"
        self.fsm.name = "Station A"
        stations = [
            {"name": "Station A", "distance_m": 0.0, "platform_length_m": 100.0},
            {"name": "Station B", "distance_m": 50.0, "platform_length_m": 100.0},
        ]
        self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=False,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertIn("station a", self.fsm._served_bases)
        nxt = self.fsm.select_next_stop(stations)
        self.assertIsNotNone(nxt)
        if nxt is not None:
            self.assertEqual(nxt["name"], "Station B")
        if self.fsm.state == "APPROACHING":
            self.assertEqual(self.fsm.name, "Station B")

    def test_stopped_to_departing_advances_next_stop(self):
        """Tras servir la primera parada, select_next_stop devuelve la segunda."""
        self.fsm.state = "STOPPED"
        self.fsm.name = "Station A"
        self.fsm._served_bases.add("station a")
        stations = [
            {"name": "Station A", "distance_m": 0.0, "scheduled": True},
            {"name": "Station B", "distance_m": 5000.0, "scheduled": True},
        ]
        nxt = self.fsm.select_next_stop(stations)
        self.assertIsNotNone(nxt)
        if nxt is not None:
            self.assertEqual(nxt["name"], "Station B")

    def test_stopped_hold_returns_hold(self):
        """En STOPPED siempre devuelve HOLD."""
        self.fsm.state = "STOPPED"
        self.fsm.name = "Test Station"
        self.fsm._stopped_at = time.time()
        self.fsm._we_stopped = True
        stations = [{"name": "Test Station", "distance_m": 10.0,
                     "platform_length_m": 100.0}]
        action, _ = self.fsm.update_state_transitions(
            speed_mph=0.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=True,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        self.assertEqual(action, "HOLD")


class TestCooldown(unittest.TestCase):
    """Tests del cooldown post-salida."""

    def test_cooldown_prevents_immediate_reentry(self):
        """No entra en APPROACHING a la misma estación inmediatamente tras salir."""
        fsm = StationFSM()
        fsm._last_departed_name = "Test Station"
        fsm._last_departed_at = time.time()  # justo ahora
        stations = [{"name": "Test Station", "distance_m": 300.0,
                     "platform_length_m": 100.0}]
        fsm.update_state_transitions(
            speed_mph=40.0, limit_mph=60.0, stations=stations,
            doors_open=False, doors_dmi=None,
            ocr_stop_dist_m=None, ocr_task=None,
            braking_dist_fn=_braking_dist_fn,
            eff_max_decel=0.9, eff_k_stop=2.5)
        # Should NOT enter APPROACHING due to cooldown
        self.assertIsNone(fsm.state)


class TestManualStop(unittest.TestCase):
    """Tests de selección de parada manual."""

    def test_select_manual_stop(self):
        """Selecciona la parada más cercana al target_stop_min_m."""
        fsm = StationFSM()
        fsm.target_stop_min_m = 5000.0
        stations = [
            {"name": "Station A", "distance_m": 2000.0},
            {"name": "Station B", "distance_m": 4800.0},
            {"name": "Station C", "distance_m": 8000.0},
        ]
        stop = fsm.select_next_stop(stations)
        self.assertIsNotNone(stop)
        if stop is not None:
            self.assertEqual(stop["name"], "Station B")

    def test_no_stop_when_target_zero(self):
        """target_stop_min_m = 0 significa sin parada."""
        fsm = StationFSM()
        fsm.target_stop_min_m = 0
        stations = [{"name": "Station A", "distance_m": 2000.0}]
        stop = fsm.select_next_stop(stations)
        self.assertIsNone(stop)


if __name__ == "__main__":
    unittest.main()
