local config = require("config")

local M = {}
local SENTINEL = 3.4028235e38

function M.lua_str(v)
    if type(v) == "string" then return v end
    if v == nil then return nil end
    local ok, s = pcall(function() return v:ToString() end)
    if ok and type(s) == "string" and s ~= "" then return s end
    ok, s = pcall(function() return tostring(v) end)
    if ok and type(s) == "string" and s ~= "" then return s end
    return nil
end

function M.out_val(t, ...)
    if type(t) ~= "table" then return nil end
    for i = 1, select("#", ...) do
        local key = select(i, ...)
        if t[key] ~= nil then return t[key] end
    end
    for _, v in pairs(t) do
        if type(v) == "number" or type(v) == "boolean" or type(v) == "string" then
            return v
        end
    end
    return nil
end

function M.is_valid_num(v)
    if type(v) ~= "number" or v ~= v then return false end
    local ok, good = pcall(function()
        return v > 0 and v < SENTINEL * 0.99
    end)
    return ok and good == true
end

function M.unwrap_number(v, depth)
    depth = depth or 0
    if v == nil or type(depth) ~= "number" or depth > 5 then return nil end
    if type(v) == "number" then return v end
    local n
    pcall(function() n = v:get() end)
    if type(n) == "number" then return n end
    if n ~= nil and type(n) ~= "number" then
        local inner = M.unwrap_number(n, depth + 1)
        if inner ~= nil then return inner end
    end
    for _, key in ipairs({ "Value", "OutputValue", "InputValue", "FloatValue" }) do
        pcall(function() n = v[key] end)
        if type(n) == "number" then return n end
    end
    pcall(function() n = v:GetValue() end)
    if type(n) == "number" then return n end
    return nil
end

function M.pick_float(...)
    for i = 1, select("#", ...) do
        local n = M.unwrap_number(select(i, ...))
        if type(n) == "number" then return n end
    end
    return nil
end

function M.scalar_ms(node)
    local n = M.unwrap_number(node)
    if type(n) == "number" then
        return M.is_valid_num(n) and n or nil
    end
    if type(node) == "table" then
        local v = M.out_val(node, "value", "Value")
        return M.is_valid_num(v) and v or nil
    end
    return nil
end

function M.fmt_num(v)
    if v == nil then return "?" end
    if type(v) == "number" then return string.format("%.4f", v) end
    return tostring(v)
end

function M.fmt_int(v)
    if v == nil then return "?" end
    if type(v) == "number" then return string.format("%d", math.floor(v + 0.5)) end
    return tostring(v)
end

function M.clamp_num(v, lo, hi)
    if v < lo then return lo end
    if v > hi then return hi end
    return v
end

function M.try_child(parent, name)
    if not parent then return nil end
    local ok, child = pcall(function() return parent[name] end)
    if ok and child and child.IsValid and child:IsValid() then
        return child
    end
    return nil
end

function M.ctrl_is_valid(ctrl)
    if not ctrl then return false end
    local ok, valid = pcall(function() return ctrl.IsValid and ctrl:IsValid() end)
    return ok and valid == true
end

function M.cmd_value_to_notch(cmd_val)
    if type(cmd_val) ~= "number" then return nil end
    return math.max(0, math.min(8, math.floor(cmd_val * 8.0 + 0.5)))
end

function M.notch_to_axis(notch)
    if type(notch) ~= "number" then return nil end
    local n = math.max(0, math.min(8, math.floor(notch + 0.5)))
    return config.PBH_INPUT_BY_NOTCH[n + 1]
end

function M.axis_value_to_notch(axis_val)
    if type(axis_val) ~= "number" then return nil end
    local best_i = 0
    local best_d = math.abs(axis_val - config.PBH_INPUT_BY_NOTCH[1])
    for i = 1, 9 do
        local d = math.abs(axis_val - config.PBH_INPUT_BY_NOTCH[i])
        if d < best_d then
            best_d = d
            best_i = i - 1
        end
    end
    return best_i
end

function M.power_to_notch(power, power_neg)
    if power == nil then return nil end
    local p = tonumber(power) or 0
    if power_neg then p = -math.abs(p) end
    return math.max(0, math.min(8, 4 + math.floor(p + 0.5)))
end

function M.ipc_log(fmt, ...)
    if config.DEBUG_IPC then
        print(string.format("[TelemetryProbe] " .. fmt .. "\n", ...))
    end
end

return M
