-- TelemetryProbeMod — telemetría + mandos IPC (SendCommand.txt)
-- Lectura: GetData.txt (~20 Hz) · Escritura: SendCommand.txt (allowlist frenos)
-- F7 on/off probe · F8 volcar línea al log

local UEHelpers = require("UEHelpers")

print("[TelemetryProbe] Mod loaded\n")

local HOOK_PATH = "/Game/Core/Player/TS2DefaultPlayerController.TS2DefaultPlayerController_C:ReceiveTick"
local WRITE_INTERVAL_S = 0.05  -- ~20 Hz
local LOG_INTERVAL_S = 2.0

local probeEnabled = true
local bridgeReady = false
local seq = 0
local lastWriteClock = 0
local lastLogClock = 0
local hooked = false
local hookPre, hookPost
local debugDumped = false

-- Planning: no bajar distancias si el tren no avanzó (odómetro / pausa ESC).
local last_odo_m = nil
local last_actor_pos = nil
local held_dist_limit_cm = nil
local held_next_limit_ms = nil
local held_dist_limit2_cm = nil
local held_next_limit2_ms = nil
local MOVE_THRESH_CM2 = 2500
local ODO_MOVE_THRESH_M = 0.05

local SEND_COMMAND_FILE = "SendCommand.txt"
local APPLY_FLAG_FILE = "TSW6ApplyCommands.flag"
local SEND_ACK_FILE = "SendCommandAck.txt"
local control_cache = {}
local last_applied = {}

local ALLOWED_CONTROLS = {
    PowerBrakeHandle = true,
    AutomaticBrake = true,
    IndependentBrake = true,
    DynamicBrake = true,
    TrainBrake = true,
    LocomotiveBrake = true,
}

