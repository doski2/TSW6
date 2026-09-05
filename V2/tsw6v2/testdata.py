"""Fixtures de test (solo desarrollo)."""

from __future__ import annotations

from pathlib import Path


def write_getdata_line(
    path: Path,
    *,
    seq: int,
    lever: int,
    speed_ms: float = 10.0,
    train_brake: float = 0.0,
    vehicle: str = "Class323",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"seq={seq} speed_ms={speed_ms} power=0 power_neg=0 "
        f"handle_notch={lever} lever_notch={lever} last_cmd_id=0 last_ack_ok=0 "
        f"train_brake={train_brake} loco_brake=0 dyn_brake=0 accel_ms2=0 "
        f"vehicle={vehicle}"
    )
    path.write_text(line + "\n", encoding="utf-8")
