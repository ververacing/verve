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
local Classes = require('lib.classes')
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

-- MEASURED level -> lap time, % slower than level 100, per car class (median of per-car best laps, 8-car veteran
-- fields, 4-lap sprints, 2026-09-21: GT3 at Spa, SF70H at Barcelona, Giulia QV at Magione; the single-make M3 E92
-- Nurburgring row of 2026-09-14 kept for touring cars). Every car type has the same shape: the first ten points
-- cost 0-2 %, 85 costs 4-8 %, and 80 falls off a cliff (15-20 % on race cars), below which the laps get erratic.
-- So the raw AC scale is not what the labels say: 80 is not "a bit slower than 90". These curves let the slider
-- mean lap-time steps instead (D.SLIDER_CURVE): 100 = expert pace, 90 = +5 %, 80 = +10 %, 70 = +15 %.
local CURVES = {
    gt      = { { 100, 0.0 }, { 95, 0.2 }, { 90, 2.1 }, { 85, 7.0 }, { 80, 16.6 }, { 70, 24.9 } },
    formula = { { 100, 0.0 }, { 95, 0.0 }, { 90, 1.1 }, { 85, 4.3 }, { 80, 15.6 }, { 70, 18.0 } },
    road    = { { 100, 0.0 }, { 95, 0.7 }, { 90, 4.7 }, { 85, 6.7 }, { 80, 11.0 }, { 70, 14.4 } },
    touring = { { 100, 0.0 }, { 90, 1.5 }, { 80, 6.7 }, { 75, 11.5 }, { 70, 16.6 } },
}
local CURVE_OF = { formula = 'formula', formula_jr = 'formula', prototype = 'gt', hypercar = 'gt', gt = 'gt', nascar = 'gt',
                   touring = 'touring', road = 'road', vintage = 'road', drift = 'road', kart = 'road', rally = 'road' }
local LEVEL_MIN = 0.72
D.SLIDER_CURVE = false        -- user option sliderCurve: outside career the slider is lap-time steps. OFF since
                              -- decision 0042 - THE SLIDER IS THE AI LEVEL. On, it maps the SLIDER through the
                              -- class curve and the per-car shift is taken from the mapped value, so slider 90
                              -- means "+5 % off expert pace" rather than "AI level 90".
D.SLIDER_PCT_PER_POINT = 0.5  -- 100 -> 0 %, 90 -> +5 %, 80 -> +10 %, 70 -> +15 %
local function curveFor(i)
    local key = 'gt'
    pcall(function() key = CURVE_OF[Classes.keyOf(i)] or 'gt' end)
    return CURVES[key], key
