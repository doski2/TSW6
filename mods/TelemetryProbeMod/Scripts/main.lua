-- TelemetryProbeMod — telemetría + mandos IPC
-- Python escribe SendCommand.txt · Lua lee mandos y escribe GetData.txt + SendCommandAck.txt
-- F7 on/off probe · F8 volcar línea al log · F9 dump controles (no en el tick)
-- Nombres de palanca: DRIVERINPUT_API.md / perfiles loco, no FindAllOf cada frame.
local PROBE_BUILD = "20260828q"
local PROBE_AUTO_START = true  -- probe ON al cargar escenario; F7 apaga/enciende

local UEHelpers = require("UEHelpers")

print("[TelemetryProbe] Mod loaded " .. PROBE_BUILD .. "\n")

local HOOK_PATH = "/Game/Core/Player/TS2DefaultPlayerController.TS2DefaultPlayerController_C:ReceiveTick"
local WRITE_INTERVAL_S = 0.05  -- ~20 Hz
local LOG_INTERVAL_S = 2.0
local IPC_POLL_INTERVAL_S = 0.05  -- ~20 Hz (no leer disco cada frame)
local COMMANDS_ARMED_TTL_S = 0.25
-- SetCurrentNotchIndex / SetInputValue() crashean UE4SS. SetCurrentInputValue (Liah) es fallback.
local SAFE_LEVER_WRITE = true
-- false = Lua escribe InputValue en UE (canal IPC principal). true = ACK :fail: y HTTP en Python.
local IPC_DELEGATE_HTTP = false

local probeEnabled = false  -- F7 ON: telemetría + IPC (autopilot)
local bridgeReady = false
local bridgeDirLogged = false
local seq = 0
local lastWriteClock = 0
local lastLogClock = 0
local perfWrites = 0
local perfWorkS = 0
local hooked = false
local hookPre, hookPost
local debugDumped = false
local limitsLogged = false
local driver_input_dumped = false
local pbh_ufn_dumped = false
local pbh_setter_names = nil  -- UFunctions del lever aptas para ProcessEvent (una vez)

-- Planning: distancias = DriverAid. No hold Lua: odo/actor no se mueven
-- (GetActorLocation/odo muertos) y Python C.3a restaba HUD×dt (probe_raw fijo).

local SEND_COMMAND_FILE = "SendCommand.txt"
local APPLY_FLAG_FILE = "TSW6ApplyCommands.flag"
local SEND_ACK_FILE = "SendCommandAck.txt"
local control_cache = {}
local control_miss = {}
local last_applied = {}
local last_cmd_id = 0
local last_ack_ok = false
local commands_armed_cache = false
local commands_armed_checked_at = 0
local read_hud_lever_notch = nil  -- definido tras helpers HUD
local control_path_logged = {}
local pbh_write_strategy = nil
local pbh_axis_by_notch = nil
local pbh_map_dumped = false

local ALLOWED_CONTROLS = {
    PowerBrakeHandle = true,
    AutomaticBrake = true,
    IndependentBrake = true,
    DynamicBrake = true,
    TrainBrake = true,
    LocomotiveBrake = true,
}

local CONTROL_ALIASES = {
    -- Class 323 UK: actor.PowerBrakeHandle (IrregularLeverComponent), eje InputValue -1..1.
    PowerBrakeHandle = {
        "PowerBrakeHandle",
        "ThrottleAndBrake",
        "CombinedHandle",
        "PowerBrake",
    },
}

local DRIVER_INPUT_PROBE_NAMES = {
    "ThrottleAndBrake",
    "PowerBrakeHandle",
    "CombinedHandle",
    "PowerBrake",
    "AutomaticBrake",
    "TrainBrake",
    "IndependentBrake",
    "DynamicBrake",
    "LocomotiveBrake",
    "Reverser",
    "EmergencyBrake_L",
    "EmergencyBrake_C",
    "ParkingBrake",
    "MasterKey",
    "RegenBrakes",
}

local SIM_BRAKE_NODES = {
    "BrakeInput",
    "EBrakeInput",
    "ThrottleAndBrake",
    "PowerBrakeHandle",
}

local LEVER_COMPONENT_TYPES = {
    "IrregularLeverComponent",
    "AnalogLeverComponent",
    "DigitalLeverComponent",
    "BaseLeverComponent",
}

local SENTINEL = 3.4028235e38

-- ── Bridge paths ─────────────────────────────────────────────────────────────

local function bridge_dir()
    local temp = os.getenv("TEMP") or os.getenv("TMP") or "."
    return temp .. "\\TSW6Bridge"
end

local function bridge_path()
    return bridge_dir() .. "\\GetData.txt"
end

local function send_command_path()
    return bridge_dir() .. "\\" .. SEND_COMMAND_FILE
end

local function apply_flag_path()
    return bridge_dir() .. "\\" .. APPLY_FLAG_FILE
end

local function send_ack_path()
    return bridge_dir() .. "\\" .. SEND_ACK_FILE
end

local function log_bridge_dir_once(dir)
    if bridgeDirLogged then return end
    bridgeDirLogged = true
    print(string.format("[TelemetryProbe] Bridge dir: %s\n", dir))
end

local function probe_bridge_writable(dir)
    local f = io.open(dir .. "\\GetData.txt", "a")
    if f then
        f:close()
        return true
    end
    return false
end

local function ensure_bridge_dir()
    if bridgeReady then
        return true
    end
    local dir = bridge_dir()
    if probe_bridge_writable(dir) then
        log_bridge_dir_once(dir)
        bridgeReady = true
        return true
    end
    pcall(function()
        os.execute('mkdir "' .. dir .. '" 2>nul')
    end)
    if probe_bridge_writable(dir) then
        log_bridge_dir_once(dir)
        bridgeReady = true
        return true
    end
    return false
end

-- ── IPC mandos ───────────────────────────────────────────────────────────────

local function commands_armed()
    local now = os.clock()
    if (now - commands_armed_checked_at) < COMMANDS_ARMED_TTL_S then
        return commands_armed_cache
    end
    commands_armed_checked_at = now
    local f = io.open(apply_flag_path(), "r")
    if f then
        f:close()
        commands_armed_cache = true
        return true
    end
    commands_armed_cache = false
    return false
end

local function clear_control_lookup_cache()
    for k in pairs(control_cache) do control_cache[k] = nil end
    for k in pairs(control_miss) do control_miss[k] = nil end
    for k in pairs(control_path_logged) do control_path_logged[k] = nil end
    driver_input_dumped = false
end

local function purge_ipc_files()
    pcall(os.remove, send_command_path())
    pcall(os.remove, apply_flag_path())
    clear_control_lookup_cache()
    for k in pairs(last_applied) do last_applied[k] = nil end
    commands_armed_cache = false
    commands_armed_checked_at = 0
    last_ipc_poll_clock = 0
end

local function clamp_num(v, lo, hi)
    if v < lo then return lo end
    if v > hi then return hi end
    return v
end

local function cmd_value_to_notch(cmd_val)
    if type(cmd_val) ~= "number" then return nil end
    return math.max(0, math.min(8, math.floor(cmd_val * 8.0 + 0.5)))
end

-- InputValue Class 323 (Liah class323.tswprofile). Índice 1 = notch 0.
local PBH_INPUT_BY_NOTCH = { -1.0, -0.6, -0.4, -0.2, 0.0, 0.25, 0.5, 0.75, 1.0 }

local function notch_to_axis(notch)
    if type(notch) ~= "number" then return nil end
    local n = math.max(0, math.min(8, math.floor(notch + 0.5)))
    return PBH_INPUT_BY_NOTCH[n + 1]
end

local function axis_value_to_notch(axis_val)
    if type(axis_val) ~= "number" then return nil end
    local best_i = 0
    local best_d = math.abs(axis_val - PBH_INPUT_BY_NOTCH[1])
    for i = 1, 9 do
        local d = math.abs(axis_val - PBH_INPUT_BY_NOTCH[i])
        if d < best_d then
            best_d = d
            best_i = i - 1
        end
    end
    return best_i
end

local function lever_input_value(control_name, cmd_value)
    local num = tonumber(cmd_value)
    if num == nil then return nil end
    if control_name == "IndependentBrake" then
        return clamp_num(num, -1.0, 1.0)
    end
    if control_name == "PowerBrakeHandle" then
        local notch = cmd_value_to_notch(num)
        if notch == nil then return nil end
        return notch_to_axis(notch)
    end
    return (clamp_num(num, 0.0, 1.0) - 0.5) * 2.0
end

local function write_send_ack(name, value, ok, cmd_id)
    ensure_bridge_dir()
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

local function try_child(parent, name)
    if not parent then return nil end
    local ok, child = pcall(function() return parent[name] end)
    if ok and child and child.IsValid and child:IsValid() then
        return child
    end
    return nil
end

local function append_control_candidate(list, seen, ctrl)
    if not ctrl or not ctrl.IsValid or not ctrl:IsValid() then return end
    if seen[ctrl] then return end
    seen[ctrl] = true
    table.insert(list, ctrl)
end

local function ctrl_is_valid(ctrl)
    if not ctrl then return false end
    local ok, valid = pcall(function() return ctrl.IsValid and ctrl:IsValid() end)
    return ok and valid == true
end

local function collect_names_for_control(name)
    return CONTROL_ALIASES[name] or { name }
end

