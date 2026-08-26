#!/usr/bin/env python3
"""
test_online_learner.py — Tests para el OnlineLearner v2.

Verifica:
  - Filtros de coherencia de signo
  - Límites duros (clamp)
  - Separación por banda de velocidad
"""

import json
import os
import tempfile
import time
import unittest

from tsw6.learning.online_learner import (
    OnlineLearner, _speed_band_index, _grad_band_index, _TRACTION_NOTCHES,
    _BRAKE_NOTCHES, _MAX_NOTCH, _COAST_NOTCH, _CLAMP,
    _GRAD_BANDS, GRAD_FLAT_THRESHOLD, _gravity_compensation,
    MIN_STABLE_S, MIN_SAMPLES,
)
from tsw6.braking.v2.physics import BRAKE_FILL_CLAMP


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
        """grad > +0.5% → uphill (1). Convención: positivo = subida."""
        self.assertEqual(_grad_band_index(1.0), 1)
        self.assertEqual(_grad_band_index(0.6), 1)

    def test_downhill_band(self):
        """grad < -0.5% → downhill (2). Convención: negativo = bajada."""
        self.assertEqual(_grad_band_index(-1.0), 2)
        self.assertEqual(_grad_band_index(-0.6), 2)

    def test_gravity_compensation(self):
        """Compensación gravitacional correcta (convención: positivo = subida).
        measured_normalized = measured - _gravity_compensation(grad)
        En subida (grad>0): comp negativa → normalizado = measured + |comp| (reduce decel de subida).
        En bajada (grad<0): comp positiva → normalizado = measured - |comp| (reduce accel de bajada)."""
        # 1% subida → comp = -0.0981 m/s² (restarlo suma desaceleración extra por gravedad)
        self.assertAlmostEqual(_gravity_compensation(1.0), -0.0981, places=3)
        # 1% bajada → comp = +0.0981 m/s² (restarlo quita la ayuda de la gravedad)
        self.assertAlmostEqual(_gravity_compensation(-1.0), 0.0981, places=3)
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


class TestPredictAccel(unittest.TestCase):
    """Verifica la predicción de aceleración por muesca (selección de muesca mínima)."""

    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_pred.json")
        # Datos por banda 0 (0-30 mph), normalizados a plano:
        band = _speed_band_index(15.0)
        self.learner._ema_bands[band][5] = 0.06   # Tracción-1
        self.learner._n_bands[band][5]   = MIN_SAMPLES
        self.learner._ema_bands[band][6] = 0.18   # Tracción-2
        self.learner._n_bands[band][6]   = MIN_SAMPLES
        self.learner._ema_bands[band][7] = 0.45   # Tracción-3
        self.learner._n_bands[band][7]   = MIN_SAMPLES

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_pred.json")
        except FileNotFoundError:
            pass

    def test_flat_returns_learned_value(self):
        """En plano devuelve el valor aprendido (sin componente de gravedad)."""
        val = self.learner.predict_accel(6, 15.0, 0.0)
        assert val is not None
        self.assertAlmostEqual(val, 0.18, places=3)

    def test_uphill_subtracts_gravity(self):
        """En subida la aceleración real baja por la gravedad."""
        flat = self.learner.predict_accel(6, 15.0, 0.0)
        up   = self.learner.predict_accel(6, 15.0, 1.0)
        assert flat is not None and up is not None
        self.assertLess(up, flat)
        # real = plano + comp(grad);  comp(1%) = -0.0981
        self.assertAlmostEqual(up, 0.18 - 0.0981, places=3)

    def test_insufficient_samples_returns_none(self):
        """Muesca sin muestras suficientes y sin EMA combinada → None."""
        self.assertIsNone(self.learner.predict_accel(8, 15.0, 0.0))

    def test_falls_back_to_combined(self):
        """Si la banda no tiene datos pero la EMA combinada sí, la usa."""
        self.learner._ema[8] = 0.5
        self.learner._n[8]   = MIN_SAMPLES
        # A 200 mph no hay datos por banda → usa la combinada
        val = self.learner.predict_accel(8, 200.0, 0.0)
        assert val is not None
        self.assertAlmostEqual(val, 0.5, places=3)


class TestThrottleCeiling(unittest.TestCase):
    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_ceil.json")

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_ceil.json")
        except FileNotFoundError:
            pass

    def test_default_ceiling_traction1(self):
        self.assertAlmostEqual(self.learner.predict_throttle_ceiling(5), 15.0)

    def test_learned_ceiling_persisted(self):
        self.learner._throttle_ceiling[5] = 14.2
        self.learner._throttle_ceiling_n[5] = MIN_SAMPLES
        self.learner._save()
        other = OnlineLearner(save_path="/tmp/test_learner_ceil.json")
        self.assertAlmostEqual(other.predict_throttle_ceiling(5), 14.2)


class TestBrakePressureFilter(unittest.TestCase):
    def setUp(self):
        self.learner = OnlineLearner(save_path="/tmp/test_learner_pressure.json")

    def tearDown(self):
        try:
            os.unlink("/tmp/test_learner_pressure.json")
        except FileNotFoundError:
            pass

    def _feed_stable_brake(self, brake_cyl_bar=None):
        """Ventana estable inyectada + feed final."""
        notch = 2
        accel = -0.5
        now = time.time()
        t0 = now - MIN_STABLE_S - 0.05
        dt = MIN_STABLE_S / 3.0
        speeds = [40.0 + i * 0.8 for i in range(4)]
        for i in range(4):
            self.learner._window.append(
                (t0 + i * dt, speeds[i], notch, 0.0, accel))
        return self.learner.feed(
            speed_mph=speeds[-1], notch=notch, grad_pct=0.0, accel_ms2=accel,
            brake_cyl_bar=brake_cyl_bar,
        )

    def test_rejects_brake_without_air(self):
        result = self._feed_stable_brake(brake_cyl_bar=1.2)
        self.assertIsNone(result)
        self.assertIn("aire", self.learner.last_reason)

    def test_accepts_brake_with_pressure(self):
        self._feed_stable_brake(brake_cyl_bar=3.0)
        self.assertIn("registrada", self.learner.last_reason)
        self.assertEqual(self.learner._n.get(2, 0), 1)

    def test_fill_time_persisted(self):
        t0 = time.time()
        self.learner._last_feed_notch = 4
        for i, delay in enumerate((0.0, 2.0, 4.0)):
            self.learner._observe_brake_fill(2, 1.0, t0 + delay)
            self.learner._observe_brake_fill(2, 3.0, t0 + delay + 1.5)
            self.learner._last_feed_notch = 4
        consts = self.learner.get_constants()
        self.assertIn("BRAKE_FILL_S", consts)
        lo, hi = BRAKE_FILL_CLAMP
        self.assertGreaterEqual(consts["BRAKE_FILL_S"], lo)
        self.assertLessEqual(consts["BRAKE_FILL_S"], hi)


if __name__ == "__main__":
    unittest.main()
