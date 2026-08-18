import tempfile
import unittest
from pathlib import Path

from tsw_ue4ss_reader import (
    ProbeSnapshot,
    SessionLogger,
    parse_probe_line,
    power_to_combined_notch,
)


class TestUe4ssReader(unittest.TestCase):
    def test_parse_probe_line(self) -> None:
        line = (
            "seq=42 speed_ms=12.34 power=3 power_neg=0 train_brake=0.1 "
            "loco_brake=0 dyn_brake=0 accel_ms2=-0.05 max_speed_ms=22.2 "
            "speed_limit_ms=20 vehicle=BNSF_SD40_2_C"
        )
        data = parse_probe_line(line)
        self.assertEqual(data["seq"], 42)
        self.assertAlmostEqual(data["speed_ms"], 12.34)
        self.assertEqual(data["vehicle"], "BNSF_SD40_2_C")
        self.assertFalse(data["power_neg"])

    def test_missing_values(self) -> None:
        data = parse_probe_line("seq=1 speed_ms=? power=? vehicle=?")
        self.assertIsNone(data["speed_ms"])
        self.assertEqual(data["vehicle"], "?")

    def test_power_to_notch(self) -> None:
        self.assertEqual(power_to_combined_notch(0), 4)
        self.assertEqual(power_to_combined_notch(-3), 1)
        self.assertEqual(power_to_combined_notch(2), 6)

    def test_parse_handle_notch(self) -> None:
        data = parse_probe_line("seq=1 handle_notch=4 power=0 vehicle=Class323")
        self.assertEqual(data["handle_notch"], 4)

    def test_parse_gradient_pct(self) -> None:
        line = (
            "seq=1 speed_ms=10 gradient_pct=1.25 speed_limit_ms=20 vehicle=Class323"
        )
        data = parse_probe_line(line)
        self.assertAlmostEqual(data["gradient_pct"], 1.25)

    def test_to_telemetry_dict(self) -> None:
        snap = ProbeSnapshot.from_dict(
            {"speed_ms": 10.0, "gradient_pct": -0.5, "vehicle": "Class323"}
        )
        telem = snap.to_telemetry_dict()
        self.assertAlmostEqual(telem["speed_mph"], 22.36936, places=3)
        self.assertAlmostEqual(telem["gradient_pct"], -0.5)
        self.assertEqual(telem["vehicle_name"], "Class323")
        self.assertEqual(telem["source"], "ue4ss")


    def test_session_logger_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "test_log.txt"
            getdata = Path(tmp) / "GetData.txt"
            logger = SessionLogger(log_path, getdata)
            snap = ProbeSnapshot.from_dict(
                {
                    "seq": 10,
                    "speed_ms": 10.0,
                    "power": 0,
                    "handle_notch": 4,
                    "vehicle": "Class323",
                }
            )
            logger.log_sample(snap, 19.5, "seq=10 speed_ms=10 power=0 vehicle=Class323")
            logger.close()
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("time_s,seq,hz", text)
            self.assertIn("Class323", text)
            self.assertIn("# muestras: 1", text)
            self.assertIn("# raw: seq=10", text)


if __name__ == "__main__":
    unittest.main()
