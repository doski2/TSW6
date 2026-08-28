#!/usr/bin/env python3
"""
governor_constants.py — Constantes físicas y de control para SpeedGovernor.

Centraliza todos los parámetros ajustables en un solo lugar para facilitar
la calibración y el mantenimiento.
"""

import math

# ── Física de frenado – Class 323 / tren genérico de cercanías ───────────────

MAX_DECEL_MS2      = 1.071   # m/s² deceleración de servicio
SAFETY_MARGIN      = 1.40    # 40 % de margen extra en distancia de frenado
COAST_DECEL_MS2    = 0.095   # m/s² deceleración mínima en inercia (suelo de braking_distance)
BRAKE_TRANSITION_S = 0.5     # segundos para transición aceleración→neutro→freno

# ── Frenado de servicio y calibración del learner ─────────────────────────────
# TARGET_ACCEL_MS2 solo lo usa OnlineLearner (--learn); el autopilot no acelera.
TARGET_ACCEL_MS2      = 0.301   # aceleración típica tracción máx (learner)
TARGET_DECEL_MS2      = 0.433   # deceleración objetivo frenado de servicio (P1 / learner)
RATE_TOLERANCE        = 0.18    # banda muerta ±0.18 m/s² (reservado física / learner)

# Handle combinado Class 323: 0=emergencia ATP, 1..3=servicio B3..B1, 4=neutro.
# El juego activa emergencia en notch 0 — no se puede soltar y seguir como servicio.
SERVICE_MIN_HANDLE = 1          # B3 — freno de servicio máximo (muesca freno 3)
EMERGENCY_BRAKE_HANDLE = 0      # solo paradas de emergencia a muy poca distancia
EMERGENCY_BRAKE_MAX_DIST_M = 25.0
SERVICE_MAX_BRAKE = 3           # B1..B3 (handle 3..1)

# ── Histéresis del controlador ────────────────────────────────────────────────

CONTROL_INTERVAL       = 0.35   # teclado: ~1 notch cada 350ms + margen
CONTROL_INTERVAL_BRAKE = 0.35   # COAST / BRAKE
CONTROL_INTERVAL_FAST = 0.25  # BRAKE_FAST / EMERGENCY
# Alias legacy (tests externos)
CONTROL_INTERVAL_EMERG = CONTROL_INTERVAL_FAST
CONTROL_INTERVAL_RPC   = 0.12  # HTTPAPI: mandos directos sin esperar tecla

# Límite mínimo creíble para next_limit_mph de la API (0 = dato inválido)
P1_MIN_NEXT_LIMIT_MPH = 1.0

# Segundos de margen de reacción añadidos al cálculo de P1 para compensar
# el tiempo que tarda el autopilot en aplicar frenos tras detectar la necesidad.
# A 52 mph (23 m/s) × 2 s = ~46 m de distancia de reacción.
P1_REACT_S = 2.0

# Segundos de guardia anti-ACK: la curva P1 empieza a frenar este tiempo antes
# de lo que la física pura requeriría. Garantiza que el ATP nunca necesite
# intervenir. A 52 mph ≈ 69 m de adelanto adicional sobre el SAFETY_MARGIN.
P1_ACK_GUARD_S = 1.0

# ── P1: urgencia vs distancia de parada (fracción de s, no metros fijos) ─────
P1_ALERTA_FACTOR    = 1.5   # dist ≤ bd_hor × 1.5 → perfil gradual
P1_CRITICO_MPH      = 10.0  # no CRÍTICO en creep (andén)
P1_EMERGENCIA_MPH   = 5.0   # reservado / logs; el disparo usa 0.5·s_parada

# ── Física: umbral de gradiente crítico ───────────────────────────────────────
CRITICAL_DECEL_THRESHOLD = 0.3  # m/s²: si effective_decel < este valor → forzar MAX_BRAKE

# ── Paradas en estación ───────────────────────────────────────────────────────

STATION_STOPPED_MPH    = 1.5   # por debajo de esto = tren parado
STATION_DWELL_TIMEOUT_S = 45   # segundos máx. en STOPPED sin datos de puertas → partir

# Perfil de frenado para paradas en andén:
# v_límite = _K_STOP * sqrt(distancia_m)  [en mph]
# Derivado de v = sqrt(2 * MAX_DECEL_MS2 / SAFETY_MARGIN * dist)
_K_STOP = math.sqrt(2.0 * MAX_DECEL_MS2 / SAFETY_MARGIN) / 0.44704

# Notch 0 = emergencia HUD; 1–3 B3..B1 InputValue -0.6/-0.4/-0.2
# (Liah class323.tswprofile); 4 neutro; 5–8 tracción 0.25..1.

NOTCH_NEUTRAL = 4   # posición central del handle combinado (neutro)

NOTCH_LABELS: dict[int, str] = {
    0: "FRENO TOTAL",
    1: "Freno 3",
    2: "Freno 2",
    3: "Freno 1",
    4: "NEUTRO",
    5: "Tracción 1",
    6: "Tracción 2",
    7: "Tracción 3",
    8: "TRACCIÓN MAX",
}
