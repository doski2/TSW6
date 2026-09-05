local config = require("config")
local util = require("util")
local bridge = require("bridge")
local telemetry = require("telemetry")

local M = {}

local control_cache = {}
local last_applied = {}

local function lever_input_value(control_name, cmd_value)
    local num = tonumber(cmd_value)
    if num == nil then return nil end
    if control_name == "IndependentBrake" then
        return util.clamp_num(num, -1.0, 1.0)
    end
    if control_name == "PowerBrakeHandle" then
        local notch = util.cmd_value_to_notch(num)
        if notch == nil then return nil end
        return util.notch_to_axis(notch)
    end
    return (util.clamp_num(num, 0.0, 1.0) - 0.5) * 2.0
end

local function get_drivable_actor(controller)
    if not controller or not controller.IsValid or not controller:IsValid() then
        return nil
    end
    local ok, actor = pcall(function() return controller:GetDrivableActor() end)
    if ok and actor and actor.IsValid and actor:IsValid() then return actor end
    return nil
end

local function collect_names_for_control(name)
    return config.CONTROL_ALIASES[name] or { name }
end

local function get_direct_actor_lever(name, controller)
    local actor = get_drivable_actor(controller)
    if not actor then return nil end
    for _, child_name in ipairs(collect_names_for_control(name)) do
        local ctrl = util.try_child(actor, child_name)
        if util.ctrl_is_valid(ctrl) then return ctrl end
    end
    return nil
end

local function find_control_on_parent(parent, names)
    if not parent then return nil end
    local di = util.try_child(parent, "DriverInput") or util.try_child(parent, "DriverInputComponent")
    if di then
        for _, child_name in ipairs(names) do
            local ctrl = util.try_child(di, child_name)
            if util.ctrl_is_valid(ctrl) then return ctrl end
        end
    end
    for _, child_name in ipairs(names) do
        local ctrl = util.try_child(parent, child_name)
        if util.ctrl_is_valid(ctrl) then return ctrl end
    end
    return nil
end

local function find_control(name, controller)
    local cached = control_cache[name]
    if util.ctrl_is_valid(cached) then return cached end
    control_cache[name] = nil
    local direct = get_direct_actor_lever(name, controller)
    if direct then
        control_cache[name] = direct
        return direct
    end
    local names = collect_names_for_control(name)
    local actor = get_drivable_actor(controller)
    local ctrl = actor and find_control_on_parent(actor, names)
    if not ctrl and controller then ctrl = find_control_on_parent(controller, names) end
    if ctrl then control_cache[name] = ctrl end
    return ctrl
end

local function hud_step_ack(hud_before, hud_after, dest, step)
    if dest == nil then return false end
    if hud_before ~= nil and hud_before == dest then
        return hud_after == nil or hud_after == dest
    end
    if hud_before == nil or hud_after == nil then return false end
    if hud_after == hud_before then return false end
    if math.abs(hud_after - dest) > math.abs(hud_before - dest) then return false end
    if math.abs(hud_after - hud_before) > 1 then
        print(string.format(
            "[TelemetryProbe] WARN PBH skip hud %s->%s (step %s dest %s)\n",
            tostring(hud_before), tostring(hud_after), tostring(step), tostring(dest)))
    end
    return true
end

local function call_method(ctrl, method, val)
    if not util.ctrl_is_valid(ctrl) then return false, "invalid_ctrl" end
    local ok, err = pcall(function() ctrl[method](ctrl, val) end)
    if ok then return true, "ok" end
    return false, tostring(err)
end

