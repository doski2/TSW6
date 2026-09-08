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
SAFETY_MARGIN = 1.10  # era 1.40→1.20→1.10 (sesión 20260906T073552Z: APPLY 60→55 @484m)
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

# ── Umbrales cartel P1 (por capa; ver REGLAS_FRENOS_P1.md) ─────────────────

# Plan BRAKE_LIMIT / histéresis muesca (penalización TSW > posted+1)
LIMIT_SCORING_MAX_OVER_MPH = 0.9
LIMIT_COAST_BAND_MPH = 0.25

# HOLD_DH / contención zona vigente (más conservador que scoring TSW)
LIMIT_ZONE_HOLD_OVER_MPH = 0.5  # bajada suave (−0.3 %%): posted 60 → 60.5
LIMIT_ZONE_HOLD_OVER_STEEP_MPH = 0.2  # bajada fuerte (−1 %%): posted 60 → 60.2
LIMIT_DOWNHILL_GRADIENT_PCT = -0.3  # umbral bajada (igual que physics.py)
LIMIT_ZONE_COAST_OVER_OPS_MPH = 0.5  # ops 59 → suelo coast 59.5

# HOLD_DH (Fase 1 bajada)
LIMIT_CONTAIN_ESCALATE_OVER_MPH = 0.65
# Bajada: si exceso ≤ esto sobre techo cartel siguiente, coast antes de B1
LIMIT_DOWNHILL_COAST_TRIM_MPH = 2.0

# Cartel pasado / cola
LIMIT_SIGN_PASSED_M = 8.0
LIMIT_OVER_ACTIVE_MPH = 0.5

# RELEASE
LIMIT_RELEASE_MAX_OVER_MPH = 0.4
LIMIT_RELEASE_MIN_SPEED_BAND_MPH = 5.0

# Transición zona lenta→rápida (35→60) y cola sin cartel adelante
ASCENDING_LIMIT_DELTA_MPH = 0.5
DESCENDING_LIMIT_DELTA_MPH = 0.5


def passenger_ops_target_mph(posted_limit_mph: float) -> float:
    """Techo operativo cartel **siguiente** (BRAKE_LIMIT: 55 → 54)."""
    return max(0.0, float(posted_limit_mph) - PASSENGER_OPS_MARGIN_MPH)


def posted_scoring_ceiling_mph(posted_limit_mph: float) -> float:
    """Techo penalización TSW (posted + 0.9; límite 60 → máx 60.9)."""
    return float(posted_limit_mph) + LIMIT_SCORING_MAX_OVER_MPH


def zone_hold_over_mph(gradient_pct: float = 0.0) -> float:
    """
    Margen HOLD sobre posted: menor en bajada fuerte (reaccionar antes).

    −0.3 %% → 0.5 mph; −1.0 %% → 0.2 mph (Cross-City 323).
    """
    g = abs(float(gradient_pct))
    if gradient_pct >= LIMIT_DOWNHILL_GRADIENT_PCT:
        return LIMIT_ZONE_HOLD_OVER_MPH
    if g <= 0.3:
        return LIMIT_ZONE_HOLD_OVER_MPH
    t = (g - 0.3) / 0.7
    return LIMIT_ZONE_HOLD_OVER_MPH - t * (
        LIMIT_ZONE_HOLD_OVER_MPH - LIMIT_ZONE_HOLD_OVER_STEEP_MPH
    )


def posted_zone_hold_ceiling_mph(
    posted_limit_mph: float,
    gradient_pct: float = 0.0,
) -> float:
    """Techo HOLD zona vigente en bajada (posted + margen según pendiente)."""
    return float(posted_limit_mph) + zone_hold_over_mph(gradient_pct)


def posted_zone_coast_floor_mph(posted_limit_mph: float) -> float:
    """Suelo coast tras contención zona (ops + 0.5; 60 → 59.5)."""
    return passenger_ops_target_mph(posted_limit_mph) + LIMIT_ZONE_COAST_OVER_OPS_MPH


def downhill_ops_coast_ceiling_mph(
    posted_limit_mph: float,
    gradient_pct: float = 0.0,
) -> float:
    """Defer/coast BRAKE_LIMIT mientras no superas el techo de la zona vigente."""
    return posted_zone_hold_ceiling_mph(posted_limit_mph, gradient_pct)
