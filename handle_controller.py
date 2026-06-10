#!/usr/bin/env python3
"""
handle_controller.py — Ejecución del handle PowerBrakeHandle + SafetyWatchdog.

Dos clases en este módulo:

  HandleController
    - Recibe (action, TrainState, conn, hwnd) y envía un paso de control
    - USA state.handle_notch como fuente de verdad (nunca un contador interno)
    - RPC preferido (set_control_value), teclado como fallback
    - Detecta interferencia del companion y suprime COAST durante 1.5s
    - Sin stuck-detection ni force_neutral automáticos

  SafetyWatchdog
    - Monitorea exceso de velocidad persistente → HARDBRAKE
    - Notch máximo sin aceleración → solo WARNING en log
    - NO fuerza resets automáticos (era la causa de los frenos de emergencia falsos)
    - El operador usa tecla N para sincronizar manualmente si hace falta

Mapa del handle PowerBrakeHandle (Class 323):
  0 = freno máximo … 4 = neutro … 8 = tracción máxima
  VK_A = subir handle (+1)   →   mayor tracción / soltar freno
  VK_D = bajar handle (−1)   →   menos tracción / más freno
"""

import logging
import time
from typing import Optional

from governor_constants import (
    CONTROL_INTERVAL, CONTROL_INTERVAL_BRAKE, CONTROL_INTERVAL_EMERG,
    SERVICE_MAX_BRAKE,
)
from tsw_keys import VK_A, VK_D, KEY_HOLD_MS, send_key
from train_state import TrainState

_log = logging.getLogger("tsw.controller")

# Handle neutro y límites
_NOTCH_NEUTRAL     = 4
_MAX_NOTCH         = 8
_BRAKE_MIN_HANDLE  = _NOTCH_NEUTRAL - SERVICE_MAX_BRAKE   # = 1 (servicio)
_GRACE_AFTER_EXT   = 1.5   # segundos de supresión de COAST tras subida externa
_RPC_DISABLE_COUNT = 5     # fallos consecutivos antes de deshabilitar RPC
_RPC_DISABLE_S     = 300.0  # segundos de penalización


