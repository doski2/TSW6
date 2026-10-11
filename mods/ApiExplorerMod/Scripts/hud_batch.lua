-- Modo hud_batch — HUD_Get* + http_guess.
local config = require("config")
local util = require("util")

local M = {}

local function read_speed(actor)
    local result = {}
    actor:HUD_GetSpeed(result)
    return util.flatten_out_table(result)
end

local function read_accel(actor)
    local result = {}
    actor:HUD_GetAcceleration(result)
    return util.flatten_out_table(result)
end

local function read_power(actor)
    local power, is_negative = {}, {}
    actor:HUD_GetPowerHandle(power, {}, is_negative)
    return {
        power = util.out_val(power, "Power"),
        is_negative = util.out_val(is_negative, "IsNegative"),
    }
end

local function read_brake_handle(actor, method)
    local handle = {}
    actor[method](actor, handle, {})
    return util.flatten_out_table(handle)
end

local function read_hud_out1(actor, method)
    local result = {}
    actor[method](actor, result)
    return util.flatten_out_table(result)
end

local function read_hud_out2(actor, method)
    local result = {}
    actor[method](actor, result, {})
    return util.flatten_out_table(result)
end

local function read_direction(actor)
    return read_hud_out2(actor, "HUD_GetDirection")
end

local function read_bool_method(actor, method)
    return read_hud_out1(actor, method)
end

local function read_tractive_effort(actor)
    local value, err = util.pcall_read("HUD_GetTractiveEffort", function()
        return read_hud_out1(actor, "HUD_GetTractiveEffort")
    end)
    if not err and value ~= nil then return value end
    return read_hud_out2(actor, "HUD_GetTractiveEffort")
end

-- L0.6d retest: HTTP expone Simulation/Axle_*/*/NetTractiveEffort; HUD suele 0 (323/M3a).
local SIM_TRACTION_AXLES = { "Axle_1_1", "Axle_1_2", "Axle_2_1", "Axle_2_2" }
local SIM_TRACTION_SUBNODES = { "Axle", "Wheel", "VirtualWheel" }
local SIM_TRACTION_FIELDS = { "NetTractiveEffort", "LocalTractiveEffort", "NetTorque_NM" }

local function read_simulation_traction_probe(actor)
    local out = {}
    local ok, err = pcall(function()
        local sim = actor.Simulation
        if sim == nil then
            out.error = "no Simulation"
            return
        end
        for _, axle_name in ipairs(SIM_TRACTION_AXLES) do
            local row = { index_ok = false, fields_by_via = {} }
            local axle_node
            local idx_ok, idx_err = pcall(function() axle_node = sim[axle_name] end)
            if not idx_ok then
                row.index_error = tostring(idx_err)
            elseif axle_node ~= nil then
                row.index_ok = true
                row.child_type = type(axle_node)
                row.child_valid = util.obj_valid(axle_node)
                for _, field in ipairs(SIM_TRACTION_FIELDS) do
                    local n = util.read_number_prop(axle_node, field)
                    if n ~= nil then
                        row.fields_by_via.direct = row.fields_by_via.direct or {}
                        row.fields_by_via.direct[field] = n
                    end
                end
                for _, sub in ipairs(SIM_TRACTION_SUBNODES) do
                    local subnode
                    pcall(function() subnode = axle_node[sub] end)
                    if subnode ~= nil then
                        local bucket = {}
                        for _, field in ipairs(SIM_TRACTION_FIELDS) do
                            local n = util.read_number_prop(subnode, field)
                            if n ~= nil then
                                bucket[field] = n
                            end
                        end
                        if next(bucket) ~= nil then
                            row.fields_by_via[sub] = bucket
                        end
                    end
                end
            end
            out[axle_name] = row
        end
    end)
    if not ok then
        out.error = tostring(err)
    end
    return out
end

local function read_gauge(actor, method)
    return read_hud_out2(actor, method)
end

local function read_max_speed(actor)
    local max_speed, is_active = {}, {}
    actor:HUD_GetMaxPermittedSpeed(max_speed, {}, is_active)
    return {
        max_speed = util.out_val(max_speed, "MaxSpeed (ms)", "MaxSpeed"),
        is_active = util.out_val(is_active, "IsActive"),
    }
end

local function read_scalar_method(actor, method)
    local value, err = util.pcall_read(method, function()
        return read_hud_out1(actor, method)
    end)
    if not err and value ~= nil then return value end
    return read_hud_out2(actor, method)
end

local READERS = {
    HUD_GetSpeed = function(a) return read_speed(a) end,
    HUD_GetAcceleration = function(a) return read_accel(a) end,
    HUD_GetPowerHandle = function(a) return read_power(a) end,
    HUD_GetTrainBrakeHandle = function(a) return read_brake_handle(a, "HUD_GetTrainBrakeHandle") end,
    HUD_GetLocomotiveBrakeHandle = function(a) return read_brake_handle(a, "HUD_GetLocomotiveBrakeHandle") end,
    HUD_GetElectricBrakeHandle = function(a) return read_brake_handle(a, "HUD_GetElectricBrakeHandle") end,
    HUD_GetDirection = function(a) return read_direction(a) end,
    HUD_GetIsSlipping = function(a) return read_bool_method(a, "HUD_GetIsSlipping") end,
    HUD_GetIsTractionLocked = function(a) return read_bool_method(a, "HUD_GetIsTractionLocked") end,
    HUD_GetTractiveEffort = function(a) return read_tractive_effort(a) end,
    HUD_GetBrakeGauge_1 = function(a) return read_gauge(a, "HUD_GetBrakeGauge_1") end,
    HUD_GetBrakeGauge_2 = function(a) return read_gauge(a, "HUD_GetBrakeGauge_2") end,
    HUD_GetMaxPermittedSpeed = function(a) return read_max_speed(a) end,
    HUD_GetSpeedControlTarget = function(a) return read_scalar_method(a, "HUD_GetSpeedControlTarget") end,
    HUD_GetAmmeter = function(a) return read_scalar_method(a, "HUD_GetAmmeter") end,
    HUD_GetEngineRPM = function(a) return read_scalar_method(a, "HUD_GetEngineRPM") end,
}

function M.capture(actor)
    local payload = {
        lua = {},
        http_guess = {},
        errors = {},
    }
    if not util.obj_valid(actor) then
        payload.errors[#payload.errors + 1] = "actor invalid"
        return payload
    end

    for _, method in ipairs(config.HUD_METHODS) do
        local reader = READERS[method]
        if reader then
            local value, err = util.pcall_read(method, function() return reader(actor) end)
            if err then
                payload.errors[#payload.errors + 1] = method .. ": " .. err
            elseif value ~= nil then
                payload.lua[method] = value
                payload.http_guess[config.http_path_for(method)] = value
            else
                payload.errors[#payload.errors + 1] = method .. ": empty"
            end
        end
    end

    payload.lua.simulation_traction = read_simulation_traction_probe(actor)

    return payload
end

return M
