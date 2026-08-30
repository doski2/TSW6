-- Modo reflect_shallow — props/funcs con tope de profundidad + árbol Simulation.
-- Nunca introspeccionar UObject con IsValid=false (crashea UE4SS en Class 323).
local config = require("config")
local util = require("util")

local M = {}

local FIELD_PROBE_SET = {
    "Pressure_BAR",
    "Pressure",
    "PressurePSI",
    "Pressure_PSI_G",
    "Mass",
    "Mass_kg",
    "TotalDistanceTravelled_M",
    "CurrentTrackAdhesion",
    "IsSlipping",
    "Slip",
    "SlipSpeed",
    "InputValue",
    "OutputValue",
    "Value",
}

local function unique_sorted(list)
    local seen = {}
    local out = {}
    for _, v in ipairs(list) do
        if v and not seen[v] then
            seen[v] = true
            out[#out + 1] = v
        end
    end
    table.sort(out)
    return out
end

local function object_path(obj)
    if obj == nil or not util.obj_valid(obj) then return nil end
    local ok, path = pcall(function() return util.lua_str(obj:GetFullName()) end)
    if ok and path and path ~= "" then return path end
    ok, path = pcall(function() return util.lua_str(obj:GetName()) end)
    if ok and path and path ~= "" then return path end
    return nil
end

local function class_name(obj)
    if obj == nil or not util.obj_valid(obj) then return nil end
    local ok, cls = pcall(function() return obj:GetClass() end)
    if not ok or cls == nil then return nil end
    return util.lua_str(cls:GetFName())
end

local function collect_class_members(class, payload, max_depth)
    if not class then return end
    local depth = 0
    while class and depth < max_depth do
        depth = depth + 1
        pcall(function()
            if type(class.ForEachFunction) == "function" then
                class:ForEachFunction(function(fn)
                    local n = util.lua_str(fn:GetFName())
                    if n then payload.functions[#payload.functions + 1] = n end
                end)
            end
        end)
        pcall(function()
            if type(class.ForEachProperty) == "function" then
                class:ForEachProperty(function(prop)
                    local n = util.lua_str(prop:GetFName())
                    if n then payload.properties[#payload.properties + 1] = n end
                end)
            end
        end)
        local super
        pcall(function()
            if type(class.GetSuperClass) == "function" then
                super = class:GetSuperClass()
            end
        end)
        if not super or super == class then break end
        class = super
    end
end

local function probe_field(obj, field)
    local row = { readable = false }
    if obj == nil or not util.obj_valid(obj) then
        row.error = "invalid or nil object"
        return row
    end
    local n = util.read_number_prop(obj, field)
    if n ~= nil then
        row.readable = true
        row.kind = "number"
        row.value = n
        return row
    end
    local ok, v = pcall(function() return obj[field] end)
    if not ok then
        row.error = tostring(v)
        return row
    end
    if v == nil then
        return row
    end
    row.raw_type = type(v)
    if type(v) == "boolean" then
        row.readable = true
        row.kind = "boolean"
        row.value = v
    elseif type(v) == "number" and util.is_valid_num(v) then
        row.readable = true
        row.kind = "number"
        row.value = v
    elseif type(v) == "string" then
        row.readable = true
        row.kind = "string"
        row.value = v
    end
    return row
end

local function sample_reflected_properties(obj, property_names, limit)
    local samples = {}
    if not util.obj_valid(obj) then return samples end
    local n = 0
    for _, name in ipairs(property_names) do
        if n >= limit then break end
        local row = probe_field(obj, name)
        if row.readable then
            samples[name] = row
            n = n + 1
        end
    end
    return samples
end

local function probe_field_set(obj, fields)
    local out = {}
    if not util.obj_valid(obj) then
        for _, field in ipairs(fields) do
            out[field] = { readable = false, error = "invalid or nil object" }
        end
        return out
    end
    for _, field in ipairs(fields) do
        out[field] = probe_field(obj, field)
    end
    return out
end

local function reflect_object(obj, label, opts)
    opts = opts or {}
    local payload = {
        label = label or "?",
        present = obj ~= nil,
        is_valid = util.obj_valid(obj),
        object_type = obj ~= nil and type(obj) or nil,
        ue_path = nil,
        class = nil,
        functions = {},
        properties = {},
        property_samples = {},
        field_probe = {},
        errors = {},
        introspection = "skipped",
    }

    if obj == nil then
        payload.errors[#payload.errors + 1] = "nil object"
        return payload
    end

    if not payload.is_valid then
        payload.errors[#payload.errors + 1] =
            "skipped introspection (invalid UObject — unsafe in UE4SS)"
        if opts.field_probe then
            payload.field_probe = probe_field_set(obj, opts.field_probe)
        end
        return payload
    end

    if opts.require_valid and not payload.is_valid then
        payload.errors[#payload.errors + 1] = "object not valid"
        return payload
    end

    payload.ue_path = object_path(obj)
    payload.class = class_name(obj)
    payload.introspection = "full"

    local class
    pcall(function() class = obj:GetClass() end)
    collect_class_members(class, payload, opts.max_depth or config.REFLECT_MAX_DEPTH)

    payload.functions = unique_sorted(payload.functions)
    payload.properties = unique_sorted(payload.properties)

    if opts.field_probe then
        payload.field_probe = probe_field_set(obj, opts.field_probe)
    end

    if #payload.properties > 0 then
        payload.property_samples = sample_reflected_properties(
            obj,
            payload.properties,
            opts.sample_limit or 24
        )
    end

    return payload
end

local function simulation_node_names()
    local names = {}
    local seen = {}
    for _, n in ipairs(config.FORMATION_BRAKE_CYLINDERS) do
        if not seen[n] then
            seen[n] = true
            names[#names + 1] = n
        end
    end
    for _, n in ipairs(config.FORMATION_MISC_NODES) do
        if not seen[n] then
            seen[n] = true
            names[#names + 1] = n
        end
    end
    return names
end

local function tally_reflect(entry)
    if type(entry) ~= "table" then
        return 0, 0
    end
    local props = #(entry.properties or {})
    local readable_fields = 0
    for _, probe in pairs(entry.field_probe or {}) do
        if type(probe) == "table" and probe.readable then
            readable_fields = readable_fields + 1
        end
    end
    for _, probe in pairs(entry.property_samples or {}) do
        if type(probe) == "table" and probe.readable then
            readable_fields = readable_fields + 1
        end
    end
    return props, readable_fields
end

local function safe_reflect_child(sim, node_name)
    local result
    local ok, err = pcall(function()
        local child
        pcall(function() child = sim[node_name] end)
        result = reflect_object(child, node_name, {
            require_valid = false,
            field_probe = FIELD_PROBE_SET,
        })
    end)
    if ok and result then
        return result
    end
    return {
        label = node_name,
        present = false,
        is_valid = false,
        introspection = "error",
        errors = { "pcall failed: " .. tostring(err) },
        functions = {},
        properties = {},
        property_samples = {},
        field_probe = {},
    }
end

function M.capture(obj, label)
    label = label or "drivable_actor"
    local payload = {
        status = "partial",
        message = "reflect shallow + Simulation tree (L0.6, safe invalid skip)",
        label = label,
        functions = {},
        properties = {},
        errors = {},
        targets = {},
    }

    local drivable = reflect_object(obj, label, { require_valid = true })
    payload.targets.drivable_actor = drivable
    payload.functions = drivable.functions
    payload.properties = drivable.properties
    for _, err in ipairs(drivable.errors) do
        payload.errors[#payload.errors + 1] = err
    end

    local sim
    pcall(function() sim = obj.Simulation end)
    local sim_reflect = reflect_object(sim, "simulation", {
        require_valid = false,
        field_probe = FIELD_PROBE_SET,
    })
    payload.targets.simulation = sim_reflect

    local children = {}
    if sim ~= nil then
        for _, node_name in ipairs(simulation_node_names()) do
            children[node_name] = safe_reflect_child(sim, node_name)
        end
    else
        payload.errors[#payload.errors + 1] = "no Simulation on drivable actor"
    end
    payload.targets.simulation_children = children

    local sim_props, sim_fields = tally_reflect(sim_reflect)
    for _, entry in pairs(children) do
        local p, f = tally_reflect(entry)
        sim_props = sim_props + p
        sim_fields = sim_fields + f
    end

    if sim_props > 0 or sim_fields > 0 then
        payload.status = "ok"
    elseif #drivable.properties > 0 or #drivable.functions > 0 then
        payload.status = "ok"
    elseif sim_reflect.present then
        payload.status = "partial"
    end

    payload.summary = {
        simulation_present = sim ~= nil,
        simulation_class = sim_reflect.class,
        simulation_is_valid = sim_reflect.is_valid,
        simulation_child_count = 0,
        simulation_property_count = sim_props,
        simulation_readable_fields = sim_fields,
        invalid_but_present = {},
    }
    for name, entry in pairs(children) do
        if entry.present then
            payload.summary.simulation_child_count = payload.summary.simulation_child_count + 1
        end
        if entry.present and not entry.is_valid then
            payload.summary.invalid_but_present[#payload.summary.invalid_but_present + 1] = name
        end
    end

    return payload
end

return M