local function lua_str(v)
    if type(v) == "string" then return v end
    if v == nil then return nil end
    local ok, s = pcall(function() return v:ToString() end)
    if ok and type(s) == "string" and s ~= "" then return s end
    ok, s = pcall(function() return tostring(v) end)
    if ok and type(s) == "string" and s ~= "" then return s end
    return nil
end

local function object_class_name(obj)
    if not obj then return "?" end
    local ok, cn = pcall(function()
        return lua_str(obj:GetClass():GetFName())
    end)
    return (ok and cn) or "?"
end

local function lever_name_matches_control(child_name, names)
    if not child_name then return false end
    for _, n in ipairs(names) do
        if child_name == n then return true end
    end
    local low = string.lower(child_name)
    if string.find(low, "throttle", 1, true) and string.find(low, "brake", 1, true) then
        return true
    end
    if string.find(low, "powerbrake", 1, true) then return true end
    if string.find(low, "combined", 1, true) and string.find(low, "handle", 1, true) then
        return true
    end
    return false
end

local function append_levers_from_actor_pairs(parent, names, candidates, seen)
    if not parent then return end
    pcall(function()
        for k, v in pairs(parent) do
            if type(k) == "string" and v and v.IsValid and v:IsValid() then
                local cls = object_class_name(v)
                if lever_name_matches_control(k, names)
                    or string.find(cls, "Lever", 1, true) then
                    append_control_candidate(candidates, seen, v)
                end
            end
        end
    end)
end

local function lever_belongs_to_actor(lever, actor)
    if not lever or not actor then return false end
    local ok, outer = pcall(function() return lever:GetOuter() end)
    for _ = 1, 12 do
        if not ok or not outer then return false end
        if outer == actor then return true end
        ok, outer = pcall(function() return outer:GetOuter() end)
    end
    return false
end

local function append_actor_levers_findall(actor, candidates, seen)
    if not actor then return end
    for _, typename in ipairs(LEVER_COMPONENT_TYPES) do
        local objs = FindAllOf(typename)
        if objs then
            for _, obj in pairs(objs) do
                if obj and obj.IsValid and obj:IsValid()
                    and lever_belongs_to_actor(obj, actor) then
                    append_control_candidate(candidates, seen, obj)
                end
            end
        end
    end
end

local function append_levers_from_driver_input(di, names, candidates, seen)
    if not di then return end
    for _, child_name in ipairs(DRIVER_INPUT_PROBE_NAMES) do
        append_control_candidate(candidates, seen, try_child(di, child_name))
    end
    pcall(function()
        for k, v in pairs(di) do
            if type(k) == "string" and v and v.IsValid and v:IsValid() then
                if lever_name_matches_control(k, names) then
                    append_control_candidate(candidates, seen, v)
                end
            end
        end
    end)
end

local function lever_read_notch(ctrl)
    if not ctrl_is_valid(ctrl) then return nil end
    -- GetCurrentNotchIndex crashea UE4SS; InputValue no existe en este UClass (build p).
    local iv = read_ctrl_number(ctrl, "CurrentInputValue")
    if iv ~= nil then return axis_value_to_notch(iv) end
    local tv = read_ctrl_number(ctrl, "TargetInputValue")
    if tv ~= nil then return axis_value_to_notch(tv) end
    return nil
end

local function candidate_score(ctrl, drivable_actor)
    local score = 0
    if drivable_actor and lever_belongs_to_actor(ctrl, drivable_actor) then
        score = score + 1000
    end
    if read_ctrl_number(ctrl, "InputValue") ~= nil then score = score + 500 end
    if read_ctrl_number(ctrl, "OutputValue") ~= nil then score = score + 40 end
    local ok, path = pcall(function() return ctrl:GetFullName():ToString() end)
    if ok and path then
        if string.find(path, "DriverInput", 1, true) then score = score + 200 end
        if string.find(path, "PowerBrake", 1, true) then score = score + 30 end
    end
    return score
end

local function sort_control_candidates(candidates, drivable_actor)
    table.sort(candidates, function(a, b)
        return candidate_score(a, drivable_actor) > candidate_score(b, drivable_actor)
    end)
end

local function get_drivable_actor(controller)
    if not controller or not controller.IsValid or not controller:IsValid() then
        return nil
    end
    local ok_actor, actor = pcall(function() return controller:GetDrivableActor() end)
    if ok_actor and actor and actor.IsValid and actor:IsValid() then
        return actor
    end
    return nil
end

local function filter_candidates_for_actor(candidates, drivable_actor)
    if not drivable_actor or #candidates == 0 then return candidates end
    local filtered = {}
    for _, ctrl in ipairs(candidates) do
        if lever_belongs_to_actor(ctrl, drivable_actor) then
            table.insert(filtered, ctrl)
        end
    end
    if #filtered > 0 then return filtered end
    return candidates
end

-- Solo mandos del tren en cabina (drivable actor primero, luego controller).
local function collect_control_candidates(name, controller)
    local candidates = {}
    local seen = {}
    local names = collect_names_for_control(name)
    local drivable = get_drivable_actor(controller)
    local function try_parent(parent)
        if not parent then return end
        local di = try_child(parent, "DriverInput")
        if di then
            for _, child_name in ipairs(names) do
                append_control_candidate(candidates, seen, try_child(di, child_name))
            end
            append_levers_from_driver_input(di, names, candidates, seen)
        end
        local dic = try_child(parent, "DriverInputComponent")
        if dic then
            for _, child_name in ipairs(names) do
                append_control_candidate(candidates, seen, try_child(dic, child_name))
            end
            append_levers_from_driver_input(dic, names, candidates, seen)
        end
        for _, child_name in ipairs(names) do
            append_control_candidate(candidates, seen, try_child(parent, child_name))
        end
        -- No pairs(actor): recorre todo el UObject y congela ReceiveTick.
    end
    if drivable then
        try_parent(drivable)
        if not SAFE_LEVER_WRITE and not IPC_DELEGATE_HTTP then
            append_actor_levers_findall(drivable, candidates, seen)
        end
    end
    if controller and controller.IsValid and controller:IsValid() then
        try_parent(controller)
    end
    sort_control_candidates(candidates, drivable)
    return filter_candidates_for_actor(candidates, drivable)
end

-- Class 323: un solo lever en el drivable actor; evita FindAllOf/pairs durante IPC.
local function get_direct_actor_lever(name, controller)
    local actor = get_drivable_actor(controller)
    if not actor then return nil end
    for _, child_name in ipairs(collect_names_for_control(name)) do
        local ctrl = try_child(actor, child_name)
        if ctrl_is_valid(ctrl) then return ctrl end
    end
    return nil
end

local function find_control(name, controller)
    local cached = control_cache[name]
    if cached and cached.IsValid and cached:IsValid() then
        return cached
    end
    if cached ~= nil then
        control_cache[name] = nil
    end
    local direct = get_direct_actor_lever(name, controller)
    if direct then
        control_cache[name] = direct
        return direct
    end
    local candidates = collect_control_candidates(name, controller)
    if #candidates == 0 then
        return nil
    end
    control_cache[name] = candidates[1]
    return candidates[1]
end

local function read_control_scalar(ctrl)
    if not ctrl or not ctrl.IsValid or not ctrl:IsValid() then
        return nil, nil
    end
    local ok, v = pcall(function() return ctrl:GetCurrentNotchIndex() end)
    if ok and type(v) == "number" then
        return "notch", v
    end
    ok, v = pcall(function() return ctrl:GetCurrentInputValue() end)
    if ok and type(v) == "number" then return "scalar", v end
    if ok and type(v) == "table" then
        local n = out_val(v, "ReturnValue")
        if type(n) == "number" then return "scalar", n end
    end
    local result = {}
    ok = pcall(function()
        ctrl.GetCurrentInputValue(ctrl, result)
    end)
    if ok then
        local n = out_val(result, "ReturnValue")
        if type(n) == "number" then return "scalar", n end
    end
    ok, v = pcall(function() return ctrl.InputValue end)
    if ok and type(v) == "number" then return "scalar", v end
    ok, v = pcall(function() return ctrl.Value end)
    if ok and type(v) == "number" then return "scalar", v end
    ok, v = pcall(function() return ctrl.OutputValue end)
    if ok and type(v) == "number" then return "scalar", v end
    return nil, nil
end

local function scalar_to_notch(kind, val)
    if val == nil then return nil end
    if kind == "notch" then
        return math.max(0, math.min(8, math.floor(val + 0.5)))
    end
    if kind == "scalar" then
        if val >= -1.05 and val <= 1.05 then
            if val >= 0.0 and val <= 1.0 then
                return cmd_value_to_notch(val)
            end
            return axis_value_to_notch(val)
        end
        return cmd_value_to_notch(val)
    end
    return nil
end

local function input_to_notch(input_val)
    return scalar_to_notch("scalar", input_val)
end

local function control_debug_label(ctrl)
    local cls = object_class_name(ctrl)
    local ok, path = pcall(function() return lua_str(ctrl:GetFullName()) end)
    if ok and path and path ~= "" then return path .. " [" .. cls .. "]" end
    ok, path = pcall(function() return lua_str(ctrl:GetName()) end)
    if ok and path and path ~= "" then return path .. " [" .. cls .. "]" end
    return tostring(ctrl) .. " [" .. cls .. "]"
end

local function fmt_probe_num(v)
    if type(v) == "number" then return string.format("%.4f", v) end
    return tostring(v)
end

local function fmt_probe_any(v)
    if v == nil then return "nil" end
    local t = type(v)
    if t == "number" then return string.format("%.4f", v) end
    if t == "boolean" or t == "string" then return tostring(v) end
    local s = lua_str(v)
    if s and s ~= "" then return s end
    return t
