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

    return payload
end

return M
