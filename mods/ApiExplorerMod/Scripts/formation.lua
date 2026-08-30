-- Modo formation — Simulation / física (L0.6).
local config = require("config")
local util = require("util")

local M = {}

local PRESSURE_FIELDS = { "Pressure_BAR", "Pressure", "PressurePSI", "Pressure_PSI_G" }
local MASS_FIELDS = { "Mass", "Mass_kg" }
local ODO_FIELDS = { "TotalDistanceTravelled_M" }
local ADHESION_FIELDS = { "CurrentTrackAdhesion", "IsSlipping", "Slip", "SlipSpeed" }

local ALL_FIELD_GROUPS = { PRESSURE_FIELDS, MASS_FIELDS, ODO_FIELDS, ADHESION_FIELDS }

local GRAPH_ACCESSORS = {
    { key = "SimulationGraphInstance", kind = "property", name = "SimulationGraphInstance" },
    { key = "SimulationGraph", kind = "property", name = "SimulationGraph" },
    { key = "GetSimulation", kind = "method", name = "GetSimulation" },
}

local SIMULATION_NODE_NAMES = nil

local function simulation_node_names()
    if SIMULATION_NODE_NAMES then
        return SIMULATION_NODE_NAMES
    end
    local names = {}
    local seen = {}
    for _, n in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        if not seen[n] then seen[n] = true; names[#names + 1] = n end
    end
    for _, n in ipairs(config.FORMATION_MISC_NODES) do
        if not seen[n] then seen[n] = true; names[#names + 1] = n end
    end
    SIMULATION_NODE_NAMES = names
    return names
end

local function class_name_from(obj)
    if not util.obj_valid(obj) then return nil end
    local ok, cls = pcall(function() return obj:GetClass() end)
    if not ok or cls == nil then return nil end
    return util.lua_str(cls:GetFName())
end

local function try_sim_child(parent, name)
    if parent == nil or name == nil then return nil end
    local ok, child = pcall(function() return parent[name] end)
    if ok and child ~= nil then return child end
    return nil
end

local function read_fields(node, field_names)
    local out = {}
    for _, field in ipairs(field_names) do
        local n = util.read_number_prop(node, field)
        if n ~= nil then
            out[field] = n
        else
            local ok, v = pcall(function() return node[field] end)
            if ok and type(v) == "boolean" then
                out[field] = v
            end
        end
    end
    if next(out) == nil then return nil end
    return out
end

local function sim_class_name(sim)
    return class_name_from(sim)
end

local function add_http_guess(payload, node_name, fields)
    for field, value in pairs(fields) do
        if type(value) == "number" or type(value) == "boolean" then
            payload.http_guess[config.http_sim_path(node_name, field)] = value
            payload.http_guess[config.http_drivable_sim_path(node_name, field)] = value
        end
    end
end

local function capture_node(payload, sim, node_name, field_groups)
    local node = try_sim_child(sim, node_name)
    if not node then return false end
    local merged = {}
    for _, names in ipairs(field_groups) do
        local part = read_fields(node, names)
        if part then
            for k, v in pairs(part) do merged[k] = v end
        end
    end
    if next(merged) == nil then return false end
    payload.lua.simulation[node_name] = merged
    add_http_guess(payload, node_name, merged)
    return true
end

local function collect_pairs_keys(sim, limit)
    local keys = {}
    pcall(function()
        for k, _ in pairs(sim) do
            if type(k) == "string" then
                keys[#keys + 1] = k
            end
        end
    end)
    table.sort(keys)
    if limit and #keys > limit then
        local trimmed = {}
        for i = 1, limit do trimmed[i] = keys[i] end
        return trimmed, #keys
    end
    return keys, #keys
end

local function scan_pairs_children(payload, sim)
    local found = 0
    pcall(function()
        for k, v in pairs(sim) do
            if type(k) ~= "string" or string.sub(k, 1, 1) == "_" then
                -- skip
            else
                local merged = read_fields(v, PRESSURE_FIELDS)
                if merged == nil and (type(v) == "userdata" or type(v) == "table") then
                    merged = read_fields(v, MASS_FIELDS)
                end
                if merged == nil then
                    merged = read_fields(v, ODO_FIELDS)
                end
                if merged == nil then
                    merged = read_fields(v, ADHESION_FIELDS)
                end
                if merged and next(merged) then
                    payload.lua.simulation[k] = merged
                    add_http_guess(payload, k, merged)
                    found = found + 1
                end
            end
        end
    end)
    return found
end

local function scan_class_properties(payload, sim)
    local found = 0
    local class
    pcall(function() class = sim:GetClass() end)
    if not class then return 0 end
    pcall(function()
        if type(class.ForEachProperty) ~= "function" then return end
        class:ForEachProperty(function(prop)
            local n = util.lua_str(prop:GetFName())
            if not n then return end
            local child = try_sim_child(sim, n)
            if not child then return end
            local merged = read_fields(child, PRESSURE_FIELDS)
            if merged == nil then
                merged = read_fields(child, MASS_FIELDS)
            end
            if merged == nil then
                merged = read_fields(child, ODO_FIELDS)
            end
            if merged and next(merged) then
                payload.lua.simulation[n] = merged
                add_http_guess(payload, n, merged)
                found = found + 1
            end
        end)
    end)
    return found
end

local function pick_brake_cyl_bar(payload)
    for _, name in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        local node = payload.lua.simulation[name]
        if node then
            if node.Pressure_BAR then
                payload.lua.summary.brake_cyl_bar = node.Pressure_BAR
                return
            end
            if node.Pressure then
                payload.lua.summary.brake_cyl_bar = node.Pressure
                return
            end
        end
    end
end

local function probe_lua_node(sim, node_name, field_names)
    local row = {
        index_ok = false,
        child_valid = false,
        fields = {},
    }
    local child
    local ok, err = pcall(function() child = sim[node_name] end)
    if not ok then
        row.index_error = tostring(err)
        return row
    end
    if child == nil then
        return row
    end
    row.index_ok = true
    row.child_type = type(child)
    row.child_valid = util.obj_valid(child)
    for _, field in ipairs(field_names) do
        local n = util.read_number_prop(child, field)
        if n ~= nil then
            row.fields[field] = n
        else
            local fok, v = pcall(function() return child[field] end)
            if fok and type(v) == "boolean" then
                row.fields[field] = v
            end
        end
    end
    return row
end

local function emit_http_probes(payload)
    local probes = {}
    local function add(node, field)
        probes[#probes + 1] = {
            path = config.http_sim_path(node, field),
            scope = "formation",
            node = node,
            field = field,
        }
        probes[#probes + 1] = {
            path = config.http_drivable_sim_path(node, field),
            scope = "drivable",
            node = node,
            field = field,
        }
    end
    for _, name in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        for _, field in ipairs(PRESSURE_FIELDS) do
            add(name, field)
        end
    end
    for _, name in ipairs(config.FORMATION_MISC_NODES) do
        for _, group in ipairs(ALL_FIELD_GROUPS) do
            for _, field in ipairs(group) do
                add(name, field)
            end
        end
    end
    payload.http_probe = probes
end

local function run_lua_probes(payload, sim)
    local probes = {}
    for _, name in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        probes[name] = probe_lua_node(sim, name, PRESSURE_FIELDS)
    end
    for _, name in ipairs(config.FORMATION_MISC_NODES) do
        local fields = {}
        for _, group in ipairs(ALL_FIELD_GROUPS) do
            for _, field in ipairs(group) do
                fields[#fields + 1] = field
            end
        end
        probes[name] = probe_lua_node(sim, name, fields)
    end
    payload.lua.lua_probe = probes
end

local function describe_ref(obj)
    if obj == nil then
        return { present = false }
    end
    local row = {
        present = true,
        object_type = type(obj),
        is_valid = util.obj_valid(obj),
    }
    if row.is_valid then
        row.class = class_name_from(obj)
    end
    return row
end

local function try_accessor(sim, spec)
    local meta = { via = spec.key }
    local obj
    if spec.kind == "property" then
        local ok, err_or_val = pcall(function() return sim[spec.name] end)
        if not ok then
            meta.error = tostring(err_or_val)
            meta.ref = { present = false }
            return meta, nil
        end
        obj = err_or_val
    else
        local ok, err_or_val = pcall(function() return sim[spec.name](sim) end)
        if not ok then
            ok, err_or_val = pcall(function() return sim:GetSimulation() end)
        end
        if not ok then
            meta.error = tostring(err_or_val)
            meta.ref = { present = false }
            return meta, nil
        end
        obj = err_or_val
    end
    meta.ref = describe_ref(obj)
    return meta, obj
end

local function probe_nodes_on_parent(parent, parent_key, field_names)
    local rows = {}
    if parent == nil then
        return rows
    end
    for _, node_name in ipairs(simulation_node_names()) do
        local row = probe_lua_node(parent, node_name, field_names)
        row.parent = parent_key
        row.node = node_name
        rows[#rows + 1] = row
    end
    return rows
end

local function capture_from_parent(payload, parent, parent_key, field_groups)
    if parent == nil or not util.obj_valid(parent) then
        return 0
    end
    local found = 0
    for _, node_name in ipairs(simulation_node_names()) do
        if payload.lua.simulation[node_name] ~= nil then
            -- already captured via another parent
        else
            local node = try_sim_child(parent, node_name)
            if node then
                local merged = {}
                for _, names in ipairs(field_groups) do
                    local part = read_fields(node, names)
                    if part then
                        for k, v in pairs(part) do merged[k] = v end
                    end
                end
                if next(merged) ~= nil then
                    payload.lua.simulation[node_name] = merged
                    add_http_guess(payload, node_name, merged)
                    payload.lua.summary.graph_capture_parent = parent_key
                    found = found + 1
                end
            end
        end
    end
    return found
end

local function run_graph_probe(payload, sim)
    local probe = {
        sim_valid = util.obj_valid(sim),
        accessors = {},
        node_attempts = {},
    }
    if not probe.sim_valid then
        probe.error = "Simulation component not valid — graph probe skipped"
        payload.lua.graph_probe = probe
        return 0
    end

    local found = 0
    local pressure_fields = {}
    for _, group in ipairs(ALL_FIELD_GROUPS) do
        for _, field in ipairs(group) do
            pressure_fields[#pressure_fields + 1] = field
        end
    end

    for _, spec in ipairs(GRAPH_ACCESSORS) do
        local meta, obj = try_accessor(sim, spec)
        probe.accessors[spec.key] = meta
        if obj ~= nil then
            local attempts = probe_nodes_on_parent(obj, spec.key, pressure_fields)
            for _, row in ipairs(attempts) do
                probe.node_attempts[#probe.node_attempts + 1] = row
            end
            if util.obj_valid(obj) then
                found = found + capture_from_parent(payload, obj, spec.key, ALL_FIELD_GROUPS)
            end
        end
    end

    payload.lua.graph_probe = probe
    return found
end

function M.capture(actor)
    local payload = {
        status = "partial",
        message = "L0.6c — Simulation physics + graph probe",
        lua = {
            simulation = {},
            summary = {},
        },
        http_guess = {},
        errors = {},
        notes = {},
    }

    if not util.obj_valid(actor) then
        payload.errors[#payload.errors + 1] = "actor invalid"
        return payload
    end

    local ok, sim = pcall(function() return actor.Simulation end)
    if not ok or sim == nil then
        payload.errors[#payload.errors + 1] = "no Simulation on drivable actor"
        return payload
    end

    payload.lua.summary.simulation_class = sim_class_name(sim)
    emit_http_probes(payload)
    run_lua_probes(payload, sim)

    run_graph_probe(payload, sim)

    for _, name in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        capture_node(payload, sim, name, { PRESSURE_FIELDS })
    end
    for _, name in ipairs(config.FORMATION_MISC_NODES) do
        capture_node(payload, sim, name, ALL_FIELD_GROUPS)
    end

    local axle = try_sim_child(sim, "Axle_1_1")
    if axle then
        local odo = read_fields(axle, ODO_FIELDS)
        if odo and odo.TotalDistanceTravelled_M then
            payload.lua.summary.odo_m = odo.TotalDistanceTravelled_M
        end
    end

    local node_count = 0
    for _ in pairs(payload.lua.simulation) do
        node_count = node_count + 1
    end

    if node_count == 0 then
        node_count = node_count + scan_class_properties(payload, sim)
    end
    if node_count == 0 then
        node_count = node_count + scan_pairs_children(payload, sim)
    end

    pick_brake_cyl_bar(payload)

    if node_count == 0 then
        local sample, total = collect_pairs_keys(sim, 40)
        payload.lua.diagnostic = {
            sim_pairs_key_count = total,
            sim_pairs_key_sample = sample,
        }
        payload.notes[#payload.notes + 1] =
            "Revisar lua.graph_probe.accessors y node_attempts (L0.6c SimulationGraph)"
        payload.notes[#payload.notes + 1] =
            "Lua no leyó nodos Simulation; ejecutar api_correlator.py --formation con -HTTPAPI"
        payload.notes[#payload.notes + 1] =
            "Comparar lua_probe (index_ok/fields) vs formation_http.json para acotar acceso Lua"
        payload.errors[#payload.errors + 1] =
            "no Simulation nodes readable in Lua (HTTP path still valid)"
    else
        payload.status = "ok"
    end

    return payload
end

return M
