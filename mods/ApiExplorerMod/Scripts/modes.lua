-- Orquestación de modos de captura.
local bridge = require("bridge")
local hud_batch = require("hud_batch")
local controls = require("controls")
local driver_aid = require("driver_aid")
local formation = require("formation")
local reflect = require("reflect")

local M = {}

local function finish(mode, payload, ctx)
    local ok, path = bridge.save_capture(mode, payload, ctx)
    if ok then
        print(string.format("[ApiExplorer] %s -> %s\n", mode, path))
    else
        print(string.format("[ApiExplorer] ERROR writing %s: %s\n", mode, tostring(path)))
    end
    return ok
end

function M.hud_batch(ctx)
    if not ctx.in_cab then return false end
    return finish("hud_batch", hud_batch.capture(ctx.actor), ctx)
end

function M.controls(ctx)
    if not ctx.in_cab then return false end
    return finish("controls", controls.capture(ctx.actor, ctx.controller), ctx)
end

function M.driver_aid(ctx)
    if not ctx.in_cab then return false end
    local payload = driver_aid.capture(ctx.controller)
    return finish("driver_aid", payload, ctx)
end

function M.formation(ctx)
    if not ctx.in_cab then return false end
    return finish("formation", formation.capture(ctx.actor), ctx)
end

function M.reflect_shallow(ctx)
    if not ctx.in_cab then return false end
    local payload = reflect.capture(ctx.actor, "drivable_actor")
    return finish("reflect_shallow", payload, ctx)
end

function M.correlate_tick(ctx)
    local payload = {
        status = "marker",
        message = "Run scripts/tools/api_correlator.py against this session",
        unix_hint = os.time(),
    }
    return finish("correlate_tick", payload, ctx)
end

return M
