"""Perfil L4 MC sobrevive a carga learner JSON (auto-profile)."""

from __future__ import annotations

import json
from pathlib import Path

from tsw6v2.learner import LearnerProfile


def test_mc_brake_profile_after_from_json(tmp_path: Path) -> None:
    learner = LearnerProfile()
    m3a = {
        "layout": "master_controller",
        "brake_air": {"model": "master_controller"},
    }
    learner.apply_vehicle_brake_profile(m3a)
    assert learner.air_ready(11.0, lever=4) is True

    path = tmp_path / "p.json"
    path.write_text(json.dumps({"brake_fill_s": 2.5, "brake_fill_n": 1}), encoding="utf-8")
    replaced = LearnerProfile.from_json(path)
    assert replaced.air_ready(11.0, lever=4) is False

    replaced.apply_vehicle_brake_profile(m3a)
    assert replaced.air_ready(11.0, lever=4) is True
