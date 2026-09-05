-- Modo formation — Simulation / física (L0.6).
local config = require("config")
local util = require("util")

local M = {}

local PRESSURE_FIELDS = { "Pressure_BAR", "Pressure", "PressurePSI", "Pressure_PSI_G" }
local MASS_FIELDS = { "Mass", "Mass_kg" }
local ODO_FIELDS = { "TotalDistanceTravelled_M" }
local ADHESION_FIELDS = { "CurrentTrackAdhesion", "IsSlipping", "Slip", "SlipSpeed" }

local ALL_FIELD_GROUPS = { PRESSURE_FIELDS, MASS_FIELDS, ODO_FIELDS, ADHESION_FIELDS }

local TRACTION_VIA_ORDER = { "Axle", "Wheel", "direct" }

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

local function add_traction_http_guess(payload, axle_name, via, fields)
    for field, value in pairs(fields) do
        if type(value) ~= "number" then
            -- skip
        elseif via == "direct" then
            payload.http_guess[config.http_sim_path(axle_name, field)] = value
            payload.http_guess[config.http_drivable_sim_path(axle_name, field)] = value
        else
            payload.http_guess[config.http_sim_nested_path(axle_name, via, field)] = value
            payload.http_guess[config.http_drivable_sim_nested_path(axle_name, via, field)] = value
        end
    end
end

local function pick_best_tractive(fields_by_via)
    for _, via in ipairs(TRACTION_VIA_ORDER) do
        local bucket = fields_by_via[via]
        if bucket and bucket.NetTractiveEffort ~= nil and bucket.NetTractiveEffort ~= 0 then
            return { via = via, field = "NetTractiveEffort", value = bucket.NetTractiveEffort }
        end
    end
    for _, via in ipairs(TRACTION_VIA_ORDER) do
        local bucket = fields_by_via[via]
        if bucket and bucket.NetTorque_NM ~= nil and bucket.NetTorque_NM ~= 0 then
            return { via = via, field = "NetTorque_NM", value = bucket.NetTorque_NM }
        end
    end
    for _, via in ipairs(TRACTION_VIA_ORDER) do
        local bucket = fields_by_via[via]
        if bucket and bucket.Power_KW ~= nil and bucket.Power_KW ~= 0 then
            return { via = via, field = "Power_KW", value = bucket.Power_KW }
        end
    end
    return nil
end

local function probe_traction_on_axle(sim, axle_name)
    local result = {
        index_ok = false,
        child_valid = false,
        fields_by_via = {},
        attempts = {},
    }
    local axle_node
    local ok, err = pcall(function() axle_node = sim[axle_name] end)
    if not ok then
        result.index_error = tostring(err)
        return result
    end
    if axle_node == nil then
        return result
    end
    result.index_ok = true
    result.child_type = type(axle_node)
    result.child_valid = util.obj_valid(axle_node)

    local direct = read_fields(axle_node, config.FORMATION_TRACTION_FIELDS)
    if direct then
        result.fields_by_via.direct = direct
        for field, value in pairs(direct) do
            result.attempts[#result.attempts + 1] = { via = "direct", field = field, value = value }
        end
    end

    for _, sub in ipairs(config.FORMATION_TRACTION_SUBNODES) do
        local subnode = try_sim_child(axle_node, sub)
        if subnode then
            local fields = read_fields(subnode, config.FORMATION_TRACTION_FIELDS)
            if fields then
                result.fields_by_via[sub] = fields
                for field, value in pairs(fields) do
                    result.attempts[#result.attempts + 1] = { via = sub, field = field, value = value }
                end
            end
        end
    end

    result.best = pick_best_tractive(result.fields_by_via)
    return result
end

local function emit_traction_http_probes(payload)
    if type(payload.http_probe) ~= "table" then
        payload.http_probe = {}
    end
    local function add(axle_name, subnode, field)
        local path
        local scope_path
        if subnode == "direct" then
            path = config.http_sim_path(axle_name, field)
            scope_path = config.http_drivable_sim_path(axle_name, field)
        else
            path = config.http_sim_nested_path(axle_name, subnode, field)
            scope_path = config.http_drivable_sim_nested_path(axle_name, subnode, field)
        end
        payload.http_probe[#payload.http_probe + 1] = {
            path = path,
            scope = "formation",
            node = axle_name,
            subnode = subnode,
            field = field,
        }
        payload.http_probe[#payload.http_probe + 1] = {
            path = scope_path,
            scope = "drivable",
            node = axle_name,
            subnode = subnode,
            field = field,
        }
    end
    for _, axle_name in ipairs(config.FORMATION_AXLE_NODES) do
        for _, field in ipairs(config.FORMATION_TRACTION_FIELDS) do
            add(axle_name, "direct", field)
        end
        for _, subnode in ipairs(config.FORMATION_TRACTION_SUBNODES) do
            for _, field in ipairs(config.FORMATION_TRACTION_FIELDS) do
                add(axle_name, subnode, field)
            end
        end
    end
end

local function run_traction_probes(payload, sim)
    local probes = {}
    local found = 0
    for _, axle_name in ipairs(config.FORMATION_AXLE_NODES) do
        local row = probe_traction_on_axle(sim, axle_name)
        probes[axle_name] = row
        for via, fields in pairs(row.fields_by_via) do
            if next(fields) then
                add_traction_http_guess(payload, axle_name, via, fields)
                found = found + 1
            end
        end
        if row.best then
            payload.lua.summary.tractive_effort_n = row.best.value
            payload.lua.summary.tractive_effort_via = axle_name .. "/" .. row.best.via .. "." .. row.best.field
        end
    end
    payload.lua.traction_probe = probes
    return found
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
        message = "L0.6d — Simulation physics + traction probe (Axle/Wheel)",
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
    emit_traction_http_probes(payload)
    run_lua_probes(payload, sim)

    run_graph_probe(payload, sim)
    local traction_found = run_traction_probes(payload, sim)

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

    local has_readable = traction_found > 0
    for _ in pairs(payload.lua.simulation) do
        has_readable = true
        break
    end

    if not has_readable then
        local node_count = scan_class_properties(payload, sim)
        if node_count == 0 then
            node_count = scan_pairs_children(payload, sim)
        end
        if node_count > 0 then
            has_readable = true
        end
    end

    pick_brake_cyl_bar(payload)

    if not has_readable then
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
            "Comparar lua_probe / traction_probe vs formation_http.json para acotar acceso Lua"
        if traction_found == 0 then
            payload.notes[#payload.notes + 1] =
                "Capturar con potencia aplicada (no coasting) — HUD_GetTractiveEffort sigue en 0 en 323"
        end
        payload.errors[#payload.errors + 1] =
            "no Simulation nodes readable in Lua (HTTP path still valid)"
    else
        payload.status = "ok"
    end

    return payload
end

return M
