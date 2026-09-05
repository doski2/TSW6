"""Parser GetData.txt — contrato D2 (CANAL_CONTROL). Sin dependencias de tsw6."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def default_getdata_path() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(temp) / "TSW6Bridge" / "GetData.txt"


def power_to_combined_notch(
    power: Optional[float],
    power_neg: bool = False,
) -> Optional[int]:
    """HUD Power (signed) → muesca combinada 0–8 (Class 323)."""
    if power is None:
        return None
    p = float(power)
    if power_neg:
        p = -abs(p)
    return max(0, min(8, 4 + round(p)))


def _as_probe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(round(val))
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _as_bool(val: str) -> bool:
    return val in ("1", "true", "True")


def parse_probe_line(line: str) -> dict[str, Any]:
    """Parsea una línea ``key=value`` separada por espacios."""
    out: dict[str, Any] = {}
    for token in line.strip().split():
        if "=" not in token:
            continue
        key, _, raw = token.partition("=")
        if raw == "?":
            out[key] = "?" if key == "vehicle" else None
            continue
        if key in ("seq", "handle_notch", "lever_notch", "last_cmd_id"):
            out[key] = _as_probe_int(raw)
            continue
        if key in (
            "power_neg",
            "doors_open",
            "doors_telem",
            "doors_dmi",
            "last_ack_ok",
            "is_slipping",
            "traction_locked",
            "signal_red",
        ):
            out[key] = _as_bool(raw)
            continue
        if key == "vehicle":
            out[key] = raw
            continue
        try:
            out[key] = float(raw)
        except ValueError:
            out[key] = raw
    return out


@dataclass
class ProbeSnapshot:
    seq: Optional[int] = None
    speed_ms: Optional[float] = None
    power: Optional[float] = None
    power_neg: bool = False
    handle_notch: Optional[int] = None
    lever_notch: Optional[int] = None
    last_cmd_id: Optional[int] = None
    last_ack_ok: Optional[bool] = None
    train_brake: Optional[float] = None
    loco_brake: Optional[float] = None
    dyn_brake: Optional[float] = None
    accel_ms2: Optional[float] = None
    brake_cyl_bar: Optional[float] = None
    max_speed_ms: Optional[float] = None
    speed_limit_ms: Optional[float] = None
    gradient_pct: Optional[float] = None
    dist_limit_cm: Optional[float] = None
    next_limit_ms: Optional[float] = None
    dist_limit2_cm: Optional[float] = None
    next_limit2_ms: Optional[float] = None
    odo_m: Optional[float] = None
    doors_open: Optional[bool] = None
    doors_telem: Optional[bool] = None
    doors_dmi: Optional[bool] = None
    is_slipping: Optional[bool] = None
    traction_locked: Optional[bool] = None
    signal_red: Optional[bool] = None
    signal_dist_cm: Optional[float] = None
    vehicle: str = "?"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProbeSnapshot:
        return cls(
            seq=data.get("seq"),
            speed_ms=data.get("speed_ms"),
            power=data.get("power"),
            power_neg=bool(data.get("power_neg", False)),
            handle_notch=data.get("handle_notch"),
            lever_notch=data.get("lever_notch"),
            last_cmd_id=data.get("last_cmd_id"),
            last_ack_ok=data.get("last_ack_ok"),
            train_brake=data.get("train_brake"),
            loco_brake=data.get("loco_brake"),
            dyn_brake=data.get("dyn_brake"),
            accel_ms2=data.get("accel_ms2"),
            brake_cyl_bar=data.get("brake_cyl_bar"),
            max_speed_ms=data.get("max_speed_ms"),
            speed_limit_ms=data.get("speed_limit_ms"),
            gradient_pct=data.get("gradient_pct"),
            dist_limit_cm=data.get("dist_limit_cm"),
            next_limit_ms=data.get("next_limit_ms"),
            dist_limit2_cm=data.get("dist_limit2_cm"),
            next_limit2_ms=data.get("next_limit2_ms"),
            odo_m=data.get("odo_m"),
            doors_open=data.get("doors_open"),
            doors_telem=data.get("doors_telem", data.get("doors_open")),
            doors_dmi=data.get("doors_dmi"),
            is_slipping=data.get("is_slipping"),
            traction_locked=data.get("traction_locked"),
            signal_red=data.get("signal_red"),
            signal_dist_cm=data.get("signal_dist_cm"),
            vehicle=str(data.get("vehicle") or "?"),
        )

    def combined_handle_notch(self) -> Optional[int]:
        notch = _as_probe_int(self.lever_notch)
        if notch is not None:
            return notch
        notch = _as_probe_int(self.handle_notch)
        if notch is not None:
            return notch
        return power_to_combined_notch(self.power, self.power_neg)


def decode_probe_raw(data: bytes) -> Optional[str]:
    if not data:
        return None
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    return text.splitlines()[-1].strip()


def read_probe_raw_line(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        return decode_probe_raw(path.read_bytes())
    except OSError:
        return None


def read_probe_file(path: Path) -> Optional[ProbeSnapshot]:
    line = read_probe_raw_line(path)
    if not line:
        return None
    parsed = parse_probe_line(line)
    if parsed.get("seq") is None or parsed.get("speed_ms") is None:
        return None
    return ProbeSnapshot.from_dict(parsed)
