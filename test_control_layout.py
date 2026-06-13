"""Tests de detección de layout de mandos (Fase 1 freight NA)."""

from control_layout import (
    LAYOUT_COMBINED,
    LAYOUT_FREIGHT_NA,
    detect_control_layout,
    validated_freight_vehicles,
)


def test_validated_vehicle_sd40():
    assert "BNSF SD40-2 C" in validated_freight_vehicles()
    assert detect_control_layout("BNSF SD40-2 C") == LAYOUT_FREIGHT_NA


def test_freight_hints():
    assert detect_control_layout("CSX ES44AC-H") == LAYOUT_FREIGHT_NA
    assert detect_control_layout("Union Pacific SD70M") == LAYOUT_FREIGHT_NA


def test_combined_class323():
    assert detect_control_layout("RVM BCC WRM Class323 DMS A C") == LAYOUT_COMBINED


def test_unknown_defaults_combined():
    assert detect_control_layout(None) == LAYOUT_COMBINED
    assert detect_control_layout("") == LAYOUT_COMBINED
    assert detect_control_layout("Mystery Loco XYZ") == LAYOUT_COMBINED
