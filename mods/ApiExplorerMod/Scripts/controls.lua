-- Modo controls — inventario palancas para paquete G-B (L0.3).
local config = require("config")
local util = require("util")

local M = {}

local MAX_NOTCHES = 16

local function try_child(parent, name)
    if not parent then return nil end
    local ok, child = pcall(function() return parent[name] end)
    if ok and util.obj_valid(child) then return child end
    return nil
end

local function object_label(obj)
    if not util.obj_valid(obj) then return "?" end
    local cls = "?"
    pcall(function()
        cls = util.lua_str(obj:GetClass():GetFName()) or "?"
    end)
    local ok, path = pcall(function() return util.lua_str(obj:GetFullName()) end)
    if ok and path and path ~= "" then return path, cls end
    ok, path = pcall(function() return util.lua_str(obj:GetName()) end)
    if ok and path and path ~= "" then return path, cls end
    return tostring(obj), cls
end

local function container_len(arr)
    if arr == nil then return nil end
    if type(arr) == "table" then
        local n = #arr
        if type(n) == "number" and n > 0 and n <= MAX_NOTCHES then return n end
        return nil
    end
    local n
    pcall(function() n = arr:GetArrayNum() end)
    if type(n) == "number" and n > 0 and n <= MAX_NOTCHES then return n end
    pcall(function() n = arr:Num() end)
    if type(n) == "number" and n > 0 and n <= MAX_NOTCHES then return n end
    return nil
end

local function read_index(arr, i)
    local v
    local ok = pcall(function() v = arr:Get(i) end)
    if ok and v ~= nil then return v end
    ok = pcall(function() v = arr[i] end)
    if ok then return v end
    ok, v = pcall(function() return arr:Get(i) end)
    return ok and v or nil
end

local function read_number_prop(obj, prop)
    local ok, v = pcall(function() return obj[prop] end)
    if ok and util.is_valid_num(v) then return v end
    return nil
end

local function read_control_scalar(ctrl)
    if not util.obj_valid(ctrl) then return nil, nil end
    local ok, v = pcall(function() return ctrl:GetCurrentInputValue() end)
    if ok and util.is_valid_num(v) then return "scalar", v end
    if ok and type(v) == "table" then
        local n = util.out_val(v, "ReturnValue")
        if util.is_valid_num(n) then return "scalar", n end
    end
    for _, prop in ipairs({ "InputValue", "OutputValue", "Value", "CurrentInputValue" }) do
        local n = read_number_prop(ctrl, prop)
        if n ~= nil then return "scalar", n end
    end
    return nil, nil
end

