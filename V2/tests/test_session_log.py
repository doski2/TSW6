from __future__ import annotations

from pathlib import Path

import _path  # noqa: F401

from tsw6v2.loop import AgentLoop
from tsw6v2.session_log import save_learner_if_dirty, session_profile_note


def test_save_learner_uses_vehicle_profile_path(tmp_path: Path) -> None:
    loop = AgentLoop(profiles_dir=tmp_path / "profiles")
    loop._note_vehicle("Class 323")
    loop.active_learner.observe_air(4, 1.0, now=0.0)
    loop.active_learner.observe_air(3, 1.1, now=0.1)
    loop.active_learner.observe_air(3, 2.6, now=2.1)

    msg = save_learner_if_dirty(loop, None)
    assert msg is not None
    path = tmp_path / "profiles" / "class_323.json"
    assert path.is_file()
    assert "fill=" in msg

    note = session_profile_note(loop, None)
    assert note is not None
    assert "auto-save" in note


def test_session_profile_note_explicit_path() -> None:
    loop = AgentLoop()
    explicit = Path("custom/profile.json")
    assert session_profile_note(loop, explicit) == str(explicit)
