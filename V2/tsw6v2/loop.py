"""Bucle agente — un tick: GetData → decisión → (opcional) un paso IPC."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.getdata import ProbeSnapshot, default_getdata_path, read_probe_file
from tsw6v2.command import BrakeCommand, BrakeReleaseState
from tsw6v2.constants import AGENT_ACK_TIMEOUT_S, MS_TO_MPH, NEUTRAL_NOTCH
from tsw6v2.decision import evaluate_limit_tick
from tsw6v2.ipc import dispatch_step_toward_notch, probe_lever
from tsw6v2.learner import LearnerProfile
from tsw6v2.limits import LimitBrakeState
from tsw6v2.p1_layers import classify_layer

DEFAULT_ACK_TIMEOUT_S = AGENT_ACK_TIMEOUT_S


@dataclass
class AgentSnapshot:
    tick: int = 0
    seq: Optional[int] = None
    speed_mph: Optional[float] = None
    lever_notch: Optional[int] = None
    train_brake: Optional[float] = None
    dyn_brake: Optional[float] = None
    brake_cyl_bar: Optional[float] = None
    accel_ms2: Optional[float] = None
    gradient_pct: Optional[float] = None
    target_notch: Optional[int] = None
    last_cmd_id: Optional[int] = None
    last_ack_ok: Optional[bool] = None
    vehicle: str = "?"
    ipc_sent: bool = False
    ipc_ok: Optional[bool] = None
    ipc_error: str = ""
    signal_red: Optional[bool] = None
    signal_dist_m: Optional[float] = None
    limit_mph: Optional[float] = None
    limit_dist_m: Optional[float] = None
    effective_limit_mph: Optional[float] = None
    p1_phase: str = ""
    p1_cmd: str = ""
    p1_dist_start_m: Optional[float] = None
    p1_apply_now: Optional[bool] = None
    p1_detail: str = ""
    p1_reason: str = ""
    p1_handle: Optional[int] = None
    p1_layer: str = ""
    ipc_cmd_id: Optional[int] = None
    brake_fill_s: Optional[float] = None

    @classmethod
    def from_probe(
        cls,
        snap: Optional[ProbeSnapshot],
        *,
        tick: int = 0,
        target_notch: Optional[int] = None,
        ipc_sent: bool = False,
        ipc_result: Optional[dict[str, Any]] = None,
        limit_mph: Optional[float] = None,
        limit_dist_m: Optional[float] = None,
        effective_limit_mph: Optional[float] = None,
        p1_phase: str = "",
        p1_cmd: str = "",
        p1_dist_start_m: Optional[float] = None,
        p1_apply_now: Optional[bool] = None,
        p1_detail: str = "",
        p1_reason: str = "",
        p1_handle: Optional[int] = None,
        p1_layer: str = "",
        ipc_cmd_id: Optional[int] = None,
        brake_fill_s: Optional[float] = None,
    ) -> AgentSnapshot:
        if snap is None:
            return cls(tick=tick, target_notch=target_notch, ipc_sent=ipc_sent)
        mph = snap.speed_ms * MS_TO_MPH if snap.speed_ms is not None else None
        dist_m = (
            snap.signal_dist_cm / 100.0
            if snap.signal_dist_cm is not None
            else None
        )
        out = cls(
            tick=tick,
            seq=snap.seq,
            speed_mph=mph,
            lever_notch=probe_lever(snap),
            train_brake=snap.train_brake,
            dyn_brake=snap.dyn_brake,
            brake_cyl_bar=snap.brake_cyl_bar,
            accel_ms2=snap.accel_ms2,
            gradient_pct=snap.gradient_pct,
            target_notch=target_notch,
            last_cmd_id=snap.last_cmd_id,
            last_ack_ok=snap.last_ack_ok,
            vehicle=snap.vehicle or "?",
            ipc_sent=ipc_sent,
            signal_red=snap.signal_red,
            signal_dist_m=dist_m,
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            effective_limit_mph=effective_limit_mph,
            p1_phase=p1_phase,
            p1_cmd=p1_cmd,
            p1_dist_start_m=p1_dist_start_m,
            p1_apply_now=p1_apply_now,
            p1_detail=p1_detail,
            p1_reason=p1_reason,
            p1_handle=p1_handle,
            p1_layer=p1_layer,
            ipc_cmd_id=ipc_cmd_id,
            brake_fill_s=brake_fill_s,
        )
        if ipc_result is not None:
            out.ipc_ok = bool(ipc_result.get("ok"))
            out.ipc_error = str(ipc_result.get("error") or "")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "seq": self.seq,
            "speed_mph": self.speed_mph,
            "lever_notch": self.lever_notch,
            "train_brake": self.train_brake,
            "dyn_brake": self.dyn_brake,
            "target_notch": self.target_notch,
            "vehicle": self.vehicle,
            "ipc_sent": self.ipc_sent,
            "ipc_ok": self.ipc_ok,
        }


@dataclass
class AgentLoop:
    getdata_path: Path = field(default_factory=default_getdata_path)
    neutral_notch: int = NEUTRAL_NOTCH
    ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S
    post_ipc_sleep_s: float = 0.02
    limit_brake_enabled: bool = False
    learner: Optional[LearnerProfile] = None

    _target_notch: Optional[int] = field(default=None, init=False, repr=False)
    _next_cmd_id: int = field(default=1, init=False, repr=False)
    _tick: int = field(default=0, init=False, repr=False)
    _limit_state: LimitBrakeState = field(default_factory=LimitBrakeState, init=False, repr=False)
    _release_state: BrakeReleaseState = field(default_factory=BrakeReleaseState, init=False, repr=False)
    _learner: LearnerProfile = field(default_factory=LearnerProfile, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.learner is not None:
            self._learner = self.learner

    def request_notch(self, notch: int) -> None:
        self._target_notch = max(0, min(8, int(notch)))

    def request_neutral(self) -> None:
        self.request_notch(self.neutral_notch)

    def clear_target(self) -> None:
        self._target_notch = None

    @property
    def target_notch(self) -> Optional[int]:
        return self._target_notch

    def read_probe(self) -> Optional[ProbeSnapshot]:
        return read_probe_file(self.getdata_path)

    def _apply_brake_command(self, cmd: BrakeCommand) -> None:
        notch = cmd.target_notch
        if notch is None:
            return
        if cmd.kind in ("RELEASE", "COAST_THROTTLE"):
            self.request_neutral()
        elif cmd.kind == "APPLY":
            self.request_notch(notch)

    def step(self) -> AgentSnapshot:
        self._tick += 1
        snap = self.read_probe()
        limit_mph: Optional[float] = None
        limit_dist_m: Optional[float] = None
        effective_limit_mph: Optional[float] = None
        p1_phase = ""
        p1_cmd = ""
        p1_dist_start_m: Optional[float] = None
        p1_apply_now: Optional[bool] = None
        p1_detail = ""
        p1_reason = ""
        p1_handle: Optional[int] = None
        p1_layer = ""
        ipc_cmd_id: Optional[int] = None

        if snap is not None and self.limit_brake_enabled:
            decision = evaluate_limit_tick(
                self._limit_state,
                self._release_state,
                snap,
                learner=self._learner,
            )
            limit_dist_m = decision.limit_dist_m
            limit_mph = decision.limit_mph
            effective_limit_mph = decision.effective_mph
            p1_phase = decision.phase
            p1_dist_start_m = decision.dist_start_m
            p1_apply_now = decision.apply_now
            p1_detail = decision.detail
            p1_reason = decision.reason
            p1_handle = decision.handle_notch
            if decision.command is not None:
                p1_cmd = decision.command.kind
                self._apply_brake_command(decision.command)
            p1_layer = classify_layer(
                reason=p1_reason,
                cmd=p1_cmd or None,
                apply_now=p1_apply_now,
                dist_start_m=p1_dist_start_m,
            )

        lever = probe_lever(snap)
        ipc_result: Optional[dict[str, Any]] = None
        ipc_sent = False

        if (
            snap is not None
            and self._target_notch is not None
            and lever is not None
            and int(lever) != int(self._target_notch)
        ):
            ipc_cmd_id = self._next_cmd_id
            ipc_result = dispatch_step_toward_notch(
                self._target_notch,
                cmd_id=self._next_cmd_id,
                ack_timeout_s=self.ack_timeout_s,
            )
            self._next_cmd_id += 1
            ipc_sent = True
            if self.post_ipc_sleep_s > 0:
                time.sleep(self.post_ipc_sleep_s)
            snap = self.read_probe()

        return AgentSnapshot.from_probe(
            snap,
            tick=self._tick,
            target_notch=self._target_notch,
            ipc_sent=ipc_sent,
            ipc_result=ipc_result,
            limit_mph=limit_mph,
            limit_dist_m=limit_dist_m,
            effective_limit_mph=effective_limit_mph,
            p1_phase=p1_phase,
            p1_cmd=p1_cmd,
            p1_dist_start_m=p1_dist_start_m,
            p1_apply_now=p1_apply_now,
            p1_detail=p1_detail,
            p1_reason=p1_reason,
            p1_handle=p1_handle,
            p1_layer=p1_layer,
            ipc_cmd_id=ipc_cmd_id,
            brake_fill_s=self._learner.brake_fill_s,
        )
