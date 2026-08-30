-- JSON mínimo (sin dependencias externas).
local M = {}

local function escape_str(s)
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    return s
end

local function encode_value(v, stack)
    local tv = type(v)
    if tv == "nil" then return "null" end
    if tv == "boolean" then return v and "true" or "false" end
    if tv == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        return string.format("%.10g", v)
    end
    if tv == "string" then
        return '"' .. escape_str(v) .. '"'
    end
    if tv ~= "table" then return "null" end
    stack = stack or {}
    if stack[v] then return '"<cycle>"' end
    stack[v] = true

    local is_array = true
    local n = 0
    for k, _ in pairs(v) do
        if type(k) ~= "number" then
            is_array = false
            break
        end
        if k > n then n = k end
    end
    if is_array and n > 0 then
        local parts = {}
        for i = 1, n do
            parts[#parts + 1] = encode_value(v[i], stack)
        end
        stack[v] = nil
        return "[" .. table.concat(parts, ",") .. "]"
    end

    local parts = {}
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    for _, k in ipairs(keys) do
        parts[#parts + 1] = encode_value(tostring(k), stack) .. ":" .. encode_value(v[k], stack)
    end
    stack[v] = nil
    return "{" .. table.concat(parts, ",") .. "}"
end

function M.encode(tbl)
    return encode_value(tbl, {})
end

function M.encode_pretty(tbl, indent)
    indent = indent or 0
    local pad = string.rep("  ", indent)
    local pad_in = string.rep("  ", indent + 1)
    local tv = type(tbl)
    if tv ~= "table" then return encode_value(tbl) end

    local is_array = true
    local n = 0
    for k, _ in pairs(tbl) do
        if type(k) ~= "number" then is_array = false break end
        if k > n then n = k end
    end

    if is_array and n > 0 then
        local lines = {}
        for i = 1, n do
            lines[#lines + 1] = pad_in .. encode_value(tbl[i])
        end
        return "[\n" .. table.concat(lines, ",\n") .. "\n" .. pad .. "]"
    end

    local keys = {}
    for k in pairs(tbl) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    if #keys == 0 then return "{}" end

    local lines = {}
    for _, k in ipairs(keys) do
        local key_json = encode_value(tostring(k))
        local val = tbl[k]
        local val_json
        if type(val) == "table" then
            val_json = M.encode_pretty(val, indent + 1)
        else
            val_json = encode_value(val)
        end
        lines[#lines + 1] = pad_in .. key_json .. ": " .. val_json
    end
    return "{\n" .. table.concat(lines, ",\n") .. "\n" .. pad .. "}"
end

return M
