"""Tests FreightLearner — Fase 2 multi-eje."""

import json
import os
import tempfile
import time
import unittest

from freight_learner import (
    FreightLearner,
    FREIGHT_AXES,
    create_learner,
    freight_quantize_level,
    infer_active_axis,
    profile_layout_from_file,
)
from online_learner import MIN_STABLE_S, OnlineLearner


class TestFreightQuantize(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(freight_quantize_level("throttle", 5.0), 5)
        self.assertEqual(freight_quantize_level("train_brake", 0.5), 5)
        self.assertEqual(freight_quantize_level("dyn_brake", 0.5), 4)


class TestInferActiveAxis(unittest.TestCase):
    def test_single_change(self):
        prev = {"throttle": 3, "train_brake": 0.0, "ind_brake": 0.0, "dyn_brake": 0.0}
        curr = {"throttle": 4, "train_brake": 0.0, "ind_brake": 0.0, "dyn_brake": 0.0}
        axis, level = infer_active_axis(prev, curr)
        self.assertEqual(axis, "throttle")
        self.assertEqual(level, 4.0)


class TestFreightLearnerFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "layout": "freight_na"}, f)
        self.learner = FreightLearner(save_path=self.tmp.name, min_speed=2.0)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _feed_window(self, axis, level, accel, controls):
        """Varias llamadas a feed espaciadas ~2 s (un eje estable)."""
        speeds = [15.0, 15.5, 16.0, 16.5, 17.0, 17.5, 18.0]
        result = None
        step = MIN_STABLE_S / (len(speeds) - 1) + 0.05
        for spd in speeds:
            result = self.learner.feed(axis, level, spd, 0.0, accel, controls)
            time.sleep(step)
        return result

    def test_throttle_positive_accel(self):
        ctrl = {"throttle": 5, "train_brake": 0.0, "ind_brake": 0.0, "dyn_brake": 0.0}
        self._feed_window("throttle", 5.0, 0.25, ctrl)
        self.assertGreater(self.learner.sample_count("throttle"), 0)
        self.assertIn("throttle", self.learner.last_reason)

    def test_train_brake_negative_accel(self):
        ctrl = {"throttle": 0, "train_brake": 0.5, "ind_brake": 0.0, "dyn_brake": 0.0}
        self._feed_window("train_brake", 0.5, -0.4, ctrl)
        self.assertGreater(self.learner.sample_count("train_brake"), 0)
        self.assertIn("train_brake", self.learner.last_reason)

    def test_save_v2_schema(self):
        ctrl = {"throttle": 4, "train_brake": 0.0, "ind_brake": 0.0, "dyn_brake": 0.0}
        self._feed_window("throttle", 4.0, 0.2, ctrl)
        with open(self.tmp.name, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["schema_version"], 2)
        self.assertEqual(d["layout"], "freight_na")
        self.assertIn("throttle", d)
        self.assertTrue(d["throttle"]["n_bands"][0] or d["throttle"]["n"])


class TestCreateLearner(unittest.TestCase):
    def test_freight_for_sd40(self):
        l = create_learner(vehicle="BNSF SD40-2 C", layout="freight_na")
        self.assertIsInstance(l, FreightLearner)

    def test_combined_for_323(self):
        l = create_learner(vehicle="Class 323", layout="combined")
        self.assertIsInstance(l, OnlineLearner)


if __name__ == "__main__":
    unittest.main()
