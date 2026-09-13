"""Helpers compartidos para tests de learner / calidad."""

from __future__ import annotations

from tsw6v2.learn_quality import MIN_STABLE_S
from tsw6v2.learner import LearnerProfile


def feed_stable_decel(
    p: LearnerProfile,
    *,
    t0: float = 0.0,
    handle: int = 3,
    speed0: float = 50.0,
    accel: float = -0.80,
    brake_cyl_bar: float = 2.8,
) -> bool:
    dt = MIN_STABLE_S / 3.0 + 0.05
    ok = False
    for i in range(4):
        speed = speed0 - i * 0.8
        if p.observe_brake_decel(
            handle=handle,
            speed_mph=speed,
            gradient_pct=0.0,
            accel_ms2=accel,
            lever=handle,
            brake_cyl_bar=brake_cyl_bar,
            now=t0 + i * dt,
        ):
            ok = True
    return ok