class HandleController:
    """
    Capa de ejecución: traduce acciones en comandos al mando del tren.

    Regla fundamental: current_notch = state.handle_notch  (siempre telemetría)

    Ciclo de execute():
      1. Rate-limit por tipo de acción
      2. Leer posición real del handle desde state.handle_notch
      3. Detectar si el companion/jugador ha subido el notch externamente
      4. Calcular notch objetivo (un solo paso hacia el destino)
      5. Suprimir COAST si hubo subida externa reciente
      6. Enviar comando: RPC o teclado
    """

    _INTERVALS: dict[str, float] = {
        "ACCELERATE": CONTROL_INTERVAL,
        "COAST":      CONTROL_INTERVAL_BRAKE,
        "BRAKE":      CONTROL_INTERVAL_BRAKE,
        "FULLSTOP":   CONTROL_INTERVAL_BRAKE,
        "HARDBRAKE":  CONTROL_INTERVAL_EMERG,
    }

    def __init__(self) -> None:
        # RPC failure tracking
        self._rpc_fail_count:     int   = 0
        self._rpc_disabled_until: float = 0.0

        # Rate limiting
        self._last_control: float = 0.0

        # Anti-oscilación: detectar subida externa de notch
        self._last_seen_notch: Optional[int] = None
        self._last_ext_up_t:   float         = 0.0

        # Para force_neutral / reset_neutral
        self._last_sync_t: float = 0.0

    # ── RPC helpers ───────────────────────────────────────────────────────

    def _use_rpc(self, conn: Optional[object]) -> bool:
        """True si RPC disponible y no penalizado."""
        if conn is None or getattr(conn, "mode", None) != "companion":
            return False
        return self._rpc_disabled_until <= time.time()

    def _try_rpc(self, conn: object, control: str, val: float) -> bool:
        """Intenta llamada RPC y actualiza el contador de fallos."""
        try:
            result = conn.set_control_value(control, val)  # type: ignore[union-attr]
            if result:
                self._rpc_fail_count = 0
                self._rpc_disabled_until = 0.0
                return True
            self._rpc_fail_count += 1
        except Exception as exc:
            _log.debug("RPC excepción: %s", exc)
            self._rpc_fail_count += 1

        if self._rpc_fail_count >= _RPC_DISABLE_COUNT:
            self._rpc_disabled_until = time.time() + _RPC_DISABLE_S
            _log.warning(
                "RPC falló %d veces — usando teclado durante %.0fs",
                self._rpc_fail_count, _RPC_DISABLE_S)
        return False

    # ── Cálculo del notch objetivo ────────────────────────────────────────

    def _target_notch(self, action: str, current: int) -> int:
        """
        Calcula el notch objetivo para la acción dada.
        Un paso por ciclo (el rate-limit controla la velocidad total).
        """
        if action == "ACCELERATE":
            return min(_MAX_NOTCH, current + 1)
        if action == "COAST":
            # Solo soltar tracción: si ya estamos en neutro o freno, no hacer nada
            if current > _NOTCH_NEUTRAL:
                return current - 1
            return current
        if action == "BRAKE":
            if current > _NOTCH_NEUTRAL:
                return current - 1          # soltar tracción primero
            return max(_BRAKE_MIN_HANDLE, current - 1)
        if action == "HARDBRAKE":
            if current > _NOTCH_NEUTRAL:
                return _NOTCH_NEUTRAL       # saltar directo a neutro
            return max(0, current - 1)      # freno completo permitido
        if action == "FULLSTOP":
            if current > _NOTCH_NEUTRAL:
                return _NOTCH_NEUTRAL
            return 0                        # freno total
        return current

    # ── Ejecución ─────────────────────────────────────────────────────────

    def execute(self, action: str, state: TrainState,
                conn: Optional[object], hwnd: Optional[int]) -> bool:
        """
        Ejecuta la acción enviando un paso de control al mando.

        Devuelve True si envió un comando, False si esperó (rate-limit,
        ya en posición, HOLD/PAUSED, o suppresión anti-oscilación).
        """
        if action in ("HOLD", "PAUSED"):
            return False

        now = time.time()
        interval = self._INTERVALS.get(action, CONTROL_INTERVAL)
        if now - self._last_control < interval:
            return False

        current = state.handle_notch  # SIEMPRE telemetría

        # Detectar incremento externo del notch (companion / jugador).
        # Solo se cuenta como "externo" si el salto es > 1 posición, porque
        # nuestros propios comandos (+1 por ciclo) pueden aparecer con un ciclo
        # de retraso en la telemetría y provocarían falsos positivos.
        if (self._last_seen_notch is not None
                and current > self._last_seen_notch + 1
                and now - self._last_control > CONTROL_INTERVAL * 0.5):
            self._last_ext_up_t = now
            _log.debug("Subida externa: notch %d → %d", self._last_seen_notch, current)
        self._last_seen_notch = current

        # Suprimir COAST durante _GRACE_AFTER_EXT tras subida externa,
        # EXCEPTO en modo ACK donde el ATP tiene control y la supresión
        # solo prolonga la lucha entre autopilot, companion y ATP.
        ack = getattr(state, "ack_required", False)
        if (action == "COAST"
                and not ack
                and now - self._last_ext_up_t < _GRACE_AFTER_EXT):
            _log.debug(
                "COAST suprimido (%.1fs tras subida externa)",
                now - self._last_ext_up_t)
            return False

        target = self._target_notch(action, current)
        if target == current:
            return False

        new_notch = current + (1 if target > current else -1)

        # Intentar RPC primero
        if self._use_rpc(conn):
            val = new_notch / float(_MAX_NOTCH)
            if self._try_rpc(conn, "PowerBrakeHandle", val):
                _log.debug(
                    "RPC  action=%-11s  notch %d→%d  (val=%.3f)",
                    action, current, new_notch, val)
                self._last_control = now
                return True
            # RPC falló: caer a teclado en esta misma llamada

        # Fallback: teclado
        if hwnd is None:
            _log.debug("execute: no hwnd — ignorando acción %s", action)
            return False

        if new_notch > current:
            send_key(hwnd, VK_A)
        else:
            send_key(hwnd, VK_D)

        _log.debug(
            "KEY  action=%-11s  notch %d→%d  key=%s",
            action, current, new_notch, "A" if new_notch > current else "D")
        self._last_control = now
        return True

    # ── Sincronización y reset ────────────────────────────────────────────

    def force_neutral(self, hwnd: Optional[int],
                      conn: Optional[object] = None) -> None:
        """
        Sincroniza el handle a neutro (4) desde posición desconocida.
        Uso: al arrancar si handle_notch no está disponible en telemetría,
             o cuando el operador pulsa tecla N.
        """
        now = time.time()

        if self._use_rpc(conn):
            _log.info("force_neutral: RPC → neutro (0.5)")
            if self._try_rpc(conn, "PowerBrakeHandle", 0.5):
                self._last_sync_t = now
                return

        if hwnd is None:
            _log.warning("force_neutral: sin hwnd, no se puede sincronizar")
            return

        _log.warning("force_neutral: sincronizando handle físicamente (~5s)...")
        pause = KEY_HOLD_MS / 1000.0 + 0.10
        # Bajar hasta el límite (máx freno: 0) partiendo de cualquier posición
        for _ in range(_MAX_NOTCH + _NOTCH_NEUTRAL + 2):
            send_key(hwnd, VK_D)
            time.sleep(pause)
        # Subir 4 posiciones para llegar a neutro (4)
        for _ in range(_NOTCH_NEUTRAL):
            send_key(hwnd, VK_A)
            time.sleep(pause)

        self._last_sync_t = now
        _log.info("force_neutral: handle en neutro (pos %d)", _NOTCH_NEUTRAL)

    def reset_neutral(self, hwnd: Optional[int],
                      current_handle: int = _NOTCH_NEUTRAL) -> None:
        """
        Lleva el handle a neutro desde una posición conocida.
        Llamar al salir del autopilot con el último handle conocido de la telemetría.
        """
        if hwnd is None:
            return
        pause = KEY_HOLD_MS / 1000.0 + 0.05
        pos = current_handle
        while pos > _NOTCH_NEUTRAL:
            send_key(hwnd, VK_D)
            time.sleep(pause)
            pos -= 1
        while pos < _NOTCH_NEUTRAL:
            send_key(hwnd, VK_A)
            time.sleep(pause)
            pos += 1
        _log.info("reset_neutral: handle en neutro")

    @property
    def in_sync_cooldown(self) -> bool:
        """True durante los 5s de gracia tras un force_neutral."""
        return (time.time() - self._last_sync_t) < 5.0


