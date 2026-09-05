from __future__ import annotations

import _path  # noqa: F401

from pathlib import Path
from unittest.mock import patch

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.constants import NEUTRAL_NOTCH
from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.testdata import write_getdata_line


class TestAgentSnapshot:
    def test_from_probe(self) -> None:
        snap = ProbeSnapshot.from_dict(
            {"seq": 1, "speed_ms": 10.0, "handle_notch": 4, "lever_notch": 4}
        )
        agent = AgentSnapshot.from_probe(snap, tick=1, target_notch=3)
        assert agent.lever_notch == 4
        assert agent.speed_mph is not None


class TestAgentLoop:
    def test_step_no_ipc_without_target(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0)
        out = loop.step()
        assert not out.ipc_sent and out.lever_notch == 6

    def test_step_one_ipc(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0)
        loop.request_notch(3)
        with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}):
            out = loop.step()
        assert out.ipc_sent and out.ipc_ok

    def test_request_neutral(self) -> None:
        loop = AgentLoop()
        loop.request_neutral()
        assert loop.target_notch == NEUTRAL_NOTCH


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
