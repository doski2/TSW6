"""Constantes del producto (323 combined UK)."""

MS_TO_MPH = 2.236936
MPH_TO_MS = 0.44704
NEUTRAL_NOTCH = 4
B1_NOTCH = 3
B1_MIN_TRAIN_BRAKE = 0.25
PROBE_STALE_S = 2.5
IPC_ACK_TIMEOUT_S = 0.35
IPC_STEP_PAUSE_S = 0.08
AGENT_ACK_TIMEOUT_S = 0.12
DEFAULT_LOOP_HZ = 20.0

# Física frenado (Class 323 — PLAN_V2 §2)
MAX_DECEL_MS2 = 1.071
SAFETY_MARGIN = 1.20  # era 1.40 — paso 1 tuning EMU (PLAN_V2 §2); validar in-game
COAST_DECEL_MS2 = 0.095
BRAKE_TRANSITION_S = 0.5
P1_REACT_S = 2.0
P1_ACK_GUARD_S = 1.0

# Freno servicio UK (handle combinado)
SERVICE_MIN_HANDLE = 1
SERVICE_MAX_BRAKE = 3
EMERGENCY_BRAKE_HANDLE = 0
EMERGENCY_BRAKE_MAX_DIST_M = 25.0

# UK EMU pasajeros: operar ~1 mph bajo cartel publicado (60 → techo 59).
PASSENGER_OPS_MARGIN_MPH = 1.0


def passenger_ops_target_mph(posted_limit_mph: float) -> float:
    """Techo operativo (HOLD_DH y BRAKE_LIMIT)."""
    return max(0.0, float(posted_limit_mph) - PASSENGER_OPS_MARGIN_MPH)
