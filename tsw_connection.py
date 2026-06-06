#!/usr/bin/env python3
"""
TswConnection — Gestión de conexión SSE con RailBridge Companion.

Descubre automáticamente la IP del companion (127.0.0.1 o LAN),
mantiene el stream SSE en background y parsea cada dmi_snapshot.
"""

import json
import logging
import os
import secrets
import socket
import threading
import time
import uuid
from typing import Optional

import requests  # type: ignore[import-untyped]

_log = logging.getLogger("tsw.connection")

# ── Configuración del companion ───────────────────────────────────────────────

COMP_PORT  = 51160
COMP_TOKEN = "aaeeb63be194470bb7f97c98b93635aa"
YD_TO_M    = 0.9144   # 1 yard = 0.9144 metros


class TswConnection:
    """
    Gestiona la conexión con el RailBridge Companion via SSE.

    El companion expone un stream Server-Sent Events en:
        GET http://{host}:51160/events?t={token}

    Eventos relevantes:
      - dmi_snapshot : velocidad, límites, distancias
      - dashboard_snapshot : estado completo del tren

    La IP del companion puede ser 127.0.0.1 o la IP LAN del PC.
    Esta clase la descubre automáticamente.
    """

    KPH_TO_MPH = 0.621371

    def __init__(self):
        self.mode            = "searching"
        self.last_probe_info = "No probado aún"
        self.comp_base: Optional[str] = None   # ej: "http://192.168.0.66:51160"
        self._telem: dict    = {}
        self._telem_lock     = threading.Lock()
        self._sse_thread: Optional[threading.Thread] = None
        self._sse_stop       = threading.Event()
        self._session        = requests.Session()
        self._dist_unit      = "m"   # 'm' o 'yd', auto-detectado del snapshot
        self._last_route_stations: list = []   # caché de estaciones del dashboard_snapshot
        self._service_name: Optional[str] = None  # headcode del servicio activo
        self._timetable: dict = self._load_timetable()   # paradas programadas por servicio
        self._device_creds: Optional[dict] = None  # {device_id, device_secret}

        # ── Throttle de logging repetitivo ────────────────────────────────────
        self._log_throttle_planning: float = 0.0     # última vez que se logueó planning_delta items
        self._log_throttle_stations: float = 0.0     # última vez que se logueó stations
        self._log_last_timetable_result: Optional[int] = None  # último resultado del filtro timetable
        self._LOG_THROTTLE_INTERVAL = 5.0            # mínimo 5s entre logs repetitivos

    # ── Carga del timetable ─────────────────────────────────────────────────

    @staticmethod
    def _load_timetable() -> dict:
        """Carga timetable.json (mismo directorio que este módulo). Devuelve {} si no existe."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timetable.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return {
                k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, list)
            }
        except Exception:
            return {}
    # ── Credenciales de dispositivo (pairing v2) ────────────────────────────────

    def _get_device_creds(self) -> dict:
        """Carga o genera credenciales de dispositivo persistidas en railbridge_device.json."""
        if self._device_creds:
            return self._device_creds
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "railbridge_device.json")
        try:
            with open(path, encoding="utf-8") as f:
                creds = json.load(f)
            if creds.get("device_id") and creds.get("device_secret"):
                self._device_creds = creds
                return creds
        except Exception:
            pass
        # Generar nuevas credenciales
        creds = {
            "device_id":     str(uuid.uuid4()),
            "device_secret": secrets.token_hex(16),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(creds, f, indent=2)
        except Exception:
            pass
        self._device_creds = creds
        return creds

    def _pair_device(self, base: str) -> bool:
        """
        Hace pairing con RailBridge Companion.
        Retorna True cuando el dispositivo queda 'trusted'.
        Bloquea hasta aprobación o hasta que _sse_stop se active.
        """
        creds = self._get_device_creds()
        url   = f"{base}/pair?t={COMP_TOKEN}"
        body  = json.dumps({
            "device_id":     creds["device_id"],
            "device_secret": creds["device_secret"],
            "device_name":   "TSW6-Autopilot",
        }).encode()
        headers = {"Content-Type": "application/json"}
        first_pending = True
        while not self._sse_stop.is_set():
            try:
                r = self._session.post(url, data=body, headers=headers, timeout=5)
                resp = r.json()
                status = resp.get("status")
                if status == "trusted":
                    _log.info("RailBridge pairing OK (trusted)")
                    return True
                if status == "pending":
                    code = resp.get("code", "?")
                    if first_pending:
                        _log.warning(
                            "RailBridge esperando aprobación — "
                            "aprueba el código  %s  en la app RailBridge Companion", code
                        )
                        first_pending = False
                    time.sleep(2)
                    continue
                if status == "rejected":
                    _log.error("RailBridge rechazó el pairing — elimina el dispositivo y vuelve a intentar")
                    return False
                _log.error("Respuesta inesperada de /pair: %s", resp)
                return False
            except Exception as e:
                _log.warning("Error en /pair: %s — reintentando", e)
                time.sleep(3)
        return False

    def _sse_url(self) -> str:
        """Construye la URL del stream SSE con las credenciales de dispositivo."""
        creds = self._get_device_creds()
        return (
            f"{self.comp_base}/events"
            f"?t={COMP_TOKEN}"
            f"&d={creds['device_id']}"
            f"&k={creds['device_secret']}"
        )
    # ── Descubrimiento de IP del companion ──────────────────────────────────

    def _find_companion_hosts(self) -> list[str]:
        """Devuelve lista de hosts a probar para el companion (127.0.0.1 + IPs LAN)."""
        hosts = ["127.0.0.1"]
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None):
                ip = str(info[4][0])
                if ip not in hosts and not ip.startswith("::") and ":" not in ip:
                    hosts.append(ip)
        except Exception:
            pass
        return hosts

    def probe(self) -> str:
        """
        Intenta conectar al companion SSE.
        Prueba 127.0.0.1 y todas las IPs LAN en el puerto 51160.
        Devuelve 'companion' si conectó, 'searching' si no.
        """
        tried = []
        for host in self._find_companion_hosts():
            s = socket.socket()
            s.settimeout(0.3)
            try:
                s.connect((host, COMP_PORT))
                s.close()
            except Exception:
                tried.append(f"{host}:cerrado")
                continue

            base = f"http://{host}:{COMP_PORT}"
            # Nueva API v2: hacer pairing antes de conectar el SSE
            self.comp_base = base
            if not self._pair_device(base):
                tried.append(f"{host}:pairing_failed")
                self.comp_base = None
                continue
            # Pairing OK — verificar que el SSE responde
            try:
                r = self._session.get(
                    self._sse_url(),
                    stream=True,
                    timeout=(1.0, 2.0),
                )
                if r.status_code == 200:
                    for raw_line in r.iter_lines(decode_unicode=True):
                        if isinstance(raw_line, str) and raw_line.startswith("data:"):
                            r.close()
                            self.mode = "companion"
                            self.last_probe_info = f"SSE en {base}/events (paired)"
                            self._start_sse()
                            return "companion"
                r.close()
            except Exception as e:
                tried.append(f"{host}:{type(e).__name__}")
                self.comp_base = None

        self.mode = "searching"
        self.comp_base = None
        self.last_probe_info = "; ".join(tried) or "Sin respuesta"
        return "searching"

    # ── Thread SSE en background ─────────────────────────────────────────────

    def _start_sse(self) -> None:
        """Lanza (o relanza) el thread que mantiene la conexión SSE activa."""
        if self._sse_thread and self._sse_thread.is_alive():
            return
        self._sse_stop.clear()
        self._sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self._sse_thread.start()

    def _sse_loop(self) -> None:
        """Lee el stream SSE indefinidamente y actualiza _telem."""
        while not self._sse_stop.is_set():
            url = self._sse_url()
            try:
                r = self._session.get(url, stream=True, timeout=(3, None))
                event_type = None
                for raw_line in r.iter_lines(decode_unicode=True):
                    if self._sse_stop.is_set():
                        break
                    if not isinstance(raw_line, str) or not raw_line:
                        continue
                    if raw_line.startswith("event:"):
                        event_type = raw_line[6:].strip()
                    elif raw_line.startswith("data:") and event_type in ("companion_dmi_delta", "dmi_snapshot"):
                        try:
                            data = json.loads(raw_line[5:].strip())
                            parsed = self._parse_dmi(data)
                            # handle_notch ahora en companion_dmi_delta.controls.throttle_notch.value
                            tn = (data.get("controls") or {}).get("throttle_notch")
                            if isinstance(tn, dict) and tn.get("value") is not None:
                                parsed["handle_notch"] = int(tn["value"])
                            with self._telem_lock:
                                # Conservar doors_open (ya no viene en este evento)
                                parsed.setdefault("doors_open", self._telem.get("doors_open", False))
                                # Preservar último doors_dmi conocido si este ciclo no trajo dato
                                if parsed.get("doors_dmi") is None and self._telem.get("doors_dmi") is not None:
                                    parsed["doors_dmi"] = self._telem["doors_dmi"]
                                # Conservar handle_notch si no vino en este ciclo
                                parsed.setdefault("handle_notch", self._telem.get("handle_notch"))
                                # Conservar gradient del último companion_dmi_planning_delta
                                parsed.setdefault("gradient_pct", self._telem.get("gradient_pct"))
                                # Actualizar service_name si el DMI lo incluye
                                svc_from_dmi = parsed.get("service_name")
                                if svc_from_dmi and not self._service_name:
                                    self._service_name = str(svc_from_dmi)
                                    _log.info("Servicio detectado (dmi_delta): %r", self._service_name)
                                if self._last_route_stations:
                                    # planning_delta es la fuente de estaciones; refrescar
                                    # distancias con datos DMI más recientes cuando coincidan.
                                    dmi_stns = parsed.get("stations") or []
                                    result = []
                                    for rs in self._last_route_stations:
                                        entry = dict(rs)
                                        if dmi_stns:
                                            best = min(
                                                dmi_stns,
                                                key=lambda s, d=rs["distance_m"]: abs(s["distance_m"] - d),
                                            )
                                            if abs(best["distance_m"] - rs["distance_m"]) < 500:
                                                entry["distance_m"] = best["distance_m"]
                                        result.append(entry)
                                    parsed["stations"] = sorted(result, key=lambda x: x["distance_m"])
                                # else: Sin planning_delta aún → parsed["stations"] ya tiene
                                # los datos del DMI tal cual (comportamiento por defecto).
                                # ── Filtrado con timetable.json ──────────────────────────
                                # La API devuelve TODAS las plataformas del trecho (incluyendo
                                # pasos como Shenstone). Filtrar usando la lista blanca del
                                # timetable: si hay servicio conocido → solo sus paradas;
                                # si no → whitelist de TODOS los servicios del timetable.
                                if self._timetable and parsed.get("stations"):
                                    if self._service_name and self._service_name in self._timetable:
                                        scheduled_lower = {
                                            s.split(",")[0].strip().lower()
                                            for s in self._timetable[self._service_name]
                                        }
                                    else:
                                        scheduled_lower = {
                                            s.split(",")[0].strip().lower()
                                            for stops in self._timetable.values()
                                            for s in stops
                                        }
                                    before = len(parsed["stations"])
                                    parsed["stations"] = [
                                        st for st in parsed["stations"]
                                        if st.get("name", "?") == "?" or
                                        st["name"].split(",")[0].strip().lower() in scheduled_lower
                                    ]
                                    if len(parsed["stations"]) != before:
                                        # Only log when the filter result changes
                                        _new_count = len(parsed["stations"])
                                        if _new_count != self._log_last_timetable_result:
                                            _log.debug(
                                                "Timetable filter: %d → %d estaciones eliminadas=%s",
                                                before, _new_count,
                                                [st["name"] for st in
                                                 self._last_route_stations or []
                                                 if st.get("name", "?") != "?" and
                                                 st["name"].split(",")[0].strip().lower()
                                                 not in scheduled_lower],
                                            )
                                            self._log_last_timetable_result = _new_count
                                _now_st = time.time()
                                if _now_st - self._log_throttle_stations >= self._LOG_THROTTLE_INTERVAL:
                                    _log.debug("stations: %s",
                                               [(s["name"],
                                                 round(s["distance_m"]),
                                                 f"andén {s['platform_length_m']:.0f}m"
                                                 if s.get("platform_length_m") else None)
                                                for s in parsed.get("stations", [])])
                                    self._log_throttle_stations = _now_st
                                self._telem = parsed
                                if self.mode != "companion":
                                    self.mode = "companion"
                        except Exception:
                            pass
                    elif raw_line.startswith("data:") and event_type in ("companion_dmi_planning_delta", "dashboard_snapshot"):
                        try:
                            data = json.loads(raw_line[5:].strip())
                            if event_type == "companion_dmi_planning_delta":
                                gradient_pct = (data.get("gradient_percent") or {}).get("value")
                                route_stations = self._parse_planning_stations(data)
                                # service_name puede estar en route_monitor en el futuro
                            else:
                                # Compatibilidad con dashboard_snapshot antiguo
                                gradient_pct = None
                                route_stations = self._parse_route_stations(data)
                                typed = (data.get("feed", {}).get("typed") or {})
                                identity = typed.get("identity") or {}
                                svc_raw = identity.get("service_name")
                                if isinstance(svc_raw, dict):
                                    svc_raw = svc_raw.get("value")
                                if svc_raw:
                                    self._service_name = str(svc_raw)
                                # handle_notch legacy desde dashboard_snapshot
                                ctrl = typed.get("controls") or {}
                                tn_raw = ctrl.get("throttle_notch")
                                if isinstance(tn_raw, dict) and tn_raw.get("value") is not None:
                                    with self._telem_lock:
                                        self._telem["handle_notch"] = int(tn_raw["value"])
                            with self._telem_lock:
                                if gradient_pct is not None:
                                    # EWMA α=0.3 para suavizar ruido de la API
                                    prev = self._telem.get("gradient_pct")
                                    if prev is not None:
                                        gradient_pct = round(0.7 * prev + 0.3 * gradient_pct, 2)
                                    self._telem["gradient_pct"] = gradient_pct
                                if route_stations:
                                    if route_stations != self._last_route_stations:
                                        _log.info("planning_delta paradas: %s",
                                                  [s["name"] for s in route_stations])
                                    self._last_route_stations = route_stations
                        except Exception:
                            pass
                    elif raw_line.startswith("data:") and event_type == "engine_event":
                        try:
                            data = json.loads(raw_line[5:].strip())
                            ev_type = data.get("type", "").lower()
                            _log.debug("engine_event type=%r  keys=%s", ev_type, list(data.keys()))
                            # Extraer service_name si el engine_event es de tipo servicio
                            if "service" in ev_type or "mission" in ev_type:
                                svc = (data.get("service_name") or data.get("service")
                                       or data.get("mission") or "")
                                if svc:
                                    self._service_name = str(svc)
                            # Detectar apertura/cierre de puertas por nombre del evento
                            elif "door" in ev_type:
                                doors_open = "open" in ev_type and "clos" not in ev_type
                                with self._telem_lock:
                                    self._telem["doors_open"] = doors_open
                                _log.debug("Puertas (event) → doors_open=%s (type=%r)", doors_open, ev_type)
                            # live_weather_updated: extraer intensidad de lluvia
                            elif ev_type == "live_weather_updated":
                                _log.debug("live_weather  keys=%s", list(data.keys()))
                                rain = self._parse_rain_intensity(data)
                                with self._telem_lock:
                                    self._telem["rain_intensity"] = rain
                                _log.info("weather → rain_intensity=%.2f  (conditions=%s)",
                                          rain, data.get("conditions"))
                            # companion_ui_state_changed: app_messages puede contener estado de puertas
                            elif ev_type == "companion_ui_state_changed":
                                app_msgs = data.get("app_messages") or []
                                if app_msgs:
                                    _log.debug("companion_ui app_messages=%s", app_msgs[:8])
                            # dmi_snapshot: loguear keys de controls y mensajes (para diagnóstico de puertas)
                            elif ev_type == "dmi_snapshot":
                                _log.debug("dmi_snapshot ctrl_keys=%s", list((data.get("controls") or {}).keys()))
                                msgs = data.get("messages") or []
                                if msgs:
                                    _log.debug("dmi_snapshot messages=%s", msgs[:5])
                                sound = data.get("sound_intents") or []
                                if sound:
                                    _log.debug("dmi_snapshot sound_intents=%s", sound[:5])
                        except Exception:
                            pass
            except Exception as _exc:
                _log.warning("SSE stream interrumpido (%s) — reconectando en 3 s", _exc)
            if not self._sse_stop.is_set():
                with self._telem_lock:
                    self.mode = "searching"
                time.sleep(3)
    # ── Parseo de estaciones desde companion_dmi_planning_delta ────────────────────

    @staticmethod
    def _parse_planning_stations(data: dict) -> list:
        """
        Extrae paradas desde companion_dmi_planning_delta.route_monitor.items.
        Usa items de tipo 'platform' con label no vacío.
        """
        try:
            items = (data.get("route_monitor") or {}).get("items") or []
            # Log diagnóstico: tipos de items disponibles (solo en primer evento)
            if items:
                types_seen = list({i.get("type") for i in items if isinstance(i, dict)})
                _now = time.time()
                if _now - self._log_throttle_planning >= self._LOG_THROTTLE_INTERVAL:
                    _log.debug("planning_delta items: %d total, tipos=%s", len(items), types_seen)
                    self._log_throttle_planning = _now
            seen: dict[str, dict] = {}
            for item in items:
                if not isinstance(item, dict) or item.get("type") != "platform":
                    continue
                platform = item.get("platform") or {}
                label = platform.get("label", "").strip()
                if not label:
                    continue
                dist = item.get("distance_end_m")
                if dist is None or float(dist) <= 0:
                    continue
                dist = float(dist)
                plat_len = platform.get("length_m")
                entry: dict = {"name": label, "distance_m": dist}
                if plat_len and float(plat_len) > 0:
                    entry["platform_length_m"] = round(float(plat_len), 1)
                # Deduplicar por nombre base (ej. 'Lichfield City, andén 1' y 'andén 2')
                base = label.split(",")[0].strip().lower()
                if base not in seen or dist < seen[base]["distance_m"]:
                    seen[base] = entry
            return sorted(seen.values(), key=lambda x: x["distance_m"])
        except Exception:
            return []
    # ── Parseo del dashboard_snapshot (puertas) ─────────────────────────────

    @staticmethod
    def _parse_doors(data: dict) -> bool:
        """
        Devuelve True si alguna puerta de pasajeros está abierta.
        Ruta: feed.typed.controls.passenger_doors[N].value.is_open
        """
        try:
            doors = (data.get("feed", {})
                        .get("typed", {})
                        .get("controls", {})
                        .get("passenger_doors", []))
            return any(
                isinstance(d, dict) and
                isinstance(d.get("value"), dict) and
                d["value"].get("is_open") is True
                for d in doors
            )
        except Exception:
            return False

    # ── Parseo de estaciones desde dashboard_snapshot ────────────────────────

    @staticmethod
    def _parse_route_stations(data: dict) -> list:
        """
        Extrae paradas desde dashboard_snapshot.feed.typed.route.

        Usa route_markers (kind='Platform') porque:
          - .label  = nombre real de la parada (ej. 'Blake Street, andén 1')
          - .distance_m = distancia al marcador de parada (extremo distal del andén)
            que es 146m más lejos que route.stations[0].distance_m (inicio del andén).
        """
        try:
            route = (data.get("feed", {})
                         .get("typed", {})
                         .get("route", {}))
            raw_markers = (route.get("route_markers", {}).get("value") or [])
            stations: list[dict] = []
            for m in raw_markers:
                if not isinstance(m, dict):
                    continue
                if m.get("kind") != "Platform":
                    continue
                dist = m.get("distance_m")
                if dist is None or float(dist) <= 0:
                    continue
                name = m.get("label") or "?"
                entry: dict = {"name": name, "distance_m": float(dist)}
                plat = m.get("platform_length_m")
                if plat and float(plat) > 0:
                    entry["platform_length_m"] = round(float(plat), 1)
                stations.append(entry)
            stations.sort(key=lambda x: x["distance_m"])
            # Deduplicar: si dos marcadores tienen el mismo nombre base
            # (ignorando ", andén N"), conservar solo el más cercano.
            seen: dict[str, dict] = {}
            for entry in stations:
                base = entry["name"].split(",")[0].strip().lower()
                if base not in seen or entry["distance_m"] < seen[base]["distance_m"]:
                    seen[base] = entry
            return sorted(seen.values(), key=lambda x: x["distance_m"])
        except Exception:
            return []

    # ── Parseo del dmi_snapshot ──────────────────────────────────────────────

    def _detect_dist_unit(self, data: dict) -> str:
        """
        Auto-detecta si las distancias del snapshot están en metros ('m') o yards ('yd').

        Estrategia:
          1. Campo explícito: measurement_system, display_units, units, etc.
          2. Nombre de campo: si existe target_distance_yd en lugar de _m → yards.
          3. Si no detecta nada → mantiene el valor anterior (o 'm' por defecto).
        """
        # 1. Campos explícitos de unidades
        for key_path in (
            ("measurement_system",),
            ("display_units",),
            ("units",),
            ("settings", "units"),
            ("meta", "units"),
        ):
            val: object = data
            for k in key_path:
                if not isinstance(val, dict):
                    val = None
                    break
                val = val.get(k)  # type: ignore[union-attr]
            if isinstance(val, str):
                s = val.lower()
                if "yd" in s or "yard" in s or "imperial" in s:
                    return "yd"
                if s in ("m", "meter", "meters", "metric", "si"):
                    return "m"

        # 2. Detectar por sufijo del nombre de campo
        limits = data.get("limits", {}) or {}
        if isinstance(limits, dict) and "target_distance_yd" in limits:
            return "yd"
        sm = data.get("speed_meter", {}) or {}
        if isinstance(sm, dict) and "advisory_brake_marker_distance_yd" in sm:
            return "yd"
        raw_stations = (data.get("planning") or {}).get("stations") or []
        if raw_stations and isinstance(raw_stations[0], dict) and "distance_yd" in raw_stations[0]:
            return "yd"

        return self._dist_unit   # Sin cambio detectado → mantener valor previo

    @staticmethod
    def _dmi_val(data: dict, *path: str) -> Optional[float]:
        """Navega un path anidado y devuelve el valor numérico o None."""
        obj = data
        for key in path:
            if not isinstance(obj, dict) or key not in obj:
                return None
            obj = obj[key]
        if isinstance(obj, (int, float)) and not (isinstance(obj, float) and (obj != obj)):
            return float(obj)
        return None

    def _parse_dmi(self, data: dict) -> dict:
        """
        Extrae telemetría del dmi_snapshot.
        Velocidades: siempre en kph → convertimos a mph.
        Distancias: auto-detecta si son metros o yards y normaliza a metros.
        """
        v = self._dmi_val
        K = self.KPH_TO_MPH

        # Auto-detectar unidades de distancia del snapshot
        dist_unit = self._detect_dist_unit(data)
        self._dist_unit = dist_unit
        d2m = YD_TO_M if dist_unit == "yd" else 1.0

        speed_mph       = v(data, "speed", "kph")
        limit_mph       = v(data, "limits", "current_permitted_speed_kph", "value")
        next_limit_mph  = v(data, "limits", "next_speed_kph", "value")

        # Distancias: intentar _m primero, luego _yd (y convertir)
        _dist_next_raw  = (v(data, "limits", "target_distance_m", "value") or
                           v(data, "limits", "target_distance_yd", "value"))
        dist_next_m     = _dist_next_raw * d2m if _dist_next_raw is not None else None

        _bm_raw         = (v(data, "speed_meter", "advisory_brake_marker_distance_m", "value") or
                           v(data, "speed_meter", "advisory_brake_marker_distance_yd", "value"))
        brake_marker_m  = _bm_raw * d2m if _bm_raw is not None else None

        accel_mps2      = v(data, "motion", "acceleration_mps2", "value")
        # gradient_pct: solo se lee desde companion_dmi_planning_delta (no desde dmi_delta)
        # para evitar que el 0.0 del dmi_delta sobreescriba el valor del planning_delta.

        # Muesca real del handle combinado (PowerBrakeHandle):
        # Viene del dashboard_snapshot (feed.typed.controls.throttle_notch.value).
        # Se preserva en _telem via setdefault en _sse_loop; no se lee aquí.

        # Paradas programadas — name y distance_m son dicts con .value (formato RailBridge)
        raw_stations = data.get("planning", {}).get("stations", []) or []
        stations: list[dict] = []

        def _sv(raw: object) -> "float | None":
            """Extrae valor numérico de un campo de estación (dict.value o directo)."""
            if raw is None:
                return None
            val = raw.get("value") if isinstance(raw, dict) else raw
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    return float(val)
                except ValueError:
                    return None
            return None

        for s in raw_stations:
            name_raw = s.get("name") or s.get("station_name") or s.get("id")
            name = (name_raw.get("value") if isinstance(name_raw, dict)
                    else name_raw) or "?"

            # Punto de parada preferido: stop_m > end_m > start_m > distance_m
            stop_raw = (_sv(s.get("distance_stop_m"))  or _sv(s.get("distance_stop_yd"))
                        or _sv(s.get("distance_end_m")) or _sv(s.get("distance_end_yd")))
            start_raw = (_sv(s.get("distance_m"))      or _sv(s.get("distance_yd"))
                         or _sv(s.get("distance_start_m")) or _sv(s.get("distance_start_yd")))

            # Usar stop como distancia principal si existe; si no, el inicio del andén
            dist_raw = stop_raw if stop_raw is not None else start_raw
            if dist_raw is None:
                continue
            dist = dist_raw * d2m

            # Solo estaciones por delante del tren (dist > 0)
            if dist <= 0:
                continue

            # Longitud del andén
            plat = (_sv(s.get("platform_length_m")) or _sv(s.get("platform_length_yd"))
                    or _sv(s.get("platform_length")))
            if plat is not None:
                plat *= d2m
            elif stop_raw is not None and start_raw is not None:
                plat = abs(stop_raw - start_raw) * d2m   # calculada desde start..stop

            entry: dict = {"name": name, "distance_m": dist}
            if plat is not None and plat > 0:
                entry["platform_length_m"] = round(plat, 1)
            stations.append(entry)

        # Ordenar de más cercana a más lejana y deduplicar por nombre base
        # (la API a veces devuelve dos entradas por andén: inicio y fin de plataforma)
        stations.sort(key=lambda x: x["distance_m"])
        seen_dmi: dict[str, dict] = {}
        for st in stations:
            base = st["name"].split(",")[0].strip().lower()
            if base not in seen_dmi or st["distance_m"] < seen_dmi[base]["distance_m"]:
                seen_dmi[base] = st
        stations = sorted(seen_dmi.values(), key=lambda x: x["distance_m"])

        service_name = (data.get("identity", {})
                            .get("service_name", {})
                            .get("value"))
        train_id     = (data.get("identity", {})
                            .get("train_identifier", {})
                            .get("value"))

        # ACK: sólo si algún mensaje del sistema de seguridad requiere reconocimiento
        # explícito (ack_required=True en el mensaje).
        # NOTA: supervision != "csm"/"sb" (modo TSM/RSM/OS) es operación normal
        # durante cualquier zona de velocidad reducida; no requiere ACK del conductor.
        supervision = (data.get("supervision") or "csm").lower()
        messages = data.get("messages", []) or []
        ack_required = any(
            isinstance(m, dict) and m.get("ack_required") is True for m in messages
        )

        # Estado de puertas desde mensajes del sistema (fuente más fiable).
        # id='dmi-doors-open'   → puertas abiertas
        # id='dmi-doors-closed' → puertas cerradas
        # Si ninguno está presente → None (desconocido)
        doors_dmi: Optional[bool] = None
        for _m in messages:
            _mid = _m.get("id", "") if isinstance(_m, dict) else ""
            if _mid == "dmi-doors-open":
                doors_dmi = True
                break
            elif _mid == "dmi-doors-closed":
                doors_dmi = False
                break
        
        # Fallback: intentar leer como fact directo si está expuesto
        fact_doors = v(data, "facts", "doors_open", "value")
        if fact_doors is not None:
            doors_dmi = bool(fact_doors)

        return {
            "speed_mph":       speed_mph  * K if speed_mph      is not None else None,
            "limit_mph":       limit_mph  * K if limit_mph      is not None else None,
            "next_limit_mph":  next_limit_mph * K if next_limit_mph is not None else None,
            "distance_next_m": dist_next_m,
            "brake_marker_m":  brake_marker_m,
            "accel_mps2":      accel_mps2,
            "stations":        stations,
            "service_name":    service_name,
            "train_id":        train_id,
            "dist_unit":       dist_unit,
            "supervision":     supervision,
            "ack_required":    ack_required,
            "doors_dmi":       doors_dmi,
        }

    # ── API pública ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_rain_intensity(data: dict) -> float:
        """
        Extrae la intensidad de lluvia del evento live_weather_updated.
        Devuelve un valor 0.0 (seco) … 1.0 (tormenta fuerte).

        La API RailBridge expone:
          data["conditions"]  → string  ej. "Rain", "Heavy Rain", "Thunderstorm",
                                           "Drizzle", "Snow", "Clear", etc.
          data["applied"]     → bool/str — si el clima está activo en el juego.

        Si "applied" es False o la condición es seca, devuelve 0.0.
        """
        applied = data.get("applied")
        if applied is False or str(applied).lower() in ("false", "0", "no"):
            return 0.0
        cond = str(data.get("conditions") or "").lower()
        # Mapa de condición → intensidad de lluvia (factor de reducción de adherencia)
        WET_MAP = {
            "thunderstorm": 1.0,
            "heavy rain":   0.9,
            "heavy snow":   0.85,
            "rain":         0.7,
            "drizzle":      0.4,
            "light rain":   0.4,
            "snow":         0.6,
            "sleet":        0.65,
            "mist":         0.2,
            "fog":          0.1,
        }
        for key, val in WET_MAP.items():
            if key in cond:
                return val
        return 0.0

    def get_telemetry(self) -> dict:
        """Devuelve el último snapshot parseado (thread-safe)."""
        if self.mode in ("manual", "searching"):
            return {}
        with self._telem_lock:
            return dict(self._telem)
