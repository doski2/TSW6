"""Perfil aprendido (opcional) — decel por muesca + L4 lite (fill aire)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from tsw6v2.brake_air import BrakeAirTracker
from tsw6v2.physics import DEFAULT_BRAKE_FILL_S


class LearnerProfile:
    """Lookup decel por muesca; vacío = usar fracciones fijas del plan."""

    def __init__(
        self,
        by_notch: dict[int, float] | None = None,
        *,
        air: BrakeAirTracker | None = None,
    ) -> None:
        self._by_notch = dict(by_notch or {})
        self._air = air or BrakeAirTracker()

    @property
    def brake_fill_s(self) -> float:
        return self._air.brake_fill_s

    @property
    def brake_fill_n(self) -> int:
        return self._air.brake_fill_n

    def observe_air(
        self,
        lever: int,
        brake_cyl_bar: float | None,
        *,
        now: float | None = None,
    ) -> None:
        self._air.observe(lever, brake_cyl_bar, now=now)

    def air_ready(self, brake_cyl_bar: float | None) -> bool:
        return self._air.air_ready(brake_cyl_bar)

    def inhibit_reapply(
        self,
        brake_cyl_bar: float | None,
        *,
        now: float | None = None,
    ) -> bool:
        return self._air.inhibit_reapply(brake_cyl_bar, now=now)

    def cap_escalation(
        self,
        *,
        committed: int | None,
        requested: int,
        brake_cyl_bar: float | None,
    ) -> int:
        return self._air.cap_escalation(
            committed=committed,
            requested=requested,
            brake_cyl_bar=brake_cyl_bar,
        )

    def predict_decel(
        self,
        handle_notch: int,
        speed_mph: float,
        gradient_pct: float,
    ) -> Optional[float]:
        del speed_mph, gradient_pct
        val = self._by_notch.get(int(handle_notch))
        if val is None or val <= 0.05:
            return None
        return float(val)

    @classmethod
    def from_json(cls, path: Path) -> LearnerProfile:
        if not path.is_file():
            return cls()
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        raw = data.get("decel_by_notch") or data.get("notch_decel") or {}
        by_notch = {int(k): float(v) for k, v in raw.items()}
        air = BrakeAirTracker()
        air.load_dict(data)
        return cls(by_notch, air=air)

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "decel_by_notch": {str(k): v for k, v in self._by_notch.items()},
            **self._air.to_dict(),
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_default(cls, vehicle: str, profiles_dir: Path | None = None) -> LearnerProfile:
        """``logs/profiles/<vehicle>.json`` si existe."""
        root = profiles_dir or Path("logs/profiles")
        slug = (vehicle or "?").strip().lower().replace(" ", "_")
        return cls.from_json(root / f"{slug}.json")