local LEVER_TYPES = {
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

local function ensure_bridge_dir()
    if bridgeReady then
        return true
    end
    local dir = bridge_dir()
    local f = io.open(dir .. "\\GetData.txt", "a")
    if f then
        f:close()
        bridgeReady = true
        return true
    end
    os.execute('mkdir "' .. dir .. '" 2>nul')
    bridgeReady = true
    return io.open(dir .. "\\GetData.txt", "a") ~= nil
end

-- ── IPC mandos ───────────────────────────────────────────────────────────────

local function commands_armed()
    local f = io.open(apply_flag_path(), "r")
    if f then
        f:close()
        return true
    end
    return false
end

local function purge_ipc_files()
    pcall(os.remove, send_command_path())
    pcall(os.remove, apply_flag_path())
    for k in pairs(control_cache) do control_cache[k] = nil end
    for k in pairs(last_applied) do last_applied[k] = nil end
end

local function clamp_num(v, lo, hi)
    if v < lo then return lo end
    if v > hi then return hi end
    return v
end

local function api_value_to_input(control_name, value)
    if control_name == "IndependentBrake" then
        return clamp_num(value, -1.0, 1.0)
    end
    return (clamp_num(value, 0.0, 1.0) - 0.5) * 2.0
end

local function lever_input_value(control_name, api_value)
    local num = tonumber(api_value)
    if num == nil then return nil end
    if control_name == "IndependentBrake" then
        return clamp_num(num, -1.0, 1.0)
    end
    -- PowerBrakeHandle UK: API 0..1 (notch/8) → eje -1..1 (neutro @ 0.5)
    return (clamp_num(num, 0.0, 1.0) - 0.5) * 2.0
end

local function write_send_ack(name, value, ok)
    ensure_bridge_dir()
    local f = io.open(send_ack_path(), "w")
    if not f then return end
    f:write(string.format("%s:%.4f:%s\n", name, value, ok and "ok" or "fail"))
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

local function find_control(name, controller)
    local cached = control_cache[name]
    if cached and cached:IsValid() then
        return cached
    end
    local function cache_and_return(lever)
        control_cache[name] = lever
        return lever
    end
    if controller and controller.IsValid and controller:IsValid() then
        local di = try_child(controller, "DriverInput")
        if di then
            local lever = try_child(di, name)
            if lever then return cache_and_return(lever) end
        end
        local ok_actor, actor = pcall(function() return controller:GetDrivableActor() end)
        if ok_actor and actor and actor.IsValid and actor:IsValid() then
            di = try_child(actor, "DriverInput")
            if di then
                local lever = try_child(di, name)
                if lever then return cache_and_return(lever) end
            end
        end
    end
    local ok_di, driverInput = pcall(function() return FindFirstOf("DriverInput") end)
    if ok_di and driverInput and driverInput.IsValid and driverInput:IsValid() then
        local lever = try_child(driverInput, name)
        if lever then return cache_and_return(lever) end
    end
    for _, typename in ipairs(LEVER_TYPES) do
        local objs = FindAllOf(typename)
        if objs then
            for _, obj in pairs(objs) do
                if obj and obj.IsValid and obj:IsValid() then
                    local ok, obj_name = pcall(function()
                        return obj:GetName():ToString()
                    end)
                    if ok and obj_name and (
                        string.find(obj_name, name, 1, true)
                        or (name == "PowerBrakeHandle"
                            and string.find(obj_name, "PowerBrake", 1, true))
                    ) then
                        return cache_and_return(obj)
                    end
                end
            end
        end
    end
    return nil
end

local function apply_control_value(name, value, controller)
    if not ALLOWED_CONTROLS[name] then return false end
    local num = tonumber(value)
    if num == nil then return false end
    -- No omitir por last_applied: la telemetría puede ir retrasada y el
    -- mando no haberse movido aunque Lua escribiera la propiedad.
    local ctrl = find_control(name, controller)
    if not ctrl then
        print("[TelemetryProbe] WARN control not found: " .. name .. "\n")
        write_send_ack(name, num, false)
        return false
    end
    local input_val = lever_input_value(name, num)
    local ok, err = pcall(function()
        if name == "PowerBrakeHandle" or name == "IndependentBrake" then
            if ctrl.InputValue ~= nil then
                ctrl.InputValue = input_val
            elseif ctrl.Value ~= nil then
                ctrl.Value = num
            else
                error("no writable property")
            end
        elseif ctrl.Value ~= nil then
            ctrl.Value = num
        elseif ctrl.InputValue ~= nil then
            ctrl.InputValue = input_val or num
        else
            error("no writable property")
        end
    end)
    if ok then
        last_applied[name] = num
        write_send_ack(name, num, true)
        return true
    end
    print(string.format(
        "[TelemetryProbe] WARN set %s=%.4f failed: %s\n", name, num, tostring(err)))
    write_send_ack(name, num, false)
    return false
end

local function process_send_commands(controller)
    if not commands_armed() then return end
    local path = send_command_path()
    local opened = false
    for line in io.lines(path) do
        opened = true
        if line ~= "" then
            local name, val = string.match(line, "^%s*([^:]+)%s*:%s*(.+)%s*$")
            if name and val then
                apply_control_value(name, val, controller)
            end
        end
    end
    if opened then
        pcall(os.remove, path)
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
    return type(v) == "number" and v == v and v > 0 and v < SENTINEL * 0.99
end

local function scalar_ms(node)
    if type(node) == "number" then
        return is_valid_num(node) and node or nil
    end
    if type(node) == "table" then
        local v = out_val(node, "value", "Value")
        return v and is_valid_num(v) and v or nil
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
    if type(msgs) ~= "table" then return nil end
    local function check_one(m)
        if type(m) ~= "table" then return nil end
        return door_state_from_id(m.id or m.Id or m.messageId or m.MessageId)
    end
    for _, m in ipairs(msgs) do
        local st = check_one(m)
        if st ~= nil then return st end
    end
    for _, m in pairs(msgs) do
        local st = check_one(m)
        if st ~= nil then return st end
    end
    return nil
end

local function read_door_component_value(door_comp)
    if not door_comp or not door_comp.IsValid or not door_comp:IsValid() then
        return nil
    end
    local result = {}
    local ok = pcall(function()
        door_comp:GetCurrentInputValue(result)
    end)
    if ok then
        local v = out_val(result, "ReturnValue")
        if type(v) == "number" then return v end
    end
    result = {}
    ok = pcall(function()
        door_comp:GetCurrentOutputValue(result)
    end)
    if ok then
        local v = out_val(result, "ReturnValue")
        if type(v) == "number" then return v end
    end
    return nil
end

local DOOR_COMPONENT_NAMES = {
    "PassengerDoor_FL", "PassengerDoor_FR",
    "PassengerDoor_BL", "PassengerDoor_BR",
    "Door_PassengerDoor_BL", "Door_PassengerDoor_BR",
}

local function read_passenger_doors(actor)
    local any_read = false
    for _, name in ipairs(DOOR_COMPONENT_NAMES) do
        local ok, door = pcall(function() return actor[name] end)
        if ok and door and door.IsValid and door:IsValid() then
            local v = read_door_component_value(door)
            if v ~= nil then
                any_read = true
                if v > 0.0 then
                    return true
                end
            end
        end
    end
    if any_read then
        return false
    end
    return nil
end

local function extract_doors_dmi(driverAid)
    if type(driverAid) ~= "table" then return nil end
    for _, key in ipairs({"Messages", "messages", "AppMessages", "app_messages"}) do
        local st = scan_door_messages(driverAid[key])
        if st ~= nil then return st end
    end
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

local function collect_limit_entries(driverAid)
    local entries = {}
    local dist_cm = driverAid.distanceToNextSpeedLimit or driverAid.DistanceToNextSpeedLimit
    local next_ms = scalar_ms(driverAid.nextSpeedLimit or driverAid.NextSpeedLimit)
    if is_valid_num(dist_cm) and next_ms then
        table.insert(entries, { dist_cm = dist_cm, limit_ms = next_ms })
    end
    local arr = driverAid.nextSpeedLimits or driverAid.NextSpeedLimits
    if type(arr) ~= "table" then
        return entries
    end
    local items = {}
    for _, item in ipairs(arr) do
        table.insert(items, item)
    end
    if #items == 0 then
        for _, item in pairs(arr) do
            if type(item) == "table" then
                table.insert(items, item)
            end
        end
    end
    for _, item in ipairs(items) do
        local d = item.distanceToNextSpeedLimit or item.DistanceToNextSpeedLimit
        local ms = scalar_ms(item.value or item.Value)
        if is_valid_num(d) and ms then
            table.insert(entries, { dist_cm = d, limit_ms = ms })
        end
    end
    return entries
end

local function dedupe_limits(entries)
    table.sort(entries, function(a, b) return a.dist_cm < b.dist_cm end)
    local out = {}
    for _, e in ipairs(entries) do
        local dup = false
        for _, prev in ipairs(out) do
            if math.abs(prev.dist_cm - e.dist_cm) <= 800 then
                dup = true
                break
            end
        end
        if not dup then
            table.insert(out, e)
        end
    end
    return out
end

local function extract_speed_limits(driverAid)
    local out = dedupe_limits(collect_limit_entries(driverAid))
    local planning = {}
    if out[1] then
        planning.dist_limit_cm = out[1].dist_cm
        planning.next_limit_ms = out[1].limit_ms
    end
    if out[2] then
        planning.dist_limit2_cm = out[2].dist_cm
        planning.next_limit2_ms = out[2].limit_ms
    end
    -- En cartel (dist=0): usar el siguiente de la cola.
    if planning.dist_limit_cm and planning.dist_limit_cm <= 0 then
        planning.dist_limit_cm = nil
        planning.next_limit_ms = nil
        if out[2] then
            planning.dist_limit_cm = out[2].dist_cm
            planning.next_limit_ms = out[2].limit_ms
            planning.dist_limit2_cm = out[3] and out[3].dist_cm or nil
            planning.next_limit2_ms = out[3] and out[3].limit_ms or nil
        end
    end
    return planning
end

local function extract_gradient(driverAid)
    if type(driverAid) ~= "table" then return nil end
    local g = driverAid.gradient or driverAid.Gradient
    if type(g) == "number" then return g end
    if type(g) == "table" then
        return out_val(g, "Value", "value")
    end
    for k, v in pairs(driverAid) do
        if type(k) == "string" and string.find(string.lower(k), "grad", 1, true) then
            if type(v) == "number" then return v end
            if type(v) == "table" then
                local nested = out_val(v, "Value", "value")
                if nested ~= nil then return nested end
            end
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

local function actor_moved_since_last(actor)
    local ok, loc = pcall(function() return actor:K2_GetActorLocation() end)
    if not ok or not loc then return true end
    if not last_actor_pos then
        last_actor_pos = { x = loc.X, y = loc.Y, z = loc.Z }
        return true
    end
    local dx = loc.X - last_actor_pos.x
    local dy = loc.Y - last_actor_pos.y
    local dz = loc.Z - last_actor_pos.z
    last_actor_pos = { x = loc.X, y = loc.Y, z = loc.Z }
    return (dx * dx + dy * dy + dz * dz) > MOVE_THRESH_CM2
end

local function train_moved_since_last(actor)
    local odo = read_odometer_m(actor)
    if odo ~= nil then
        if last_odo_m == nil then
            last_odo_m = odo
            return true
        end
        local moved = math.abs(odo - last_odo_m) > ODO_MOVE_THRESH_M
        last_odo_m = odo
        return moved
    end
    return actor_moved_since_last(actor)
end

local function hold_planning_if_stationary(sample, actor)
    if not sample.dist_limit_cm then return end
    if train_moved_since_last(actor) then
        held_dist_limit_cm = sample.dist_limit_cm
        held_next_limit_ms = sample.next_limit_ms
        held_dist_limit2_cm = sample.dist_limit2_cm
        held_next_limit2_ms = sample.next_limit2_ms
        return
    end
    if held_dist_limit_cm then
        sample.dist_limit_cm = held_dist_limit_cm
        sample.next_limit_ms = held_next_limit_ms
        sample.dist_limit2_cm = held_dist_limit2_cm
        sample.next_limit2_ms = held_next_limit2_ms
    end
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
    "dist_limit_cm", "next_limit_ms", "dist_limit2_cm", "next_limit2_ms", "odo_m",
}

