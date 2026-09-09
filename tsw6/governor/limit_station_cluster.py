"""Re-export cluster cartel↔andén (canónico en ``tsw6v2``)."""

from tsw6v2.limit_station_cluster import (
    cluster_approach_in_range,
    merged_approach_overspeed,
    next_sign_is_reduction_beyond_station,
    should_merge_limit_and_station_plans,
    station_may_ignore_limit_approach,
    station_waits_for_approach_limit,
    targets_are_clustered,
    will_be_below_limit_at_pass,
)

__all__ = [
    "cluster_approach_in_range",
    "merged_approach_overspeed",
    "next_sign_is_reduction_beyond_station",
    "should_merge_limit_and_station_plans",
    "station_may_ignore_limit_approach",
    "station_waits_for_approach_limit",
    "targets_are_clustered",
    "will_be_below_limit_at_pass",
]
