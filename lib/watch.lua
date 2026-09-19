-- lib/watch.lua -- who else is driving the AI? A write-then-read-back watchdog.
--
-- Verve writes each car's AI level (lib/drivers.lua) and aggression (lib/racecraft.lua) through CSP; CSP lets a script
-- read both back. If a value comes back different from what Verve last wrote, something else is writing it: AI
-- Whisperer, CSP's own rubber-banding, another Lua script, anything - named or not. Counted per car per variable over a
-- rolling window; steady mismatches are a CONFLICT, logged once a minute and reported to the UI and diagnostics.
-- Caution, extra grip, throttle limits, brake hints and shift thresholds are write-only in CSP, so they cannot be
-- watched this way; the pace-vs-expected check covers those indirectly. Owner's ask 2026-09-18: "flag and adjust when
-- two things influence the same variable". Adjusting (re-assert or yield) comes after the first night of readings.

local Drivers   = require('lib.drivers')
local Racecraft = require('lib.racecraft')

local W = {}
W.ENABLED  = true
W.TOL_LVL  = 0.006     -- level read-back tolerance (Verve rounds to 0.001)
W.TOL_AGG  = 0.03      -- aggression tolerance (a launcher-set value reads back x0.95; an API-set one is checked here)
W.WINDOW   = 5.0       -- seconds of readings per verdict
W.conflicts = { level = 0, aggr = 0 }   -- cars currently in conflict, per variable (UI + diag)
W.detail = ''                            -- one line for the UI
local samples = {}      -- [i] = { n, lvlBad, aggBad, t0 }
local lastLog = 0

function W.reset() samples = {}; W.conflicts = { level = 0, aggr = 0 }; W.detail = ''; lastLog = 0 end

function W.update(dt)
    if not W.ENABLED then return end
    local ok, sim = pcall(ac.getSim); if not ok or not sim then return end
    local now = os.clock()
    local lvlC, aggC = 0, 0
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and c.isAIControlled then
            local s = samples[i]
            if not s or now - s.t0 > W.WINDOW then
                if s and s.n >= 30 then
                    s.lvlVerdict = (s.lvlBad / s.n) > 0.5
                    s.aggVerdict = (s.aggBad / s.n) > 0.5
                end
                s = { n = 0, lvlBad = 0, aggBad = 0, t0 = now, lvlVerdict = s and s.lvlVerdict or false, aggVerdict = s and s.aggVerdict or false }
                samples[i] = s
            end
            local wl = Drivers.appliedLevel(i)
            local wa = Racecraft.last[i] and Racecraft.last[i].aggr
            if wl or wa then
                s.n = s.n + 1
                if wl and type(c.aiLevel) == 'number' and c.aiLevel >= 0 and math.abs(c.aiLevel - wl) > W.TOL_LVL then s.lvlBad = s.lvlBad + 1 end
                if wa and type(c.aiAggression) == 'number' and c.aiAggression >= 0 and math.abs(c.aiAggression - wa) > W.TOL_AGG then s.aggBad = s.aggBad + 1 end
            end
            if s.lvlVerdict then lvlC = lvlC + 1 end
            if s.aggVerdict then aggC = aggC + 1 end
        end
    end
    W.conflicts.level, W.conflicts.aggr = lvlC, aggC
    if lvlC > 0 or aggC > 0 then
        W.detail = string.format('Something else is changing the AI: level on %d cars, aggression on %d', lvlC, aggC)
        if now - lastLog > 60 then
            lastLog = now
            pcall(function() ac.log('Verve watch: ' .. W.detail) end)
        end
    else
        W.detail = ''
    end
end

return W