end

local function container_len(arr)
    if arr == nil then return nil end
    local t = type(arr)
    if t == "table" then
        local n = #arr
        if type(n) == "number" and n > 0 and n <= 16 then return n end
        return nil
    end
    -- No usar # sobre userdata UE: puede devolver un N enorme y congelar el tick.
    local n
    pcall(function() n = arr:GetArrayNum() end)
    if type(n) == "number" and n > 0 and n <= 16 then return n end
    pcall(function() n = arr:Num() end)
    if type(n) == "number" and n > 0 and n <= 16 then return n end
    pcall(function() n = arr:GetNumElements() end)
    if type(n) == "number" and n > 0 and n <= 16 then return n end
    return nil
end

local function read_index(arr, i)
    local v
    local ok = pcall(function() v = arr:Get(i) end)
    if ok and v ~= nil then return v end
    ok = pcall(function() v = arr[i] end)
    if ok and v ~= nil then return v end
    return nil
end

-- TArray convertido a tabla Lua (1-based). ForEach/Get(0..8)/pairs en
-- UScriptStruct tiran ReceiveTick (seq 1→2 ~2.7 s).
local function foreach_container(arr, fn)
    if arr == nil then return end
    local kind = type(arr)
    if kind ~= "table" and kind ~= "userdata" then return end
    for i = 1, 8 do
        local item
        pcall(function() item = arr[i] end)
        if item == nil then return end
        if fn(item) == false then return end
    end
end

-- UE4SS: `n ~= v` / `v > 0` entre number y UScriptStruct tira
-- "attempt to compare number with UScriptStruct" (pcall de DriverAid entero).
local function unwrap_number(v, depth)
    depth = depth or 0
    if v == nil or type(depth) ~= "number" or depth > 5 then return nil end
    if type(v) == "number" then return v end
    local n
    pcall(function() n = v:get() end)
    if type(n) == "number" then return n end
    if n ~= nil and type(n) ~= "number" then
        local inner = unwrap_number(n, depth + 1)
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

local function dump_struct_numbers(el, prefix)
    local found = {}
    local function take(name, val)
        local num = unwrap_number(val)
        if type(name) == "string" and type(num) == "number" then
            found[name] = num
            if prefix then
                print(string.format(
                    "[TelemetryProbe] PBH %s.%s=%.4f\n", prefix, name, num))
            end
        end
    end
    pcall(function()
        local class = el.GetClass and el:GetClass() or nil
        if class and type(class.ForEachProperty) == "function" then
            class:ForEachProperty(function(prop)
                local n = lua_str(prop:GetFName())
                if not n then return end
                local val
                pcall(function() val = el[n] end)
                take(n, val)
            end)
        end
    end)
    pcall(function()
        if type(el.ForEachProperty) == "function" then
            el:ForEachProperty(function(prop)
                local n = lua_str(prop:GetFName())
                local val
                pcall(function() val = el[n] end)
                take(n, val)
            end)
        end
    end)
    for _, key in ipairs({
        "OutputValue", "InputValue", "Value", "NormalisedValue",
        "NotchID", "NotchIndex", "Index",
    }) do
        if found[key] == nil then
            local val
            pcall(function() val = el[key] end)
            take(key, val)
        end
    end
    return found
end

local function struct_axis(el)
    if type(el) == "number" then return el end
    if el == nil then return nil end
    local n = unwrap_number(el)
    if n ~= nil then return n end
    local fields = dump_struct_numbers(el, nil)
    return fields.OutputValue or fields.InputValue or fields.Value or fields.NormalisedValue
end

local function struct_notch_id(el)
    if type(el) == "number" then return nil end
    if el == nil then return nil end
    for _, key in ipairs({ "NotchID", "NotchIndex", "Index", "ID" }) do
        local ok, v = pcall(function() return el[key] end)
        if ok and type(v) == "number" then return math.floor(v + 0.5) end
    end
    return nil
end

-- Una vez (F9): Notches.InputValue. El 323 ya está en PBH_INPUT_BY_NOTCH.
local function dump_pbh_valuemap(ctrl)
    if pbh_map_dumped or not ctrl_is_valid(ctrl) then
        return
    end
    local cls = object_class_name(ctrl)
    local path = control_debug_label(ctrl)
    if not string.find(path, "PowerBrakeHandle", 1, true)
        and cls ~= "IrregularLeverComponent" then
        return
    end
    pbh_map_dumped = true
    local nnotch
    pcall(function() nnotch = ctrl.NumberOfNotches end)
    print(string.format(
        "[TelemetryProbe] PBH map NumberOfNotches=%s class=%s\n",
        tostring(nnotch), object_class_name(ctrl)))
    local axis_by = {}
    local function remember(idx, axis, src)
        if type(idx) ~= "number" or type(axis) ~= "number" then return end
        idx = math.floor(idx + 0.5)
        if idx < 0 or idx > 16 then return end
        axis_by[idx] = axis
        print(string.format(
            "[TelemetryProbe] PBH map %s notch=%d axis=%.4f\n", src, idx, axis))
    end
    pcall(function()
        local arr = ctrl.Notches
        local len = container_len(arr)
        print(string.format(
            "[TelemetryProbe] PBH Notches type=%s len=%s\n",
            type(arr), tostring(len)))
        if type(arr) == "table" or (arr ~= nil and type(arr) ~= "number") then
            local maxn = len or 12
            if maxn > 16 then maxn = 16 end
            for i = 0, maxn do
                local el = read_index(arr, i)
                if el ~= nil then
                    local fields = dump_struct_numbers(el, "Notches[" .. tostring(i) .. "]")
                    local axis = fields.MinimumInputValue or fields.MaximumInputValue
                        or fields.InputValue or fields.OutputValue or struct_axis(el)
                    local nid = (i >= 1) and (i - 1) or i
                    remember(nid, axis, "Notches[" .. tostring(i) .. "]")
                end
            end
        end
    end)
    -- ValueMap es potencia HUD (−4…4), no InputValue; no volcar (ruido).
    local count = 0
    for _ in pairs(axis_by) do count = count + 1 end
    if count > 0 then
        pbh_axis_by_notch = axis_by
        print(string.format("[TelemetryProbe] PBH map ready entries=%d\n", count))
    else
        print("[TelemetryProbe] PBH map empty (usar eje lineal)\n")
    end
end

local function dump_lever_snapshot(scope_label, ctrl)
    local parts = {
        scope_label,
        "class=" .. object_class_name(ctrl),
        "obj=" .. control_debug_label(ctrl),
    }
    local kind, val = read_control_scalar(ctrl)
    if kind and val ~= nil then
        table.insert(parts, string.format("read_%s=%s", kind, fmt_probe_num(val)))
        local notch = scalar_to_notch(kind, val)
        if notch ~= nil then
            table.insert(parts, "notch=" .. tostring(notch))
        end
    end
    for _, prop in ipairs({
        "CurrentInputValue", "CurrentOutputValue", "TargetInputValue",
        "TargetOutputValue", "CurrentNotchID", "bInputEnabled",
    }) do
        local ok, v = pcall(function() return ctrl[prop] end)
        if ok then
            if type(v) == "number" then
                table.insert(parts, prop .. "=" .. fmt_probe_num(v))
            elseif type(v) == "boolean" then
                table.insert(parts, prop .. "=" .. tostring(v))
            else
                table.insert(parts, prop .. "_type=" .. type(v))
            end
        else
            table.insert(parts, prop .. "=err")
        end
    end
    local ok_n, n = pcall(function() return ctrl.NumberOfNotches end)
    if ok_n and type(n) == "number" then
        table.insert(parts, "NumberOfNotches=" .. tostring(n))
    end
    print("[TelemetryProbe] DI lever " .. table.concat(parts, " | ") .. "\n")
    dump_pbh_valuemap(ctrl)
end

-- Llamadas nativas que ya tumbaron UE4SS (pcall no las atrapa).
local CRASH_UFUNCTION = {
    SetCurrentNotchIndex = true,
    SetInputValue = true,
    ConditionalBeginTick = true,
    GetCurrentNotchIndex = true,
}

local function ufunction_is_safe_setter(name)
    if not name or CRASH_UFUNCTION[name] then return false end
    if string.sub(name, 1, 3) == "Get" or string.sub(name, 1, 2) == "Is" then
        return false
    end
    local low = string.lower(name)
    if string.find(low, "input", 1, true) and string.find(low, "set", 1, true) then
        return true
    end
    if string.find(low, "setvalue", 1, true) then return true end
    if string.find(low, "applyinput", 1, true) then return true end
    if string.find(low, "setaxis", 1, true) then return true end
    return false
end