local function read_notch_entries(ctrl)
    local entries = {}
    local ok_n, nnotch = pcall(function() return ctrl.NumberOfNotches end)
    local arr_ok, arr = pcall(function() return ctrl.Notches end)
    if not arr_ok or arr == nil then
        return entries, nnotch
    end
    local len = container_len(arr) or (type(nnotch) == "number" and math.min(nnotch + 1, MAX_NOTCHES))
    if not len or len < 1 then return entries, nnotch end
    for i = 0, len - 1 do
        local el = read_index(arr, i)
        if el ~= nil then
            local row = { index = i }
            for _, key in ipairs({
                "InputValue", "OutputValue", "MinimumInputValue", "MaximumInputValue", "NotchID",
            }) do
                local n = read_number_prop(el, key)
                if n ~= nil then row[key] = n end
            end
            if next(row) ~= nil and row.index ~= nil then
                entries[#entries + 1] = row
            end
        end
    end
    return entries, nnotch
end

local function snapshot_lever(scope, name, ctrl)
    if not util.obj_valid(ctrl) then return nil end
    local path, cls = object_label(ctrl)
    local kind, val = read_control_scalar(ctrl)
    local notches, nnotch = read_notch_entries(ctrl)
    local snap = {
        name = name,
        scope = scope,
        ue_path = path,
        class = cls,
        number_of_notches = nnotch,
    }
    if kind and val ~= nil then
        snap.read_kind = kind
        snap.read_value = val
    end
    for _, prop in ipairs({
        "CurrentInputValue", "CurrentOutputValue", "TargetInputValue",
        "CurrentNotchID", "bInputEnabled",
    }) do
        local n = read_number_prop(ctrl, prop)
        if n ~= nil then snap[prop] = n end
    end
    if #notches > 0 then snap.notches = notches end
    return snap
end

local function collect_named_levers(parent, scope, names, seen, out)
    for _, name in ipairs(names) do
        if not seen[name] then
            local ctrl = try_child(parent, name)
            if ctrl then
                seen[name] = true
                local snap = snapshot_lever(scope, name, ctrl)
                if snap then out[#out + 1] = snap end
            end
        end
    end
end

local function collect_pair_levers(parent, scope, seen, out)
    pcall(function()
        for k, v in pairs(parent) do
            if type(k) == "string" and util.obj_valid(v) then
                local cls = "?"
                pcall(function() cls = util.lua_str(v:GetClass():GetFName()) or "?" end)
                if string.find(cls, "Lever", 1, true) and not seen["pairs:" .. k] then
                    seen["pairs:" .. k] = true
                    local snap = snapshot_lever(scope .. ".pairs", k, v)
                    if snap then out[#out + 1] = snap end
                end
            end
        end
    end)
end

local function collect_findall_levers(actor, seen, out)
    for _, typename in ipairs(config.LEVER_COMPONENT_TYPES) do
        local objs = FindAllOf(typename)
        if objs then
            for _, obj in pairs(objs) do
                if util.obj_valid(obj) then
                    local ok_outer, outer = pcall(function() return obj:GetOuter() end)
                    local belongs = false
                    for _ = 1, 12 do
                        if not ok_outer or not outer then break end
                        if outer == actor then belongs = true break end
                        ok_outer, outer = pcall(function() return outer:GetOuter() end)
                    end
                    if belongs then
                        local _, cls = object_label(obj)
                        local key = "findall:" .. cls .. ":" .. tostring(obj)
                        if not seen[key] then
                            seen[key] = true
                            local snap = snapshot_lever("actor.findall", cls, obj)
                            if snap then
                                snap.name = snap.name or cls
                                out[#out + 1] = snap
                            end
                        end
                    end
                end
            end
        end
    end
end

local function list_driver_input_children(parent, scope)
    local di = try_child(parent, "DriverInput")
    if not di then return nil end
    local names = {}
    pcall(function()
        for k, v in pairs(di) do
            if type(k) == "string" then
                if util.obj_valid(v) then
                    names[#names + 1] = k
                elseif type(v) == "number" or type(v) == "boolean" then
                    names[#names + 1] = k .. "=" .. tostring(v)
                end
            end
        end
    end)
    table.sort(names)
    return { scope = scope, children = names }
end

local function infer_layout_hint(levers)
    local names = {}
    for _, lev in ipairs(levers) do
        names[lev.name] = true
        local low = string.lower(lev.name or "")
        if string.find(low, "powerbrake", 1, true) or string.find(low, "combined", 1, true) then
            return "combined"
        end
    end
    local freight = 0
    if names.TrainBrake or names.AutomaticBrake then freight = freight + 1 end
    if names.LocomotiveBrake or names.IndependentBrake then freight = freight + 1 end
    if names.DynamicBrake or names.RegenBrakes then freight = freight + 1 end
    if freight >= 2 then return "freight_na" end
    if names.PowerBrakeHandle or names.ThrottleAndBrake or names.CombinedHandle then
        return "combined"
    end
    return "unknown"
end

local function suggest_ipc_aliases(levers)
    local aliases = {}
    local by_name = {}
    for _, lev in ipairs(levers) do
        if lev.name and lev.scope and string.find(lev.scope, "actor", 1, true) then
            by_name[lev.name] = lev
        end
    end
    for ipc_name, candidates in pairs(config.CONTROL_ALIASES) do
        for _, cand in ipairs(candidates) do
            if by_name[cand] then
                aliases[ipc_name] = cand
                break
            end
        end
    end
    return aliases
end

local function http_guess_for_lever(snap)
    local guesses = {}
    if snap.read_value ~= nil then
        guesses[config.http_driver_input(snap.name .. ".InputValue")] = snap.read_value
        guesses[config.http_formation_component(snap.name, "InputValue")] = snap.read_value
    end
    if snap.CurrentInputValue ~= nil then
        guesses[config.http_formation_component(snap.name, "CurrentInputValue")] = snap.CurrentInputValue
    end
    return guesses
end

function M.capture(actor, controller)
    print("[ApiExplorer] controls scan start\n")
    local payload = {
        status = "ok",
        layout_hint = "unknown",
        lua = {
            levers = {},
            driver_input = {},
            simulation = {},
        },
        http_guess = {},
        ipc_aliases = {},
        errors = {},
    }
    if not util.obj_valid(actor) then
        payload.status = "error"
        payload.errors[#payload.errors + 1] = "actor invalid"
        return payload
    end

    local path = object_label(actor)
    payload.lua.actor_ue_path = path

    local levers = {}
    local seen = {}

    collect_named_levers(actor, "actor", config.CONTROL_PROBE_NAMES, seen, levers)
    collect_pair_levers(actor, "actor", seen, levers)

    local sim = try_child(actor, "Simulation")
    if sim then
        payload.lua.simulation.class = object_label(sim)
        for _, node_name in ipairs(config.SIM_BRAKE_NODES) do
            local node = try_child(sim, node_name)
            if node then
                local snap = snapshot_lever("actor.Simulation", node_name, node)
                if snap then levers[#levers + 1] = snap end
            end
        end
    end

    if controller and util.obj_valid(controller) then
        local di = list_driver_input_children(controller, "controller")
        if di then payload.lua.driver_input[#payload.lua.driver_input + 1] = di end
        collect_named_levers(controller, "controller", config.CONTROL_PROBE_NAMES, seen, levers)
    end

    local di_actor = list_driver_input_children(actor, "actor")
    if di_actor then payload.lua.driver_input[#payload.lua.driver_input + 1] = di_actor end

    if config.USE_FINDALL_CONTROLS then
        collect_findall_levers(actor, seen, levers)
    end

    payload.lua.levers = levers
    payload.layout_hint = infer_layout_hint(levers)
    payload.ipc_aliases = suggest_ipc_aliases(levers)

    for _, snap in ipairs(levers) do
        local g = http_guess_for_lever(snap)
        for k, v in pairs(g) do payload.http_guess[k] = v end
    end

    if #levers == 0 then
        payload.status = "empty"
        payload.errors[#payload.errors + 1] = "no levers found on drivable actor"
    end

    print(string.format("[ApiExplorer] controls scan done levers=%d hint=%s\n",
        #levers, payload.layout_hint))
    return payload
end

return M
