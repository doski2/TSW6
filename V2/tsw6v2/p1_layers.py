"""Capas P1 legibles — debate sin jerga APPLY/COAST/command_none."""

from __future__ import annotations

from typing import Any, Optional

# id estable en JSONL · etiqueta consola · qué significa
LAYERS: dict[str, tuple[str, str]] = {
    "WATCH": (
        "Vigilar",
        "Cartel lejos: calculamos plan pero aún no toca mandar (apply_now=false).",
    ),
    "WAIT": (
        "Esperar ventana",
        "Plan listo; faltan metros para la zona de frenado (apply_deferred).",
    ),
    "COAST_PWR": (
        "Quitar tracción",
        "Palanca en potencia: primero neutro, luego freno (COAST_THROTTLE).",
    ),
    "BRAKE": (
        "Frenar",
        "En ventana: mandar B1/B2/B3 (APPLY).",
    ),
    "RELEASE": (
        "Soltar freno",
        "Velocidad en cartel: volver a neutro (RELEASE).",
    ),
    "HOLD": (
        "Mantener",
        "Tras soltar, no re-frenar de inmediato (coast_latch).",
    ),
    "HOLD_DH": (
        "Mantener bajada",
        "Fase 1 H1: límite vigente en bajada; B1 si repunta (fuera horizonte del cartel).",
    ),
    "OK": (
        "Velocidad OK",
        "Por debajo del cartel o en banda coast; sin plan activo.",
    ),
    "NONE": (
        "Sin cartel",
        "GetData sin dist_limit / next_limit.",
    ),
    "GAP": (
        "Revisar",
        "apply_now=true pero sin comando — candidato a bug o umbral malo.",
    ),
    "IDLE": (
        "—",
        "Sin P1 este tick.",
    ),
}

# reason técnico (código) -> capa
_REASON_TO_LAYER: dict[str, str] = {
    "plan": "BRAKE",
    "release": "RELEASE",
    "coast_throttle": "COAST_PWR",
    "downhill_hold": "HOLD_DH",
    "apply_deferred": "WAIT",
    "air_fill": "WAIT",
    "air_recharge": "WAIT",
    "coast_latch": "HOLD",
    "no_plan": "OK",
    "no_limit_sign": "NONE",
    "no_speed": "IDLE",
    "command_none": "WATCH",
}


def classify_layer(
    *,
    reason: str = "",
    cmd: Optional[str] = None,
    apply_now: Optional[bool] = None,
    dist_start_m: Optional[float] = None,
) -> str:
    """Id de capa (WATCH, BRAKE, …) para trace y gráficos."""
    if cmd == "RELEASE":
        return "RELEASE"
    if cmd == "COAST_THROTTLE":
        return "COAST_PWR"
    if cmd == "APPLY":
        if reason == "downhill_hold":
            return "HOLD_DH"
        return "BRAKE"

    layer = _REASON_TO_LAYER.get(reason, "IDLE")
    if reason == "command_none" and apply_now is True:
        return "GAP"
    if reason == "command_none" and dist_start_m is not None and dist_start_m < 0:
        return "WAIT"
    return layer


def classify_from_p1(p1: Optional[dict[str, Any]]) -> str:
    if not p1:
        return "IDLE"
    return classify_layer(
        reason=str(p1.get("reason") or ""),
        cmd=p1.get("cmd"),
        apply_now=p1.get("apply_now"),
        dist_start_m=p1.get("dist_start_m"),
    )


def layer_label(layer_id: str) -> str:
    return LAYERS.get(layer_id, ("?", ""))[0]


def layer_help(layer_id: str) -> str:
    return LAYERS.get(layer_id, ("?", ""))[1]


def format_layer_tag(layer_id: str) -> str:
    """Consola: capa legible + id corto."""
    label = layer_label(layer_id)
    if layer_id in ("IDLE", "—"):
        return ""
    return f"{label} [{layer_id}]"
