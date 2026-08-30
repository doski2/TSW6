-- Helpers UE4SS compartidos (sin depender del probe).
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
    if type(v) ~= "number" then return false end
    if v ~= v then return false end
    if math.abs(v) >= SENTINEL then return false end
    return true
end

function M.unwrap_number(v, depth)
    depth = depth or 0
    if v == nil or depth > 5 then return nil end
    if type(v) == "number" then
        return M.is_valid_num(v) and v or nil
    end
    local n
    pcall(function() n = v:get() end)
    if type(n) == "number" and M.is_valid_num(n) then return n end
    if type(v) == "table" then
        local inner = M.out_val(v, "value", "Value", "OutputValue", "InputValue")
        if type(inner) == "number" and M.is_valid_num(inner) then return inner end
    end
    for _, key in ipairs({ "Value", "OutputValue", "InputValue", "FloatValue" }) do
        pcall(function() n = v[key] end)
        if type(n) == "number" and M.is_valid_num(n) then return n end
    end
    pcall(function() n = v:GetValue() end)
    if type(n) == "number" and M.is_valid_num(n) then return n end
    return nil
end

function M.read_number_prop(obj, prop)
    if obj == nil then return nil end
    local ok, v = pcall(function() return obj[prop] end)
    if not ok then return nil end
    return M.unwrap_number(v)
end

function M.obj_valid(obj)
    if not obj then return false end
    local ok, valid = pcall(function() return obj.IsValid and obj:IsValid() end)
    return ok and valid == true
end

function M.pcall_read(label, fn)
    local ok, result = pcall(fn)
    if not ok then
        return nil, tostring(result)
    end
    return result, nil
end

function M.flatten_out_table(t)
    if type(t) ~= "table" then
        if type(t) == "number" and M.is_valid_num(t) then return t end
        if type(t) == "boolean" or type(t) == "string" then return t end
        return nil
    end
    local flat = {}
    for k, v in pairs(t) do
        if type(k) == "string" then
            if type(v) == "number" and M.is_valid_num(v) then
                flat[k] = v
            elseif type(v) == "boolean" or type(v) == "string" then
                flat[k] = v
            elseif type(v) == "table" then
                local inner = M.flatten_out_table(v)
                if inner ~= nil then flat[k] = inner end
            end
        end
    end
    if next(flat) == nil then
        local scalar = M.out_val(t)
        if scalar ~= nil then return scalar end
    end
    return flat
end

return M
