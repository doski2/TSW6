-- TelemetryProbeMod v2 — solo I/O: GetData.txt + IPC mandos.
-- F7 on/off · F8 volcar línea al log. Dumps de inventario → ApiExplorerMod.
local config = require("config")
local bridge = require("bridge")
local telemetry = require("telemetry")
local ipc = require("ipc")

print("[TelemetryProbe] Mod loaded " .. config.PROBE_BUILD .. " (v2 modules)\n")

local probeEnabled = false
local last_controller = nil
local seq = 0
local lastWriteClock = 0
local lastLogClock = 0
local perfWrites = 0
local perfWorkS = 0
local hooked = false
local hookPre, hookPost

local state = {
    seq = 0,
    last_cmd_id = 0,
    last_ack_ok = false,
    last_ipc_poll_clock = 0,
    debug_dumped = false,
    limits_logged = false,
}

local function reset_session_state()
    seq = 0
    state.seq = 0
    state.last_cmd_id = 0
    state.last_ack_ok = false
    state.debug_dumped = false
    state.limits_logged = false
    ipc.clear_control_cache()
    bridge.purge_ipc_files()
end

local function maybe_write(controller, force)
    if not probeEnabled and not force then return end
    local now = os.clock()
    if not force and (now - lastWriteClock) < config.WRITE_INTERVAL_S then return end

    seq = seq + 1
    state.seq = seq
    local t0 = os.clock()
    local sample, err = telemetry.collect_sample(controller, state)
    if err == "no_drivable" then return end

    local line = telemetry.build_line(sample)
    bridge.write_getdata_line(line)
    perfWrites = perfWrites + 1
    perfWorkS = perfWorkS + (os.clock() - t0)
    lastWriteClock = now

    if force or (now - lastLogClock) >= config.LOG_INTERVAL_S then
        local span = now - lastLogClock
        if lastLogClock <= 0 then span = config.LOG_INTERVAL_S end
        local avg_ms = perfWrites > 0 and (perfWorkS / perfWrites) * 1000 or 0
        local hz = span > 0.001 and (perfWrites / span) or 0
        print("[TelemetryProbe] " .. line .. "\n")
        print(string.format(
            "[TelemetryProbe] perf writes=%d avg_ms=%.2f hz=%.1f span=%.2fs\n",
            perfWrites, avg_ms, hz, span))
        perfWrites = 0
        perfWorkS = 0
        lastLogClock = now
    end
end

local function register_hook()
    if hooked then return end
    hookPre, hookPost = RegisterHook(config.HOOK_PATH, function(self)
        if not probeEnabled then return end
        local controller = self:get()
        if not controller or not controller:IsValid() then return end
        last_controller = controller
        ipc.process_send_commands(controller, state)
        maybe_write(controller, false)
    end)
    hooked = true
end

local function unregister_hook()
    if not hooked then return end
    if hookPre then UnregisterHook(config.HOOK_PATH, hookPre, hookPost) end
    hookPre, hookPost = nil, nil
    hooked = false
end

local function set_probe_enabled(on)
    probeEnabled = on == true
    if probeEnabled then
        register_hook()
        print("[TelemetryProbe] probe ON (F7 toggle)\n")
    else
        unregister_hook()
        print("[TelemetryProbe] probe OFF\n")
    end
end

RegisterKeyBind(Key.F7, {}, function()
    set_probe_enabled(not probeEnabled)
end)

RegisterKeyBind(Key.F8, {}, function()
    local controller = last_controller
    if not controller or not controller.IsValid or not controller:IsValid() then
        print("[TelemetryProbe] F8: no controller (entra en cabina primero)\n")
        return
    end
    maybe_write(controller, true)
end)

reset_session_state()
bridge.ensure_bridge_dir()
if config.PROBE_AUTO_START then
    set_probe_enabled(true)
else
    print("[TelemetryProbe] F7 probe/autopilot · F8 dump línea · lab dumps en ApiExplorerMod\n")
end
