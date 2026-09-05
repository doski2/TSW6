"""Lectura GetData y formato."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from tsw6v2.bridge.getdata import (
    ProbeSnapshot,
    default_getdata_path,
    read_probe_file,
)
from tsw6v2.constants import MS_TO_MPH, PROBE_STALE_S
from tsw6v2.ipc import probe_lever


def read_snapshot(path: Optional[Path] = None) -> Optional[ProbeSnapshot]:
    return read_probe_file(path or default_getdata_path())


def is_probe_fresh(
    snap: Optional[ProbeSnapshot],
    *,
    path: Optional[Path] = None,
    stale_s: float = PROBE_STALE_S,
) -> bool:
    if snap is None or snap.seq is None or snap.speed_ms is None:
        return False
    getdata = path or default_getdata_path()
    if not getdata.is_file():
        return False
    try:
        return (time.time() - getdata.stat().st_mtime) <= stale_s
    except OSError:
        return False


def fmt_num(value: Any, *, places: int = 2) -> str:
    if value is None:
        return "?"
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return str(value)


def print_getdata_summary(snap: Optional[ProbeSnapshot], title: str) -> None:
    print(f"  {title}")
    if snap is None:
        print("    (sin lectura GetData)")
        return
    mph = snap.speed_ms * MS_TO_MPH if snap.speed_ms is not None else None
    lever = probe_lever(snap)
    print(f"    speed_mph:         {fmt_num(mph, places=1) if mph is not None else '?'}")
    print(f"    lever_notch:       {lever if lever is not None else '?'}")
    print(f"    train_brake:       {fmt_num(snap.train_brake)}")
    print(f"    dyn_brake:         {fmt_num(snap.dyn_brake)}")
    print(f"    brake_cyl_bar:     {fmt_num(snap.brake_cyl_bar)}")
    print(f"    accel_ms2:         {fmt_num(snap.accel_ms2, places=3)}")
    print(f"    seq:               {snap.seq if snap.seq is not None else '?'}")
    print(f"    last_cmd_id:       {snap.last_cmd_id if snap.last_cmd_id is not None else '?'}")
    print(f"    last_ack_ok:       {snap.last_ack_ok if snap.last_ack_ok is not None else '?'}")
