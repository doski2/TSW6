local config = require("config")
local util = require("util")

local M = {}

local function log_hud_error(label, err)
    print(string.format("[TelemetryProbe] WARN %s: %s\n", label, tostring(err)))
end

local function read_speed(actor)
    local result = {}
    actor:HUD_GetSpeed(result)
    return util.out_val(result, "Speed (ms)")
end

local function read_power(actor)
    local power, isNegative = {}, {}
    actor:HUD_GetPowerHandle(power, {}, isNegative)
    return util.out_val(power, "Power"), util.out_val(isNegative, "IsNegative") == true
end

local function read_brake_handle(actor, method)
    local handle = {}
    actor[method](actor, handle, {})
    return util.out_val(handle, "HandlePosition")
end

local function read_accel(actor)
    local result = {}
    actor:HUD_GetAcceleration(result)
    return util.out_val(result, "Acceleration (ms2)")
end

local function read_max_speed(actor)
    local maxSpeed, isActive = {}, {}
    actor:HUD_GetMaxPermittedSpeed(maxSpeed, {}, isActive)
    if util.out_val(isActive, "IsActive") then
        return util.out_val(maxSpeed, "MaxSpeed (ms)")
    end
    return nil
end

local function read_bool_hud(actor, method, key)
    local result = {}
    local ok = pcall(function() actor[method](actor, result) end)
    if not ok then return nil end
    local v = util.out_val(result, key)
    if type(v) == "boolean" then return v end
    if type(v) == "number" then return v ~= 0 end
    return nil
end

function M.read_hud_lever_notch(controller)
    if not controller or not controller.IsValid or not controller:IsValid() then
        return nil
    end
    local ok_actor, actor = pcall(function() return controller:GetDrivableActor() end)
    if not ok_actor or not actor or not actor.IsValid or not actor:IsValid() then
        return nil
    end
    local ok, power, power_neg = pcall(function() return read_power(actor) end)
    if ok and power ~= nil then
        return util.power_to_notch(power, power_neg == true)
    end
    return nil
end

local function read_door_component_value(door_comp)
    if not util.ctrl_is_valid(door_comp) then return nil end
    local ok, v = pcall(function() return door_comp.CurrentInputValue end)
    if ok and type(v) == "number" then return v end
    ok, v = pcall(function() return door_comp:GetCurrentInputValue() end)
    if ok and type(v) == "number" then return v end
    return nil
end

local function read_passenger_doors(actor)
    local ok, doors = pcall(function()
        local out = {}
        for i = 1, 8 do
            local comp = util.try_child(actor, "PassengerDoor_" .. tostring(i))
            if comp then
                local v = read_door_component_value(comp)
                if v ~= nil and v > 0.01 then
                    out.open = true
                    return out
                end
            end
        end
        out.open = false
        return out
    end)
    if ok and type(doors) == "table" then return doors.open end
    return nil
end

local function extract_doors_dmi(driverAid)
    local raw = driverAid.bDoorsOpen or driverAid.DoorsOpen or driverAid.doors_open
    if type(raw) == "boolean" then return raw end
    if type(raw) == "number" then return raw ~= 0 end
    if type(raw) == "table" then
        local v = raw.value or raw.Value
        if type(v) == "boolean" then return v end
    end
    return nil
end

local function extract_speed_limits(driverAid)
    local dist_cm = util.pick_float(
        driverAid.DistanceToNextSpeedLimit,
        driverAid.distanceToNextSpeedLimit)
    local limit_ms = util.scalar_ms(driverAid.nextSpeedLimit or driverAid.NextSpeedLimit)
    if not util.is_valid_num(dist_cm) or not limit_ms or dist_cm <= 0 then
        return {}
    end
    return { dist_limit_cm = dist_cm, next_limit_ms = limit_ms }
end

local function extract_gradient(driverAid)
    if type(driverAid) ~= "table" then return nil end
    for _, key in ipairs({ "gradient", "Gradient", "gradient_percent" }) do
        local g = driverAid[key]
        if type(g) == "number" then return g end
        if type(g) == "table" then
            local nested = util.out_val(g, "Value", "value")
            if nested ~= nil then return nested end
        end
    end
    return nil
end

-- C1 (PLAN_V2 §3): solo si aspecto rojo adelante (UK 323 enum 2).
function M.extract_signal_red(driverAid)
    local aspect = util.pick_float(
        driverAid.signalAspectClass,
        driverAid.SignalAspectClass)
    local dist_cm = util.pick_float(
        driverAid.distanceToSignal,
        driverAid.DistanceToSignal)
    if aspect == nil or dist_cm == nil or dist_cm <= 0 then
        return nil, nil
    end
    if math.floor(aspect + 0.5) == config.SIGNAL_RED_ASPECT then
        return 1, dist_cm
    end
    return nil, nil
