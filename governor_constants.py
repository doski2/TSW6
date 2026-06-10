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

# ── Protocolo de tracción / frenado de servicio ───────────────────────────────
# Basado en teoría de tracción ferroviaria: control por tasa de aceleración
# en lugar de control proporcional por error de velocidad.
TARGET_ACCEL_MS2      = 0.301   # tasa de aceleración objetivo (arranque → crucero)
TARGET_DECEL_MS2      = 0.433   # tasa de deceleración objetivo (frenado de servicio)
RATE_TOLERANCE        = 0.18    # banda muerta ±0.18 m/s² para decisiones de frenado (P2)

# ── P3: Control por proyección de velocidad ───────────────────────────────────
# En lugar de perseguir una tasa de aceleración instantánea, P3 proyecta la
# velocidad a P3_LOOKAHEAD_S segundos y solo mueve el notch si la trayectoria
# sale de la banda ±P3_SPEED_TOL_MPH alrededor del objetivo.
# Ventaja: el acelerómetro ya incorpora el efecto del gradiente, por lo que
# ruido o cambios pequeños de gradiente NO generan cambios de muesca.
P3_LOOKAHEAD_S     = 8.0    # horizonte de proyección (s): v_proj = v + a·t
P3_SPEED_TOL_MPH   = 2.0    # mph: banda muerta en velocidad proyectada
P3_RAMP_MAX_MPH    = 10.0   # mph: rampa suave de arranque — notch máx 2 por debajo
# Ciclos de banda muerta anti-oscilación antes de permitir cambio de dirección de notch
P3_DEADBAND_CYCLES = 3      # 3 ciclos × ~200ms = 600ms de estabilización

# Notch 4 = freno máximo: solo para parada final en andén y emergencia.
# El frenado de servicio (reducciones de límite) usa como mucho notch 3.
SERVICE_MAX_BRAKE = 3

# ── Histéresis del controlador ────────────────────────────────────────────────

CONTROL_INTERVAL       = 1.0   # segundos entre pulsaciones de ACCELERATE
CONTROL_INTERVAL_BRAKE = 0.4   # COAST / BRAKE / FULLSTOP (respuesta más rápida)
CONTROL_INTERVAL_EMERG = 0.25  # HARDBRAKE y ACK

# ── Histéresis de frenado TSM/overspeed (v3) ─────────────────────────────────
# Exceso mínimo sobre límite para activar BRAKE (antes era 0.0)
P2_TSM_BRAKE_THRESHOLD   = 0.5   # mph: exceso mínimo para BRAKE con sup=tsm
P2_LIMIT_BRAKE_THRESHOLD = 1.0   # mph: exceso mínimo para BRAKE por límite de vía

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

# ── P1 mejorado: umbrales de urgencia progresiva ─────────────────────────────
P1_ALERTA_FACTOR    = 1.5   # dist ≤ bd_hor × 1.5 → perfil gradual
P1_EMERGENCIA_DIST  = 50.0  # metros: dist ≤ 50m con exceso > 5mph → HARDBRAKE
P1_EMERGENCIA_MPH   = 5.0   # mph de exceso para P1-EMERGENCIA
P1_CRITICO_DIST     = 20.0  # metros: dist ≤ 20m con exceso > 10mph → FULLSTOP
P1_CRITICO_MPH      = 10.0  # mph de exceso para P1-CRITICO

# ── Física: umbral de gradiente crítico ───────────────────────────────────────
CRITICAL_DECEL_THRESHOLD = 0.3  # m/s²: si effective_decel < este valor → forzar MAX_BRAKE

# ── Paradas en estación ───────────────────────────────────────────────────────

STATION_APPROACH_M     = 150   # metros extra antes de empezar a frenar para parar
STATION_STOPPED_MPH    = 1.5   # por debajo de esto = tren parado
STATION_DWELL_TIMEOUT_S = 45   # segundos máx. en STOPPED sin datos de puertas → partir

# Perfil de frenado para paradas en andén:
# v_límite = _K_STOP * sqrt(distancia_m)  [en mph]
# Derivado de v = sqrt(2 * MAX_DECEL_MS2 / SAFETY_MARGIN * dist)
_K_STOP = math.sqrt(2.0 * MAX_DECEL_MS2 / SAFETY_MARGIN) / 0.44704

# ── Handle combinado PowerBrakeHandle (Class 323) ────────────────────────────
# Notch 0 = freno máximo … 4 = neutro … 8 = tracción máxima

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
