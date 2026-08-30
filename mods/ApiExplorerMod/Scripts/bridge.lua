-- Escritura JSON + manifest en data/lab_exports/exports/<session>/ (repo, vía lab_root.txt)
local config = require("config")
local serialize = require("serialize")

local M = {}

local session_id = nil
local session_dir = nil
local modes_seen = {}
local ready = false

local function ensure_dir(path)
    local f = io.open(path .. "\\.write_test", "w")
    if f then
        f:close()
        pcall(os.remove, path .. "\\.write_test")
        return true
    end
    pcall(function() os.execute('mkdir "' .. path .. '" 2>nul') end)
    f = io.open(path .. "\\.write_test", "w")
    if f then
        f:close()
        pcall(os.remove, path .. "\\.write_test")
        return true
    end
    return false
end

local function new_session_id()
    return os.date("!%Y%m%dT%H%M%SZ")
end

function M.reset_session()
    session_id = new_session_id()
    session_dir = config.lab_root() .. "\\" .. config.EXPORTS_DIR .. "\\" .. session_id
    modes_seen = {}
    ready = ensure_dir(session_dir)
    if ready then
        print(string.format("[ApiExplorer] session %s -> %s\n", session_id, session_dir))
    else
        print("[ApiExplorer] ERROR: cannot create lab dir\n")
    end
    return session_id
end

function M.ensure_session()
    if session_id and ready then return session_id end
    return M.reset_session()
end

function M.session_dir()
    M.ensure_session()
    return session_dir
end

function M.session_id()
    return session_id
end

function M.note_mode(mode)
    if modes_seen[mode] then return end
    modes_seen[mode] = true
end

function M.modes_list()
    local list = {}
    for mode in pairs(modes_seen) do
        list[#list + 1] = mode
    end
    table.sort(list)
    return list
end

function M.write_json(filename, payload)
    M.ensure_session()
    if not ready or not session_dir then
        return false, "lab dir not ready"
    end
    local path = session_dir .. "\\" .. filename
    local f, err = io.open(path, "w")
    if not f then
        return false, tostring(err)
    end
    f:write(serialize.encode_pretty(payload))
    f:write("\n")
    f:flush()
    f:close()
    return true, path
end

function M.write_manifest(ctx, extra)
    M.ensure_session()
    local manifest = {
        schema = config.SCHEMA,
        build = config.BUILD,
        session_id = session_id,
        captured_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
        vehicle_class = ctx and ctx.vehicle_class or "?",
        route_hint = ctx and ctx.route_hint or nil,
        in_cab = ctx and ctx.in_cab or false,
        modes_run = M.modes_list(),
    }
    if extra then
        for k, v in pairs(extra) do manifest[k] = v end
    end
    return M.write_json("session.json", manifest)
end

function M.save_capture(mode, payload, ctx)
    M.note_mode(mode)
    payload.schema = config.SCHEMA
    payload.build = config.BUILD
    payload.mode = mode
    payload.session_id = session_id
    payload.captured_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
    if ctx then
        payload.vehicle_class = ctx.vehicle_class
        payload.in_cab = ctx.in_cab
    end
    local ok, path = M.write_json(mode .. ".json", payload)
    if ok then
        M.write_manifest(ctx, { last_mode = mode, last_file = mode .. ".json" })
    end
    return ok, path
end

return M
