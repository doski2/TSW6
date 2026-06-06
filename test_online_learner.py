#!/usr/bin/env python3
"""
test_online_learner.py — Tests para el OnlineLearner v2.

Verifica:
  - Filtros de coherencia de signo
  - Límites duros (clamp)
  - Decay/reset ante divergencia
  - Separación por banda de velocidad
"""

import json
import os
import tempfile
import time
import unittest

from online_learner import (
    OnlineLearner, _speed_band_index, _grad_band_index, _TRACTION_NOTCHES,
    _BRAKE_NOTCHES, _MAX_NOTCH, _COAST_NOTCH, _CLAMP, _INITIAL_REFS,
    _GRAD_BANDS, GRAD_FLAT_THRESHOLD, _gravity_compensation,
    MIN_STABLE_S, MIN_SAMPLES,
)


class TestSignCoherence(unittest.TestCase):
    """Verifica que el learner rechaza muestras incoherentes con el signo."""

    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_sign.json")

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_sign.json")
        except FileNotFoundError:
            pass

    def _feed_stable_window(self, notch, speed_mph, accel_ms2):
        """Simula una ventana estable para provocar un feed real."""
        # Necesitamos >= 4 muestras con notch estable y duración >= MIN_STABLE_S
        base_t = time.time()
        # Inyectar directamente en la ventana para simular estabilidad
        dt = MIN_STABLE_S / 3.0
        speeds = [speed_mph, speed_mph + 1.0, speed_mph + 2.0, speed_mph + 3.0]
        for i, spd in enumerate(speeds):
            self.learner._window.append(
                (base_t + i * dt, spd, notch, 0.0, accel_ms2))
        # Ahora llamar feed con la última muestra
        return self.learner.feed(
            speed_mph=speeds[-1], notch=notch,
            grad_pct=0.0, accel_ms2=accel_ms2)

    def test_traction_rejects_negative_accel(self):
        """Notch 7-8 (tracción) debe rechazar aceleración negativa."""
        result = self._feed_stable_window(notch=7, speed_mph=30.0, accel_ms2=-0.5)
        # Should return None (rejected)
        self.assertIsNone(result)
        # No samples recorded for traction
        self.assertEqual(self.learner._n.get(7, 0), 0)

    def test_braking_rejects_positive_accel(self):
        """Notch 0-3 (freno) debe rechazar aceleración positiva."""
        result = self._feed_stable_window(notch=1, speed_mph=40.0, accel_ms2=0.3)
        self.assertIsNone(result)
        self.assertEqual(self.learner._n.get(1, 0), 0)


class TestClampLimits(unittest.TestCase):
    """Verifica que los valores aprendidos nunca salen de los límites."""

    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_clamp.json")

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_clamp.json")
        except FileNotFoundError:
            pass

    def test_target_accel_clamped_high(self):
        """TARGET_ACCEL no puede superar 0.80."""
        # Force extreme EMA values
        for notch in _TRACTION_NOTCHES:
            self.learner._ema_bands[0][notch] = 2.0
            self.learner._n_bands[0][notch] = 10
        self.learner._recalculate_combined()
        consts = self.learner.get_constants()
        if "TARGET_ACCEL_MS2" in consts:
            self.assertLessEqual(consts["TARGET_ACCEL_MS2"], 0.80)

    def test_target_accel_clamped_low(self):
        """TARGET_ACCEL no puede bajar de 0.15."""
        for notch in _TRACTION_NOTCHES:
            self.learner._ema_bands[0][notch] = 0.01
            self.learner._n_bands[0][notch] = 10
        self.learner._recalculate_combined()
        consts = self.learner.get_constants()
        if "TARGET_ACCEL_MS2" in consts:
            self.assertGreaterEqual(consts["TARGET_ACCEL_MS2"], 0.15)

    def test_coast_clamped_low(self):
        """COAST_DECEL debe ser >= 0.02."""
        self.learner._ema_bands[0][_COAST_NOTCH] = -0.001
        self.learner._n_bands[0][_COAST_NOTCH] = 10
        self.learner._recalculate_combined()
        consts = self.learner.get_constants()
        if "COAST_DECEL_MS2" in consts:
            self.assertGreaterEqual(consts["COAST_DECEL_MS2"], 0.02)


