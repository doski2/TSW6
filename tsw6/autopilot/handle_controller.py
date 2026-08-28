#!/usr/bin/env python3
"""
handle_controller.py — Ejecución del handle PowerBrakeHandle + SafetyWatchdog.

Dos clases en este módulo:

  HandleController
    - Recibe (action, TrainState, conn, hwnd) y envía un paso de control
    - USA state.handle_notch como fuente de verdad (nunca un contador interno)
    - IPC preferido: un paso de muesca; teclado solo si IPC falla
    - Detecta interferencia externa y suprime COAST durante 1.5s
    - Sin stuck-detection ni force_neutral automáticos

  SafetyWatchdog
    - Monitorea exceso de velocidad persistente → BRAKE_FAST
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

from tsw6.autopilot.control_actions import (
    BRAKE, BRAKE_FAST, COAST, EMERGENCY, HOLD, PAUSED,
)
from tsw6.braking.v2.command import BrakeCommand
from tsw6.governor.governor_constants import (
    CONTROL_INTERVAL, CONTROL_INTERVAL_BRAKE, CONTROL_INTERVAL_FAST,
    CONTROL_INTERVAL_RPC,
    EMERGENCY_BRAKE_HANDLE,
    NOTCH_MAX,
    NOTCH_NEUTRAL,
    SERVICE_MAX_BRAKE,
)
from tsw6.autopilot.tsw_keys import VK_A, VK_D, KEY_HOLD_MS, KEY_TAP_MS, send_key
from tsw6.braking.v2.command import clamp_brake_handle
from tsw6.autopilot.train_state import TrainState

_log = logging.getLogger("tsw.controller")

_NOTCH_NEUTRAL     = NOTCH_NEUTRAL
_MAX_NOTCH         = NOTCH_MAX
_BRAKE_MIN_HANDLE  = _NOTCH_NEUTRAL - SERVICE_MAX_BRAKE   # = 1 (servicio)
_GRACE_AFTER_EXT   = 1.5   # segundos de supresión de COAST tras subida externa
_RPC_MAX_RETRIES   = 3     # reintentos por mando antes de contar fallo
_RPC_RETRY_BACKOFF_S = 0.025
_RPC_DISABLE_COUNT = 12    # fallos tras reintentos antes de pausa corta IPC
_RPC_DISABLE_S     = 5.0   # pausa IPC (s); teclado solo si sigue fallando


class HandleController:
    """
    Capa de ejecución: traduce acciones en comandos al mando del tren.

    Regla fundamental: current_notch = state.handle_notch  (siempre telemetría)

    Ciclo de execute():
      1. Rate-limit por tipo de acción
      2. Leer posición real del handle desde state.handle_notch
      3. Detectar si el jugador ha subido el notch externamente
      4. Calcular notch objetivo (un solo paso hacia el destino)
      5. Suprimir COAST si hubo subida externa reciente
      6. Enviar comando: RPC o teclado
    """

    _INTERVALS: dict[str, float] = {
        COAST:      CONTROL_INTERVAL_BRAKE,
        BRAKE:      CONTROL_INTERVAL_BRAKE,
        BRAKE_FAST: CONTROL_INTERVAL_FAST,
        EMERGENCY:  CONTROL_INTERVAL_FAST,
    }

    def __init__(self) -> None:
        # RPC failure tracking
        self._rpc_fail_count:     int   = 0
        self._rpc_disabled_until: float = 0.0
        self._last_ipc_notch:     Optional[int] = None
        self._last_ipc_notch_t:   float = 0.0

        # Rate limiting
        self._last_control: float = 0.0

        # Anti-oscilación: detectar subida externa de notch
        self._last_seen_notch: Optional[int] = None
        self._last_ext_up_t:   float         = 0.0

        # Para force_neutral / reset_neutral
        self._last_sync_t: float = 0.0

        # Métricas de sesión (logs CANAL_CONTROL)
        self._metrics_ipc_async: int = 0
        self._metrics_ipc_sync: int = 0
        self._metrics_keyboard: int = 0
        self._metrics_p1_rejected: int = 0

        # Teclado: no repetir KEY hasta que GetData refleje el paso (evita 4→3→2)
        self._key_wait_from: Optional[int] = None
        self._key_wait_deadline: float = 0.0

    def _prefer_keyboard(self, conn: Optional[object]) -> bool:
        return bool(
            getattr(conn, "prefer_keyboard_actuator", lambda: False)()
        )

    def _command_interval(
        self,
        conn: Optional[object],
        use_rpc: bool,
        default: float,
    ) -> float:
        if self._prefer_keyboard(conn):
            return CONTROL_INTERVAL_BRAKE
        if use_rpc:
            return CONTROL_INTERVAL_RPC
        return default

    def _keyboard_waiting(self, current: int) -> bool:
        """True si ya pulsamos KEY y la telemetría aún no cambió de muesca."""
        if self._key_wait_from is None:
            return False
        if current != self._key_wait_from:
            self._key_wait_from = None
            self._key_wait_deadline = 0.0
            return False
        if time.time() > self._key_wait_deadline:
            _log.debug(
                "KEY espera telemetría timeout notch=%d — permitir reintento",
                current,
            )
            self._key_wait_from = None
            self._key_wait_deadline = 0.0
            return False
        return True

    def _clear_keyboard_wait(self) -> None:
        self._key_wait_from = None
        self._key_wait_deadline = 0.0

    def session_metrics(self) -> dict[str, int]:
        return {
            "ipc_async": self._metrics_ipc_async,
            "ipc_sync": self._metrics_ipc_sync,
            "keyboard": self._metrics_keyboard,
            "p1_rejected": self._metrics_p1_rejected,
        }

    def _use_async_ipc(self, conn: Optional[object]) -> bool:
        """True si hay cola IPC async (Fase A/B) — sin penalización global."""
        if conn is None or getattr(conn, "mode", None) != "ue4ss":
            return False
        return callable(getattr(conn, "enqueue_control_value", None))

    def _use_rpc(self, conn: Optional[object]) -> bool:
        """True si IPC Lua disponible y no penalizado."""
        if conn is None or getattr(conn, "mode", None) != "ue4ss":
            return False
        if self._use_async_ipc(conn):
            has_api = getattr(conn, "has_control_api", None)
            if callable(has_api):
                return bool(has_api())
            return False
        if self._rpc_disabled_until > time.time():
            return False
        has_api = getattr(conn, "has_control_api", None)
        if callable(has_api):
            return bool(has_api())
        return False

    def _try_rpc(self, conn: object, control: str, val: float) -> bool:
        """Intenta IPC con reintentos; pausa corta IPC tras racha de fallos."""
        last_exc: Optional[Exception] = None
        for attempt in range(_RPC_MAX_RETRIES):
            try:
                result = conn.set_control_value(control, val)  # type: ignore[union-attr]
                if result:
                    self._rpc_fail_count = 0
                    self._rpc_disabled_until = 0.0
                    if attempt > 0:
                        _log.info(
                            "IPC OK %s=%.3f (reintento %d/%d)",
                            control, val, attempt + 1, _RPC_MAX_RETRIES)
                    return True
            except Exception as exc:
                last_exc = exc
                _log.debug("RPC excepción (intento %d): %s", attempt + 1, exc)
            if attempt < _RPC_MAX_RETRIES - 1:
                time.sleep(_RPC_RETRY_BACKOFF_S * (attempt + 1))

        self._rpc_fail_count += 1
        if last_exc is not None:
            _log.debug(
                "RPC falló tras %d intentos (%s=%.3f): %s",
                _RPC_MAX_RETRIES, control, val, last_exc)

        if self._rpc_fail_count >= _RPC_DISABLE_COUNT:
            self._rpc_disabled_until = time.time() + _RPC_DISABLE_S
            _log.warning(
                "IPC pausado %.0fs tras %d fallos — fallback teclado",
                _RPC_DISABLE_S, self._rpc_fail_count)
        return False

    # ── Cálculo del notch objetivo ────────────────────────────────────────

    def _target_notch(self, action: str, current: int) -> int:
        """
        Calcula el notch objetivo para la acción dada.
        Un paso por ciclo (el rate-limit controla la velocidad total).
        """
        if action == COAST:
            # Solo soltar tracción: si ya estamos en neutro o freno, no hacer nada
            if current > _NOTCH_NEUTRAL:
                return current - 1
            return current
        if action == BRAKE:
            if current > _NOTCH_NEUTRAL:
                return current - 1          # soltar tracción primero
            return max(_BRAKE_MIN_HANDLE, current - 1)
        if action in (BRAKE_FAST, EMERGENCY):
            if current > _NOTCH_NEUTRAL:
                return _NOTCH_NEUTRAL
            if action == EMERGENCY:
                return EMERGENCY_BRAKE_HANDLE
            return max(_BRAKE_MIN_HANDLE, current - 1)
        return current

    # ── Ejecución ─────────────────────────────────────────────────────────

    def _keyboard_notch_step(
        self,
        hwnd: int,
        new_notch: int,
        current: int,
        label: str,
    ) -> bool:
        if self._keyboard_waiting(current):
            return False

        step = current + (1 if new_notch > current else -1)
        key = VK_A if new_notch > current else VK_D
        hold_ms = KEY_TAP_MS if abs(step - current) == 1 else KEY_HOLD_MS
        send_key(hwnd, key, hold_ms=hold_ms)
        self._metrics_keyboard += 1
        self._key_wait_from = current
        self._key_wait_deadline = time.time() + 1.2
        _log.info(
            "KEY  %-11s  notch %d→%d  (obj=%d  %s  %dms  fallback)",
            label, current, step, new_notch,
            "A" if new_notch > current else "D", hold_ms)
        return True

    def _apply_combined_notch(
        self,
        conn: Optional[object],
        hwnd: Optional[int],
        new_notch: int,
        current: int,
        *,
        label: str,
        ipc_only: bool = False,
    ) -> bool:
        """Escribe un paso hacia ``new_notch`` (0–8): IPC Class 323; teclado si no ``ipc_only``."""
        new_notch = max(0, min(_MAX_NOTCH, int(new_notch)))
        if new_notch == current:
            return False
        step = current + (1 if new_notch > current else -1)
        step = max(0, min(_MAX_NOTCH, step))

        prefer_key = self._prefer_keyboard(conn)
        if prefer_key and hwnd is not None:
            return self._keyboard_notch_step(hwnd, new_notch, current, label)

        now = time.time()
        if (
            self._use_rpc(conn)
            and self._last_ipc_notch == step
            and now - self._last_ipc_notch_t < 0.40
            and current != step
        ):
            return False

        if self._use_rpc(conn):
            val = step / float(_MAX_NOTCH)
            enqueue_fn = getattr(conn, "enqueue_control_value", None)
            if callable(enqueue_fn):
                if enqueue_fn("PowerBrakeHandle", val):
                    self._metrics_ipc_async += 1
                    self._last_ipc_notch = step
                    self._last_ipc_notch_t = time.time()
                    _log.info(
                        "IPC  %-11s  notch %d→%d  (obj=%d  val=%.3f  async)",
                        label, current, step, new_notch, val)
                    return True
                _log.warning(
                    "IPC cola llena %s notch %d→%d",
                    label, current, step)
                if ipc_only:
                    self._metrics_p1_rejected += 1
                    return False
            elif self._try_rpc(conn, "PowerBrakeHandle", val):
                self._metrics_ipc_sync += 1
                self._last_ipc_notch = step
                self._last_ipc_notch_t = time.time()
                _log.info(
                    "IPC  %-11s  notch %d→%d  (obj=%d  val=%.3f)",
                    label, current, step, new_notch, val)
                return True
            else:
                _log.warning(
                    "IPC falló %s notch %d→%d%s",
                    label, current, step,
                    "" if ipc_only else " — probando teclado")

        if ipc_only:
            self._metrics_p1_rejected += 1
            _log.error(
                "P1 sin IPC %s notch %d→%d — sin fallback teclado",
                label, current, new_notch)
            return False

        if hwnd is not None:
            return self._keyboard_notch_step(hwnd, new_notch, current, label)

        _log.warning("execute: sin IPC ni hwnd — no se puede enviar %s", label)
        return False

    def execute(
        self,
        action: str,
        state: TrainState,
        conn: Optional[object],
        hwnd: Optional[int],
        brake_command: Optional[BrakeCommand] = None,
    ) -> bool:
        """
        Ejecuta la acción enviando un paso de control al mando.

        Devuelve True si envió un comando, False si esperó (rate-limit,
        ya en posición, HOLD/PAUSED, o suppresión anti-oscilación).
        """
        now = time.time()
        use_rpc = self._use_rpc(conn)

        # ── Dastsc P1: notch del plan (antes de HOLD — action puede ser HOLD) ─
        if brake_command is not None and brake_command.target_notch is not None:
            interval = self._command_interval(
                conn, use_rpc, CONTROL_INTERVAL_BRAKE)
            if now - self._last_control < interval:
                return False
            current = state.handle_notch
            label = brake_command.display_action()
            target = brake_command.target_notch
            if brake_command.kind == "COAST_THROTTLE":
                target = min(current, _NOTCH_NEUTRAL)
            elif brake_command.kind == "RELEASE":
                target = _NOTCH_NEUTRAL
            elif brake_command.kind == "APPLY" and target is not None:
                target = clamp_brake_handle(target, brake_command.distance_m)
            if self._apply_combined_notch(
                    conn, hwnd, target, current, label=label, ipc_only=True):
                self._last_control = now
                return True
            return False

        if action in (HOLD, PAUSED):
            return False

        interval = self._command_interval(
            conn,
            use_rpc,
            self._INTERVALS.get(action, CONTROL_INTERVAL),
        )
        if now - self._last_control < interval:
            return False

        current = state.handle_notch  # SIEMPRE telemetría

        # Detectar incremento externo del notch (jugador / otro sistema).
        # Solo se cuenta como "externo" si el salto es > 1 posición, porque
        # nuestros propios comandos (+1 por ciclo) pueden aparecer con un ciclo
        # de retraso en la telemetría y provocarían falsos positivos.
        if (self._last_seen_notch is not None
                and current > self._last_seen_notch + 1
                and now - self._last_control > CONTROL_INTERVAL * 0.5):
            self._last_ext_up_t = now
            _log.debug("Subida externa: notch %d → %d", self._last_seen_notch, current)
        self._last_seen_notch = current

        # Suprimir COAST durante _GRACE_AFTER_EXT tras subida externa.
        if (action == COAST
                and now - self._last_ext_up_t < _GRACE_AFTER_EXT):
            _log.debug(
                "COAST suprimido (%.1fs tras subida externa)",
                now - self._last_ext_up_t)
            return False

        target = self._target_notch(action, current)
        if target == current:
            return False

        new_notch = current + (1 if target > current else -1)

        if self._apply_combined_notch(
                conn, hwnd, new_notch, current, label=action):
            self._last_control = now
            return True
        return False

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

        self._clear_keyboard_wait()
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

    def reset_neutral(
        self,
        hwnd: Optional[int],
        current_handle: int = _NOTCH_NEUTRAL,
        conn: Optional[object] = None,
    ) -> None:
        """
        Lleva el handle a neutro desde una posición conocida.
        Llamar al salir del autopilot con el último handle conocido de la telemetría.
        """
        if self._use_rpc(conn):
            _log.info("reset_neutral: IPC → neutro (0.5)")
            if self._try_rpc(conn, "PowerBrakeHandle", 0.5):
                return

        if hwnd is None:
            _log.warning("reset_neutral: sin IPC ni hwnd")
            return
        self._clear_keyboard_wait()
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
        _log.info("reset_neutral: handle en neutro (teclado)")


# ─────────────────────────────────────────────────────────────────────────────


class SafetyWatchdog:
    """
    Capa de seguridad: monitorea condiciones críticas y genera overrides.

    Diseño conservador:
    - BRAKE_FAST solo para exceso de velocidad PERSISTENTE (> 5mph durante > 3s)
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
            BRAKE_FAST si se debe frenar con urgencia, None si todo OK.
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
                    "SafetyWatchdog BRAKE_FAST: exceso %.1f mph durante ≥%.0fs",
                    state.speed_mph - state.limit_mph, self._OVERSPEED_TRIGGER_S)
                return BRAKE_FAST
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
