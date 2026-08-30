-- Modo driver_aid — escalares GetDriverAidData (C1/C2/lim2 candidatos).
local util = require("util")

local M = {}

local SCALAR_KEYS = {
    "gradient",
    "Gradient",
    "speedLimit",
    "SpeedLimit",
    "speedLimitSeen",
    "SpeedLimitSeen",
    "trackMaxSpeed",
    "TrackMaxSpeed",
    "formationMaxSpeed",
    "FormationMaxSpeed",
    "serviceMaxSpeed",
    "ServiceMaxSpeed",
    "currentSpeedLimitSource",
    "CurrentSpeedLimitSource",
    "distanceToNextSpeedLimit",
    "DistanceToNextSpeedLimit",
    "nextSpeedLimit",
    "NextSpeedLimit",
    "distanceToSignal",
    "DistanceToSignal",
    "signalSeen",
    "SignalSeen",
    "signalAspectClass",
    "SignalAspectClass",
    "bSignalIsPermissive",
    "BSignalIsPermissive",
    "signalPropertyGuid",
    "SignalPropertyGuid",
}

local function unwrap_number(v, depth)
    depth = depth or 0
    if v == nil or depth > 5 then return nil end
    if type(v) == "number" then
        return util.is_valid_num(v) and v or nil
    end
    local n
    pcall(function() n = v:get() end)
    if type(n) == "number" and util.is_valid_num(n) then return n end
    if type(v) == "table" then
        local inner = util.out_val(v, "value", "Value", "OutputValue", "InputValue")
        if type(inner) == "number" and util.is_valid_num(inner) then return inner end
    end
    for _, key in ipairs({ "Value", "OutputValue", "InputValue", "FloatValue" }) do
        pcall(function() n = v[key] end)
        if type(n) == "number" and util.is_valid_num(n) then return n end
    end
    pcall(function() n = v:GetValue() end)
    if type(n) == "number" and util.is_valid_num(n) then return n end
    return nil
end

local function scalar_ms(node)
    return unwrap_number(node)
end

local function read_scalar_field(driverAid, key)
    local raw = driverAid[key]
    if raw == nil then return nil end
    if type(raw) == "boolean" or type(raw) == "string" then return raw end
    if type(raw) == "number" then
        return util.is_valid_num(raw) and raw or nil
    end
    return scalar_ms(raw)
end

local function http_key_for(lua_key)
    local lower = lua_key:sub(1, 1):lower() .. lua_key:sub(2)
    return "DriverAid.Data." .. lower
end

local function pick_first(driverAid, ...)
    for i = 1, select("#", ...) do
        local key = select(i, ...)
        local v = read_scalar_field(driverAid, key)
        if v ~= nil then return v, key end
    end
    return nil, nil
end

local function read_vec3(node)
    if type(node) ~= "table" then return nil end
    local x = unwrap_number(node.x or node.X)
    local y = unwrap_number(node.y or node.Y)
    local z = unwrap_number(node.z or node.Z)
    if x == nil and y == nil and z == nil then return nil end
    return { x = x, y = y, z = z }
end

local function read_index(arr, i)
    if arr == nil then return nil end
    local ok, v = pcall(function() return arr[i] end)
    if ok then return v end
    ok, v = pcall(function() return arr[i + 1] end)
    if ok then return v end
    return nil
end

local function read_signal_item(item)
    if type(item) ~= "table" then return nil end
    local dist = pick_first(item, "distanceToNextSignal", "DistanceToNextSignal")
    local aspect = pick_first(item, "value", "Value", "signalAspectClass", "SignalAspectClass")
    local pos = read_vec3(item.nextSignalPosition or item.NextSignalPosition)
    if dist == nil and aspect == nil and pos == nil then return nil end
    return {
        distance_cm = dist,
        aspect = type(aspect) == "string" and aspect or nil,
        position = pos,
    }
end

