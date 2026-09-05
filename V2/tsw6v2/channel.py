"""Lectura GetData en segundo plano (~20 Hz) — desacoplada del bucle agente."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional

from tsw6v2.bridge.getdata import (
    ProbeSnapshot,
    decode_probe_raw,
    default_getdata_path,
    parse_probe_line,
)

DEFAULT_TELEM_HZ = 20.0


@dataclass
class _TelemSlot:
    snap: Optional[ProbeSnapshot] = None
    age_ms: float = 0.0
    read_count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class TelemetryReader:
    """Lee GetData en hilo aparte; el visor solo consume ``get_snapshot()``."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        hz: float = DEFAULT_TELEM_HZ,
    ) -> None:
        self._path = path or default_getdata_path()
        self._interval = 1.0 / max(1.0, float(hz))
        self._lock = threading.Lock()
        self._slot = _TelemSlot()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fh: Optional[BinaryIO] = None

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="tsw6v2-telem",
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
        except OSError:
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
            snap = self._read_snapshot()
            age_ms = 0.0
            if snap is not None:
                try:
                    age_ms = max(0.0, (time.time() - self._path.stat().st_mtime) * 1000.0)
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