class TestDivergenceReset(unittest.TestCase):
    """Verifica que el learner resetea cuando diverge >50%."""

    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_div.json")

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_div.json")
        except FileNotFoundError:
            pass

    def test_divergence_triggers_reset(self):
        """Si TARGET_ACCEL diverge >50%, se resetean las bandas."""
        ref = _INITIAL_REFS["TARGET_ACCEL_MS2"]
        for notch in _TRACTION_NOTCHES:
            for i in range(len(self.learner._ema_bands)):
                self.learner._ema_bands[i][notch] = ref * 0.3  # 70% menor
                self.learner._n_bands[i][notch] = 15
        self.learner._recalculate_combined()
        self.learner._check_divergence()
        # After reset, n should be 0
        for notch in _TRACTION_NOTCHES:
            self.assertEqual(self.learner._n.get(notch, 0), 0)


class TestSpeedBands(unittest.TestCase):
    """Verifica la separación por bandas de velocidad."""

    def test_low_band(self):
        """0-30 mph va a banda 0."""
        self.assertEqual(_speed_band_index(15.0), 0)

    def test_mid_band(self):
        """30-60 mph va a banda 1."""
        self.assertEqual(_speed_band_index(45.0), 1)

    def test_high_band(self):
        """60+ mph va a banda 2."""
        self.assertEqual(_speed_band_index(75.0), 2)

    def test_boundary_30(self):
        """30 mph va a banda mid (1)."""
        self.assertEqual(_speed_band_index(30.0), 1)


class TestPersistence(unittest.TestCase):
    """Verifica la persistencia JSON."""

    def test_save_and_load(self):
        """Guardar y cargar preserva los valores."""
        path = "/tmp/test_learner_persist.json"
        try:
            learner = OnlineLearner(save_path=path)
            # Simular aprendizaje
            learner._ema_bands[1][7] = 0.55
            learner._n_bands[1][7] = 20
            learner._ema_grad_bands[2][7] = 0.60  # bajada
            learner._n_grad_bands[2][7] = 5
            learner._recalculate_combined()
            learner._save()

            # Crear nuevo learner con mismo path
            learner2 = OnlineLearner(save_path=path)
            self.assertEqual(learner2._n_bands[1].get(7, 0), 20)
            self.assertAlmostEqual(learner2._ema_bands[1][7], 0.55, places=3)
            # v3: gradient bands persistence
            self.assertEqual(learner2._n_grad_bands[2].get(7, 0), 5)
            self.assertAlmostEqual(learner2._ema_grad_bands[2][7], 0.60, places=3)
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


class TestGradientBands(unittest.TestCase):
    """Verifica la separación por bandas de gradiente (v3)."""

    def test_flat_band(self):
        """|grad| < 0.5% → flat (0)."""
        self.assertEqual(_grad_band_index(0.0), 0)
        self.assertEqual(_grad_band_index(0.3), 0)
        self.assertEqual(_grad_band_index(-0.4), 0)

    def test_uphill_band(self):
        """grad < -0.5% → uphill (1)."""
        self.assertEqual(_grad_band_index(-1.0), 1)
        self.assertEqual(_grad_band_index(-0.6), 1)

    def test_downhill_band(self):
        """grad > +0.5% → downhill (2)."""
        self.assertEqual(_grad_band_index(1.0), 2)
        self.assertEqual(_grad_band_index(0.6), 2)

    def test_gravity_compensation(self):
        """Compensación gravitacional correcta."""
        # 1% bajada → +0.0981 m/s²
        self.assertAlmostEqual(_gravity_compensation(1.0), 0.0981, places=3)
        # 1% subida → -0.0981 m/s²
        self.assertAlmostEqual(_gravity_compensation(-1.0), -0.0981, places=3)
        # Plano → 0
        self.assertAlmostEqual(_gravity_compensation(0.0), 0.0, places=5)

    def test_gradient_band_confidence(self):
        """confidence_by_gradient devuelve datos por banda."""
        learner = OnlineLearner(save_path="/tmp/test_learner_grad.json")
        try:
            learner._ema_grad_bands[0][7] = 0.3
            learner._n_grad_bands[0][7] = 5
            learner._ema_grad_bands[2][7] = 0.4
            learner._n_grad_bands[2][7] = 3
            conf = learner.confidence_by_gradient()
            self.assertEqual(conf["flat"]["ACCEL(n7)"], 5)
            self.assertEqual(conf["downhill"]["ACCEL(n7)"], 3)
            self.assertEqual(conf["uphill"]["ACCEL(n7)"], 0)
        finally:
            try:
                os.unlink("/tmp/test_learner_grad.json")
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()