local function read_next_signals(driverAid, max_items)
    local arr = driverAid.nextSignals or driverAid.NextSignals
    if arr == nil then return nil, "nextSignals missing" end
    local out = {}
    local errors = {}
    for i = 0, (max_items or 3) - 1 do
        local item = read_index(arr, i)
        if item == nil then break end
        local parsed, err = util.pcall_read("nextSignals[" .. tostring(i) .. "]", function()
            return read_signal_item(item)
        end)
        if parsed then
            out[#out + 1] = parsed
        elseif err then
            errors[#errors + 1] = err
        end
    end
    if #out == 0 and #errors > 0 then
        return nil, table.concat(errors, "; ")
    end
    return out, nil
end

local function read_speed_limit_item(item)
    if type(item) ~= "table" then return nil end
    local dist = pick_first(item, "distanceToNextSpeedLimit", "DistanceToNextSpeedLimit")
    local limit = scalar_ms(item.value or item.Value or item.nextSpeedLimit or item.NextSpeedLimit)
    local rtype = pick_first(item, "restrictionType", "RestrictionType")
    if dist == nil and limit == nil then return nil end
    return {
        distance_cm = dist,
        limit_ms = limit,
        restriction_type = type(rtype) == "string" and rtype or nil,
    }
end

local function read_next_speed_limits(driverAid, max_items)
    local arr = driverAid.nextSpeedLimits or driverAid.NextSpeedLimits
    if arr == nil then return nil, "nextSpeedLimits missing" end
    local out = {}
    local errors = {}
    for i = 0, (max_items or 4) - 1 do
        local item = read_index(arr, i)
        if item == nil then break end
        local parsed, err = util.pcall_read("nextSpeedLimits[" .. tostring(i) .. "]", function()
            return read_speed_limit_item(item)
        end)
        if parsed then
            out[#out + 1] = parsed
        elseif err then
            errors[#errors + 1] = err
        end
    end
    if #out == 0 and #errors > 0 then
        return nil, table.concat(errors, "; ")
    end
    return out, nil
end

local function build_probe_candidates(lua_scalars, signals)
    local c1 = {}
    local aspect = lua_scalars.signal_aspect or lua_scalars.signalAspectClass
    local dist_sig = lua_scalars.distance_to_signal_cm or lua_scalars.distanceToSignal
    if aspect ~= nil then c1.signal_aspect = aspect end
    if dist_sig ~= nil then c1.signal_dist_cm = dist_sig end
    if aspect == "Stop" or aspect == "DANGER" then
        c1.signal_red_candidate = 1
    elseif aspect ~= nil then
        c1.signal_red_candidate = 0
    end
    if signals and signals[1] and signals[1].aspect then
        c1.next_signal_0 = signals[1].aspect
    end
    return {
        c1 = c1,
        c2 = {
            note = "station_dist_cm requires DriverAid.TrackData (HTTP ~2s) or governor state",
        },
        lim2 = {
            note = "probe uses parent scalars only; nextSpeedLimits[] array parsed here if readable",
        },
    }
end

function M.capture(controller)
    local payload = {
        lua = { scalars = {}, vectors = {} },
        http_guess = {},
        arrays = {},
        probe_candidates = {},
        http_only = {
            TrackData = "DriverAid.TrackData — markers/stations; poll HTTP in Python",
        },
        errors = {},
    }

    if not util.obj_valid(controller) then
        payload.errors[#payload.errors + 1] = "controller invalid"
        return payload
    end

    local driverAid = {}
    local ok, err = util.pcall_read("GetDriverAidData", function()
        controller:GetDriverAidData(driverAid)
        return true
    end)
    if not ok or err then
        payload.errors[#payload.errors + 1] = "GetDriverAidData: " .. tostring(err)
        return payload
    end

    local seen = {}
    for _, key in ipairs(SCALAR_KEYS) do
        if not seen[key:lower()] then
            local v = read_scalar_field(driverAid, key)
            if v ~= nil then
                local canon = key:sub(1, 1):lower() .. key:sub(2)
                payload.lua.scalars[canon] = v
                payload.http_guess[http_key_for(key)] = v
                seen[key:lower()] = true
            end
        end
    end

    local dist_lim, _ = pick_first(driverAid, "distanceToNextSpeedLimit", "DistanceToNextSpeedLimit")
    local next_lim, _ = pick_first(driverAid, "nextSpeedLimit", "NextSpeedLimit")
    if dist_lim ~= nil then payload.lua.scalars.dist_limit_cm = dist_lim end
    if next_lim ~= nil then payload.lua.scalars.next_limit_ms = next_lim end

    local grad, _ = pick_first(driverAid, "gradient", "Gradient")
    if grad ~= nil then payload.lua.scalars.gradient_pct = grad end

    local speed_lim, _ = pick_first(driverAid, "speedLimit", "SpeedLimit")
    if speed_lim ~= nil then payload.lua.scalars.speed_limit_ms = speed_lim end

    local sig_pos = read_vec3(driverAid.nextSignalPosition or driverAid.NextSignalPosition)
    if sig_pos then
        payload.lua.vectors.next_signal_position = sig_pos
        payload.http_guess["DriverAid.Data.nextSignalPosition"] = sig_pos
    end

    local lim_pos = read_vec3(driverAid.nextSpeedLimitPosition or driverAid.NextSpeedLimitPosition)
    if lim_pos then
        payload.lua.vectors.next_speed_limit_position = lim_pos
        payload.http_guess["DriverAid.Data.nextSpeedLimitPosition"] = lim_pos
    end

    local signals, sig_err = read_next_signals(driverAid, 4)
    if signals then payload.arrays.next_signals = signals end
    if sig_err then payload.errors[#payload.errors + 1] = "nextSignals: " .. sig_err end

    local limits, lim_err = read_next_speed_limits(driverAid, 4)
    if limits then payload.arrays.next_speed_limits = limits end
    if lim_err then payload.errors[#payload.errors + 1] = "nextSpeedLimits: " .. lim_err end

    payload.probe_candidates = build_probe_candidates(payload.lua.scalars, signals)
    return payload
end

return M
