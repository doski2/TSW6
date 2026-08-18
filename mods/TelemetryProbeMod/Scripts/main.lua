-- TelemetryProbeMod — A3: escribe telemetría HUD a %TEMP%\TSW6Bridge\GetData.txt
-- Solo lectura; no toca el HUD. F7 on/off · F8 volcar línea al log.

local UEHelpers = require("UEHelpers")

print("[TelemetryProbe] Mod loaded\n")

local HOOK_PATH = "/Game/Core/Player/TS2DefaultPlayerController.TS2DefaultPlayerController_C:ReceiveTick"
local WRITE_INTERVAL_S = 0.05  -- ~20 Hz
local LOG_INTERVAL_S = 2.0

local probeEnabled = true
local bridgeReady = false
local seq = 0
local lastWriteClock = 0
local lastLogClock = 0
local hooked = false
local hookPre, hookPost
local debugDumped = false

local function bridge_dir()
    local temp = os.getenv("TEMP") or os.getenv("TMP") or "."
    return temp .. "\\TSW6Bridge"
end

local function bridge_path()
    return bridge_dir() .. "\\GetData.txt"
end

local function ensure_bridge_dir()
    if bridgeReady then
        return true
    end
    local dir = bridge_dir()
    local f = io.open(dir .. "\\GetData.txt", "a")
    if f then
        f:close()
        bridgeReady = true
        return true
    end
    -- Un solo mkdir al arranque (nunca en cada tick).
    os.execute('mkdir "' .. dir .. '" 2>nul')
    bridgeReady = true
    return io.open(dir .. "\\GetData.txt", "a") ~= nil
end

local function log_hud_error(label, err)
    print(string.format("[TelemetryProbe] WARN %s: %s\n", label, tostring(err)))
end

-- UE4SS: cada parámetro CPF_OutParm necesita su propia tabla {}.
-- Struct único (Speed, Acceleration) → una tabla con campos nombrados.
local function out_val(t, ...)
    if type(t) ~= "table" then
        return nil
    end
    for i = 1, select("#", ...) do
        local key = select(i, ...)
        if t[key] ~= nil then
            return t[key]
        end
    end
    for _, v in pairs(t) do
        if type(v) == "number" or type(v) == "boolean" then
            return v
        end
    end
    return nil
end

local function read_speed(actor)
    local result = {}
    actor:HUD_GetSpeed(result)
    return out_val(result, "Speed (ms)")
end

local function read_power(actor)
    local power = {}
    local isActive = {}
    local isNegative = {}
    actor:HUD_GetPowerHandle(power, isActive, isNegative)
    return out_val(power, "Power"),
           out_val(isNegative, "IsNegative"),
           out_val(isActive, "IsActive")
end

local function read_train_brake(actor)
    local handle = {}
    local isActive = {}
    actor:HUD_GetTrainBrakeHandle(handle, isActive)
    return out_val(handle, "HandlePosition"), out_val(isActive, "IsActive")
end

local function read_loco_brake(actor)
    local handle = {}
    local isActive = {}
    actor:HUD_GetLocomotiveBrakeHandle(handle, isActive)
    return out_val(handle, "HandlePosition"), out_val(isActive, "IsActive")
end

local function read_dyn_brake(actor)
    local handle = {}
    local isActive = {}
    actor:HUD_GetElectricBrakeHandle(handle, isActive)
    return out_val(handle, "HandlePosition"), out_val(isActive, "IsActive")
end

local function read_accel(actor)
    local result = {}
    actor:HUD_GetAcceleration(result)
    return out_val(result, "Acceleration (ms2)")
end

local function read_max_speed(actor)
    local maxSpeed = {}
    local warningSpeed = {}
    local isActive = {}
    actor:HUD_GetMaxPermittedSpeed(maxSpeed, warningSpeed, isActive)
    local active = out_val(isActive, "IsActive")
    if active then
        return out_val(maxSpeed, "MaxSpeed (ms)"), true
    end
    return nil, false
end

-- HUD Power: negativo = freno, 0 = neutro, positivo = tracción → muesca 0–8.
local function power_to_notch(power, power_neg)
    if power == nil then
        return nil
    end
    local p = tonumber(power) or 0
    if power_neg then
        p = -math.abs(p)
    end
    local notch = 4 + math.floor(p + 0.5)
    if notch < 0 then notch = 0 end
    if notch > 8 then notch = 8 end
    return notch
