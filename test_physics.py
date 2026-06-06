#!/usr/bin/env python3
"""
test_physics.py — Tests para TrainPhysics.braking_distance().

Verifica:
  - Distancia básica de frenado
  - Efecto del gradiente (subida reduce, bajada aumenta)
  - Margen de seguridad
  - Aceleración actual añade distancia de transición
"""

import unittest

from governor_physics import TrainPhysics


class TestBrakingDistanceBasic(unittest.TestCase):
    """Tests básicos de distancia de frenado."""

    def setUp(self):
        self.physics = TrainPhysics()

    def test_zero_speed_diff(self):
        """Si from_mph <= to_mph, distancia = 0."""
        self.assertEqual(self.physics.braking_distance(30.0, 30.0), 0.0)
        self.assertEqual(self.physics.braking_distance(20.0, 30.0), 0.0)

    def test_positive_distance(self):
        """Frenado normal produce distancia positiva."""
        d = self.physics.braking_distance(60.0, 0.0)
        self.assertGreater(d, 0.0)

    def test_higher_speed_longer_distance(self):
        """Mayor velocidad → mayor distancia de frenado."""
        d30 = self.physics.braking_distance(30.0, 0.0)
        d60 = self.physics.braking_distance(60.0, 0.0)
        self.assertGreater(d60, d30)

    def test_margin_increases_distance(self):
        """Margen > 1 aumenta la distancia."""
        d_no_margin = self.physics.braking_distance(60.0, 0.0, margin=1.0)
        d_margin = self.physics.braking_distance(60.0, 0.0, margin=1.4)
        self.assertAlmostEqual(d_margin, d_no_margin * 1.4, places=1)


class TestBrakingDistanceGradient(unittest.TestCase):
    """Tests del efecto del gradiente en la distancia de frenado."""

    def setUp(self):
        self.physics = TrainPhysics()

    def test_downhill_increases_distance(self):
        """Bajada (gradient_pct < 0) → mayor distancia de frenado."""
        d_flat = self.physics.braking_distance(60.0, 0.0, gradient_pct=0.0)
        d_down = self.physics.braking_distance(60.0, 0.0, gradient_pct=-2.0)
        self.assertGreater(d_down, d_flat)

    def test_uphill_decreases_distance(self):
        """Subida (gradient_pct > 0) → menor distancia de frenado."""
        d_flat = self.physics.braking_distance(60.0, 0.0, gradient_pct=0.0)
        d_up = self.physics.braking_distance(60.0, 0.0, gradient_pct=2.0)
        self.assertLess(d_up, d_flat)

    def test_steep_downhill_longer_than_gentle(self):
        """Bajada fuerte produce mayor distancia que bajada leve."""
        d_gentle = self.physics.braking_distance(60.0, 0.0, gradient_pct=-1.0)
        d_steep = self.physics.braking_distance(60.0, 0.0, gradient_pct=-3.0)
        self.assertGreater(d_steep, d_gentle)


class TestBrakingDistanceAcceleration(unittest.TestCase):
    """Tests con aceleración actual (transición accel→brake)."""

    def setUp(self):
        self.physics = TrainPhysics()

    def test_positive_accel_increases_distance(self):
        """Aceleración actual positiva añade distancia de transición."""
        d_no_accel = self.physics.braking_distance(60.0, 30.0)
        d_accel = self.physics.braking_distance(60.0, 30.0,
                                                 current_accel_ms2=0.5)
        self.assertGreater(d_accel, d_no_accel)

    def test_zero_accel_same_as_none(self):
        """Aceleración = 0 no cambia la distancia."""
        d_none = self.physics.braking_distance(60.0, 30.0)
        d_zero = self.physics.braking_distance(60.0, 30.0,
                                                current_accel_ms2=0.0)
        self.assertAlmostEqual(d_none, d_zero, places=1)


class TestShouldBrakeForNext(unittest.TestCase):
    """Tests para should_brake_for_next()."""

    def setUp(self):
        self.physics = TrainPhysics()

    def test_no_limit_returns_false(self):
        """Sin límite siguiente, no frena."""
        self.assertFalse(
            self.physics.should_brake_for_next(60.0, None, 500.0))

    def test_limit_higher_than_speed_returns_false(self):
        """Límite mayor que velocidad actual, no frena."""
        self.assertFalse(
            self.physics.should_brake_for_next(30.0, 60.0, 100.0))

    def test_close_distance_returns_true(self):
        """Distancia muy corta al límite inferior, debe frenar."""
        self.assertTrue(
            self.physics.should_brake_for_next(60.0, 30.0, 10.0))

    def test_far_distance_returns_false(self):
        """Distancia muy lejana, no frena aún."""
        self.assertFalse(
            self.physics.should_brake_for_next(60.0, 30.0, 5000.0))


if __name__ == "__main__":
    unittest.main()
