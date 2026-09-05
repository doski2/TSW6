from __future__ import annotations

import _path  # noqa: F401

from tsw6v2.p1_layers import LAYERS, classify_layer, layer_label


def test_classify_brake():
    assert classify_layer(reason="plan", cmd="APPLY", apply_now=True) == "BRAKE"
    assert layer_label("BRAKE") == "Frenar"


def test_classify_watch():
    assert (
        classify_layer(
            reason="command_none",
            cmd=None,
            apply_now=False,
            dist_start_m=200.0,
        )
        == "WATCH"
    )


def test_classify_air_fill():
    assert classify_layer(reason="air_fill") == "WAIT"
    assert classify_layer(reason="air_recharge") == "WAIT"
    assert (
        classify_layer(
            reason="command_none",
            cmd=None,
            apply_now=True,
            dist_start_m=10.0,
        )
        == "GAP"
    )


def test_layers_glossary():
    assert "WATCH" in LAYERS
    assert "Frenar" in LAYERS["BRAKE"][0]


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
