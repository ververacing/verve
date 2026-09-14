-- Verve / lib/difficulty.lua
-- Makes the difficulty setting mean something. AC's launcher writes an AI level per car into race.ini, but on
-- the install this was calibrated on AC ignored it completely (60 and 100 gave identical lap times, 2026-09-13),
-- so "novice" career races ran at full pace. Verve applies the levels itself through physics.setAILevel, which
-- demonstrably changes pace.
--
-- Two layers:
--   * everywhere: each AI car gets the level the launcher configured for it (race.ini CAR_n AI_LEVEL, else the
--     [RACE] level) -- so 80 on the slider is a slower field than 100, as everyone expects;
--   * CAREER events (optional, on by default): the launcher's meter picks a BAND of pace relative to expert
--     pace, and the event's position on AC's own career ramp (80 at Novice 1 -> 97 at the top) slides the field
--     from the band's easy end to its hard end. A beginner leaves the meter at 80 and gets a soft first series
--     and a real fight at the end, never leaving beginner territory; 100 is for the very best.
--
-- CALIBRATION STATUS: the level -> lap-time mapping (pctToLevel) is PROVISIONAL (speed ~ level). It is
-- re-fitted from the single-make calibration runs (tools/harness_results, labels vcal_*).
local Career = require('lib.career')
local D = {}
D.CAREER_CURVE = true     -- the band/ramp layer for career events (user option "careerCurve")
D.ENABLED = true

-- band edges: how many % slower than expert pace the field is at the START and END of the career, by meter
local BAND = {   -- meter -> {start_pct, end_pct}
    [100] = { 3, 0 },
    [90]  = { 8, 4 },
    [80]  = { 15, 8 },
    [70]  = { 22, 14 },
    [60]  = { 30, 20 },
}
local function bandFor(meter)
    meter = math.max(60, math.min(100, meter or 100))
    local lo = math.floor(meter / 10) * 10
    local hi = math.min(100, lo + 10)
    local a, b = BAND[lo], BAND[hi]
    if lo == hi or not b then return a[1], a[2] end
    local f = (meter - lo) / 10
    return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
end

-- MEASURED level -> lap time (single-make M3 E92 field, Nurburgring Sprint, 3 laps each, 2026-09-14;
-- blend of best and median-of-best laps, % slower than level 1.00). Two things the numbers say: the first
-- ten points barely register, and below ~0.75 the AI falls off a cliff (0.70 and 0.60 are identical: the
-- sim floors the level there, and the laps get erratic). So the usable range is 0.75..1.00, about 0..12%.
local PCT_AT_LEVEL = { [100] = 0.0, [90] = 1.5, [80] = 6.7, [75] = 11.5, [70] = 16.6 }
local LEVEL_MIN = 0.72
-- % slower than expert -> AI level (inverse of the table, linear between points, clamped to the usable range)
function D.pctToLevel(pct)
    pct = math.max(0, pct or 0)
    local pts = { { 100, 0.0 }, { 90, 1.5 }, { 80, 6.7 }, { 75, 11.5 }, { 70, 16.6 } }
    for k = 1, #pts - 1 do
        local l1, p1 = pts[k][1], pts[k][2]
        local l2, p2 = pts[k + 1][1], pts[k + 1][2]
        if pct <= p2 then
            local f = (p2 > p1) and (pct - p1) / (p2 - p1) or 0
            return math.max(LEVEL_MIN, (l1 + (l2 - l1) * f) / 100)
        end
    end
    return LEVEL_MIN
end
local pctToLevel = D.pctToLevel
-- and the forward direction (what a level costs), for the UI / reports
function D.levelToPct(level)
    local l = (level or 1) * 100
    local pts = { { 100, 0.0 }, { 90, 1.5 }, { 80, 6.7 }, { 75, 11.5 }, { 70, 16.6 } }
    if l >= 100 then return 0 end
    for k = 1, #pts - 1 do
        if l >= pts[k + 1][1] then
            local f = (pts[k][1] - l) / (pts[k][1] - pts[k + 1][1])
            return pts[k][2] + (pts[k + 1][2] - pts[k][2]) * f
        end
    end
    return pts[#pts][2]
end

local cache = {}          -- [i] = level
local cachedFor = nil

function D.reset() cache = {}; cachedFor = nil end

local function compute(i)
    local car = ac.getCar(i)
    if not car then return nil end
    local iniLevel = Career.carLevels[i] or Career.meter or 100        -- launcher's number for this car (0..100+)
    if Career.active and D.CAREER_CURVE then
        local startPct, endPct = bandFor(Career.meter)
        local pct = startPct + (endPct - startPct) * (Career.ramp or 0)
        local base = pctToLevel(pct)
        -- keep the event's own relative spread between opponents (86..88 => +-1%), measured against the grid's
        -- own average so a harness-forced flat grid comes out at exactly the band level
        local sum, cnt = 0, 0
        for k, v in pairs(Career.carLevels) do if k > 0 and v and v > 0 then sum = sum + v; cnt = cnt + 1 end end
        local mean = cnt > 0 and sum / cnt or (Career.eventLevel or iniLevel)
        local rel = (mean > 0 and iniLevel > 0) and (iniLevel / mean) or 1.0
        return math.max(LEVEL_MIN, math.min(1.2, base * rel))
    end
    -- outside career the launcher's number is taken as AC's own level scale, clamped out of the cliff
    return math.max(LEVEL_MIN, math.min(1.2, iniLevel / 100.0))
end

-- the level car i should run at this session (nil = leave AC's own)
function D.levelFor(i)
    if not D.ENABLED then return nil end
    local sim = ac.getSim(); if not sim then return nil end
    local idx = sim.currentSessionIndex or 0
    if cachedFor ~= idx then cache = {}; cachedFor = idx end
    local v = cache[i]
    if v == nil then v = compute(i) or false; cache[i] = v end
    return v or nil
end

function D.describe()
    if not Career.active then return string.format('Field at the configured level (%d)', Career.meter or 100) end
    if not D.CAREER_CURVE then return string.format('Career, flat: %d', Career.meter or 100) end
    local s, e = bandFor(Career.meter)
    local pct = s + (e - s) * (Career.ramp or 0)
    return string.format('Career curve: meter %d, %.0f%% into the career, field %.0f%% off expert pace', Career.meter or 100, (Career.ramp or 0) * 100, pct)
end

return D
