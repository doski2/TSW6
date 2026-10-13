from __future__ import annotations

import json
from pathlib import Path

import _path  # noqa: F401
import pytest

from learn_helpers import feed_stable_decel

from tsw6v2.learner import LearnerProfile


def test_electric_amps_do_not_enter_air_decel() -> None:
    p = LearnerProfile()
    p.note_amps(-80.0)
    assert p.observe_brake_decel(
        handle=3,
        speed_mph=30.0,
        gradient_pct=0.0,
        accel_ms2=-0.4,
        lever=3,
        brake_cyl_bar=2.0,
    ) is False
    ev = p.pop_learn_event()
    assert ev is not None and ev.reason == "electric"
    assert p.decel_observe_n == 0
    assert p.regen_n == 1


def test_mc_position_learns_without_uk_notch() -> None:
    p = LearnerProfile()
    ok = False
    for i in range(8):
        ok = p.observe_mc_brake(
            fraction=0.49,
            speed_mph=30.0 - i * 0.4,
            gradient_pct=-0.4,
            accel_ms2=-0.35,
            now=100.0 + i * 0.4,
        ) or ok
    assert p.mc_decel_n == 1
    assert ok is True
    ev = p.pop_learn_event()
    assert ev is not None and ev.accepted and ev.kind == "mc"


def test_note_amps_counts_regen_only() -> None:
    p = LearnerProfile()
    before = p.predict_decel(3, 40.0, 0.0)
    p.note_amps(300.0)
    p.note_amps(-120.0)
    p.note_amps(None)
    assert p.regen_n == 1
    assert p.predict_decel(3, 40.0, 0.0) == before


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
    assert b1 is not None and b1 > 0.15
    assert b2 is not None and b2 > b1
    assert b3 is not None and b3 > b2


def test_learner_load_default_missing(tmp_path: Path) -> None:
    p = LearnerProfile.load_default("Class 323", profiles_dir=tmp_path)
    assert p.predict_decel(3, 50.0, 0.0) is None


def test_learner_profile_path_for_vehicle(tmp_path: Path) -> None:
    path = LearnerProfile.profile_path_for_vehicle(
        "Class 323",
        profiles_dir=tmp_path,
    )
    assert path == tmp_path / "class_323.json"
    assert LearnerProfile.profile_path_for_vehicle("?") is None


def test_learner_resolve_profile_path(tmp_path: Path) -> None:
    path = tmp_path / "rvm_bcc_wrm_class323_dms_a_c.json"
    path.write_text('{"decel_by_notch": {"3": 0.5}}', encoding="utf-8")
    found = LearnerProfile.resolve_profile_path(
        "rvm_bcc_wrm_class323_dms_a_c", profiles_dir=tmp_path
    )
    assert found == path
    assert LearnerProfile.resolve_profile_path("missing", profiles_dir=tmp_path) is None


def test_learner_observe_brake_decel_updates_ema(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "ema": {"3": -0.56},
                "n": {"3": 10},
                "ema_bands": [{"3": -0.40}, {"3": -0.56}, {}],
                "n_bands": [{"3": 5}, {"3": 20}, {}],
            }
        ),
        encoding="utf-8",
    )
    p = LearnerProfile.from_json(path)
    before = p.predict_decel(3, 50.0, 0.0)
    assert before is not None

    ok = feed_stable_decel(p, accel=-0.58)
    assert ok is True
    assert p.decel_observe_n == 1
    after = p.predict_decel(3, 50.0, 0.0)
    assert after is not None and after > before

    p.save_json(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["n_bands"][1]["3"] == 21


def test_learner_observe_rejects_non_brake_accel() -> None:
    p = LearnerProfile()
    assert not p.observe_brake_decel(
        handle=3,
        speed_mph=50.0,
        gradient_pct=0.0,
        accel_ms2=0.12,
    )
    assert p.decel_observe_n == 0


def test_learner_observe_rejects_low_pressure() -> None:
    p = LearnerProfile()
    assert not p.observe_brake_decel(
        handle=3,
        speed_mph=50.0,
        gradient_pct=0.0,
        accel_ms2=-0.50,
        lever=3,
        brake_cyl_bar=1.2,
    )
    assert p.decel_observe_n == 0


def test_learner_load_default_found(tmp_path: Path) -> None:
    path = tmp_path / "class_323.json"
    path.write_text('{"decel_by_notch": {"3": 0.33}}', encoding="utf-8")
    p = LearnerProfile.load_default("Class 323", profiles_dir=tmp_path)
    assert p.predict_decel(3, 50.0, 0.0) == 0.33


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())


def _feed_mixed_decel(p: LearnerProfile) -> None:
    mph = [20.0, 19.6, 19.2, 18.8, 18.4, 18.0, 17.6, 17.2, 16.8, 16.4]
    for rep in range(4):
        for i, m in enumerate(mph):
            p.observe_brake_decel(
                handle=2,
                speed_mph=m,
                gradient_pct=-0.6,
                accel_ms2=-0.38,
                lever=2,
                brake_cyl_bar=10.7,
                now=float(rep * 100 + i),
                brake_kind="mixed",
            )


def test_mixed_profile_survives_save_and_reload(tmp_path: Path) -> None:
    """Perfil ``mixed`` (freno eléctrico + aire) guardado, recargado y usado en predicción."""
    from tsw6v2.learner import _predict_for_kind

    p = LearnerProfile()
    p.note_amps(-80.0)
    _feed_mixed_decel(p)
    path = tmp_path / "profile.json"
    p.save_json(path)

    reloaded = LearnerProfile.from_json(path)
    assert "mixed" in reloaded.__dict__.get("_v1_by_kind", {})
    assert _predict_for_kind(reloaded, "mixed")(2, 18.0, -0.6) == pytest.approx(0.38, abs=0.02)
    assert _predict_for_kind(reloaded, "air")(2, 18.0, -0.6) is None


def test_electric_sample_rejected_for_air_accepted_for_mixed() -> None:
    air = LearnerProfile()
    air.note_amps(-80.0)
    air.observe_brake_decel(
        handle=3, speed_mph=30.0, gradient_pct=0.0, accel_ms2=-0.4,
        lever=3, brake_cyl_bar=2.0, brake_kind="air",
    )
    air_ev = air.pop_learn_event()
    assert air_ev is not None
    assert air_ev.reason == "electric"

    mixed = LearnerProfile()
    mixed.note_amps(-80.0)
    mixed.observe_brake_decel(
        handle=3, speed_mph=30.0, gradient_pct=0.0, accel_ms2=-0.4,
        lever=3, brake_cyl_bar=2.0, brake_kind="mixed",
    )
    ev = mixed.pop_learn_event()
    assert ev is None or ev.reason != "electric"
    assert mixed._decel_window.last_reason != "electric"