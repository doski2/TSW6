from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.physics import coast_trim_covers_overspeed


def test_coast_trim_small_overspeed_downhill() -> None:
    assert coast_trim_covers_overspeed(
        speed_mph=55.5,
        target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
    )


def test_coast_trim_not_large_overspeed() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=60.0,
        ops_target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
        dist_start=100.0,
        current_posted_mph=55.0,
        next_posted_mph=55.0,
    )


def test_coast_trim_defers_while_legal_in_current_zone() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert downhill_defer_brake_commit(
        speed_mph=60.0,
        ops_target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
        dist_start=80.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )


def test_coast_trim_not_when_over_current_ops_band() -> None:
    from tsw6v2.limit_notch import downhill_defer_brake_commit

    assert not downhill_defer_brake_commit(
        speed_mph=62.0,
        ops_target_mph=54.0,
        distance_m=500.0,
        gradient_pct=-1.0,
        dist_start=80.0,
        current_posted_mph=60.0,
        next_posted_mph=55.0,
    )
