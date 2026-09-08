from __future__ import annotations

import json
from pathlib import Path

import _path  # noqa: F401
import pytest

from tsw6v2.learner import LearnerProfile


def test_learner_empty() -> None:
    p = LearnerProfile()
    assert p.predict_decel(3, 50.0, 0.0) is None


def test_learner_from_json(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text('{"decel_by_notch": {"3": 0.42}}', encoding="utf-8")
    p = LearnerProfile.from_json(path)
    assert p.predict_decel(3, 50.0, 0.0) == 0.42


def test_learner_v1_ema_bands(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "ema": {"3": -0.56},
                "n": {"3": 10},
                "ema_bands": [
                    {"3": -0.40},
                    {"3": -0.56},
                    {"3": -0.70},
                ],
                "n_bands": [
                    {"3": 5},
                    {"3": 20},
                    {"3": 3},
                ],
                "brake_fill_s": 2.5,
            }
        ),
        encoding="utf-8",
    )
    p = LearnerProfile.from_json(path)
    assert p.has_decel_profile
    assert p.brake_fill_s == 2.5
    d = p.predict_decel(3, 50.0, 0.0)
    assert d is not None and abs(d - 0.56) < 0.02
    d_down = p.predict_decel(3, 50.0, -1.0)
    assert d_down is not None and d_down < d


def test_learner_v1_save_preserves_ema(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        '{"ema": {"3": -0.56}, "n": {"3": 10}, "brake_fill_s": 2.5, "brake_fill_n": 0}',
        encoding="utf-8",
    )
    p = LearnerProfile.from_json(path)
    p.observe_air(4, 1.0, now=0.0)
    p.observe_air(3, 1.1, now=0.1)
    p.observe_air(3, 2.6, now=2.1)
    p.save_json(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ema"]["3"] == -0.56
    assert saved["n"]["3"] == 10
    assert saved["brake_fill_n"] >= 1


def test_learner_real_class323_profile() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "logs" / "profiles" / "RVM_BCC_WRM_Class323_DMS_A_C.json"
    if not path.is_file():
        pytest.skip("perfil 323 no presente")
    p = LearnerProfile.from_json(path)
    assert p.has_decel_profile
    b1 = p.predict_decel(3, 50.0, 0.0)
    b2 = p.predict_decel(2, 50.0, 0.0)
    b3 = p.predict_decel(1, 50.0, 0.0)
    assert b1 is not None and 0.45 < b1 < 0.65
    assert b2 is not None and b2 > b1
    assert b3 is not None and b3 > b2


def test_learner_load_default_missing(tmp_path: Path) -> None:
    p = LearnerProfile.load_default("Class 323", profiles_dir=tmp_path)
    assert p.predict_decel(3, 50.0, 0.0) is None


def test_learner_resolve_profile_path(tmp_path: Path) -> None:
    path = tmp_path / "rvm_bcc_wrm_class323_dms_a_c.json"
    path.write_text('{"decel_by_notch": {"3": 0.5}}', encoding="utf-8")
    found = LearnerProfile.resolve_profile_path(
        "rvm_bcc_wrm_class323_dms_a_c", profiles_dir=tmp_path
    )
    assert found == path
    assert LearnerProfile.resolve_profile_path("missing", profiles_dir=tmp_path) is None


def test_learner_load_default_found(tmp_path: Path) -> None:
    path = tmp_path / "class_323.json"
    path.write_text('{"decel_by_notch": {"3": 0.33}}', encoding="utf-8")
    p = LearnerProfile.load_default("Class 323", profiles_dir=tmp_path)
    assert p.predict_decel(3, 50.0, 0.0) == 0.33


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
