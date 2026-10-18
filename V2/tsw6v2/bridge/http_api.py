"""Cliente HTTP mínimo para DriverAid (TSW6 -HTTPAPI). Sin dependencia de ``tsw6``."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

_log = logging.getLogger("tsw6v2.http_api")

TSW_API_BASE = "http://localhost:31270"
# La API del juego tarda ~1-2 s por GET con el juego a 50 fps (103432Z: 1 de 3 polls caducaba con 1,0 s).
DEFAULT_READ_TIMEOUT_S = 3.0

KEY_PATHS: tuple[Path, ...] = (
    Path.home() / "Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6EGS/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6WGDK/Saved/Config/CommAPIKey.txt",
    Path.home() / "OneDrive/Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
)


def encode_api_path(path: str) -> str:
    parts = str(path).strip().split(".")
    return ".".join(quote(part, safe="") for part in parts if part)


def find_api_key() -> Optional[str]:
    for p in KEY_PATHS:
        if not p.is_file():
            continue
        key = p.read_text(encoding="utf-8").strip()
        if key:
            return key
    return None


# Diagnóstico de fluidez: ms acumulados en GET y json.loads desde el último reinicio (los pone el poller).
POLL_TIMING_MS: dict[str, float] = {"http": 0.0, "json": 0.0}


def get_driver_aid_node(
    node: str,
    *,
    api_key: Optional[str] = None,
    base_url: str = TSW_API_BASE,
    timeout_s: float = DEFAULT_READ_TIMEOUT_S,
) -> Optional[dict[str, Any]]:
    """GET ``/get/DriverAid.<nodo>`` → dict ``Values`` o ``None``."""
    key = api_key or find_api_key()
    if not key:
        return None
    encoded = encode_api_path(node)
    url = f"{base_url.rstrip('/')}/get/{encoded}"
    req = urllib.request.Request(
        url,
        headers={"DTGCommKey": key, "X-API-Key": key},
        method="GET",
    )
    t_http = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log.debug("GET %s: %s", node, exc)
        return None
    t_json = time.perf_counter()
    POLL_TIMING_MS["http"] += (t_json - t_http) * 1000.0
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    finally:
        POLL_TIMING_MS["json"] += (time.perf_counter() - t_json) * 1000.0
    if not isinstance(data, dict) or data.get("Result") != "Success":
        return None
    values = data.get("Values")
    return values if isinstance(values, dict) else None


def probe_http_api(
    *,
    api_key: Optional[str] = None,
    base_url: str = TSW_API_BASE,
    timeout_s: float = DEFAULT_READ_TIMEOUT_S,
) -> bool:
    key = api_key or find_api_key()
    if not key:
        return False
    url = f"{base_url.rstrip('/')}/info"
    req = urllib.request.Request(
        url,
        headers={"DTGCommKey": key, "X-API-Key": key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
