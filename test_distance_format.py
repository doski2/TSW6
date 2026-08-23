#!/usr/bin/env python3
"""Tests para distance_format.py."""

from distance_format import (
    UNITS_METRIC,
    UNITS_UK,
    UNITS_US,
    format_distance,
    format_distance_pair,
    infer_distance_units,
)


def test_infer_uk_class323():
    assert infer_distance_units("RVM BCC WRM Class323 DMS A C") == UNITS_UK


def test_infer_us_freight():
    assert infer_distance_units("BNSF SD40-2 C") == UNITS_US


def test_infer_metric_ice():
    assert infer_distance_units("DB ICE 3") == UNITS_METRIC


def test_format_uk_yards():
    # ~200 m → ~219 yd
    s = format_distance(200.0, UNITS_UK)
    assert "yd" in s
    assert abs(int(s.split()[0]) - 219) <= 2


def test_format_uk_miles():
    s = format_distance(2000.0, UNITS_UK)
    assert "mi" in s
    assert abs(float(s.split()[0]) - 1.2) < 0.1


def test_format_us_feet():
    s = format_distance(200.0, UNITS_US)
    assert "ft" in s


def test_format_us_miles():
    s = format_distance(3000.0, UNITS_US)
    assert "mi" in s


def test_format_metric_m():
    assert format_distance(500.0, UNITS_METRIC) == "500 m"


def test_format_metric_km():
    assert format_distance(2500.0, UNITS_METRIC) == "2.5 km"


def test_format_distance_pair_shows_probe_when_drift():
    s = format_distance_pair(200.0, 180.0, UNITS_UK)
    assert "probe" in s
