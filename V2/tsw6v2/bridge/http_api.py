"""Cliente HTTP mínimo para DriverAid (TSW6 -HTTPAPI). Sin dependencia de ``tsw6``."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

_log = logging.getLogger("tsw6v2.http_api")

TSW_API_BASE = "http://localhost:31270"
DEFAULT_READ_TIMEOUT_S = 1.0

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
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log.debug("GET %s: %s", node, exc)
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
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
