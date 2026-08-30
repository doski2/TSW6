-- ApiExplorerMod — rutas, schema, mapeo HTTP
local M = {}

M.BUILD = "20260830l"
M.SCHEMA = "tsw6-lab-export/1"
M.HTTP_PREFIX = "CurrentFormation/0/Function."

M.EXPORTS_DIR = "exports"

M.REFLECT_MAX_DEPTH = 2
M.KEY_DEBOUNCE_S = 0.35
M.USE_FINDALL_CONTROLS = false

-- Nombres típicos de mandos (G-B / DRIVERINPUT_API). Orden: combined UK primero.
M.CONTROL_PROBE_NAMES = {
    "PowerBrakeHandle",
    "ThrottleAndBrake",
    "CombinedHandle",
    "PowerBrake",
    "AutomaticBrake",
    "TrainBrake",
    "IndependentBrake",
    "DynamicBrake",
    "LocomotiveBrake",
    "Reverser",
    "EmergencyBrake_L",
    "EmergencyBrake_C",
    "ParkingBrake",
    "MasterKey",
    "RegenBrakes",
}

M.LEVER_COMPONENT_TYPES = {
    "IrregularLeverComponent",
    "AnalogLeverComponent",
    "DigitalLeverComponent",
    "BaseLeverComponent",
}

M.SIM_BRAKE_NODES = {
    "BrakeInput",
    "EBrakeInput",
    "ThrottleAndBrake",
    "PowerBrakeHandle",
}

M.CONTROL_ALIASES = {
    PowerBrakeHandle = { "PowerBrakeHandle", "ThrottleAndBrake", "CombinedHandle", "PowerBrake" },
    TrainBrake = { "TrainBrake", "AutomaticBrake" },
    LocomotiveBrake = { "LocomotiveBrake", "IndependentBrake" },
    DynamicBrake = { "DynamicBrake", "RegenBrakes" },
}

function M.http_driver_input(path_suffix)
    return "DriverInput/0/" .. path_suffix
end

M.FORMATION_BRAKE_CYLINDERS = {
    "BrakeCylinder_2_1",
    "BrakeCylinder_Direct_P",
    "BrakeCylinder_1_1",
}

M.FORMATION_MISC_NODES = {
    "MR (AirPipe)",
    "ClampPowerInput",
    "LoadSensingBrakeModifier",
    "Axle_1_1",
    "Axle_2_1",
    "ParkingBrakeCylinder",
}

function M.http_sim_path(node, field)
    return "CurrentFormation/0/Simulation/" .. node .. "." .. field
end

function M.http_drivable_sim_path(node, field)
    return "CurrentDrivableActor/Simulation/" .. node .. "." .. field
end

function M.http_formation_component(name, field)
    return "CurrentFormation/0/" .. name .. "." .. field
end

M.HUD_METHODS = {
    "HUD_GetSpeed",
    "HUD_GetAcceleration",
    "HUD_GetPowerHandle",
    "HUD_GetTrainBrakeHandle",
    "HUD_GetLocomotiveBrakeHandle",
    "HUD_GetElectricBrakeHandle",
    "HUD_GetDirection",
    "HUD_GetIsSlipping",
    "HUD_GetIsTractionLocked",
    "HUD_GetTractiveEffort",
    "HUD_GetBrakeGauge_1",
    "HUD_GetBrakeGauge_2",
    "HUD_GetMaxPermittedSpeed",
    "HUD_GetSpeedControlTarget",
    "HUD_GetAmmeter",
    "HUD_GetEngineRPM",
}

function M.trim(s)
    if not s then return nil end
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function read_pointer_file(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local line = M.trim(f:read("*l"))
    f:close()
    if line and line ~= "" then return line end
    return nil
end

-- Prioridad: TSW6_LAB_DIR > Documents\TSW6\lab_root.txt > %TEMP%\TSW6Lab (fallback)
function M.lab_root()
    local env = os.getenv("TSW6_LAB_DIR")
    if env and env ~= "" then
        return M.trim(env)
    end
    local profile = os.getenv("USERPROFILE") or ""
    if profile ~= "" then
        local from_docs = read_pointer_file(profile .. "\\Documents\\TSW6\\lab_root.txt")
        if from_docs then return from_docs end
    end
    local temp = os.getenv("TEMP") or os.getenv("TMP") or "."
    local from_temp = read_pointer_file(temp .. "\\TSW6Lab\\lab_root.txt")
    if from_temp then return from_temp end
    return temp .. "\\TSW6Lab"
end

function M.http_path_for(method)
    return M.HTTP_PREFIX .. method
end

return M