end

local function read_driver_aid(controller)
    local driverAid = {}
    controller:GetDriverAidData(driverAid)
    local speedLimit = util.scalar_ms(driverAid.SpeedLimit or driverAid.speedLimit)
    local planning = extract_speed_limits(driverAid)
    local doors_dmi = extract_doors_dmi(driverAid)
    local signal_red, signal_dist_cm = M.extract_signal_red(driverAid)
    return speedLimit, extract_gradient(driverAid), planning, doors_dmi, signal_red, signal_dist_cm
end

local function read_odometer_m(actor)
    local ok, v = pcall(function()
        local sim = actor.Simulation
        if sim and sim.Axle_1_1 then
            return sim.Axle_1_1.TotalDistanceTravelled_M
        end
        return nil
    end)
    if ok and type(v) == "number" and v == v and v >= 0 then return v end
    return nil
end

local function read_hud_gauge_pa(actor, method)
    local result = {}
    local ok = pcall(function() actor[method](actor, result, {}) end)
    if not ok then
        ok = pcall(function() actor[method](actor, result) end)
        if not ok then return nil end
    end
    return util.pick_float(
        util.out_val(result, "RedNeedle (Pa)", "RedNeedle"),
        util.out_val(result, "WhiteNeedle (Pa)", "WhiteNeedle"))
end

-- Class 323: Simulation.BrakeCylinder_* no expone escalares en UE4SS tick (lab L0.6).
-- HUD_GetBrakeGauge_1 RedNeedle (Pa) ÷ 100000 coincide con HTTP Pressure_BAR (213100Z).
local function read_brake_cylinder_bar(actor)
    for _, method in ipairs(config.BRAKE_GAUGE_METHODS) do
        local ok, pa = pcall(function() return read_hud_gauge_pa(actor, method) end)
        if ok and type(pa) == "number" and pa == pa and pa >= 0 then
            return pa / 100000.0
        end
    end
    local ok, v = pcall(function()
        local sim = actor.Simulation
        if not sim then return nil end
        for _, name in ipairs(config.BRAKE_CYL_NAMES) do
            local cyl
            pcall(function() cyl = sim[name] end)
            if cyl then
                for _, field in ipairs(config.BRAKE_CYL_PRESSURE_FIELDS) do
                    local raw
                    pcall(function() raw = cyl[field] end)
                    local p = util.pick_float(raw)
                    if type(p) == "number" and p == p and p >= 0 then
                        return p
                    end
                end
            end
        end
        return nil
    end)
    if ok and type(v) == "number" and v == v and v >= 0 then return v end
    return nil
end

local function read_vehicle_class(actor)
    local classObj = actor:GetClass()
    if classObj and classObj:IsValid() then
        return classObj:GetFName():ToString()
    end
    return "?"
end

function M.build_line(sample)
    local parts = {
        "seq=" .. tostring(sample.seq),
        "speed_ms=" .. util.fmt_num(sample.speed_ms),
        "power=" .. util.fmt_num(sample.power),
        "power_neg=" .. (sample.power_neg and "1" or "0"),
        "handle_notch=" .. util.fmt_int(sample.handle_notch),
        "lever_notch=" .. util.fmt_int(sample.lever_notch),
        "last_cmd_id=" .. tostring(sample.last_cmd_id or 0),
        "last_ack_ok=" .. (sample.last_ack_ok and "1" or "0"),
        "train_brake=" .. util.fmt_num(sample.train_brake),
        "loco_brake=" .. util.fmt_num(sample.loco_brake),
        "dyn_brake=" .. util.fmt_num(sample.dyn_brake),
        "accel_ms2=" .. util.fmt_num(sample.accel_ms2),
        "brake_cyl_bar=" .. util.fmt_num(sample.brake_cyl_bar),
        "max_speed_ms=" .. util.fmt_num(sample.max_speed_ms),
        "speed_limit_ms=" .. util.fmt_num(sample.speed_limit_ms),
        "gradient_pct=" .. util.fmt_num(sample.gradient_pct),
        "vehicle=" .. (sample.vehicle or "?"),
    }
    for _, key in ipairs(config.PLANNING_FIELDS) do
        if sample[key] ~= nil then
            table.insert(parts, key .. "=" .. util.fmt_num(sample[key]))
        end
    end
    if sample.doors_telem ~= nil then
        table.insert(parts, "doors_telem=" .. (sample.doors_telem and "1" or "0"))
    end
    if sample.doors_dmi ~= nil then
        table.insert(parts, "doors_dmi=" .. (sample.doors_dmi and "1" or "0"))
    end
    if sample.signal_red ~= nil then
        table.insert(parts, "signal_red=" .. tostring(sample.signal_red))
        if sample.signal_dist_cm ~= nil then
            table.insert(parts, "signal_dist_cm=" .. util.fmt_num(sample.signal_dist_cm))
        end
    end
    if sample.is_slipping ~= nil then
        table.insert(parts, "is_slipping=" .. (sample.is_slipping and "1" or "0"))
    end
    if sample.traction_locked ~= nil then
        table.insert(parts, "traction_locked=" .. (sample.traction_locked and "1" or "0"))
    end
    return table.concat(parts, " ")
