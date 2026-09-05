local config = require("config")

local M = {}

local SEND_COMMAND_FILE = "SendCommand.txt"
local APPLY_FLAG_FILE = "TSW6ApplyCommands.flag"
local SEND_ACK_FILE = "SendCommandAck.txt"

local bridge_ready = false
local bridge_dir_logged = false
local commands_armed_cache = false
local commands_armed_checked_at = 0

function M.bridge_dir()
    local temp = os.getenv("TEMP") or os.getenv("TMP") or "."
    return temp .. "\\TSW6Bridge"
end

function M.getdata_path()
    return M.bridge_dir() .. "\\GetData.txt"
end

local function send_command_path()
    return M.bridge_dir() .. "\\" .. SEND_COMMAND_FILE
end

local function apply_flag_path()
    return M.bridge_dir() .. "\\" .. APPLY_FLAG_FILE
end

local function send_ack_path()
    return M.bridge_dir() .. "\\" .. SEND_ACK_FILE
end

local function log_bridge_dir_once(dir)
    if bridge_dir_logged then return end
    bridge_dir_logged = true
    print("[TelemetryProbe] bridge dir: " .. dir .. "\n")
end

local function probe_bridge_writable(dir)
    local test = dir .. "\\.probe_write_test"
    local f = io.open(test, "w")
    if not f then return false end
    f:write("ok\n")
    f:close()
    os.remove(test)
    return true
end

function M.ensure_bridge_dir()
    local dir = M.bridge_dir()
    if bridge_ready then return true end
    os.execute('mkdir "' .. dir .. '" 2>nul')
    log_bridge_dir_once(dir)
    if not probe_bridge_writable(dir) then
        print("[TelemetryProbe] ERROR: bridge not writable: " .. dir .. "\n")
        return false
    end
    bridge_ready = true
    return true
end

function M.commands_armed()
    local now = os.clock()
    if (now - commands_armed_checked_at) < config.COMMANDS_ARMED_TTL_S then
        return commands_armed_cache
    end
    commands_armed_checked_at = now
    local f = io.open(apply_flag_path(), "r")
    if not f then
        commands_armed_cache = false
        return false
    end
    local line = f:read("*l")
    f:close()
    commands_armed_cache = line ~= nil and line ~= ""
    return commands_armed_cache
end

function M.purge_ipc_files()
    pcall(function() os.remove(send_command_path()) end)
    pcall(function() os.remove(apply_flag_path()) end)
    pcall(function() os.remove(send_ack_path()) end)
end

function M.write_send_ack(name, value, ok, cmd_id)
    M.ensure_bridge_dir()
    local f = io.open(send_ack_path(), "w")
    if not f then return end
    if cmd_id then
        f:write(string.format(
            "%s:%.4f:%s:%d\n", name, value, ok and "ok" or "fail", cmd_id))
    else
        f:write(string.format("%s:%.4f:%s\n", name, value, ok and "ok" or "fail"))
    end
    f:flush()
    f:close()
end

function M.write_getdata_line(line)
    if not M.ensure_bridge_dir() then return false end
    local f = io.open(M.getdata_path(), "w")
    if not f then
        print("[TelemetryProbe] ERROR: cannot open " .. M.getdata_path() .. "\n")
        return false
    end
    f:write(line .. "\n")
    f:close()
    return true
end

function M.parse_send_line(line)
    local name, val, cid = line:match("^([^:]+):([^:]+):(%d+)$")
    if name and val and cid then
        return name, tonumber(val), tonumber(cid)
    end
    name, val = line:match("^([^:]+):([^:]+)$")
    if name and val then return name, tonumber(val), nil end
    return nil, nil, nil
end

function M.read_send_commands()
    if not M.commands_armed() then return {} end
    local f = io.open(send_command_path(), "r")
    if not f then return {} end
    local content = f:read("*a") or ""
    f:close()
    local out = {}
    for line in content:gmatch("[^\r\n]+") do
        if line ~= "" then
            local name, val, cid = M.parse_send_line(line)
            if name and val then
                out[#out + 1] = { name = name, value = val, cmd_id = cid }
            end
        end
    end
    return out
end

return M