local function write_pbh_one_step(ctrl, num, controller)
    local dest = util.cmd_value_to_notch(num)
    local hud_before = telemetry.read_hud_lever_notch(controller)
    if dest == nil then return false, "bad_cmd" end
    if hud_before ~= nil and hud_before == dest then
        util.ipc_log("IPC PBH already hud=%s dest=%s", tostring(hud_before), tostring(dest))
        return true, "already"
    end
    local step = dest
    if hud_before ~= nil then
        if dest > hud_before then step = hud_before + 1
        elseif dest < hud_before then step = hud_before - 1 end
        step = math.max(0, math.min(8, step))
    end
    local out_val = step - 4
    local hud_after = hud_before
    local okc = select(1, call_method(ctrl, "SetCurrentOutputValue", out_val))
    hud_after = telemetry.read_hud_lever_notch(controller)
    if okc and (hud_before == nil or hud_step_ack(hud_before, hud_after, dest, step)) then
        return true, "SetCurrentOutputValue"
    end
    local in_val = util.notch_to_axis(step)
    if in_val == nil then return false, "no_effect" end
    if controller then
        pcall(function() controller:BeginChangingVHIDComponent(ctrl) end)
    end
    okc = select(1, call_method(ctrl, "SetCurrentInputValue", in_val))
    hud_after = telemetry.read_hud_lever_notch(controller)
    if controller then
        pcall(function() controller:EndUsingVHIDComponent(ctrl) end)
    end
    if okc and (hud_before == nil or hud_step_ack(hud_before, hud_after, dest, step)) then
        return true, "SetCurrentInputValue"
    end
    return false, "no_effect"
end

local function write_lever_control(name, ctrl, num, controller)
    if not util.ctrl_is_valid(ctrl) then return false, "invalid_ctrl" end
    if name == "PowerBrakeHandle" and config.SAFE_LEVER_WRITE then
        return write_pbh_one_step(ctrl, num, controller)
    end
    local input_val = lever_input_value(name, num)
    local ok = pcall(function() ctrl.InputValue = input_val or num end)
    if ok then return true, "InputValue" end
    ok = pcall(function() ctrl.Value = num end)
    return ok, ok and "Value" or "no_effect"
end

function M.apply_control_value(name, value, controller, cmd_id, state)
    if not config.ALLOWED_CONTROLS[name] then return false end
    local num = tonumber(value)
    if num == nil then return false end

    print(string.format(
        "[TelemetryProbe] IPC recv %s=%.4f id=%s build=%s\n",
        name, num, tostring(cmd_id or "?"), config.PROBE_BUILD))

    if config.IPC_DELEGATE_HTTP then
        if cmd_id then state.last_cmd_id = cmd_id end
        state.last_ack_ok = false
        bridge.write_send_ack(name, num, false, cmd_id)
        return false
    end

    if name == "PowerBrakeHandle" and config.SAFE_LEVER_WRITE then
        local direct = get_direct_actor_lever(name, controller)
        if not direct then
            if cmd_id then state.last_cmd_id = cmd_id end
            state.last_ack_ok = false
            bridge.write_send_ack(name, num, false, cmd_id)
            print("[TelemetryProbe] WARN direct PBH not found on drivable actor\n")
            return false
        end
        local ok, _ = write_lever_control(name, direct, num, controller)
        if cmd_id then state.last_cmd_id = cmd_id end
        if ok then
            control_cache[name] = direct
            state.last_ack_ok = true
            last_applied[name] = num
            bridge.write_send_ack(name, num, true, cmd_id)
            return true
        end
        state.last_ack_ok = false
        bridge.write_send_ack(name, num, false, cmd_id)
        return false
    end

    local ctrl = find_control(name, controller)
    if not ctrl then
        if cmd_id then state.last_cmd_id = cmd_id end
        state.last_ack_ok = false
        bridge.write_send_ack(name, num, false, cmd_id)
        print("[TelemetryProbe] WARN control not found: " .. name .. "\n")
        return false
    end

    local ok, _ = write_lever_control(name, ctrl, num, controller)
    if cmd_id then state.last_cmd_id = cmd_id end
    if ok then
        state.last_ack_ok = true
        last_applied[name] = num
        bridge.write_send_ack(name, num, true, cmd_id)
        return true
    end
    state.last_ack_ok = false
    bridge.write_send_ack(name, num, false, cmd_id)
    return false
end

function M.process_send_commands(controller, state)
    local now = os.clock()
    if (now - state.last_ipc_poll_clock) < config.IPC_POLL_INTERVAL_S then return end
    state.last_ipc_poll_clock = now
    if not bridge.commands_armed() then return end
    for _, cmd in ipairs(bridge.read_send_commands()) do
        M.apply_control_value(cmd.name, cmd.value, controller, cmd.cmd_id, state)
    end
end

function M.clear_control_cache()
    control_cache = {}
    last_applied = {}
end

return M