local function dump_uobject_reflection(obj, label)
    local funcs = {}
    local props = {}
    if not ctrl_is_valid(obj) then
        print(string.format("[TelemetryProbe] reflect %s: invalid\n", tostring(label)))
        return funcs, props
    end
    print(string.format(
        "[TelemetryProbe] === Reflect %s %s ===\n",
        tostring(label), control_debug_label(obj)))
    local class
    pcall(function() class = obj:GetClass() end)
    local depth = 0
    while class and depth < 8 do
        depth = depth + 1
        local cname = "?"
        pcall(function() cname = lua_str(class:GetFName()) or "?" end)
        print(string.format("[TelemetryProbe] reflect class[%d]=%s\n", depth, cname))
        pcall(function()
            if type(class.ForEachFunction) == "function" then
                class:ForEachFunction(function(fn)
                    local n = lua_str(fn:GetFName())
                    if n then
                        table.insert(funcs, n)
                        if #funcs <= 80 then
                            print("[TelemetryProbe]   fn " .. n .. "\n")
                        end
                    end
                end)
            end
        end)
        pcall(function()
            if type(class.ForEachProperty) == "function" then
                class:ForEachProperty(function(prop)
                    local n = lua_str(prop:GetFName())
                    local pt = "?"
                    pcall(function() pt = lua_str(prop:GetClass():GetFName()) or "?" end)
                    if n then
                        table.insert(props, n .. ":" .. pt)
                        if #props <= 80 then
                            print("[TelemetryProbe]   prop " .. n .. " [" .. pt .. "]\n")
                        end
                    end
                end)
            end
        end)
        local super
        pcall(function()
            if type(class.GetSuperClass) == "function" then
                super = class:GetSuperClass()
            elseif type(class.GetSuperStruct) == "function" then
                super = class:GetSuperStruct()
            end
        end)
        if not super or super == class then break end
        class = super
        if cname == "Object" or cname == "ActorComponent" then break end
    end
    if #funcs == 0 then
        pcall(function()
            if type(obj.ForEachFunction) == "function" then
                obj:ForEachFunction(function(fn)
                    local n = lua_str(fn:GetFName())
                    if n then
                        table.insert(funcs, n)
                        print("[TelemetryProbe]   fn " .. n .. "\n")
                    end
                end)
            end
        end)
    end
    print(string.format(
        "[TelemetryProbe] reflect done funcs=%d props=%d\n", #funcs, #props))
    return funcs, props
end

local function collect_pbh_setters(ctrl)
    if pbh_setter_names ~= nil then return pbh_setter_names end
    local funcs = dump_uobject_reflection(ctrl, "PBH")
    local setters = {}
    local preferred = {
        "SetCurrentInputValue",
        "SetNormalizedInputValue",
        "SetTargetInputValue",
        "ApplyInputValue",
        "SetValue",
    }
    local have = {}
    for _, n in ipairs(funcs) do have[n] = true end
    for _, n in ipairs(preferred) do
        if have[n] and ufunction_is_safe_setter(n) then
            table.insert(setters, n)
        end
    end
    for _, n in ipairs(funcs) do
        if ufunction_is_safe_setter(n) then
            local dup = false
            for _, s in ipairs(setters) do
                if s == n then dup = true break end
            end
            if not dup then table.insert(setters, n) end
        end
    end
    pbh_setter_names = setters
    if #setters == 0 then
        print("[TelemetryProbe] reflect: ninguna UFunction setter segura\n")
    else
        print("[TelemetryProbe] reflect setters: " .. table.concat(setters, ", ") .. "\n")
    end
    return setters
end

local function dump_ufunction_params(obj, fname)
    local fn
    pcall(function() fn = obj:GetFunction(fname) end)
    if not fn then
        print(string.format("[TelemetryProbe] ufn %s: GetFunction=nil\n", fname))
        return
    end
    local names = {}
    pcall(function()
        if type(fn.ForEachProperty) == "function" then
            fn:ForEachProperty(function(prop)
                local n = lua_str(prop:GetFName())
                local pt = "?"
                pcall(function() pt = lua_str(prop:GetClass():GetFName()) or "?" end)
                if n then
                    table.insert(names, n .. ":" .. pt)
                    print("[TelemetryProbe]   ufn-param " .. n .. " [" .. pt .. "]\n")
                end
            end)
        end
    end)
    print(string.format(
        "[TelemetryProbe] ufn %s params(%d)=%s\n",
        fname, #names, #names > 0 and table.concat(names, ", ") or "?"))
end

local function method_type_label(method)
    if method == nil then return "nil" end
    local lt = type(method)
    local ut
    pcall(function()
        if type(method.type) == "function" then
            ut = method:type()
        end
    end)
    if ut and ut ~= "" then return lt .. "/" .. ut end
    return lt
end

-- UFunction obtenida por obj.Func ya lleva contexto: NO pasar obj otra vez
-- (build t: BeginDecreaseDigital expected 2 received 0; SetPositionDeltaAnalogue expected 3 received 1).
local function dump_bound_fn_params(fn, fname)
    if fn == nil then
        print(string.format("[TelemetryProbe] bound %s: nil\n", fname))
        return
    end
    local names = {}
    pcall(function()
        if type(fn.ForEachProperty) == "function" then
            fn:ForEachProperty(function(prop)
                local n = lua_str(prop:GetFName())
                local pt = "?"
                pcall(function() pt = lua_str(prop:GetClass():GetFName()) or "?" end)
                if n then
                    table.insert(names, n .. ":" .. pt)
                end
            end)
        end
    end)
    print(string.format(
        "[TelemetryProbe] bound %s type=%s params=%s\n",
        fname, method_type_label(fn),
        #names > 0 and table.concat(names, ", ") or "?"))
end

local function call_bound(fn, args)
    if fn == nil then return false, "no_method" end
    local n = args and #args or 0
    local a1, a2, a3, a4 = args and args[1], args and args[2], args and args[3], args and args[4]
    local ok, err = pcall(function()
        if n == 0 then
            fn()
        elseif n == 1 then
            fn(a1)
        elseif n == 2 then
            fn(a1, a2)
        elseif n == 3 then
            fn(a1, a2, a3)
        else
            fn(a1, a2, a3, a4)
        end
    end)
    if not ok then
        return false, tostring(err)
    end
    return true, "ok"
end

local function try_call_colon(obj, fname, ...)
    if not ctrl_is_valid(obj) or CRASH_UFUNCTION[fname] then
        return false, "blocked"
    end
    local method = obj[fname]
    if method == nil then
        return false, "no_method"
    end
    local args = {...}
    return call_bound(method, args)
end

local function dump_driver_input_node(scope_label, parent)
    if not parent then return end
    local di = try_child(parent, "DriverInput")
    if not di then
        print(string.format("[TelemetryProbe] DI %s: sin DriverInput\n", scope_label))
        return
    end
    print(string.format(
        "[TelemetryProbe] DI %s DriverInput=%s\n", scope_label, control_debug_label(di)))
    local pair_names = {}
    pcall(function()
        for k, v in pairs(di) do
            if type(k) == "string" then
                if v and v.IsValid and v:IsValid() then
                    table.insert(pair_names, k .. ":UObject")
                elseif type(v) == "number" or type(v) == "boolean" then
                    table.insert(pair_names, k .. "=" .. tostring(v))
                end
            end
        end
    end)
    table.sort(pair_names)
    if #pair_names > 0 then
        print(string.format(
            "[TelemetryProbe] DI %s pairs(%d): %s\n",
            scope_label, #pair_names, table.concat(pair_names, ", ")))
    end
    for _, child_name in ipairs(DRIVER_INPUT_PROBE_NAMES) do
        local child = try_child(di, child_name)
        if child then
            dump_lever_snapshot(scope_label .. "." .. child_name, child)
        end
    end
end

local function dump_actor_control_tree(actor, scope_label)
    if not actor then return end
    print(string.format("[TelemetryProbe] DI %s direct levers:\n", scope_label))
    local named = 0
    for _, child_name in ipairs(DRIVER_INPUT_PROBE_NAMES) do
        local child = try_child(actor, child_name)
        if child then
            named = named + 1
            dump_lever_snapshot(scope_label .. "." .. child_name, child)
        end
    end
    local pair_levers = {}
    pcall(function()
        for k, v in pairs(actor) do
            if type(k) == "string" and v and v.IsValid and v:IsValid() then
                local cls = object_class_name(v)
                if string.find(cls, "Lever", 1, true) then
                    table.insert(pair_levers, k .. ":" .. cls)
                    dump_lever_snapshot(scope_label .. ".pairs." .. k, v)
                end
            end
        end
    end)
    if #pair_levers > 0 then
        print(string.format(
            "[TelemetryProbe] DI %s pairs levers: %s\n",
            scope_label, table.concat(pair_levers, ", ")))
    elseif named == 0 then
        print(string.format("[TelemetryProbe] DI %s: sin levers directos\n", scope_label))
    end
    local sim = try_child(actor, "Simulation")
    if sim then
        print(string.format("[TelemetryProbe] DI %s Simulation=%s\n",
            scope_label, object_class_name(sim)))
        for _, node_name in ipairs(SIM_BRAKE_NODES) do
            local node = try_child(sim, node_name)
            if node then
                dump_lever_snapshot(scope_label .. ".Simulation." .. node_name, node)
            end
        end
    else
        print(string.format("[TelemetryProbe] DI %s: sin Simulation\n", scope_label))
    end
end

local function dump_driver_input_inventory(controller, reason)
    if driver_input_dumped then return end
    driver_input_dumped = true
    print(string.format(
        "[TelemetryProbe] === Control dump (%s) build=%s ===\n",
        tostring(reason or "?"), PROBE_BUILD))
    print("[TelemetryProbe] Nota: en UE4SS el lever suele estar en actor; hijo DriverInput no siempre existe.\n")
    if not controller or not controller.IsValid or not controller:IsValid() then
        print("[TelemetryProbe] DI: controller invalido\n")
        print("[TelemetryProbe] === Control dump end ===\n")
        return
    end
    dump_driver_input_node("controller", controller)
    local ok_actor, actor = pcall(function() return controller:GetDrivableActor() end)
    if ok_actor and actor and actor.IsValid and actor:IsValid() then
        print(string.format(
            "[TelemetryProbe] DI actor=%s\n", control_debug_label(actor)))
        dump_driver_input_node("actor", actor)
        dump_actor_control_tree(actor, "actor")
    else
        print("[TelemetryProbe] DI actor: sin drivable\n")
    end
    local ok_di, global_di = pcall(function() return FindFirstOf("DriverInput") end)
    if ok_di and global_di and global_di.IsValid and global_di:IsValid() then
        print(string.format(
            "[TelemetryProbe] DI FindFirstOf(ref)=%s\n", control_debug_label(global_di)))
        for _, child_name in ipairs(DRIVER_INPUT_PROBE_NAMES) do
            local child = try_child(global_di, child_name)
            if child then
                dump_lever_snapshot("FindFirstOf." .. child_name, child)
            end
        end
    else
        print("[TelemetryProbe] DI FindFirstOf(DriverInput): nil (normal en UE4SS)\n")
    end
    local pbh = get_direct_actor_lever("PowerBrakeHandle", controller)
    if pbh then
        pbh_setter_names = nil
        pbh_ufn_dumped = false
        collect_pbh_setters(pbh)
    else
        print("[TelemetryProbe] reflect: sin actor.PowerBrakeHandle\n")
    end
    print("[TelemetryProbe] === Control dump end ===\n")
end

local function log_control_path(name, ctrl, idx)
    local key = name .. "#" .. tostring(idx or 1)
    if control_path_logged[key] then return end
    control_path_logged[key] = true
    print(string.format(
        "[TelemetryProbe] control %s[%s] -> %s\n", name, tostring(idx or 1),
        control_debug_label(ctrl)))
end

local function hud_notch_moved_toward(hud_before, hud_after, target)
    if hud_before == nil or hud_after == nil or target == nil then
        return false
    end
    local d0 = math.abs(hud_before - target)
    local d1 = math.abs(hud_after - target)
    return d1 < d0
end

-- Class 323: un paso hacia destino. Rechaza alejarse; avisa si UE salta >1.
local function hud_step_ack(hud_before, hud_after, dest, step)
    if dest == nil then return false end
    if hud_before ~= nil and hud_before == dest then
        return hud_after == nil or hud_after == dest
    end
    if hud_before == nil or hud_after == nil then
        return false
    end
    if hud_after == hud_before then
        return false
    end
    if math.abs(hud_after - dest) > math.abs(hud_before - dest) then
        return false
    end
    if math.abs(hud_after - hud_before) > 1 then
        print(string.format(
            "[TelemetryProbe] WARN PBH skip hud %s->%s (wanted step %s dest %s)\n",
            tostring(hud_before), tostring(hud_after), tostring(step), tostring(dest)))
    end
    return true
end

local function read_ctrl_number(ctrl, prop)
    local ok, v = pcall(function() return ctrl[prop] end)
    if ok and type(v) == "number" then return v end
    return nil
end

local function safe_assign_lever_prop(ctrl, prop, val)
    local before = read_ctrl_number(ctrl, prop)
    local wok = pcall(function() ctrl[prop] = val end)
    local after = read_ctrl_number(ctrl, prop)
    return wok, before, after
end

local function write_pbh_one_step(ctrl, num, controller)
    local dest = cmd_value_to_notch(num)
    local hud_before = read_hud_lever_notch and read_hud_lever_notch(controller)
    if dest == nil then
        return false, "bad_cmd"
    end
    if hud_before ~= nil and hud_before == dest then
        print(string.format(
            "[TelemetryProbe] IPC PBH already hud=%s dest=%s (no write)\n",
            tostring(hud_before), tostring(dest)))
        return true, "already"
    end
    local step = dest
    local sign = 0
    if hud_before ~= nil then
        if dest > hud_before then
            step = hud_before + 1
            sign = 1
        elseif dest < hud_before then
            step = hud_before - 1
            sign = -1
        end
        step = math.max(0, math.min(8, step))
    end
    -- SetCurrentOutputValue espera potencia HUD (muesca-4), no InputValue −1…1.
    local out_val = step - 4
    local hud_after = hud_before
    local okc, why = call_bound(ctrl.SetCurrentOutputValue, { out_val })
    hud_after = read_hud_lever_notch and read_hud_lever_notch(controller)
    print(string.format(
        "[TelemetryProbe] IPC SetCurrentOutputValue step=%s axis=%.4f dest=%s → %s hud %s->%s\n",
        tostring(step), out_val, tostring(dest), tostring(why),
        tostring(hud_before), tostring(hud_after)))
    if okc then
        if hud_before == nil then
            pbh_write_strategy = "SetCurrentOutputValue"
            return true, "SetCurrentOutputValue"
        end
        if hud_step_ack(hud_before, hud_after, dest, step) then
            pbh_write_strategy = "SetCurrentOutputValue"
            print(string.format(
                "[TelemetryProbe] PBH write OK via SetCurrentOutputValue hud %s->%s step=%s dest=%s\n",
                tostring(hud_before), tostring(hud_after), tostring(step), tostring(dest)))
            return true, "SetCurrentOutputValue"
        end
        if hud_after ~= nil and hud_after ~= hud_before then
            return false, "away"
        end
    end
    -- Liah dllmain: BeginChangingVHID + SetCurrentInputValue (peldaños −0.6…1). No SetInputValue().
    local in_val = notch_to_axis(step)
    if in_val == nil then
        return false, "no_effect"
    end
    if controller then
        try_call_colon(controller, "BeginChangingVHIDComponent", ctrl)
    end
    okc, why = call_bound(ctrl.SetCurrentInputValue, { in_val })
    hud_after = read_hud_lever_notch and read_hud_lever_notch(controller)
    print(string.format(
        "[TelemetryProbe] IPC VHID SetCurrentInputValue step=%s in=%.4f dest=%s → %s hud %s->%s\n",
        tostring(step), in_val, tostring(dest), tostring(why),
        tostring(hud_before), tostring(hud_after)))
    if okc and hud_before == nil then
        pbh_write_strategy = "SetCurrentInputValue"
        if controller then
            try_call_colon(controller, "EndUsingVHIDComponent", ctrl)
        end
        return true, "SetCurrentInputValue"
    end
    if okc and hud_step_ack(hud_before, hud_after, dest, step) then
        pbh_write_strategy = "SetCurrentInputValue"
        if controller then
            try_call_colon(controller, "EndUsingVHIDComponent", ctrl)
        end
        print(string.format(
            "[TelemetryProbe] PBH write OK via VHID SetCurrentInputValue hud %s->%s step=%s dest=%s\n",
            tostring(hud_before), tostring(hud_after), tostring(step), tostring(dest)))
        return true, "SetCurrentInputValue"
    end
    if hud_after ~= nil and hud_after ~= hud_before then
        return false, "away"
    end
    return false, "no_effect"
end

local function write_lever_control(name, ctrl, num, input_val, controller)
    if not ctrl_is_valid(ctrl) then
        return false, "invalid_ctrl"
    end
    if name == "PowerBrakeHandle" and SAFE_LEVER_WRITE then
        return write_pbh_one_step(ctrl, num, controller)
    end
    local hud_before = read_hud_lever_notch and read_hud_lever_notch(controller)
    local target = cmd_value_to_notch(num)
    local axis_from_notch = target and notch_to_axis(target)
    local strategies = {}
    if name == "PowerBrakeHandle" then
        -- Sin SAFE: no SetInputValue/SetNotch (crash). Un eje = Liah.
        if axis_from_notch ~= nil then
            table.insert(strategies, {"InputValue", axis_from_notch})
        end
    else
        if type(ctrl.SetInputValue) == "function" then
            table.insert(strategies, 1, {"_SetInputValue", input_val})
        end
        table.insert(strategies, {"Value", num})
        table.insert(strategies, {"InputValue", input_val})
        table.insert(strategies, {"InputValue", num})
        table.insert(strategies, {"OutputValue", num})
        if axis_from_notch ~= nil then
            table.insert(strategies, {"InputValue", axis_from_notch})
        end
    end
    for _, pair in ipairs(strategies) do
        local key, val = pair[1], pair[2]
        if not ctrl_is_valid(ctrl) then
            return false, "invalid_ctrl"
        end
        if name == "PowerBrakeHandle" and SAFE_LEVER_WRITE and key == "_interact_input" then
            print(string.format(
                "[TelemetryProbe] IPC write PBH interact+InputValue=%.4f (cmd=%.4f notch=%s)\n",
                val, num, tostring(target)))
        elseif name == "PowerBrakeHandle" and SAFE_LEVER_WRITE then
            print(string.format(
                "[TelemetryProbe] IPC write PBH %s=%.4f (cmd=%.4f notch=%s)\n",
                key, val, num, tostring(target)))
        end
        local wok, err = pcall(function()
            if key == "_SetInputValue" then
                ctrl:SetInputValue(val)
            elseif key == "_SetNotch" then
                ctrl:SetCurrentNotchIndex(val)
            elseif key == "_interact_input" then
                pcall(function() ctrl.Interacting = true end)
                ctrl.InputValue = val
                pcall(function()
                    if type(ctrl.ConditionalBeginTick) == "function" then
                        ctrl:ConditionalBeginTick()
                    end
                end)
            else
                ctrl[key] = val
            end
        end)
        if wok and name == "PowerBrakeHandle" and SAFE_LEVER_WRITE then
            local civ = read_ctrl_number(ctrl, "CurrentInputValue")
            local tiv = read_ctrl_number(ctrl, "TargetInputValue")
            local nid = read_ctrl_number(ctrl, "CurrentNotchID")
            print(string.format(
                "[TelemetryProbe] PBH readback CurrentInput=%s TargetInput=%s NotchID=%s hud=%s\n",
                tostring(civ), tostring(tiv), tostring(nid),
                tostring(read_hud_lever_notch and read_hud_lever_notch(controller))))
        end
        if wok then
            local hud_after = read_hud_lever_notch and read_hud_lever_notch(controller)
            local verified = false
            if hud_before ~= nil and hud_after ~= nil then
                verified = hud_notch_moved_toward(hud_before, hud_after, target)
            end
            if not verified then
                local nid = read_ctrl_number(ctrl, "CurrentNotchID")
                if type(nid) == "number" and target ~= nil and nid ~= hud_before then
                    verified = hud_notch_moved_toward(hud_before, nid, target)
                end
            end
            if verified then
                if name == "PowerBrakeHandle" and not pbh_write_strategy then
                    pbh_write_strategy = key
                    print(string.format(
                        "[TelemetryProbe] PBH write OK via %s axis=%.4f cmd=%.4f hud %s->%s\n",
                        key, tonumber(val) or 0, num,
                        tostring(hud_before), tostring(hud_after)))
                end
                return true, key
            end
        end
    end
    if hud_before ~= nil then
        print(string.format(
            "[TelemetryProbe] WARN write %s cmd=%.4f axis=%s no HUD change (hud=%s target_notch=%s)\n",
            name, num, tostring(axis_from_notch), tostring(hud_before), tostring(target)))
    end
    return false, "no_effect"
end

local function write_simulation_brake(actor, num, input_val, controller)
    if not actor or not actor.IsValid or not actor:IsValid() then
        return false, "no_actor"
    end
    local sim = try_child(actor, "Simulation")
    if not sim then return false, "no_simulation" end
    local hud_before = read_hud_lever_notch and read_hud_lever_notch(controller)
    local target = cmd_value_to_notch(num)
    for _, node_name in ipairs(SIM_BRAKE_NODES) do
        local node = try_child(sim, node_name)
        if node then
            local tries = {
                {"InputValue", input_val},
                {"InputValue", (target - 4) / 4.0},
                {"InputValue", num},
                {"Value", num},
            }
            for _, pair in ipairs(tries) do
                local prop, val = pair[1], pair[2]
                local wok = pcall(function() node[prop] = val end)
                if wok then
                    local hud_after = read_hud_lever_notch and read_hud_lever_notch(controller)
                    if hud_before ~= nil and hud_after ~= nil
                        and hud_notch_moved_toward(hud_before, hud_after, target) then
                        local path = "Simulation." .. node_name .. "." .. prop
                        print(string.format(
                            "[TelemetryProbe] PBH write OK via %s cmd=%.4f hud %s->%s\n",
                            path, num, tostring(hud_before), tostring(hud_after)))
                        return true, path
                    end
                end
            end
        end
    end
    return false, "sim_no_effect"
end

local function read_lever_notch(controller)
    if read_hud_lever_notch then
        local hud = read_hud_lever_notch(controller)
        if hud ~= nil then return hud end
    end
    local ctrl = find_control("PowerBrakeHandle", controller)
    if ctrl then
        local kind, val = read_control_scalar(ctrl)
        local notch = scalar_to_notch(kind, val)
        if notch ~= nil then return notch end
    end
    return nil
end

local function apply_control_value(name, value, controller, cmd_id)
    if not ALLOWED_CONTROLS[name] then return false end
    local num = tonumber(value)
    if num == nil then return false end
    print(string.format(
        "[TelemetryProbe] IPC recv %s=%.4f id=%s build=%s\n",
        name, num, tostring(cmd_id or "?"), PROBE_BUILD))
    if IPC_DELEGATE_HTTP then
        if cmd_id then last_cmd_id = cmd_id end
        last_ack_ok = false
        write_send_ack(name, num, false, cmd_id)
        print(string.format(
            "[TelemetryProbe] IPC delegate %s=%.4f id=%s notch=%s → HTTP (sin write UE)\n",
            name, num, tostring(cmd_id or "?"),
            tostring(cmd_value_to_notch(num))))
        return false
    end
    local input_val = lever_input_value(name, num)
    if name == "PowerBrakeHandle" and SAFE_LEVER_WRITE then
        local direct = get_direct_actor_lever(name, controller)
        if direct then
            print(string.format(
                "[TelemetryProbe] IPC direct PBH %s cmd=%.4f notch=%s\n",
                control_debug_label(direct), num, tostring(cmd_value_to_notch(num))))
            local ok, detail = write_lever_control(name, direct, num, input_val, controller)
            if cmd_id then last_cmd_id = cmd_id end
            if ok then
                control_cache[name] = direct
                control_miss[name] = nil
                last_ack_ok = true
                last_applied[name] = num
                write_send_ack(name, num, true, cmd_id)
                return true
            end
            control_cache[name] = nil
            last_ack_ok = false
            print(string.format(
                "[TelemetryProbe] WARN direct PBH set=%.4f failed: %s\n",
                num, tostring(detail)))
            write_send_ack(name, num, false, cmd_id)
            return false
        end
        print("[TelemetryProbe] WARN direct PBH not found on drivable actor\n")
        if cmd_id then last_cmd_id = cmd_id end
        last_ack_ok = false
        write_send_ack(name, num, false, cmd_id)
        return false
    end
    local candidates = collect_control_candidates(name, controller)
    local drivable = get_drivable_actor(controller)
    local cached = control_cache[name]
    if cached and drivable and not lever_belongs_to_actor(cached, drivable) then
        control_cache[name] = nil
        cached = nil
    end
    if cached and cached.IsValid and cached:IsValid() then
        local seen = { [cached] = true }
        local ordered = { cached }
        for _, ctrl in ipairs(candidates) do
            if not seen[ctrl] then
                seen[ctrl] = true
                table.insert(ordered, ctrl)
            end
        end
        candidates = ordered
    end
    if #candidates == 0 then
        print("[TelemetryProbe] WARN control not found (scoped): " .. name .. "\n")
        if cmd_id then last_cmd_id = cmd_id end
        last_ack_ok = false
        write_send_ack(name, num, false, cmd_id)
        return false
    end
    local ok, detail, winning_ctrl
    for idx, ctrl in ipairs(candidates) do
        log_control_path(name, ctrl, idx)
        if name == "PowerBrakeHandle" or name == "IndependentBrake" then
            ok, detail = write_lever_control(name, ctrl, num, input_val, controller)
        else
            ok, detail = pcall(function()
                ctrl.Value = num
            end)
            if not ok then
                ok, detail = pcall(function()
                    ctrl.InputValue = input_val or num
                end)
            end
            if ok then detail = "Value" end
        end
        if ok then
            winning_ctrl = ctrl
            break
        end
    end
    if not ok and name == "PowerBrakeHandle" and not SAFE_LEVER_WRITE then
        local actor = drivable or get_drivable_actor(controller)
        if actor then
            ok, detail = write_simulation_brake(actor, num, input_val, controller)
        end
    end
    if cmd_id then last_cmd_id = cmd_id end
    if ok then
        if winning_ctrl then
            control_cache[name] = winning_ctrl
        end
        control_miss[name] = nil
        last_ack_ok = true
        last_applied[name] = num
        write_send_ack(name, num, true, cmd_id)
        return true
    end
    control_cache[name] = nil
    last_ack_ok = false
    print(string.format(
        "[TelemetryProbe] WARN set %s=%.4f failed (%d candidates): %s\n",
        name, num, #candidates, tostring(detail)))
    for idx, ctrl in ipairs(candidates) do
        print(string.format(
            "[TelemetryProbe]   cand[%d] %s read_notch=%s\n",
            idx, control_debug_label(ctrl), tostring(lever_read_notch(ctrl))))
    end
    if name == "PowerBrakeHandle" and not SAFE_LEVER_WRITE then
        dump_driver_input_inventory(controller, "write_fail")
    end
    write_send_ack(name, num, false, cmd_id)
    return false
end

local function parse_send_line(line)
    local name, val, cid = string.match(line, "^%s*([^:]+)%s*:%s*([^:]+)%s*:%s*(%d+)%s*$")
    if name then return name, val, tonumber(cid) end
    name, val = string.match(line, "^%s*([^:]+)%s*:%s*(.+)%s*$")
    return name, val, nil
end

local function process_send_commands(controller)
    if not commands_armed() then return end
    local now = os.clock()
    if (now - last_ipc_poll_clock) < IPC_POLL_INTERVAL_S then return end
    last_ipc_poll_clock = now
    local path = send_command_path()
    local f = io.open(path, "r")
    if not f then return end
    local content = f:read("*a") or ""
    f:close()
    if content == "" then return end
    pcall(os.remove, path)
    for line in content:gmatch("[^\r\n]+") do
        if line ~= "" then
            local name, val, cid = parse_send_line(line)
            if name and val then
                apply_control_value(name, val, controller, cid)
            end
        end
    end
end

-- ── HUD / DriverAid helpers ───────────────────────────────────────────────────

local function log_hud_error(label, err)
    print(string.format("[TelemetryProbe] WARN %s: %s\n", label, tostring(err)))
end

-- UE4SS: cada parámetro CPF_OutParm necesita su propia tabla {}.
local function out_val(t, ...)
    if type(t) ~= "table" then return nil end
    for i = 1, select("#", ...) do
        local key = select(i, ...)
        if t[key] ~= nil then return t[key] end
    end
    for _, v in pairs(t) do
        if type(v) == "number" or type(v) == "boolean" then
            return v
        end
    end
    return nil
end

local function is_valid_num(v)
    if type(v) ~= "number" or v ~= v then return false end
    local ok, good = pcall(function()
        return v > 0 and v < SENTINEL * 0.99
    end)
    return ok and good == true
end

local function scalar_ms(node)
    local n = unwrap_number(node)
    if type(n) == "number" then
        return is_valid_num(n) and n or nil
    end
    if type(node) == "table" then
        local v = out_val(node, "value", "Value")
        return is_valid_num(v) and v or nil
    end
    return nil
end

local function read_speed(actor)
    local result = {}
    actor:HUD_GetSpeed(result)
    return out_val(result, "Speed (ms)")
end

local function read_power(actor)
    local power, isNegative = {}, {}
    actor:HUD_GetPowerHandle(power, {}, isNegative)
    return out_val(power, "Power"), out_val(isNegative, "IsNegative") == true
end

local function read_brake_handle(actor, method)
    local handle = {}
    actor[method](actor, handle, {})
    return out_val(handle, "HandlePosition")
end

local function read_accel(actor)
    local result = {}
    actor:HUD_GetAcceleration(result)
    return out_val(result, "Acceleration (ms2)")
end

local function read_max_speed(actor)
    local maxSpeed, isActive = {}, {}
    actor:HUD_GetMaxPermittedSpeed(maxSpeed, {}, isActive)
    if out_val(isActive, "IsActive") then
        return out_val(maxSpeed, "MaxSpeed (ms)")
    end
    return nil
end

local function power_to_notch(power, power_neg)
    if power == nil then return nil end
    local p = tonumber(power) or 0
    if power_neg then p = -math.abs(p) end
    return math.max(0, math.min(8, 4 + math.floor(p + 0.5)))
end

read_hud_lever_notch = function(controller)
    if not controller or not controller.IsValid or not controller:IsValid() then
        return nil
    end
    local ok_actor, actor = pcall(function() return controller:GetDrivableActor() end)
    if not ok_actor or not actor or not actor.IsValid or not actor:IsValid() then
        return nil
    end
    local ok, power, power_neg = pcall(function() return read_power(actor) end)
    if ok and power ~= nil then
        return power_to_notch(power, power_neg == true)
    end
    return nil
end

local function door_state_from_id(id)
    if not id then return nil end
    local mid = string.lower(tostring(id))
    if mid == "dmi-doors-open" or mid == "doors-open" or mid == "door-open" then
        return true
    end
    if mid == "dmi-doors-closed" or mid == "doors-closed" or mid == "door-closed" then
        return false
    end
    if string.find(mid, "door", 1, true) and string.find(mid, "open", 1, true)
        and not string.find(mid, "clos", 1, true) then
        return true
    end
    if string.find(mid, "door", 1, true) and string.find(mid, "clos", 1, true) then
        return false
    end
    return nil
end

local function scan_door_messages(msgs)
    if msgs == nil then return nil end
    local found = nil
    foreach_container(msgs, function(m)
        local id
        pcall(function()
            id = m.id or m.Id or m.messageId or m.MessageId
        end)
        found = door_state_from_id(id)
        if found ~= nil then return false end
    end)
    return found
end

local function read_door_component_value(door_comp)
    if not door_comp or not door_comp.IsValid or not door_comp:IsValid() then
        return nil
    end
    local ok, v = pcall(function() return door_comp.CurrentInputValue end)
    if ok and type(v) == "number" then return v end
    ok, v = pcall(function() return door_comp:GetCurrentInputValue() end)
    if ok and type(v) == "number" then return v end
    return nil
end

local DOOR_COMPONENT_NAMES = {
    "PassengerDoor_FL", "PassengerDoor_FR",
    "PassengerDoor_BL", "PassengerDoor_BR",
    "Door_PassengerDoor_BL", "Door_PassengerDoor_BR",
}

local function read_passenger_doors(actor)
    local any_open = false
    local any_read = false
    for _, name in ipairs(DOOR_COMPONENT_NAMES) do
        local ok, door = pcall(function() return actor[name] end)
        if ok and door and door.IsValid and door:IsValid() then
            local v = read_door_component_value(door)
            if v ~= nil then
                any_read = true
                if v > 0.0 then
                    any_open = true
                end
            end
        end
    end
    if any_open then
        return true
    end
    if any_read then
        return false
    end
    return nil
end

local function extract_doors_dmi(driverAid)
    if type(driverAid) ~= "table" then return nil end
    -- No recorrer Messages (TArray) cada tick: Find/Get en ReceiveTick tira el juego.
    local facts = driverAid.Facts or driverAid.facts
    if type(facts) == "table" then
        local raw = facts.doors_open or facts.doorsOpen or facts.DoorsOpen
        if type(raw) == "table" then raw = raw.value or raw.Value end
        if type(raw) == "boolean" then return raw end
        if type(raw) == "number" then return raw ~= 0 end
    end
    local direct = driverAid.bDoorsOpen or driverAid.DoorsOpen or driverAid.doors_open
    if type(direct) == "boolean" then return direct end
    if type(direct) == "table" then
        local v = direct.value or direct.Value
        if type(v) == "boolean" then return v end
    end
    return nil
end

local function dump_driver_aid(driverAid)
    local parts = {}
    for k, v in pairs(driverAid) do
        if type(v) == "table" then
            local inner = {}
            for ik, iv in pairs(v) do
                table.insert(inner, tostring(ik) .. "=" .. tostring(iv))
            end
            table.insert(parts, string.format("%s={%s}", tostring(k), table.concat(inner, ",")))
        else
            table.insert(parts, string.format("%s=%s", tostring(k), tostring(v)))
        end
    end
    print("[TelemetryProbe] DriverAid dump: " .. table.concat(parts, " | ") .. "\n")
end

local function pick_float(...)
    for i = 1, select("#", ...) do
        local n = unwrap_number(select(i, ...))
        if type(n) == "number" then return n end
    end
    return nil
end

-- Un cartel: escalares del padre. NextSpeedLimits[] es UScriptStruct sin floats
-- en el tick (lim2 aparcado; docs/DRIVERAID_API.md).
local function extract_speed_limits(driverAid)
    local dist_cm = pick_float(
        driverAid.DistanceToNextSpeedLimit,
        driverAid.distanceToNextSpeedLimit)
    local limit_ms = scalar_ms(driverAid.nextSpeedLimit or driverAid.NextSpeedLimit)
    if not is_valid_num(dist_cm) or not limit_ms then
        return {}
    end
    if dist_cm <= 0 then
        return {}
    end
    return { dist_limit_cm = dist_cm, next_limit_ms = limit_ms }
end

local function extract_gradient(driverAid)
    if type(driverAid) ~= "table" then return nil end
    for _, key in ipairs({"gradient", "Gradient", "gradient_percent"}) do
        local g = driverAid[key]
        if type(g) == "number" then return g end
        if type(g) == "table" then
            local nested = out_val(g, "Value", "value")
            if nested ~= nil then return nested end
        end
    end
    return nil
end

local function read_driver_aid(controller, debug_dump)
    local driverAid = {}
    controller:GetDriverAidData(driverAid)
    if debug_dump then
        dump_driver_aid(driverAid)
    end
    local speedLimit = scalar_ms(driverAid.SpeedLimit or driverAid.speedLimit)
    local planning = extract_speed_limits(driverAid)
    local doors_dmi = extract_doors_dmi(driverAid)
    return speedLimit, extract_gradient(driverAid), planning, doors_dmi
end

local function read_odometer_m(actor)
    local ok, v = pcall(function()
        local sim = actor.Simulation
        if sim and sim.Axle_1_1 then
            return sim.Axle_1_1.TotalDistanceTravelled_M
        end
        return nil
    end)
    if ok and type(v) == "number" and v == v and v >= 0 then
        return v
    end
    return nil
end

-- Presión cilindro freno servicio (BAR). Validado en juego Class 323 2026-08-26:
-- ~1 BAR reposo, ~5+ BAR con B1–B3. HUD_GetTractiveEffort devuelve 0 siempre.
local BRAKE_CYL_NAMES = { "BrakeCylinder_2_1", "BrakeCylinder_Direct_P", "BrakeCylinder_1_1" }

local function read_brake_cylinder_bar(actor)
    local ok, v = pcall(function()
        local sim = actor.Simulation
        if not sim then return nil end
        for _, name in ipairs(BRAKE_CYL_NAMES) do
            local cyl = sim[name]
            if cyl and type(cyl.Pressure_BAR) == "number" and cyl.Pressure_BAR == cyl.Pressure_BAR then
                return cyl.Pressure_BAR
            end
        end
        return nil
    end)
    if ok and type(v) == "number" and v == v and v >= 0 then
        return v
    end
    return nil
end

local function read_vehicle_class(actor)
    local classObj = actor:GetClass()
    if classObj and classObj:IsValid() then
        return classObj:GetFName():ToString()
    end
    return "?"
end

-- ── Muestra / escritura ───────────────────────────────────────────────────────

local function fmt_num(v)
    if v == nil then return "?" end
    return string.format("%.6g", v)
end

local PLANNING_FIELDS = {
    "dist_limit_cm", "next_limit_ms", "odo_m",
}

local function build_line(sample)
    local parts = {
        "seq=" .. tostring(sample.seq),
        "speed_ms=" .. fmt_num(sample.speed_ms),
        "power=" .. fmt_num(sample.power),
        "power_neg=" .. (sample.power_neg and "1" or "0"),
        "handle_notch=" .. fmt_num(sample.handle_notch),
        "lever_notch=" .. fmt_num(sample.lever_notch),
        "last_cmd_id=" .. tostring(sample.last_cmd_id or 0),
        "last_ack_ok=" .. (sample.last_ack_ok and "1" or "0"),
        "train_brake=" .. fmt_num(sample.train_brake),
        "loco_brake=" .. fmt_num(sample.loco_brake),
        "dyn_brake=" .. fmt_num(sample.dyn_brake),
        "accel_ms2=" .. fmt_num(sample.accel_ms2),
        "brake_cyl_bar=" .. fmt_num(sample.brake_cyl_bar),
        "max_speed_ms=" .. fmt_num(sample.max_speed_ms),
        "speed_limit_ms=" .. fmt_num(sample.speed_limit_ms),
        "gradient_pct=" .. fmt_num(sample.gradient_pct),
        "vehicle=" .. (sample.vehicle or "?"),
    }
    for _, key in ipairs(PLANNING_FIELDS) do
        if sample[key] ~= nil then
            table.insert(parts, key .. "=" .. fmt_num(sample[key]))
        end
    end
    if sample.doors_telem ~= nil then
        table.insert(parts, "doors_telem=" .. (sample.doors_telem and "1" or "0"))
    end
    if sample.doors_dmi ~= nil then
        table.insert(parts, "doors_dmi=" .. (sample.doors_dmi and "1" or "0"))
    end
    return table.concat(parts, " ")
end

local function write_line(line)
    if not ensure_bridge_dir() then
        return false
    end
    local f = io.open(bridge_path(), "w")
    if not f then
        print("[TelemetryProbe] ERROR: cannot open " .. bridge_path() .. "\n")
        return false
    end
    f:write(line .. "\n")
    f:close()
    return true
end

local function safe_read(label, fn)
    local ok, result = pcall(fn)
    if not ok then
        log_hud_error(label, result)
        return nil
    end
    return result
end

local function apply_driver_aid(sample, controller, debug_driver_aid, actor)
    local ok, speed_limit, gradient, planning, doors_dmi = pcall(function()
        return read_driver_aid(controller, debug_driver_aid)
    end)
    if not ok then
        log_hud_error("driver_aid", speed_limit)
        return
    end
    sample.speed_limit_ms = speed_limit
    sample.gradient_pct = gradient
    if doors_dmi ~= nil then
        sample.doors_dmi = doors_dmi
    end
    if type(planning) == "table" then
        sample.dist_limit_cm = planning.dist_limit_cm
        sample.next_limit_ms = planning.next_limit_ms
        if not limitsLogged then
            limitsLogged = true
            print(string.format(
                "[TelemetryProbe] limit dist_cm=%s next_ms=%s\n",
                tostring(planning.dist_limit_cm),
                tostring(planning.next_limit_ms)))
        end
    end
end

local function collect_sample(controller, debug_driver_aid)
    local sample = { seq = seq, vehicle = "?", power_neg = false }

    local actor = controller:GetDrivableActor()
    if not actor or not actor:IsValid() then
        return sample, "no_drivable"
    end

    sample.speed_ms = safe_read("speed", function() return read_speed(actor) end)
    do
        local ok, power, power_neg = pcall(function() return read_power(actor) end)
        if ok then
            sample.power = power
            sample.power_neg = power_neg == true
        else
            log_hud_error("power", power)
        end
    end
    sample.train_brake = safe_read("train_brake", function()
        return read_brake_handle(actor, "HUD_GetTrainBrakeHandle")
    end)
    sample.loco_brake = safe_read("loco_brake", function()
        return read_brake_handle(actor, "HUD_GetLocomotiveBrakeHandle")
    end)
    sample.dyn_brake = safe_read("dyn_brake", function()
        return read_brake_handle(actor, "HUD_GetElectricBrakeHandle")
    end)
    sample.accel_ms2 = safe_read("accel", function() return read_accel(actor) end)
    sample.brake_cyl_bar = safe_read("brake_cyl", function() return read_brake_cylinder_bar(actor) end)
    sample.odo_m = safe_read("odo", function() return read_odometer_m(actor) end)
    sample.max_speed_ms = safe_read("max_speed", function() return read_max_speed(actor) end)
    sample.handle_notch = power_to_notch(sample.power, sample.power_neg)
    sample.lever_notch = safe_read("lever", function() return read_lever_notch(controller) end)
    sample.last_cmd_id = last_cmd_id
    sample.last_ack_ok = last_ack_ok
    local doors_telem = safe_read("doors_telem", function() return read_passenger_doors(actor) end)
    if doors_telem ~= nil then
        sample.doors_telem = doors_telem
    end
    apply_driver_aid(sample, controller, debug_driver_aid, actor)
    sample.vehicle = safe_read("vehicle", function() return read_vehicle_class(actor) end) or "?"

    if not debugDumped and sample.power ~= nil then
        debugDumped = true
        print(string.format(
            "[TelemetryProbe] OK power=%s train=%s loco=%s dyn=%s grad=%s\n",
            tostring(sample.power),
            tostring(sample.train_brake),
            tostring(sample.loco_brake),
            tostring(sample.dyn_brake),
            tostring(sample.gradient_pct)))
    end

    return sample, nil
end

local function maybe_write(controller, force)
    if not probeEnabled and not force then return end
    local now = os.clock()
    if not force and (now - lastWriteClock) < WRITE_INTERVAL_S then return end

    seq = seq + 1
    local t0 = os.clock()
    local sample, err = collect_sample(controller, force)
    if err == "no_drivable" then return end

    local line = build_line(sample)
    write_line(line)
    perfWrites = perfWrites + 1
    perfWorkS = perfWorkS + (os.clock() - t0)
    lastWriteClock = now

    if force or (now - lastLogClock) >= LOG_INTERVAL_S then
        local span = now - lastLogClock
        if lastLogClock <= 0 then span = LOG_INTERVAL_S end
        local avg_ms = 0
        if perfWrites > 0 then
            avg_ms = (perfWorkS / perfWrites) * 1000
        end
        local hz = 0
        if span > 0.001 then hz = perfWrites / span end
        print("[TelemetryProbe] " .. line .. "\n")
        print(string.format(
            "[TelemetryProbe] perf writes=%d avg_ms=%.2f hz=%.1f span=%.2fs\n",
            perfWrites, avg_ms, hz, span))
        perfWrites = 0
        perfWorkS = 0
        lastLogClock = now
    end
end

-- ── Hooks / teclas ────────────────────────────────────────────────────────────

local function register_hook()
    if hooked then return end
    hookPre, hookPost = RegisterHook(HOOK_PATH, function(self)
        if not probeEnabled then return end
        local controller = self:get()
        if not controller or not controller:IsValid() then return end
        process_send_commands(controller)
        maybe_write(controller, false)
    end)
    hooked = true
    print("[TelemetryProbe] Hook registered\n")
end

local function unregister_hook()
    if not hooked then return end
    UnregisterHook(HOOK_PATH, hookPre, hookPost)
    hooked = false
    hookPre, hookPost = nil, nil
    print("[TelemetryProbe] Hook unregistered\n")
end

local function reset_session_state()
    seq = 0
    lastWriteClock = 0
    lastLogClock = 0
    perfWrites = 0
    perfWorkS = 0
    last_ipc_poll_clock = 0
    debugDumped = false
    limitsLogged = false
    driver_input_dumped = false
end

RegisterInitGameStatePreHook(function()
    unregister_hook()
    purge_ipc_files()
    reset_session_state()
end)

local lastF7Clock = 0

local function set_probe_enabled(on)
    probeEnabled = on == true
    print("[TelemetryProbe] " .. (probeEnabled and "ENABLED" or "DISABLED") .. "\n")
    if probeEnabled then
        clear_control_lookup_cache()
        register_hook()
    end
    -- F7 OFF: el hook sigue, ReceiveTick sale al instante. UnregisterHook cada
    -- pulsación (UE4SS dispara F7 al pulsar y al soltar) tira el framerate.
end

RegisterInitGameStatePostHook(function()
    ensure_bridge_dir()
    if PROBE_AUTO_START then
        ExecuteInGameThread(function()
            set_probe_enabled(true)
            print("[TelemetryProbe] AUTO-START activo (F7 para apagar en juego libre)\n")
        end)
    else
        print("[TelemetryProbe] F7 probe/autopilot · F9 dump controles · F7 OFF jugar normal\n")
    end
end)

RegisterKeyBind(Key.F7, {}, function()
    ExecuteInGameThread(function()
        local now = os.clock()
        if (now - lastF7Clock) < 0.35 then
            return
        end
        lastF7Clock = now
        set_probe_enabled(not probeEnabled)
    end)
end)

RegisterKeyBind(Key.F8, {}, function()
    ExecuteInGameThread(function()
        local controller = UEHelpers.GetPlayerController()
        maybe_write(controller, true)
        print("[TelemetryProbe] Manual dump -> " .. bridge_path() .. "\n")
    end)
end)

RegisterKeyBind(Key.F9, {}, function()
    ExecuteInGameThread(function()
        driver_input_dumped = false
        pbh_setter_names = nil
        pbh_ufn_dumped = false
        pbh_map_dumped = false
        pbh_axis_by_notch = nil
        local controller = UEHelpers.GetPlayerController()
        dump_driver_input_inventory(controller, "F9")
    end)
end)