# ─────────────────────────────────────────────────────────────────────────────


class SafetyWatchdog:
    """
    Capa de seguridad: monitorea condiciones críticas y genera overrides.

    Diseño conservador:
    - HARDBRAKE solo para exceso de velocidad PERSISTENTE (> 5mph durante > 3s)
    - Notch máximo sin respuesta → solo log de warning, SIN reset forzado
    - El operador decide cuándo sincronizar con tecla N

    Esto elimina los falsos positivos del stuck-detection anterior que
    causaban frenos de emergencia inesperados.
    """

    # Segundos de exceso continuo antes de intervenir
    _OVERSPEED_TRIGGER_S = 3.0
    # mph de exceso necesarios para activar el watchdog
    _OVERSPEED_MPH = 5.0
    # Intervalo mínimo entre warnings de notch máximo
    _NOTCH_WARN_INTERVAL_S = 15.0

    def __init__(self) -> None:
        self._overspeed_since:    Optional[float] = None
        self._notch_max_logged_t: float           = 0.0

    def check(self, state: TrainState) -> Optional[str]:
        """
        Evalúa el estado del tren en busca de condiciones de emergencia.

        Returns:
            "HARDBRAKE" si se debe frenar de emergencia, None si todo OK.
        """
        now = time.time()

        # Exceso de velocidad crítico persistente
        if state.limit_mph > 0 and state.speed_mph > state.limit_mph + self._OVERSPEED_MPH:
            if self._overspeed_since is None:
                self._overspeed_since = now
                _log.warning(
                    "SafetyWatchdog: exceso %.1f mph sobre límite %.1f mph — iniciando cuenta",
                    state.speed_mph - state.limit_mph, state.limit_mph)
            elif now - self._overspeed_since >= self._OVERSPEED_TRIGGER_S:
                _log.warning(
                    "SafetyWatchdog HARDBRAKE: exceso %.1f mph durante ≥%.0fs",
                    state.speed_mph - state.limit_mph, self._OVERSPEED_TRIGGER_S)
                return "HARDBRAKE"
        else:
            self._overspeed_since = None

        # Notch máximo sin aceleración → warning sin acción
        if (state.handle_notch >= _MAX_NOTCH
                and state.acceleration_ms2 is not None
                and state.acceleration_ms2 < 0.05
                and now - self._notch_max_logged_t >= self._NOTCH_WARN_INTERVAL_S):
            _log.warning(
                "Notch máximo sin aceleración (a=%.3f m/s²) — "
                "¿freno emergencia o reversor? Pulsa N para sincronizar.",
                state.acceleration_ms2)
            self._notch_max_logged_t = now

        return None
