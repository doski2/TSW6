"""Bucle agente — un tick: GetData → decisión → (opcional) un paso IPC."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.getdata import ProbeSnapshot, default_getdata_path, read_probe_file
from tsw6v2.bridge.ipc_bus import purge_lua_commands
from tsw6v2.command import (
    BrakeCommand,
    BrakeReleaseState,
    is_brake_applied,
    release_brake_command,
)
from tsw6v2.constants import (
    AGENT_ACK_TIMEOUT_S,
    DRIVER_OVERRIDE_COOLDOWN_S,
    MS_TO_MPH,
    NEUTRAL_NOTCH,
)
from tsw6v2.decision import evaluate_p1_tick
from tsw6v2.p1_station_gate import StationDwellGate
from tsw6v2.planning_poller import StationPlanning
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
    p1_target_kind: str = ""
    station_dist_m: Optional[float] = None
    station_eta: Optional[str] = None
    station_fsm: str = ""
    doors_open: Optional[bool] = None
    doors_telem: Optional[bool] = None
    doors_dmi: Optional[bool] = None
    ipc_cmd_id: Optional[int] = None
    brake_fill_s: Optional[float] = None
    fb_a_pred_ms2: Optional[float] = None
    fb_a_obs_ms2: Optional[float] = None
    fb_shortfall: bool = False
    fb_escalated: bool = False
    driver_override_s: float = 0.0

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
        p1_target_kind: str = "",
        station_dist_m: Optional[float] = None,
        station_eta: Optional[str] = None,
        station_fsm: str = "",
        doors_open: Optional[bool] = None,
        doors_telem: Optional[bool] = None,
        doors_dmi: Optional[bool] = None,
        ipc_cmd_id: Optional[int] = None,
        brake_fill_s: Optional[float] = None,
        fb_a_pred_ms2: Optional[float] = None,
        fb_a_obs_ms2: Optional[float] = None,
        fb_shortfall: bool = False,
        fb_escalated: bool = False,
        driver_override_s: float = 0.0,
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
            p1_target_kind=p1_target_kind,
            station_dist_m=station_dist_m,
            station_eta=station_eta,
            station_fsm=station_fsm,
            doors_open=snap.doors_open,
            doors_telem=snap.doors_telem,
            doors_dmi=snap.doors_dmi,
            ipc_cmd_id=ipc_cmd_id,
            brake_fill_s=brake_fill_s,
            fb_a_pred_ms2=fb_a_pred_ms2,
            fb_a_obs_ms2=fb_a_obs_ms2,
            fb_shortfall=fb_shortfall,
            fb_escalated=fb_escalated,
            driver_override_s=driver_override_s,
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
    driver_override_cooldown_s: float = DRIVER_OVERRIDE_COOLDOWN_S
    limit_brake_enabled: bool = False
    station_brake_enabled: bool = False
    signal_brake_enabled: bool = False
    learner: Optional[LearnerProfile] = None
    auto_profile: bool = True
    profiles_dir: Optional[Path] = None

    _target_notch: Optional[int] = field(default=None, init=False, repr=False)
    _next_cmd_id: int = field(default=1, init=False, repr=False)
    _tick: int = field(default=0, init=False, repr=False)
    _limit_state: LimitBrakeState = field(default_factory=LimitBrakeState, init=False, repr=False)
    _release_state: BrakeReleaseState = field(default_factory=BrakeReleaseState, init=False, repr=False)
    _learner: LearnerProfile = field(default_factory=LearnerProfile, init=False, repr=False)
    _learner_explicit: bool = field(default=False, init=False, repr=False)
    _profile_path: Optional[Path] = field(default=None, init=False, repr=False)
    _auto_profile_tried: bool = field(default=False, init=False, repr=False)
    station_planning_http: bool = True
    _station_planning: StationPlanning = field(init=False, repr=False)
    _station_gate: StationDwellGate = field(default_factory=StationDwellGate, init=False, repr=False)
    _last_lever: Optional[int] = field(default=None, init=False, repr=False)
    _manual_override_until: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.learner is not None:
            self._learner = self.learner
            self._learner_explicit = True
        self._station_planning = StationPlanning(http_enabled=self.station_planning_http)

    @property
    def loaded_profile_path(self) -> Optional[Path]:
        return self._profile_path

    @property
    def active_learner(self) -> LearnerProfile:
        return self._learner

    @property
    def station_planning_source(self) -> str:
        """``http`` | ``file`` | ``none`` (planning andén)."""
        return self._station_planning.source

    @property
    def station_planning_channel(self) -> str:
        """Descripción humana de la fuente de distancia andén."""
        if self._station_planning.http_active:
            sched = self._station_planning.schedule_source
            base = "HTTP DriverAid.TrackData (~2 s)"
            if sched == "hud_db":
                return f"{base} + tsw_hud.db"
            if sched == "timetable_json":
                return f"{base} + timetable.json"
            return base
        return "Planning.txt (manual o fallback sin -HTTPAPI)"

    @property
    def station_schedule_source(self) -> str:
        return self._station_planning.schedule_source

    def shutdown(self) -> None:
        """Cierra recursos en segundo plano (planning HTTP)."""
        self._station_planning.close()

    def _try_auto_load_profile(self, vehicle: str) -> None:
        if self._auto_profile_tried or self._learner_explicit or not self.auto_profile:
            return
        self._auto_profile_tried = True
        if not vehicle or vehicle == "?":
            return
        path = LearnerProfile.resolve_profile_path(
            vehicle, profiles_dir=self.profiles_dir
        )
        if path is None:
            return
        loaded = LearnerProfile.from_json(path)
        self._learner = loaded
        self._profile_path = path

    def request_notch(self, notch: int) -> None:
        self._target_notch = max(0, min(8, int(notch)))

    def request_neutral(self) -> None:
        self.request_notch(self.neutral_notch)

    def clear_target(self) -> None:
        if self._target_notch is not None:
            purge_lua_commands()
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

    def driver_override_remaining_s(self) -> float:
        return max(0.0, self._manual_override_until - time.monotonic())

    def _manual_override_active(self) -> bool:
        return self.driver_override_remaining_s() > 0.0

    def _arm_manual_override(self) -> None:
        self._manual_override_until = time.monotonic() + max(
            0.5, float(self.driver_override_cooldown_s)
        )

    def _maybe_release_driver_control(self, lever: Optional[int]) -> None:
        """Suelta ``target`` IPC si la palanca ya alcanzó el objetivo."""
        if self._target_notch is None or lever is None:
            return
        target = int(self._target_notch)
        lev = int(lever)
        neutral = int(self.neutral_notch)
        reached = lev >= target if target >= neutral else lev <= target
        if reached:
            self.clear_target()

    def _check_driver_takeover(self, lever: int) -> None:
        """Si la palanca se aleja del objetivo IPC, asumir conducción manual."""
        if self._target_notch is None:
            self._last_lever = lever
            return
        prev = self._last_lever
        self._last_lever = lever
        if prev is None or lever == prev:
            return
        target = int(self._target_notch)
        if abs(lever - target) > abs(prev - target):
            self.clear_target()
            self._arm_manual_override()

    def step(self) -> AgentSnapshot:
        self._tick += 1
        snap = self.read_probe()
        if snap is not None and snap.vehicle:
            self._try_auto_load_profile(snap.vehicle)
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
        fb_a_pred_ms2: Optional[float] = None
        fb_a_obs_ms2: Optional[float] = None
        fb_shortfall = False
        fb_escalated = False

        station_dist_m: Optional[float] = None
        station_fsm = ""
        p1_target_kind = ""
        lever = probe_lever(snap)
        if lever is not None:
            self._check_driver_takeover(int(lever))

        station_p1_enabled = self.station_brake_enabled
        manual_active = self._manual_override_active()
        if snap is not None and (
            self.limit_brake_enabled
            or self.station_brake_enabled
            or self.signal_brake_enabled
        ):
            mph = (
                float(snap.speed_ms) * MS_TO_MPH
                if snap is not None and snap.speed_ms is not None
                else 0.0
            )
            dwell_release: Optional[BrakeCommand] = None
            if self.station_brake_enabled:
                planning = self._station_planning.update(
                    mph,
                    probe_seq=snap.seq,
                )
                station_dist_m = planning.station_distance_m
                prev_station_fsm = self._station_gate.state
                self._station_gate.update(
                    speed_mph=mph,
                    station_dist_m=station_dist_m,
                    doors_open=snap.doors_open,
                    doors_telem=snap.doors_telem,
                    doors_dmi=snap.doors_dmi,
                    throttle_notch=lever if lever is not None else 4,
                )
                station_fsm = self._station_gate.state or ""
                if self._station_gate.suppress_station_brake(
                    station_dist_m=station_dist_m,
                    throttle_notch=lever if lever is not None else 4,
                    speed_mph=mph,
                ):
                    station_p1_enabled = False
                if (
                    station_fsm == "STOPPED"
                    and prev_station_fsm != "STOPPED"
                    and lever is not None
                    and is_brake_applied(int(lever))
                ):
                    dwell_release = release_brake_command(at_target=True)
            decision = evaluate_p1_tick(
                self._limit_state,
                self._release_state,
                snap,
                learner=self._learner,
                station_distance_m=station_dist_m,
                limit_brake_enabled=self.limit_brake_enabled,
                station_brake_enabled=station_p1_enabled,
                signal_brake_enabled=self.signal_brake_enabled,
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
            p1_target_kind = decision.target_kind
            if decision.station_dist_m is not None:
                station_dist_m = decision.station_dist_m
            fb_a_pred_ms2 = decision.fb_a_pred_ms2
            fb_a_obs_ms2 = decision.fb_a_obs_ms2
            fb_shortfall = decision.fb_shortfall
            fb_escalated = decision.fb_escalated
            if not manual_active and decision.command is not None:
                p1_cmd = decision.command.kind
                self._apply_brake_command(decision.command)
            elif not manual_active and dwell_release is not None:
                p1_cmd = dwell_release.kind
                p1_phase = dwell_release.phase or ""
                p1_reason = dwell_release.reason or ""
                p1_detail = "Andén: parada — soltar freno"
                self._apply_brake_command(dwell_release)
            else:
                self._maybe_release_driver_control(lever)
            p1_layer = classify_layer(
                reason=p1_reason,
                cmd=p1_cmd or None,
                apply_now=p1_apply_now,
                dist_start_m=p1_dist_start_m,
            )

        ipc_result: Optional[dict[str, Any]] = None
        ipc_sent = False

        if (
            not manual_active
            and snap is not None
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
            p1_target_kind=p1_target_kind,
            station_dist_m=station_dist_m,
            station_eta=None,
            station_fsm=station_fsm,
            ipc_cmd_id=ipc_cmd_id,
            brake_fill_s=self._learner.brake_fill_s,
            fb_a_pred_ms2=fb_a_pred_ms2,
            fb_a_obs_ms2=fb_a_obs_ms2,
            fb_shortfall=fb_shortfall,
            fb_escalated=fb_escalated,
            driver_override_s=self.driver_override_remaining_s(),
        )
