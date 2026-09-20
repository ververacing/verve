-- lib/contacts.lua -- contacts from CSP's collision state, independent of the damage setting.
--
-- Until 2026-09-19 every Verve contact signal (feed incidents, telemetry, the diagnostics trace, the live fault judge)
-- came from jumps in car.damage. With damage switched off in the launcher - as at least one outside install does - those
-- jumps never happen and Verve reports a 23-car, 34-lap race as incident-free. CSP exposes the collision itself:
-- car.collisionDepth (> 0 while touching) and car.collidedWith (0 = the track, otherwise a car). This module turns the
-- rising edge of a collision into an EVENT with the other car, the speed lost and the position, once per pair per
-- 1.5 s. Consumers read events by cursor; damage jumps remain a fallback signal for builds without these fields.

local C = {}
C.ENABLED = true
local DEPTH_ON   = 0.005    -- m of collision depth that counts as touching
local DEBOUNCE   = 1.5      -- s: one event per car pair
local events = {}           -- { id, t, car, other (-1 = track), spd0, drop, lap, spline }
local nextId = 1
local touching, lastPair, spdHist = {}, {}, {}
C.count = 0                 -- events this session (UI / diag)
C.available = nil           -- true once collisionDepth has been seen as a number (field exists on this build)

function C.reset() events = {}; nextId = 1; touching = {}; lastPair = {}; spdHist = {}; C.count = 0 end

local function pairKey(a, b) if b < 0 then return a .. ':t' end; if a < b then return a .. ':' .. b end; return b .. ':' .. a end

function C.update(dt)
    if not C.ENABLED then return end
    local ok, sim = pcall(ac.getSim); if not ok or not sim then return end
    local now = os.clock()
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c then
            local depth = c.collisionDepth
            if type(depth) == 'number' then
                C.available = true
                local spd = c.speedKmh or 0
                local h = spdHist[i]
                if not h then h = { spd, spd, spd }; spdHist[i] = h end
                if depth > DEPTH_ON then
                    if not touching[i] then
                        touching[i] = true
                        local other = -1
                        local cw = c.collidedWith
                        if type(cw) == 'number' and cw > 0 then other = cw - 1 end     -- CSP: 0 = track, else car index + 1
                        if other == i then other = -1 end
                        local key = pairKey(i, other)
                        if now - (lastPair[key] or -1e9) > DEBOUNCE then
                            lastPair[key] = now
                            local spd0 = math.max(h[1], h[2], h[3])                  -- speed a few frames ago
                            events[#events + 1] = { id = nextId, t = now, car = i, other = other, spd0 = spd0,
                                                    drop = math.max(0, spd0 - spd), lap = c.lapCount or 0, spline = c.splinePosition or 0 }
                            nextId = nextId + 1; C.count = C.count + 1
                            if #events > 400 then table.remove(events, 1) end
                        end
                    end
                else
                    touching[i] = false
                end
                h[3] = h[2]; h[2] = h[1]; h[1] = spd
            end
        end
    end
end

-- events newer than `afterId`, for a consumer keeping its own cursor; returns the list and the newest id
function C.since(afterId)
    local out = {}
    for _, e in ipairs(events) do if e.id > (afterId or 0) then out[#out + 1] = e end end
    return out, (nextId - 1)
end

-- the freshest event for a car within the last `window` seconds (nil if none)
function C.recent(i, window)
    local now = os.clock()
    for k = #events, 1, -1 do
        local e = events[k]
        if e.car == i and now - e.t <= (window or 1.0) then return e end
        if now - e.t > (window or 1.0) then break end
    end
    return nil
end

return C
