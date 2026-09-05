from __future__ import annotations

import _path  # noqa: F401

from pathlib import Path

from tsw6v2.learner import LearnerProfile


def test_learner_empty() -> None:
    p = LearnerProfile()
    assert p.predict_decel(3, 50.0, 0.0) is None


def test_learner_from_json(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text('{"decel_by_notch": {"3": 0.42}}', encoding="utf-8")
    p = LearnerProfile.from_json(path)
    assert p.predict_decel(3, 50.0, 0.0) == 0.42


def test_learner_load_default_missing(tmp_path: Path) -> None:
    p = LearnerProfile.load_default("Class 323", profiles_dir=tmp_path)
    assert p.predict_decel(3, 50.0, 0.0) is None


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