end

local function safe_read(label, fn)
    local ok, result = pcall(fn)
    if not ok then
        log_hud_error(label, result)
        return nil
    end
    return result
end

function M.collect_sample(controller, state)
    local sample = { seq = state.seq, vehicle = "?", power_neg = false }

    local actor = controller:GetDrivableActor()
    if not actor or not actor:IsValid() then
        return sample, "no_drivable"
    end

    sample.speed_ms = safe_read("speed", function() return read_speed(actor) end)
    do
        local ok, power, power_neg = pcall(function() return read_power(actor) end)
        if ok then
            sample.power = power
            sample.power_neg = power_neg == true
        else
            log_hud_error("power", power)
        end
    end
    sample.train_brake = safe_read("train_brake", function()
        return read_brake_handle(actor, "HUD_GetTrainBrakeHandle")
    end)
    sample.loco_brake = safe_read("loco_brake", function()
        return read_brake_handle(actor, "HUD_GetLocomotiveBrakeHandle")
    end)
    sample.dyn_brake = safe_read("dyn_brake", function()
        return read_brake_handle(actor, "HUD_GetElectricBrakeHandle")
    end)
    sample.accel_ms2 = safe_read("accel", function() return read_accel(actor) end)
    sample.brake_cyl_bar = safe_read("brake_cyl", function()
        return read_brake_cylinder_bar(actor)
    end)
    sample.odo_m = safe_read("odo", function() return read_odometer_m(actor) end)
    sample.max_speed_ms = safe_read("max_speed", function() return read_max_speed(actor) end)
    sample.handle_notch = util.power_to_notch(sample.power, sample.power_neg)
    sample.lever_notch = safe_read("lever", function()
        return M.read_hud_lever_notch(controller)
    end)
    sample.last_cmd_id = state.last_cmd_id
    sample.last_ack_ok = state.last_ack_ok

    local doors_telem = safe_read("doors_telem", function() return read_passenger_doors(actor) end)
    if doors_telem ~= nil then sample.doors_telem = doors_telem end

    sample.is_slipping = safe_read("is_slipping", function()
        return read_bool_hud(actor, "HUD_GetIsSlipping", "IsSlipping")
    end)
    sample.traction_locked = safe_read("traction_locked", function()
        return read_bool_hud(actor, "HUD_GetIsTractionLocked", "IsTractionLocked")
    end)

    local ok, speed_limit, gradient, planning, doors_dmi, signal_red, signal_dist_cm = pcall(
        function() return read_driver_aid(controller) end)
    if ok then
        sample.speed_limit_ms = speed_limit
        sample.gradient_pct = gradient
        if doors_dmi ~= nil then sample.doors_dmi = doors_dmi end
        if signal_red ~= nil then
            sample.signal_red = signal_red
            sample.signal_dist_cm = signal_dist_cm
        end
        if type(planning) == "table" then
            sample.dist_limit_cm = planning.dist_limit_cm
            sample.next_limit_ms = planning.next_limit_ms
            if not state.limits_logged then
                state.limits_logged = true
                print(string.format(
                    "[TelemetryProbe] limit dist_cm=%s next_ms=%s\n",
                    tostring(planning.dist_limit_cm),
                    tostring(planning.next_limit_ms)))
            end
        end
    else
        log_hud_error("driver_aid", speed_limit)
    end

    sample.vehicle = safe_read("vehicle", function() return read_vehicle_class(actor) end) or "?"

    if not state.debug_dumped and sample.power ~= nil then
        state.debug_dumped = true
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

return M
