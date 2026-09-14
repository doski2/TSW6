from __future__ import annotations

import _path  # noqa: F401

from pathlib import Path
from unittest.mock import patch

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.command import BrakeCommand
from tsw6v2.constants import NEUTRAL_NOTCH, SERVICE_MAX_BRAKE
from tsw6v2.learner import LearnerProfile
from tsw6v2.loop import AgentLoop, AgentSnapshot
from tsw6v2.planning_feed import PlanningSnapshot
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

    def test_apply_release_skipped_when_already_neutral(self) -> None:
        loop = AgentLoop()
        loop._apply_brake_command(
            BrakeCommand(kind="RELEASE", target_notch=NEUTRAL_NOTCH, phase="NEU"),
            lever=NEUTRAL_NOTCH,
        )
        assert loop.target_notch is None

    def test_coast_throttle_requests_neutral_from_power_session_225330(self) -> None:
        """P2 + COAST_THROTTLE debe pedir neutro (no confundir con RELEASE ya suelto)."""
        loop = AgentLoop()
        loop._apply_brake_command(
            BrakeCommand(
                kind="COAST_THROTTLE",
                target_notch=NEUTRAL_NOTCH,
                reason="Soltar tracción antes de freno",
            ),
            lever=6,
        )
        assert loop.target_notch == NEUTRAL_NOTCH

    def test_clear_target_when_driver_accelerates(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
        loop.request_neutral()
        with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
            out = loop.step()
        assert loop.target_notch is None
        assert not out.ipc_sent
        ipc.assert_not_called()

    def test_holds_neutral_ipc_while_brake_releasing(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=3)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0)
        loop.request_neutral()
        with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
            loop.step()
        ipc.assert_called_once()

    def test_holds_brake_target_while_handle_at_neutral(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=4)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
        loop.request_notch(3)
        with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
            from tsw6v2.decision import LimitBrakeDecision

            eval_tick.return_value = LimitBrakeDecision.idle(reason="apply_deferred")
            with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
                loop.step()
        assert loop.target_notch == 3
        ipc.assert_called_once()

    def test_clear_brake_target_when_handle_reached_b1(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=3)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
        loop.request_notch(3)
        with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
            from tsw6v2.decision import LimitBrakeDecision

            eval_tick.return_value = LimitBrakeDecision.idle(reason="command_none")
            with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
                loop.step()
        assert loop.target_notch is None
        ipc.assert_not_called()

    def test_clear_brake_target_when_handle_stronger_than_target(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=2)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
        loop.request_notch(3)
        with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
            from tsw6v2.decision import LimitBrakeDecision

            eval_tick.return_value = LimitBrakeDecision.idle(reason="command_none")
            with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
                loop.step()
        assert loop.target_notch is None
        ipc.assert_not_called()

    def test_manual_override_when_driver_brakes_from_neutral(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=4)
        loop = AgentLoop(
            getdata_path=gd,
            post_ipc_sleep_s=0.0,
            driver_override_cooldown_s=5.0,
            limit_brake_enabled=True,
        )
        loop.request_neutral()
        loop._last_lever = 4
        write_getdata_line(gd, seq=2, lever=3)
        with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
            from tsw6v2.decision import LimitBrakeDecision

            eval_tick.return_value = LimitBrakeDecision.idle(reason="command_none")
            with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
                out = loop.step()
        assert loop.target_notch is None
        assert not out.ipc_sent
        ipc.assert_not_called()
        assert out.driver_override_s > 0.0

    def test_manual_override_blocks_p1_ipc_while_active(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=3)
        loop = AgentLoop(
            getdata_path=gd,
            post_ipc_sleep_s=0.0,
            driver_override_cooldown_s=10.0,
            limit_brake_enabled=True,
        )
        loop._arm_manual_override()
        with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
            from tsw6v2.command import BrakeCommand
            from tsw6v2.decision import LimitBrakeDecision

            eval_tick.return_value = LimitBrakeDecision(
                command=BrakeCommand(kind="APPLY", target_notch=2),
                reason="plan",
            )
            with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
                out = loop.step()
        assert loop.target_notch is None
        assert not out.ipc_sent
        ipc.assert_not_called()

    def test_clear_target_at_neutral_after_release(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=4)
        loop = AgentLoop(getdata_path=gd, post_ipc_sleep_s=0.0, limit_brake_enabled=True)
        loop.request_neutral()
        with patch("tsw6v2.loop.dispatch_step_toward_notch", return_value={"ok": True}) as ipc:
            loop.step()
        assert loop.target_notch is None
        ipc.assert_not_called()

    def test_auto_profile_load(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        profile = profiles / "class323.json"
        profile.write_text('{"decel_by_notch": {"3": 0.44}}', encoding="utf-8")
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6, vehicle="Class323")
        loop = AgentLoop(
            getdata_path=gd,
            post_ipc_sleep_s=0.0,
            profiles_dir=profiles,
        )
        out = loop.step()
        assert loop.loaded_profile_path == profile
        assert loop.active_learner.predict_decel(3, 50.0, 0.0) == 0.44
        assert out.vehicle == "Class323"

    def test_dwell_applies_b1_while_stopped_neutral(self, tmp_path: Path) -> None:
        """TSW exige freno (B1) para abrir puertas; no RELEASE al entrar STOPPED."""
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=4, speed_ms=0.0)
        loop = AgentLoop(
            getdata_path=gd,
            post_ipc_sleep_s=0.0,
            station_brake_enabled=True,
            limit_brake_enabled=False,
        )
        loop._station_gate.state = "STOPPED"
        snap = PlanningSnapshot(station_distance_m=30.0)
        with patch.object(loop._station_planning, "update", return_value=snap):
            with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
                from tsw6v2.decision import LimitBrakeDecision

                eval_tick.return_value = LimitBrakeDecision.idle(reason="no_plan")
                loop.step()
        assert loop.target_notch == SERVICE_MAX_BRAKE

    def test_decision_releases_brake_on_departing(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=3, speed_ms=0.0)
        loop = AgentLoop(
            getdata_path=gd,
            post_ipc_sleep_s=0.0,
            station_brake_enabled=True,
            limit_brake_enabled=False,
        )
        loop._station_gate.state = "DEPARTING"
        snap = PlanningSnapshot(station_distance_m=30.0)
        with patch.object(loop._station_planning, "update", return_value=snap):
            with patch("tsw6v2.loop.evaluate_p1_tick") as eval_tick:
                from tsw6v2.command import release_brake_command
                from tsw6v2.decision import LimitBrakeDecision

                rel = release_brake_command(at_target=True)
                eval_tick.return_value = LimitBrakeDecision(
                    command=rel,
                    reason="release",
                    phase="NEU",
                    handle_notch=NEUTRAL_NOTCH,
                )
                loop.step()
        assert loop.target_notch == NEUTRAL_NOTCH

    def test_auto_profile_skipped_when_explicit(self, tmp_path: Path) -> None:
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        profile = profiles / "class323.json"
        profile.write_text('{"decel_by_notch": {"3": 0.99}}', encoding="utf-8")
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6, vehicle="Class323")
        explicit = LearnerProfile()
        loop = AgentLoop(
            getdata_path=gd,
            learner=explicit,
            auto_profile=True,
            profiles_dir=profiles,
            post_ipc_sleep_s=0.0,
        )
        loop.step()
        assert loop.loaded_profile_path is None
        assert loop.active_learner is explicit


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
