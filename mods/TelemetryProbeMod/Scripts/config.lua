-- TelemetryProbeMod v2 — constantes (solo I/O GetData + IPC).
local M = {}

M.PROBE_BUILD = "20260905b"
M.PROBE_AUTO_START = true

M.HOOK_PATH =
    "/Game/Core/Player/TS2DefaultPlayerController.TS2DefaultPlayerController_C:ReceiveTick"
M.WRITE_INTERVAL_S = 0.05
M.LOG_INTERVAL_S = 2.0
M.IPC_POLL_INTERVAL_S = 0.05
M.COMMANDS_ARMED_TTL_S = 0.25

M.SAFE_LEVER_WRITE = true
M.IPC_DELEGATE_HTTP = false
M.DEBUG_IPC = false

M.ALLOWED_CONTROLS = {
    PowerBrakeHandle = true,
    AutomaticBrake = true,
    IndependentBrake = true,
    DynamicBrake = true,
    TrainBrake = true,
    LocomotiveBrake = true,
}

M.CONTROL_ALIASES = {
    PowerBrakeHandle = {
        "PowerBrakeHandle",
        "ThrottleAndBrake",
        "CombinedHandle",
        "PowerBrake",
    },
}

-- Class 323 (Liah profile). Índice 1 = notch 0.
M.PBH_INPUT_BY_NOTCH = { -1.0, -0.6, -0.4, -0.2, 0.0, 0.25, 0.5, 0.75, 1.0 }

M.PLANNING_FIELDS = {
    "dist_limit_cm", "next_limit_ms", "odo_m",
}

-- Manómetro cabina (canal fiable 323 en tick; ver lab_export / PLAN_V2 §L4).
M.BRAKE_GAUGE_METHODS = { "HUD_GetBrakeGauge_1", "HUD_GetBrakeGauge_2" }

-- Fallback otros rolling stock — Simulation suele estar bloqueado en 323 UE4SS.
M.BRAKE_CYL_NAMES = { "BrakeCylinder_2_1", "BrakeCylinder_Direct_P", "BrakeCylinder_1_1" }
M.BRAKE_CYL_PRESSURE_FIELDS = {
    "Pressure_BAR", "Pressure", "PressurePSI", "Pressure_PSI_G",
}

-- UK 323 lab L0.4b: signalAspectClass enum 2 = rojo adelante.
M.SIGNAL_RED_ASPECT = 2

return M
