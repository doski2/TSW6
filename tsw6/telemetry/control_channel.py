#!/usr/bin/env python3
"""
control_channel.py — Fase A/B: telemetría y mandos desacoplados del bucle de control.

TelemetryReader: hilo que lee GetData.txt a ~20 Hz.
AsyncCommandWriter: cola IPC; ACK + reintentos en hilo aparte (el tick nunca espera).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional

from tsw6.telemetry.tsw_ipc_bus import (
    adaptive_ack_timeout_s,
    dispatch_ipc_brake,
    dispatch_ipc_combined_notch,
    enable_lua_commands,
)
from tsw6.telemetry.tsw_ue4ss_reader import (
    ProbeSnapshot,
    decode_probe_raw,
    parse_probe_line,
)

_log = logging.getLogger("tsw.telemetry.channel")

DEFAULT_TELEM_HZ = 20.0
DEFAULT_ACK_TIMEOUT_S = 0.12
_MAX_QUEUE = 8
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = 0.025


@dataclass
class CommandState:
    """Estado observable del escritor asíncrono (para logs / GUI)."""

    cmd_id: int = 0
    target_notch: Optional[int] = None
    pending: bool = False
    inflight: bool = False
    queue_depth: int = 0
    last_ok: bool = False
    last_ack_ms: float = 0.0
    last_error: str = ""
    drops: int = 0
    retries: int = 0
    failures: int = 0
    successes: int = 0
    confirmed_cmd_id: Optional[int] = None
    telem_cmd_id: Optional[int] = None
    reached_notch: bool = False
    ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S
    last_via: str = ""  # "ipc" | "http" | ""
    ipc_ok: int = 0
    http_ok: int = 0


@dataclass
class _CmdItem:
    cmd_id: int
    control: str
    value: float
    notch: Optional[int] = None
    attempt: int = 0


@dataclass
class _TelemSlot:
    snap: Optional[ProbeSnapshot] = None
    age_ms: float = 0.0
    read_count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class TelemetryReader:
    """Lee GetData en segundo plano; el bucle principal solo consume snapshot."""

    def __init__(
        self,
        path: Path,
        *,
        hz: float = DEFAULT_TELEM_HZ,
    ) -> None:
        self._path = path
        self._interval = 1.0 / max(1.0, float(hz))
        self._lock = threading.Lock()
        self._slot = _TelemSlot()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fh: Optional[BinaryIO] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="tsw-telem-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        self._close_fh()

    def _close_fh(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def _read_snapshot(self) -> Optional[ProbeSnapshot]:
        path = self._path
        try:
            if self._fh is None:
                if not path.is_file():
                    return None
                self._fh = open(path, "rb")
            self._fh.seek(0)
            data = self._fh.read()
        except OSError as exc:
            _log.debug("TelemetryReader read error: %s", exc)
            self._close_fh()
            return None
        if not data:
            self._close_fh()
            return None
        line = decode_probe_raw(data)
        if not line:
            return None
        parsed = parse_probe_line(line)
        if parsed.get("seq") is None or parsed.get("speed_ms") is None:
            return None
        return ProbeSnapshot.from_dict(parsed)

    def poll_hz(self) -> float:
        with self._lock:
            slot = self._slot
            elapsed = time.monotonic() - slot.window_start
            if elapsed < 0.05 or slot.read_count == 0:
                return 0.0
            return slot.read_count / elapsed

    def get_snapshot(self) -> tuple[Optional[ProbeSnapshot], float]:
        with self._lock:
            return self._slot.snap, self._slot.age_ms

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            snap: Optional[ProbeSnapshot] = None
            age_ms = 0.0
            snap = self._read_snapshot()
            if snap is not None:
                try:
                    age_ms = max(
                        0.0,
                        (time.time() - self._path.stat().st_mtime) * 1000.0,
                    )
                except OSError:
                    age_ms = 0.0

            with self._lock:
                slot = self._slot
                if snap is not None:
                    slot.snap = snap
                    slot.age_ms = age_ms
                slot.read_count += 1
                if time.monotonic() - slot.window_start >= 2.0:
                    slot.read_count = 1
                    slot.window_start = time.monotonic()

            elapsed = time.perf_counter() - t0
            wait = self._interval - elapsed
            if wait > 0:
                self._stop.wait(wait)


class AsyncCommandWriter:
    """Cola de mandos IPC; procesa ACK y reintentos fuera del hilo de control."""

    def __init__(
        self,
        *,
        schema: Optional[dict] = None,
        ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S,
        max_queue: int = _MAX_QUEUE,
        max_attempts: int = _MAX_ATTEMPTS,
        http_fallback: Optional[Callable[[str, float], bool]] = None,
        on_ipc_fail: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._schema = schema
        self._base_ack_timeout_s = ack_timeout_s
        self._max_queue = max(1, int(max_queue))
        self._max_attempts = max(1, int(max_attempts))
        self._http_fallback = http_fallback
        self._on_ipc_fail = on_ipc_fail
        self._q: queue.Queue[Optional[_CmdItem]] = queue.Queue(maxsize=self._max_queue)
        self._lock = threading.Lock()
        self._state = CommandState()
        self._next_id = 0
        self._inflight: Optional[_CmdItem] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_enqueued_notch: Optional[int] = None
        self._last_enqueued_t = 0.0
        self._recent_acks: list[float] = []
        self._enqueued = 0

    def start(self) -> None:
        enable_lua_commands()
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="tsw-cmd-writer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def session_stats(self) -> tuple[CommandState, list[float], int]:
        with self._lock:
            st = CommandState(
                cmd_id=self._state.cmd_id,
                target_notch=self._state.target_notch,
                pending=self._state.pending,
                inflight=self._state.inflight,
                queue_depth=self._q.qsize() + (1 if self._inflight else 0),
                last_ok=self._state.last_ok,
                last_ack_ms=self._state.last_ack_ms,
                last_error=self._state.last_error,
                drops=self._state.drops,
                retries=self._state.retries,
                failures=self._state.failures,
                successes=self._state.successes,
                confirmed_cmd_id=self._state.confirmed_cmd_id,
                telem_cmd_id=self._state.telem_cmd_id,
                reached_notch=self._state.reached_notch,
                ack_timeout_s=self._state.ack_timeout_s,
                last_via=self._state.last_via,
                ipc_ok=self._state.ipc_ok,
                http_ok=self._state.http_ok,
            )
            return st, list(self._recent_acks), self._enqueued

    def state(self) -> CommandState:
        st, _, _ = self.session_stats()
        return st

    def update_telem_correlation(
        self,
        telem_cmd_id: Optional[int],
        telem_ack_ok: Optional[bool],
        lever_notch: Optional[int],
    ) -> None:
        """Correlaciona GetData (last_cmd_id) con el último mando encolado."""
        with self._lock:
            self._state.telem_cmd_id = telem_cmd_id
            if (
                telem_cmd_id is not None
                and telem_ack_ok
                and telem_cmd_id == self._state.cmd_id
            ):
                self._state.confirmed_cmd_id = telem_cmd_id
            if (
                lever_notch is not None
                and self._state.target_notch is not None
            ):
                self._state.reached_notch = (
                    int(lever_notch) == int(self._state.target_notch)
                )

    def enqueue_combined_notch(self, notch: int) -> int:
        """Encola muesca absoluta 0–8. Devuelve cmd_id (>0) o 0 si se descarta."""
        notch = max(0, min(8, int(notch)))
        now = time.monotonic()
        if (
            self._last_enqueued_notch == notch
            and now - self._last_enqueued_t < 0.08
        ):
            with self._lock:
                return self._state.cmd_id if self._state.pending else 0

        self._next_id += 1
        cmd_id = self._next_id
        item = _CmdItem(
            cmd_id=cmd_id,
            control="combined_brake",
            value=notch / 8.0,
            notch=notch,
        )
        try:
            self._q.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._state.drops += 1
            _log.warning("Cola IPC llena — mando B%d descartado", notch)
            return 0

        self._last_enqueued_notch = notch
        self._last_enqueued_t = now
        with self._lock:
            self._enqueued += 1
            self._state.cmd_id = cmd_id
            self._state.target_notch = notch
            self._state.pending = True
            self._state.queue_depth = self._q.qsize()
        return cmd_id

    def enqueue_control(self, control: str, value: float) -> int:
        name = str(control or "").strip()
        if name == "PowerBrakeHandle":
            from tsw6.telemetry.tsw_command_bus import combined_value_to_notch

            return self.enqueue_combined_notch(combined_value_to_notch(value))

        self._next_id += 1
        cmd_id = self._next_id
        item = _CmdItem(cmd_id=cmd_id, control=name, value=float(value))
        try:
            self._q.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._state.drops += 1
            return 0
        with self._lock:
            self._enqueued += 1
            self._state.cmd_id = cmd_id
            self._state.target_notch = None
            self._state.pending = True
        return cmd_id

    def _ack_timeout(self) -> float:
        return adaptive_ack_timeout_s(self._recent_acks)

    def _dispatch(self, item: _CmdItem) -> dict[str, Any]:
        timeout = self._ack_timeout()
        with self._lock:
            self._state.ack_timeout_s = timeout
        if item.control == "combined_brake" and item.notch is not None:
            return dispatch_ipc_combined_notch(
                item.notch,
                self._schema,
                cmd_id=item.cmd_id,
                ack_timeout_s=timeout,
            )
        return dispatch_ipc_brake(
            item.control,
            item.value,
            self._schema,
            wait_ack=True,
            cmd_id=item.cmd_id,
            ack_timeout_s=timeout,
        )

    def _record_result(self, item: _CmdItem, result: dict[str, Any]) -> None:
        ok = bool(result.get("ok"))
        err = str(result.get("error") or "")
        ack_ms = float(result.get("ack_ms") or 0.0)
        with self._lock:
            self._state.inflight = False
            self._state.pending = self._q.qsize() > 0
            self._state.last_ok = ok
            self._state.last_ack_ms = ack_ms
            self._state.last_error = err if not ok else ""
            if ok:
                self._state.successes += 1
                self._state.last_via = "ipc"
                self._state.ipc_ok += 1
                self._recent_acks.append(ack_ms)
                if len(self._recent_acks) > 40:
                    self._recent_acks.pop(0)
            else:
                self._state.failures += 1
        if not ok:
            _log.warning(
                "IPC async id=%d notch=%s intento=%d/%d falló (%s) ack=%.0fms",
                item.cmd_id,
                item.notch,
                item.attempt + 1,
                self._max_attempts,
                err or "?",
                ack_ms,
            )
            if self._http_fallback is not None:
                ctrl = item.control
                val = float(item.value)
                if item.notch is not None:
                    from tsw6.telemetry.tsw_command_bus import combined_notch_to_value

                    ctrl = "PowerBrakeHandle"
                    val = combined_notch_to_value(item.notch)
                try:
                    if self._http_fallback(ctrl, val):
                        with self._lock:
                            self._state.successes += 1
                            self._state.last_ok = True
                            self._state.last_error = ""
                            self._state.last_via = "http"
                            self._state.http_ok += 1
                            self._state.failures -= 1
                        _log.info(
                            "HTTP fallback OK id=%d control=%s val=%.3f via=http",
                            item.cmd_id, ctrl, val)
                        return
                except Exception as exc:
                    _log.debug("HTTP fallback error id=%d: %s", item.cmd_id, exc)
                if self._on_ipc_fail is not None:
                    try:
                        self._on_ipc_fail(err or "ipc_fail")
                    except Exception:
                        pass
            elif self._on_ipc_fail is not None:
                try:
                    self._on_ipc_fail(err or "ipc_fail")
                except Exception:
                    pass
        else:
            _log.info(
                "IPC ok id=%d notch=%s ack=%.0fms timeout=%.0fms via=ipc",
                item.cmd_id,
                item.notch,
                ack_ms,
                self._ack_timeout() * 1000.0,
            )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is None:
                break

            self._inflight = item
            with self._lock:
                self._state.inflight = True

            result: dict[str, Any] = {"ok": False, "error": "no_attempt"}
            for attempt in range(self._max_attempts):
                item.attempt = attempt
                if attempt > 0:
                    with self._lock:
                        self._state.retries += 1
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                result = self._dispatch(item)
                if result.get("ok"):
                    break

            self._record_result(item, result)
            self._inflight = None
            self._q.task_done()
