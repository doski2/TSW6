#!/usr/bin/env python3
"""
tsw_api_client.py — Cliente HTTP para la API externa de TSW6 (V2).

Requiere TSW6 con -HTTPAPI y CommAPIKey.txt generado.
Documentación: docs/ARQUITECTURA.md
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

_log = logging.getLogger("tsw.api")

TSW_API_BASE = "http://localhost:31270"
HUD_POWER_PATH = "CurrentDrivableActor.Function.HUD_GetPowerHandle"

KEY_PATHS: tuple[Path, ...] = (
    Path.home() / "Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6EGS/Saved/Config/CommAPIKey.txt",
    Path.home() / "Documents/My Games/TrainSimWorld6WGDK/Saved/Config/CommAPIKey.txt",
    Path.home() / "OneDrive/Documents/My Games/TrainSimWorld6/Saved/Config/CommAPIKey.txt",
)


def find_api_key() -> Optional[str]:
    """Lee CommAPIKey.txt de las rutas conocidas (Steam / EGS / WGDK)."""
    path = get_key_path()
    if path is None:
        return None
    key = path.read_text(encoding="utf-8").strip()
    return key or None


def get_key_path() -> Optional[Path]:
    for p in KEY_PATHS:
        if p.exists():
            return p
    return None


def encode_control_path(path: str) -> str:
    """
    Codifica ruta de nodo API (p. ej. DriverInput.PowerBrakeHandle).
    Conserva '.' como separador; espacios → %20.
    """
    parts = str(path).strip().split(".")
    return ".".join(quote(part, safe="") for part in parts if part)


def api_driver_input_path(control_path: str) -> str:
    """Prefijo DriverInput para PATCH/GET de mandos de cabina."""
    path = str(control_path or "").strip()
    if not path:
        return path
    if path.startswith("DriverInput."):
        return path
    return f"DriverInput.{path}"


def _parse_patch_response(
    response: requests.Response,
    api_path: str,
    value: float,
) -> dict[str, Any]:
    if response.status_code != 200:
        return {
            "ok": False,
            "error": "http_error",
            "status": response.status_code,
            "path": api_path,
            "body": (response.text or "")[:300],
        }
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("Result") == "Error":
            return {
                "ok": False,
                "error": "api_error",
                "path": api_path,
                "message": str(data.get("Message") or data.get("message") or ""),
                "body": (response.text or "")[:300],
            }
    except (ValueError, TypeError):
        pass
    return {"ok": True, "path": api_path, "value": value}


class TswApiClient:
    """Cliente mínimo GET/PATCH contra localhost:31270."""

    def __init__(
        self,
        api_key: str,
        base_url: str = TSW_API_BASE,
        session: Optional[requests.Session] = None,
        timeout: float = 2.0,
    ) -> None:
        if not api_key or not str(api_key).strip():
            raise ValueError("api_key vacía")
        self.api_key = str(api_key).strip()
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        # DTGCommKey es el header documentado; X-API-Key lo usa tsw_monitor.py
        return {
            "DTGCommKey": self.api_key,
            "X-API-Key": self.api_key,
        }

    def probe(self) -> bool:
        """True si el juego responde (p. ej. GET /info)."""
        return self.get_json("/info") is not None

    def get_json(self, endpoint: str) -> Optional[Any]:
        """GET genérico; None si falla conexión o HTTP != 200."""
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{path}"
        try:
            r = self._session.get(url, headers=self._headers(), timeout=self.timeout)
            if r.status_code != 200:
                _log.debug("GET %s → %d", path, r.status_code)
                return None
            return r.json()
        except requests.exceptions.ConnectionError:
            return None
        except Exception as exc:
            _log.debug("GET %s error: %s", path, exc)
            return None

    def list_controls(self) -> Optional[Any]:
        """GET /list — árbol de mandos del tren en cabina."""
        return self.get_json("/list")

    def list_node(self, node_name: str) -> Optional[Any]:
        """GET /list/{nodo} — hijos y endpoints del nodo (p. ej. CurrentDrivableActor)."""
        encoded = encode_control_path(node_name)
        return self.get_json(f"/list/{encoded}")

    def get_node(self, node_endpoint: str,
                 timeout: Optional[float] = None) -> Optional[dict[str, Any]]:
        """
        GET /get/{ruta} — lectura HUD u otras propiedades del actor en cabina.
        Devuelve el dict ``Values`` si Result == Success.
        """
        encoded = encode_control_path(node_endpoint)
        req_timeout = self.timeout if timeout is None else timeout
        path = f"/get/{encoded}"
        url = f"{self.base_url}{path}"
        try:
            r = self._session.get(
                url, headers=self._headers(), timeout=req_timeout)
            if r.status_code != 200:
                _log.debug("GET %s → %d", path, r.status_code)
                return None
            data = r.json()
        except requests.exceptions.ConnectionError:
            return None
        except Exception as exc:
            _log.debug("GET %s error: %s", path, exc)
            return None
        if not isinstance(data, dict) or data.get("Result") != "Success":
            return None
        values = data.get("Values")
        return values if isinstance(values, dict) else None

    def get_value(self, control_path: str) -> Optional[float]:
        """Lee {control_path}.Value vía GET /get/..."""
        api_path = api_driver_input_path(control_path)
        encoded = encode_control_path(api_path)
        data = self.get_json(f"/get/{encoded}.Value")
        if data is None:
            return None
        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, dict):
            for key in ("value", "Value", "val"):
                if key in data and data[key] is not None:
                    try:
                        return float(data[key])
                    except (TypeError, ValueError):
                        pass
        return None

    def get_input_value(self, control_path: str) -> Optional[float]:
        """Lee {control_path}.InputValue (eje -1..1 en Class 323)."""
        api_path = api_driver_input_path(control_path)
        encoded = encode_control_path(api_path)
        data = self.get_json(f"/get/{encoded}.InputValue")
        if data is None:
            return None
        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, dict):
            for key in ("value", "Value", "val"):
                if key in data and data[key] is not None:
                    try:
                        return float(data[key])
                    except (TypeError, ValueError):
                        pass
        return None

    def read_hud_combined_notch(self) -> Optional[int]:
        """HUD_GetPowerHandle → muesca UK 0–8."""
        from tsw6.telemetry.tsw_ue4ss_reader import power_to_combined_notch

        values = self.get_node(HUD_POWER_PATH)
        if not values or "Power" not in values:
            return None
        try:
            power = float(values["Power"])
        except (TypeError, ValueError):
            return None
        return power_to_combined_notch(power, bool(values.get("IsNegative", False)))

    def set_value(self, control_path: str, value: float,
                  timeout: Optional[float] = None) -> dict[str, Any]:
        """
        PATCH /set/{path}.Value?Value={n}
        Devuelve {ok: bool, ...} sin lanzar excepciones de red.
        """
        api_path = api_driver_input_path(control_path)
        encoded = encode_control_path(api_path)
        url = f"{self.base_url}/set/{encoded}.Value"
        req_timeout = self.timeout if timeout is None else timeout
        try:
            r = self._session.patch(
                url,
                headers=self._headers(),
                params={"Value": value},
                timeout=req_timeout,
            )
            return _parse_patch_response(r, api_path, value)
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error": "connection_refused", "path": api_path}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": api_path}

    def set_input_value(self, control_path: str, value: float,
                        timeout: Optional[float] = None) -> dict[str, Any]:
        """
        PATCH /set/{path}.InputValue?Value={n}
        Eje -1..1 en PowerBrakeHandle (Class 323 UK).
        """
        api_path = api_driver_input_path(control_path)
        encoded = encode_control_path(api_path)
        url = f"{self.base_url}/set/{encoded}.InputValue"
        req_timeout = self.timeout if timeout is None else timeout
        try:
            r = self._session.patch(
                url,
                headers=self._headers(),
                params={"Value": value},
                timeout=req_timeout,
            )
            return _parse_patch_response(r, api_path, value)
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error": "connection_refused", "path": api_path}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": api_path}

    def subscribe_path(self, subscription_id: int, node_endpoint: str) -> bool:
        """
        POST /subscription/{ruta}?Subscription={id}
        Formato correcto según integraciones TSW (path en la URL, no en query Path=).
        """
        encoded = encode_control_path(node_endpoint)
        url = f"{self.base_url}/subscription/{encoded}"
        try:
            r = self._session.post(
                url,
                headers=self._headers(),
                params={"Subscription": subscription_id},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                _log.debug("subscribe %s → %d", node_endpoint, r.status_code)
                return False
            data = r.json() if r.text else {}
            if isinstance(data, dict) and data.get("CurrentlyValid") is False:
                return False
            return True
        except Exception as exc:
            _log.debug("subscribe %s error: %s", node_endpoint, exc)
            return False

    def read_subscription(self, subscription_id: int) -> Optional[list[dict[str, Any]]]:
        """GET /subscription?Subscription={id} — lectura batched de paths suscritos."""
        data = self.get_json(f"/subscription?Subscription={subscription_id}")
        if not isinstance(data, dict):
            return None
        entries = data.get("Entries")
        return entries if isinstance(entries, list) else None

    def unsubscribe(self, subscription_id: int, node_endpoint: str) -> bool:
        encoded = encode_control_path(node_endpoint)
        url = f"{self.base_url}/subscription/{encoded}"
        try:
            r = self._session.delete(
                url,
                headers=self._headers(),
                params={"Subscription": subscription_id},
                timeout=self.timeout,
            )
            return r.status_code == 200
        except Exception:
            return False


def client_from_key_file() -> Optional[TswApiClient]:
    """Construye cliente si existe CommAPIKey.txt."""
    key = find_api_key()
    if not key:
        return None
    return TswApiClient(key)
