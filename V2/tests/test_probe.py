from __future__ import annotations

import _path  # noqa: F401

import time
from unittest.mock import patch

from tsw6v2.bridge.getdata import ProbeSnapshot
from tsw6v2.probe import fmt_num, is_probe_fresh


def test_fmt_num() -> None:
    assert fmt_num(None) == "?"
    assert fmt_num(1.0) == "1.00"


def test_is_probe_fresh() -> None:
    snap = ProbeSnapshot(seq=10, speed_ms=5.0)
    with patch("tsw6v2.probe.default_getdata_path") as gp:
        gp.return_value.is_file.return_value = True
        gp.return_value.stat.return_value.st_mtime = time.time()
        assert is_probe_fresh(snap)


if __name__ == "__main__":
    raise SystemExit(_path.run_self_tests())
