-- Controller, drivable actor, vehicle id.
local util = require("util")

local M = {}

function M.read_vehicle_class(actor)
    if not util.obj_valid(actor) then return "?" end
    local ok, name = pcall(function()
        return util.lua_str(actor:GetClass():GetFName())
    end)
    return (ok and name) or "?"
end

function M.collect(ue_helpers)
    local ctx = {
        in_cab = false,
        vehicle_class = "?",
        route_hint = nil,
        errors = {},
    }
    if not ue_helpers then
        ctx.errors[#ctx.errors + 1] = "UEHelpers missing"
        return ctx
    end

    local controller
    local ok_c, ctrl_or_err = pcall(function() return ue_helpers.GetPlayerController() end)
    if ok_c then controller = ctrl_or_err end
    if not util.obj_valid(controller) then
        ctx.errors[#ctx.errors + 1] = "player controller invalid"
        return ctx
    end

    local actor
    local ok_a, actor_or_err = pcall(function() return controller:GetDrivableActor() end)
    if ok_a then actor = actor_or_err end
    if not util.obj_valid(actor) then
        ctx.errors[#ctx.errors + 1] = "drivable actor invalid (not in cab?)"
        return ctx
    end

    ctx.in_cab = true
    ctx.controller = controller
    ctx.actor = actor
    ctx.vehicle_class = M.read_vehicle_class(actor)
    return ctx
end

return M