local function build_line(sample)
    local parts = {
        "seq=" .. tostring(sample.seq),
        "speed_ms=" .. fmt_num(sample.speed_ms),
        "power=" .. fmt_num(sample.power),
        "power_neg=" .. (sample.power_neg and "1" or "0"),
        "handle_notch=" .. fmt_num(sample.handle_notch),
        "train_brake=" .. fmt_num(sample.train_brake),
        "loco_brake=" .. fmt_num(sample.loco_brake),
        "dyn_brake=" .. fmt_num(sample.dyn_brake),
        "accel_ms2=" .. fmt_num(sample.accel_ms2),
        "max_speed_ms=" .. fmt_num(sample.max_speed_ms),
        "speed_limit_ms=" .. fmt_num(sample.speed_limit_ms),
        "gradient_pct=" .. fmt_num(sample.gradient_pct),
        "vehicle=" .. (sample.vehicle or "?"),
    }
    for _, key in ipairs(PLANNING_FIELDS) do
        if sample[key] then
            table.insert(parts, key .. "=" .. fmt_num(sample[key]))
        end
    end
    if sample.doors_open ~= nil then
        table.insert(parts, "doors_open=" .. (sample.doors_open and "1" or "0"))
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
    ensure_bridge_dir()
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
        sample.dist_limit2_cm = planning.dist_limit2_cm
        sample.next_limit2_ms = planning.next_limit2_ms
        hold_planning_if_stationary(sample, actor)
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
    sample.odo_m = safe_read("odo", function() return read_odometer_m(actor) end)
    sample.max_speed_ms = safe_read("max_speed", function() return read_max_speed(actor) end)
    sample.handle_notch = power_to_notch(sample.power, sample.power_neg)
    local doors_telem = safe_read("doors_telem", function() return read_passenger_doors(actor) end)
    if doors_telem ~= nil then
        sample.doors_telem = doors_telem
        sample.doors_open = doors_telem
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
    local sample, err = collect_sample(controller, force)
    if err == "no_drivable" then return end

    local line = build_line(sample)
    write_line(line)
    lastWriteClock = now

    if force or (now - lastLogClock) >= LOG_INTERVAL_S then
        print("[TelemetryProbe] " .. line .. "\n")
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
    last_odo_m = nil
    last_actor_pos = nil
    held_dist_limit_cm = nil
    held_next_limit_ms = nil
    held_dist_limit2_cm = nil
    held_next_limit2_ms = nil
    debugDumped = false
end

RegisterInitGameStatePreHook(function()
    unregister_hook()
    purge_ipc_files()
    reset_session_state()
end)

RegisterInitGameStatePostHook(function()
    print("[TelemetryProbe] Starting\n")
    ensure_bridge_dir()
    register_hook()
end)

RegisterKeyBind(Key.F7, {}, function()
    ExecuteInGameThread(function()
        probeEnabled = not probeEnabled
        print("[TelemetryProbe] " .. (probeEnabled and "ENABLED" or "DISABLED") .. "\n")
        if probeEnabled then register_hook() end
    end)
end)

RegisterKeyBind(Key.F8, {}, function()
    ExecuteInGameThread(function()
        local controller = UEHelpers.GetPlayerController()
        maybe_write(controller, true)
        print("[TelemetryProbe] Manual dump -> " .. bridge_path() .. "\n")
    end)
end)