end

local function dump_table_shallow(t)
    if type(t) ~= "table" then
        return tostring(t)
    end
    local parts = {}
    for k, v in pairs(t) do
        table.insert(parts, tostring(k) .. "=" .. tostring(v))
    end
    return table.concat(parts, ",")
end

local function dump_driver_aid(driverAid)
    local parts = {}
    for k, v in pairs(driverAid) do
        if type(v) == "table" then
            table.insert(parts, string.format("%s={%s}", tostring(k), dump_table_shallow(v)))
        else
            table.insert(parts, string.format("%s=%s", tostring(k), tostring(v)))
        end
    end
    print("[TelemetryProbe] DriverAid dump: " .. table.concat(parts, " | ") .. "\n")
end

local function extract_gradient(driverAid)
    if type(driverAid) ~= "table" then
        return nil
    end
    if type(driverAid.gradient) == "number" then
        return driverAid.gradient
    end
    if type(driverAid.Gradient) == "number" then
        return driverAid.Gradient
    end
    if type(driverAid.Gradient) == "table" then
        local g = out_val(driverAid.Gradient, "Value", "value")
        if g ~= nil then return g end
    end
    for k, v in pairs(driverAid) do
        if type(k) == "string" and string.find(string.lower(k), "grad", 1, true) then
            if type(v) == "number" then
                return v
            end
            if type(v) == "table" then
                local g = out_val(v, "Value", "value")
                if g ~= nil then return g end
            end
        end
    end
    return nil
end

local function read_driver_aid(controller, debug_dump)
    -- No inicializar gradient=0.0: enmascaraba el valor real con el default.
    local driverAid = {
        SpeedLimit = { Value = 0.0 },
        speedLimit = { value = 0.0 },
    }
    controller:GetDriverAidData(driverAid)
    if debug_dump then
        dump_driver_aid(driverAid)
    end
    local speedLimit = nil
    if driverAid.SpeedLimit then
        speedLimit = out_val(driverAid.SpeedLimit, "Value")
    end
    if speedLimit == nil and driverAid.speedLimit then
        speedLimit = out_val(driverAid.speedLimit, "value", "Value")
    end
    return speedLimit, extract_gradient(driverAid)
end

local function read_vehicle_class(actor)
    local classObj = actor:GetClass()
    if classObj and classObj:IsValid() then
        return classObj:GetFName():ToString()
    end
    return "?"
end

local function fmt_num(v)
    if v == nil then
        return "?"
    end
    return string.format("%.6g", v)
end

local function build_line(sample)
    local parts = {
        "seq=" .. tostring(sample.seq),
        "speed_ms=" .. fmt_num(sample.speed_ms),
        "power=" .. fmt_num(sample.power),
        "power_neg=" .. (sample.power_neg and "1" or "0"),
        "handle_notch=" .. fmt_num(sample.handle_notch),
        "train_brake=" .. fmt_num(sample.train_brake),
        "loco_brake=" .. fmt_num(sample.loco_brake),
        "dyn_brake=" .. fmt_num(sample.dyn_brake),
        "accel_ms2=" .. fmt_num(sample.accel_ms2),
        "max_speed_ms=" .. fmt_num(sample.max_speed_ms),
        "speed_limit_ms=" .. fmt_num(sample.speed_limit_ms),
        "gradient_pct=" .. fmt_num(sample.gradient_pct),
        "vehicle=" .. (sample.vehicle or "?"),
    }
    return table.concat(parts, " ")
end

local function write_line(line)
    ensure_bridge_dir()
    local path = bridge_path()
    local f = io.open(path, "w")
    if not f then
        print("[TelemetryProbe] ERROR: cannot open " .. path .. "\n")
        return false
    end
    f:write(line .. "\n")
    f:close()
    return true
end

