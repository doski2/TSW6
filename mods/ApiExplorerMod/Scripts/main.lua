local UEHelpers = require("UEHelpers")
local config = require("config")
local bridge = require("bridge")
local context = require("context")
local modes = require("modes")

print("[ApiExplorer] Mod loaded " .. config.BUILD .. " (lab only)\n")

local last_key_at = {}

local function debounced(key)
    local now = os.clock()
    local prev = last_key_at[key] or 0
    if (now - prev) < config.KEY_DEBOUNCE_S then
        return false
    end
    last_key_at[key] = now
    return true
end

local function run_mode(mode_name)
    ExecuteInGameThread(function()
        local ctx = context.collect(UEHelpers)
        if not ctx.in_cab then
            local msg = ctx.errors[1] or "not in cab"
            print("[ApiExplorer] skip " .. mode_name .. ": " .. msg .. "\n")
            return
        end
        local fn = modes[mode_name]
        if not fn then
            print("[ApiExplorer] unknown mode " .. tostring(mode_name) .. "\n")
            return
        end
        fn(ctx)
    end)
end

RegisterInitGameStatePostHook(function()
    bridge.reset_session()
    print("[ApiExplorer] F5 HUD · F6 controls · F7 DriverAid\n")
    print("[ApiExplorer] Shift+F5 formation · Shift+F6 reflect · Shift+F7 correlate\n")
    print("[ApiExplorer] (F10 = consola UE4SS ConsoleEnablerMod — no usar para lab)\n")
    print("[ApiExplorer] Lab dir: " .. config.lab_root() .. "\n")
    print("[ApiExplorer] Disable this mod when running autopilot (TelemetryProbeMod only)\n")
end)

-- F5–F7: libres con probe OFF; evita F10 (ConsoleEnablerMod en mods.txt)
RegisterKeyBind(Key.F5, {}, function()
    if debounced("F5") then run_mode("hud_batch") end
end)

RegisterKeyBind(Key.F6, {}, function()
    if debounced("F6") then run_mode("controls") end
end)

RegisterKeyBind(Key.F7, {}, function()
    if debounced("F7") then run_mode("driver_aid") end
end)

RegisterKeyBind(Key.F5, { ModifierKey.SHIFT }, function()
    if debounced("Shift+F5") then run_mode("formation") end
end)

RegisterKeyBind(Key.F6, { ModifierKey.SHIFT }, function()
    if debounced("Shift+F6") then run_mode("reflect_shallow") end
end)

RegisterKeyBind(Key.F7, { ModifierKey.SHIFT }, function()
    if debounced("Shift+F7") then run_mode("correlate_tick") end
end)
