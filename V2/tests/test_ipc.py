from __future__ import annotations

import _path  # noqa: F401

from pathlib import Path
from unittest.mock import patch

from tsw6v2.ipc import dispatch_step_toward_notch, drive_to_notch, ipc_steps_needed
from tsw6v2.testdata import write_getdata_line


class TestIpcStepsNeeded:
    def test_steps_between_notches(self) -> None:
        assert ipc_steps_needed(6, 3) == 3
        assert ipc_steps_needed(4, 4) == 0


class TestDriveToNotch:
    def test_reaches_target(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        write_getdata_line(gd, seq=1, lever=6)
        calls: list[int] = []

        def fake(target: int, *, cmd_id: int, ack_timeout_s: float = 0.12, **_: object):
            calls.append(cmd_id)
            write_getdata_line(gd, seq=1 + len(calls), lever=max(6 - len(calls), 3))
            return {"ok": True}

        with patch("tsw6v2.ipc.dispatch_step_toward_notch", side_effect=fake):
            ok, snap, _, n = drive_to_notch(3, path=gd, step_pause_s=0.0, step_wait_s=0.01)
        assert ok and n == 3 and snap and snap.combined_handle_notch() == 3


class TestDriveToNotchMc:
    def test_mc_single_ipc_command(self, tmp_path: Path) -> None:
        gd = tmp_path / "GetData.txt"
        vehicle = "RVM_NYH_MNR_M3a-B_C"
        write_getdata_line(gd, seq=1, lever=4, vehicle=vehicle)
        with patch(
            "tsw6v2.ipc.dispatch_ipc_master_controller",
            return_value={"ok": True, "value": 0.85},
        ) as mc:
            with patch("tsw6v2.ipc.dispatch_ipc_combined_notch") as notch:
                ok, _, results, n = drive_to_notch(
                    3,
                    path=gd,
                    vehicle=vehicle,
                    step_pause_s=0.0,
                    step_wait_s=0.01,
                )
        assert ok and n == 1 and len(results) == 1
        mc.assert_called_once()
        notch.assert_not_called()


class TestDispatchStepMcPackage:
    def test_mc_package_calls_master_controller(self) -> None:
        pkg = {
            "layout": "master_controller",
            "uk_combined_notch_ipc": {"3": 0.85},
        }
        with patch(
            "tsw6v2.ipc.dispatch_ipc_master_controller",
            return_value={"ok": True, "value": 0.85},
        ) as mc:
            with patch("tsw6v2.ipc.dispatch_ipc_combined_notch") as notch:
                dispatch_step_toward_notch(3, cmd_id=7, vehicle_package=pkg)
        mc.assert_called_once()
        assert mc.call_args[0][0] == 0.85
        notch.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