local function collect_sample(controller, debug_driver_aid)
    local sample = {
        seq = seq,
        vehicle = "?",
        power_neg = false,
    }

    local actor = controller:GetDrivableActor()
    if not actor or not actor:IsValid() then
        return sample, "no_drivable"
    end

    local ok, err

    ok, sample.speed_ms = pcall(function() return read_speed(actor) end)
    if not ok then log_hud_error("speed", sample.speed_ms) end

    ok, sample.power, sample.power_neg = pcall(function()
        local p, neg, _active = read_power(actor)
        return p, neg
    end)
    if not ok then log_hud_error("power", sample.power) end

    ok, sample.train_brake = pcall(function()
        local pos, _active = read_train_brake(actor)
        return pos
    end)
    if not ok then log_hud_error("train_brake", sample.train_brake) end

    ok, sample.loco_brake = pcall(function()
        local pos, _active = read_loco_brake(actor)
        return pos
    end)
    if not ok then log_hud_error("loco_brake", sample.loco_brake) end

    ok, sample.dyn_brake = pcall(function()
        local pos, _active = read_dyn_brake(actor)
        return pos
    end)
    if not ok then log_hud_error("dyn_brake", sample.dyn_brake) end

    ok, sample.accel_ms2 = pcall(function() return read_accel(actor) end)
    if not ok then log_hud_error("accel", sample.accel_ms2) end

    ok, sample.max_speed_ms, sample.max_speed_active = pcall(function()
        local maxMs, active = read_max_speed(actor)
        return maxMs, active
    end)
    if not ok then
        log_hud_error("max_speed", sample.max_speed_ms)
        sample.max_speed_active = false
    end

    if not sample.max_speed_active then
        sample.max_speed_ms = nil
    end

    sample.handle_notch = power_to_notch(sample.power, sample.power_neg)

    ok, sample.speed_limit_ms, sample.gradient_pct = pcall(function()
        return read_driver_aid(controller, debug_driver_aid)
    end)
    if not ok then
        log_hud_error("driver_aid", sample.speed_limit_ms)
        sample.gradient_pct = nil
    end

    ok, sample.vehicle = pcall(function() return read_vehicle_class(actor) end)
    if not ok then log_hud_error("vehicle", sample.vehicle) end

    if not debugDumped and sample.power ~= nil then
        debugDumped = true
        print(string.format(
            "[TelemetryProbe] OK power=%s train=%s loco=%s dyn=%s grad=%s\n",
            tostring(sample.power),
            tostring(sample.train_brake),
            tostring(sample.loco_brake),
            tostring(sample.dyn_brake),
            tostring(sample.gradient_pct)))
    end

    return sample, nil
end

local function maybe_write(controller, force)
    if not probeEnabled and not force then
        return
    end

    local now = os.clock()
    if not force and (now - lastWriteClock) < WRITE_INTERVAL_S then
        return
    end

    seq = seq + 1
    local sample, err = collect_sample(controller, force)
    if err == "no_drivable" then
        return
    end

    local line = build_line(sample)
    write_line(line)
    lastWriteClock = now

    if force or (now - lastLogClock) >= LOG_INTERVAL_S then
        print("[TelemetryProbe] " .. line .. "\n")
        lastLogClock = now
    end
end

local function register_hook()
    if hooked then
        return
    end
    hookPre, hookPost = RegisterHook(HOOK_PATH, function(self)
        if not probeEnabled then
            return
        end
        local controller = self:get()
        if not controller or not controller:IsValid() then
            return
        end
        maybe_write(controller, false)
    end)
    hooked = true
    print("[TelemetryProbe] Hook registered\n")
end

local function unregister_hook()
    if not hooked then
        return
    end
    UnregisterHook(HOOK_PATH, hookPre, hookPost)
    hooked = false
    hookPre, hookPost = nil, nil
    print("[TelemetryProbe] Hook unregistered\n")
end

RegisterInitGameStatePreHook(function()
    unregister_hook()
    seq = 0
    lastWriteClock = 0
    lastLogClock = 0
    debugDumped = false
end)

RegisterInitGameStatePostHook(function()
    print("[TelemetryProbe] Starting\n")
    ensure_bridge_dir()
    register_hook()
end)

RegisterKeyBind(Key.F7, {}, function()
    ExecuteInGameThread(function()
        probeEnabled = not probeEnabled
        print("[TelemetryProbe] " .. (probeEnabled and "ENABLED" or "DISABLED") .. "\n")
        if probeEnabled then
            register_hook()
        end
    end)
end)

RegisterKeyBind(Key.F8, {}, function()
    ExecuteInGameThread(function()
        local controller = UEHelpers.GetPlayerController()
        maybe_write(controller, true)
        print("[TelemetryProbe] Manual dump -> " .. bridge_path() .. "\n")
    end)
end)