end
-- % slower than expert -> AI level (inverse of the curve, linear between points, clamped to the usable range)
function D.pctToLevel(pct, pts)
    pct = math.max(0, pct or 0)
    pts = pts or CURVES.gt
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
-- % slower than expert -> this car's AI level on its OWN class curve (driver profiles with D.PACE_ABS: a Rookie F1 and a
-- Rookie GT3 are the same lap-time step off expert pace, not the same raw AC level)
function D.levelForPct(i, pct) return pctToLevel(pct, (curveFor(i))) end
-- and the forward direction (what a level costs), for the UI / reports
function D.levelToPct(level, pts)
    local l = (level or 1) * 100
    pts = pts or CURVES.gt
    if l >= 100 then return 0 end
    for k = 1, #pts - 1 do
        if l >= pts[k + 1][1] then
            local f = (pts[k][1] - l) / (pts[k][1] - pts[k + 1][1])
            return pts[k][2] + (pts[k + 1][2] - pts[k][2]) * f
        end
    end
    return pts[#pts][2]
end

-- a car's level -> % off expert pace on ITS class curve (the inverse of levelForPct); Drivers.paceOf reads an unprofiled car's pace from it
function D.pctOf(i, level) return D.levelToPct(level, (curveFor(i))) end

D.sliderOverride = nil    -- one-line notice for the UI when the slider overrode the grid's per-car levels
local cache = {}          -- [i] = level
local cachedFor = nil

function D.reset() cache = {}; cachedFor = nil end

local function compute(i)
    local car = ac.getCar(i)
    if not car then return nil end
    -- (0.16) NO `or 100`. An unreadable level used to become maximum, which is the opposite of standing down.
    -- compute() already returns nil for a car it cannot judge, so nil here means Verve leaves this car alone
    -- and the player gets stock AC behaviour rather than our guess.
    local iniLevel = Career.carLevels[i] or Career.meter               -- launcher's number for this car (0..100+)
    if not iniLevel then return nil end
    if Career.active and D.CAREER_CURVE then
        local startPct, endPct = bandFor(Career.meter or iniLevel)   -- (0.16) the car's own level if the
                                                                     -- race-wide one was never readable
        local pct = startPct + (endPct - startPct) * (Career.ramp or 0)
        local base = pctToLevel(pct, (curveFor(i)))
        -- keep the event's own relative spread between opponents (86..88 => +-1%), measured against the grid's
        -- own average so a harness-forced flat grid comes out at exactly the band level
        local sum, cnt = 0, 0
        for k, v in pairs(Career.carLevels) do if k > 0 and v and v > 0 then sum = sum + v; cnt = cnt + 1 end end
        local mean = cnt > 0 and sum / cnt or (Career.eventLevel or iniLevel)
        local rel = (mean > 0 and iniLevel > 0) and (iniLevel / mean) or 1.0
        return math.max(LEVEL_MIN, math.min(1.2, base * rel))
    end
    -- outside career: THE SLIDER IS THE TRUTH (owner 2026-09-18). Content Manager writes a per-car AI level for every
    -- opponent from an older slider value or a grid preset (Sochi: slider 80, per-car 97-104, so the field ran at 100).
    -- The field runs at the slider; the per-car numbers only keep their relative spread around it. The one exception is
    -- a grid whose per-car levels are DELIBERATELY spread (more than DELIB_SPREAD apart): that is someone hand-setting
    -- opponents in the grid, and it is honoured as written.
    -- (0042) NO SLIDER AT ALL - GT Life writes a per-car level for every opponent and no race-wide one, so
    -- Career.meterSource is 'per-car median'. Each car runs ITS OWN level exactly as written, at any spread,
    -- with no curve and no re-centring: there is no slider on screen to follow.
    local own = Career.carLevels[i]
    local meter = Career.meter
    if Career.meterSource ~= 'race.ini' or not meter then
        D.sliderOverride = nil
        return math.max(LEVEL_MIN, math.min(1.2, iniLevel / 100.0))
    end
    -- (0042) THE SLIDER SETS THE AI LEVEL. The per-car numbers supply the VARIATION, the slider supplies the
    -- LEVEL:   level_i = slider - (max(per-car) - level_i)
    -- Identity when the fastest car is already at the slider, so a launcher that writes its variation BELOW the
    -- slider passes through untouched and we need to know nothing about any launcher's convention. A grid whose
    -- fastest car is not at the slider moves - up or down - with its spacing preserved, and no car ever ends up
    -- above what the player set. A flat grid lands every car on the slider, which is the owner's own case:
    -- slider 80 with every car at 100 ran at 100 before this.
    local hi, cnt = -1e9, 0
    for k, v in pairs(Career.carLevels) do
        if k > 0 and v and v > 0 then cnt = cnt + 1; if v > hi then hi = v end end
    end
    -- the slider's own value, unless sliderCurve reads it as lap-time steps on this class's measured curve -
    -- in which case the per-car shift below is taken from the MAPPED level, so the two features compose.
    local em = meter
    if D.SLIDER_CURVE and meter < 100 then
        em = pctToLevel((100 - meter) * D.SLIDER_PCT_PER_POINT, (curveFor(i))) * 100
    end
    local lvl = (cnt > 0 and own) and (em - (hi - own)) or em
    -- %.0f everywhere, never %d: a slider can be fractional (97.5) and so can a per-car level.
    if cnt > 0 and math.abs(hi - em) > 0.5 then
        D.sliderOverride = string.format('grid levels up to %.0f, slider %.0f: field shifted to the slider (this car %.0f)', hi, meter, lvl)
    elseif D.SLIDER_CURVE and meter < 100 then
        D.sliderOverride = string.format('slider %.0f = +%.0f%% off expert pace = level %.0f', meter, (100 - meter) * D.SLIDER_PCT_PER_POINT, em)
    else
        D.sliderOverride = nil
    end
    return math.max(LEVEL_MIN, math.min(1.2, lvl / 100.0))
end

-- the level car i should run at this session (nil = leave AC's own)
function D.levelFor(i)
    if not D.ENABLED then return nil end
    local sim = ac.getSim(); if not sim then return nil end
    -- (0.15.1) the two curve options are part of the key: flipped mid-session they apply now, not next session (audit 2026-09-30)
    local idx = (sim.currentSessionIndex or 0) * 4 + (D.SLIDER_CURVE and 1 or 0) + (D.CAREER_CURVE and 2 or 0)
    if cachedFor ~= idx then cache = {}; cachedFor = idx end
    local v = cache[i]
    if v == nil then v = compute(i) or false; cache[i] = v end
    return v or nil
end

-- (0.15.1) the launcher's own level for car i (what AC runs with Verve off), 0..1.2; nil when unknown
function D.stockLevel(i)
    local v = Career.carLevels[i] or Career.meter
    if type(v) == 'number' and v > 0 then return math.max(0.3, math.min(1.2, v / 100)) end   -- (not LEVEL_MIN: stock AC runs what the launcher says)
    return nil
end

function D.describe()
    if not Career.active then
        if D.sliderOverride then return D.sliderOverride end
        if not Career.meter then return 'Difficulty NOT DETECTED - leaving the level alone (check the launcher)' end
        return string.format('Field at the configured level (%d, from %s)', Career.meter, Career.meterSource or '?')
    end
    if not D.CAREER_CURVE then return string.format('Career, flat: %d', Career.meter or 0) end
    local s, e = bandFor(Career.meter)
    local pct = s + (e - s) * (Career.ramp or 0)
    return string.format('Career curve: meter %d, %.0f%% into the career, field %.0f%% off expert pace', Career.meter or 100, (Career.ramp or 0) * 100, pct)
end

return D
