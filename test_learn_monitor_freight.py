"""Tests UI freight del monitor de aprendizaje — Fase 3."""

import json
import os
import tempfile
import unittest

from freight_learner import FreightLearner
from learn_monitor import LearnMonitor
from online_learner import _SPEED_BANDS
from train_labels import FREIGHT_AXIS_ROWS, control_level_label, control_value_label


class TestControlLabels(unittest.TestCase):
    def test_level_labels(self):
        self.assertEqual(control_level_label("throttle", 5), "N5")
        self.assertEqual(control_level_label("train_brake", 5), "50%")
        self.assertEqual(control_level_label("ind_brake", -4), "-40%")
        self.assertEqual(control_level_label("dyn_brake", 3), "D3")

    def test_value_labels(self):
        self.assertEqual(control_value_label("throttle", 5.0), "N5")
        self.assertEqual(control_value_label("train_brake", 0.5), "50%")
        self.assertEqual(control_value_label("ind_brake", -0.3), "-30%")
        self.assertEqual(control_value_label("dyn_brake", 0.0), "Off")


class TestLearnMonitorFreight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "layout": "freight_na"}, f)
        self.learner = FreightLearner(save_path=self.tmp.name)
        self.monitor = LearnMonitor(
            self.learner, "BNSF SD40-2 C", target=8, layout="freight_na")

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_total_progress_cells(self):
        expected = sum(
            len(rows) * len(_SPEED_BANDS)
            for _, rows in FREIGHT_AXIS_ROWS.values())
        done, total = self.monitor._total_progress()
        self.assertEqual(total, expected)
        self.assertEqual(done, 0)

    def test_count_freight_after_sample(self):
        st = self.learner._stores["throttle"]
        st["n_bands"][1][5] = 3
        self.assertEqual(self.monitor._count_freight("throttle", 1, 5), 3)

    def test_render_freight_no_crash(self):
        self.monitor._cur_speed = 25.0
        self.monitor._cur_controls = {
            "throttle": 5.0,
            "train_brake": 0.0,
            "ind_brake": 0.0,
            "dyn_brake": 0.0,
        }
        self.monitor._render_freight()

    def test_hints_freight_mentions_axis(self):
        hints = self.monitor._hints_freight()
        self.assertTrue(any("tracción" in h.lower() for h in hints))


if __name__ == "__main__":
    unittest.main()
