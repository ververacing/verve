-- Verve -- STRATEGY: deliberate manoeuvres on top of attack mode.
--
-- Attack mode (racecraft.lua) is reactive: tuck in, pick the open side, go. Real drivers also PLAN a pass:
--   SET-UP   sit in the tow for a corner or two, learn where the car ahead is weak, then go on a straight
--   LUNGE    the late-brake dive: inside is open at a braking zone, brake later than them, claim the apex
--   SWITCHBACK (over-under) the inside is covered, so take the wide line in, carry exit speed, and cross
--            back underneath them on the way out
--   SLINGSHOT oval/draft racing: run right up in the tow, then pull out at the last moment
-- Each class has its own playbook (a GT driver out-brakes, a formula driver sets it up on the straight, a
-- stock car slingshots). They are UNLOCKED by difficulty and by driver skill: below UNLOCK_METER nobody
-- uses them (the field races honestly but simply); from there, a driver's pace rating decides the tier --
-- a Rookie never switchbacks, a Veteran does. A manoeuvre is a short state machine per car; it returns
-- overrides for the racecraft offset / caution / aggression and clears itself when done or aborted.
-- Everything here is pcall-guarded by the caller; nothing touches physics directly.
local Difficulty = require('lib.difficulty')
local Drivers    = require('lib.drivers')
local Career     = require('lib.career')

local S = {}
S.ENABLED      = true
S.UNLOCK_METER = 90     -- launcher / quick-race meter at or above which the strategy layer is on at all
S.last         = {}     -- per car: manoeuvre code this frame (diagnostics): 0 none, 1 switchback, 2 lunge, 3 set-up, 4 slingshot
S.attempts     = 0      -- session tally (UI / diagnostics)
S.ok           = 0      -- ...of which gained a place within 8 s of finishing (judged in S.tick)
S.byType       = {}     -- name -> attempts
S.byTypeOK     = {}     -- name -> attempts that completed the pass
local pending  = {}     -- finished manoeuvres waiting for their verdict: { i, target, pos0, at, name }
local VERDICT_T = 20.0  -- s after the move to judge it: ahead of the car we attacked (or a place gained) = success
local CODE = { switchback = 1, lunge = 2, setup = 3, slingshot = 4 }
local MIN_TIER = { setup = 1, lunge = 1, slingshot = 1, switchback = 2 }
local COOLDOWN = 12.0   -- s after a manoeuvre before the same car plans another (7 -> 12: one move per car per lap was too many)
local EAGER_SCALE = 0.5 -- attempt-rate scale (GT3 A/B 2026-09-14: +83% overtaking but +80% incidents at 1.0)
local PACK_MAX = 3      -- no planned moves inside a pack this big (the opening-lap melee is where the extra incidents were)
local SAMPLE_D = 0.004  -- spline fraction between racing-line samples (matches racecraft)
local TURN     = 0.01   -- (1 - dot) between tangents that counts as "turning"

-- the playbook: which manoeuvres a class uses and how readily (weight 0 = never). Set-up corners = how many
-- corners a driver sits in the tow behind a NEW car before going for it (formula cars need the straight anyway).
-- Weights re-fitted 2026-09-15 from an overnight class set (completed/attempted): lunges convert in touring (27%),
-- kart (22%), GT3 (18%) and vintage, hardly at all in Formula Abarth (3%), prototypes (7%) and GT1 (5%);
-- switchbacks ~9% overall, best in the low-downforce single-seaters (17%).
local BOOK = {
    formula    = { setup = 1.0, lunge = 0.5, switchback = 0.6, setupCorners = 2 },
    formula_jr = { setup = 0.7, lunge = 0.3, switchback = 0.9, setupCorners = 1 },
    prototype  = { setup = 1.0, lunge = 0.25, switchback = 0.5, setupCorners = 2 },
    hypercar   = { setup = 0.9, lunge = 0.4, switchback = 0.6, setupCorners = 2 },
    gt         = { setup = 0.5, lunge = 0.8, switchback = 0.6, setupCorners = 1 },
    touring    = { setup = 0.3, lunge = 1.2, switchback = 0.6, setupCorners = 1 },
    road       = { setup = 0.5, lunge = 0.6, switchback = 0.4, setupCorners = 1 },
    vintage    = { setup = 0.7, lunge = 0.5, switchback = 0.6, setupCorners = 1 },
    kart       = { setup = 0.2, lunge = 1.2, switchback = 0.4, setupCorners = 0 },
    rally      = { setup = 0.4, lunge = 0.7, switchback = 0.6, setupCorners = 1 },
    nascar     = { setup = 0.6, slingshot = 1.2, setupCorners = 0 },
    drift      = {},
}

local plan, cool, stalk, tierCache, tierAt = {}, {}, {}, {}, {}

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function sgn(x) if x > 0.1 then return 1 elseif x < -0.1 then return -1 else return 0 end end
local function hash01(n)
    local x = math.sin(n * 12.9898 + 78.233) * 43758.5453
    return x - math.floor(x)
end

-- Skill tier: 0 = plain racing, 1 = set-up / lunge / slingshot, 2 = everything incl. the switchback.
-- Meter gate first (the launcher's number), then the driver's pace rating (profile; Rookie .30, Midfielder .60,
-- Veteran .85). Cars without a profile count as mid-pack (tier 1 above the meter gate).
function S.tierOf(i)
    if not S.ENABLED then return 0 end
    local now = os.clock()
    if tierCache[i] ~= nil and now - (tierAt[i] or 0) < 2.0 then return tierCache[i] end
    local tier = 0
    pcall(function()
        local meter = Career.meter or 100
        if meter < S.UNLOCK_METER then return end
        local prof = Drivers.statsOf(i)
        local pace = prof and prof.pace or 0.6
        local lvl = (Difficulty.levelFor(i) or 1) * 100
        if pace >= 0.75 and lvl >= S.UNLOCK_METER - 3 then tier = 2
        elseif pace >= 0.45 then tier = 1 end
    end)
    tierCache[i], tierAt[i] = tier, now
    return tier
end

-- Track geometry around the car: is it turning HERE and is it turning AHEAD? From that, a corner phase:
--   entry (straight now, corner ahead) / mid (turning, more to come) / exit (turning, straight ahead) / straight
-- plus the inside sign (+1 = right in the track frame) of the corner in play (the next one on entry/straight,
-- the current one on mid/exit). Racing-line geometry only, so it doesn't depend on steering units.
local function turnAt(prog)
    local p0 = ac.trackProgressToWorldCoordinate((prog - SAMPLE_D) % 1, false)
    local p1 = ac.trackProgressToWorldCoordinate(prog % 1, false)
    local p2 = ac.trackProgressToWorldCoordinate((prog + SAMPLE_D) % 1, false)
    if not (p0 and p1 and p2) then return 0, nil end
    local v1 = (p1 - p0):normalize()
    local v2 = (p2 - p1):normalize()
    local turn = 1 - v1:dot(v2)
    local c = v2 - v1
    if c:length() < 1e-4 then return turn, nil end
    local latHere = ac.worldCoordinateToTrack(p1)
    local latIn = ac.worldCoordinateToTrack(p1 + c:normalize() * 3.0)
    if not (latHere and latIn) then return turn, nil end
    return turn, (latIn.x >= latHere.x) and 1 or -1
end
local function geom(prog)
    local g = { phase = 'straight', inside = 0 }
    pcall(function()
        local tNow, inNow = turnAt(prog)
        local tAhead, inAhead = turnAt(prog + 2 * SAMPLE_D)
        local now, ahead = tNow >= TURN, tAhead >= TURN
        if now and ahead then g.phase = 'mid'; g.inside = inNow or inAhead or 0
        elseif now then g.phase = 'exit'; g.inside = inNow or 0
        elseif ahead then g.phase = 'entry'; g.inside = inAhead or 0
        else
            local tFar, inFar = turnAt(prog + 4 * SAMPLE_D)     -- a corner a bit further out: pre-position for it
            g.inside = (tFar >= TURN) and (inFar or 0) or 0
        end
    end)
    return g
end

local function start(i, name, fields)
    local p = { name = name, t0 = os.clock(), pos0 = 0 }
    for k, v in pairs(fields) do p[k] = v end
    pcall(function() local c = ac.getCar(i); p.pos0 = c and c.racePosition or 0 end)
    plan[i] = p
    if name ~= 'setup' then S.attempts = S.attempts + 1 end     -- set-up is the patient phase before a move, not a move
    S.byType[name] = (S.byType[name] or 0) + 1
    return p
end
local function finish(i)
    local p = plan[i]
    if p and p.name ~= 'setup' and (p.pos0 or 0) > 0 then
        pending[#pending + 1] = { i = i, target = p.car, pos0 = p.pos0, at = os.clock() + VERDICT_T, name = p.name }
    end
    plan[i] = nil
    cool[i] = os.clock() + COOLDOWN
end
-- once per frame (from Racecraft.beginFrame): score finished manoeuvres -- did the car gain a place?
function S.tick()
    if #pending == 0 then return end
    local now = os.clock()
    local k = 1
    while k <= #pending do
        local q = pending[k]
        if now >= q.at then
            pcall(function()
                local c = ac.getCar(q.i)
                if not c then return end
                local myPos = c.racePosition or 99
                local won = myPos < q.pos0
                if not won and type(q.target) == 'number' and q.target >= 0 then
                    local tc = ac.getCar(q.target)
                    if tc and not tc.isRetired and (tc.racePosition or 0) > myPos then won = true end   -- we are past the car we attacked
                end
                if won then S.ok = S.ok + 1; S.byTypeOK[q.name] = (S.byTypeOK[q.name] or 0) + 1 end
            end)
            table.remove(pending, k)
        else k = k + 1 end
    end
end

-- run the current plan; returns the override or nil when it ends
local function run(i, p, c, g, book)
    local now = os.clock()
    local age = now - p.t0
    if c.gapA > c.attackGap or c.aheadIdx ~= p.car then finish(i); return nil end   -- they got away / a different car
    if p.name == 'lunge' then
        if age < 1.3 then
            return { target = p.side * c.off * 1.4, geo = p.side, caut = -0.5 * (book.lunge or 1), aggr = 0.2, hold = 1.0, code = CODE.lunge }
        elseif age < 2.2 then                                -- gather it up: brake a touch more, hold the inside
            return { target = p.side * c.off * 0.7, geo = p.side, caut = 0.3, aggr = 0, code = CODE.lunge }
        end
        finish(i); return nil
    elseif p.name == 'switchback' then
        if p.phase == 'wide' then
            if g.phase == 'exit' or (g.phase == 'straight' and age > 1.0) then p.phase = 'cross'; p.tCross = now
            elseif age > 6.0 then finish(i); return nil end
            -- wide in, no extra risk on entry (the whole point is the exit)
            return { target = -p.side * c.off * 0.9, geo = -p.side, caut = 0.05, aggr = 0, hold = 0.8, code = CODE.switchback }
        else
            if now - p.tCross < 1.8 then
                return { target = p.side * c.off * 1.3, geo = p.side, caut = -0.45 * (book.switchback or 1), aggr = 0.2, hold = 1.6, code = CODE.switchback }
            end
            finish(i); return nil
        end
    elseif p.name == 'setup' then
        -- in the tow, on the line, until the corner count is served (or the gap opens); ends by itself
        if (stalk[i] and stalk[i].corners or 0) >= (book.setupCorners or 1) or age > 12.0 then plan[i] = nil; return nil end
        return { target = 0, caut = -0.15 * (book.setup or 1), aggr = 0, code = CODE.setup }
    elseif p.name == 'slingshot' then
        if p.phase == 'tow' then
            if c.gapA < c.passGap * 0.7 or age > 2.5 then p.phase = 'swing'; p.tSwing = now end
            return { target = 0, caut = -0.5 * (book.slingshot or 1), aggr = 0.1, code = CODE.slingshot }
        else
            if now - p.tSwing < 2.0 then
                return { target = p.side * c.off * 1.4, geo = p.side, caut = -0.3, aggr = 0.2, hold = 2.0, code = CODE.slingshot }
            end
            finish(i); return nil
        end
    end
    finish(i); return nil
end

-- c = { dt, gapA, spd, aheadSpd, aheadIdx, prog, dLat, myLat, wide, baseA, prof, classKey, off, passGap, attackGap, isOval }
-- Called by racecraft while a car is in ATTACK. Returns nil (no opinion) or { target, caut, aggr, hold, code, geo }: `geo` is the
-- side the move wants (+1 right); with R.MV_GEO on, racecraft resolves it to a point clear of the target car (target = fallback).
function S.evaluate(i, c)
    S.last[i] = 0
    local tier = S.tierOf(i)
    if tier == 0 then return nil end
    local book = BOOK[c.classKey] or BOOK.road
    if c.isOval and book.slingshot == nil then book = BOOK.nascar end   -- any class on an oval drafts
    local now = os.clock()
    local g = geom(c.prog)

    -- who am I stalking, and for how many corners?
    local st = stalk[i]
    if not st or st.car ~= c.aheadIdx then st = { car = c.aheadIdx, t0 = now, corners = 0, lastPhase = g.phase }; stalk[i] = st end
    if g.phase == 'entry' and st.lastPhase ~= 'entry' then st.corners = st.corners + 1 end
    st.lastPhase = g.phase

    local p = plan[i]
    if p then
        local ov = run(i, p, c, g, book)
        if ov then S.last[i] = ov.code; return ov end
        return nil
    end
    if cool[i] and now < cool[i] then return nil end

    -- plan something? Aggressive drivers try more; a driver's RISK rating feeds the lunge (the risky move).
    -- not on the opening lap, not in a pack: those are where a planned dive turns into a pile-up
    if (c.lap or 1) == 0 or (c.crowd or 0) >= PACK_MAX then return nil end
    local risk = c.prof and c.prof.risk or 0.35
    local eager = (0.35 + 0.65 * c.baseA) * EAGER_SCALE
    local roll = hash01(i * 13 + st.corners * 7 + math.floor(st.t0))   -- one roll per car-and-corner, not per frame
    local closeIn = c.gapA < c.passGap * 1.5
    local keepingUp = c.spd >= c.aheadSpd - 3
    local closing = c.spd >= c.aheadSpd + 2          -- a lunge needs a genuine run, not a parity dive

    -- SET-UP: a NEW car ahead, and this class serves a corner or two in the tow first
    if (book.setup or 0) > 0 and tier >= MIN_TIER.setup and st.corners < (book.setupCorners or 0) and closeIn and now - st.t0 < 0.5 then
        start(i, 'setup', { car = c.aheadIdx })
        S.last[i] = CODE.setup
        return { target = 0, caut = -0.15 * book.setup, aggr = 0, code = CODE.setup }
    end
    if st.corners < (book.setupCorners or 0) then return nil end   -- still serving the set-up

    if c.isOval or book.slingshot then
        if (book.slingshot or 0) > 0 and tier >= MIN_TIER.slingshot and g.phase == 'straight' and closeIn and keepingUp and roll < eager * 0.6 then
            local side = c.dLat ~= 0 and -sgn(c.dLat) or ((hash01(i * 3 + 1) < 0.5) and -1 or 1)
            if side == 0 then side = 1 end
            start(i, 'slingshot', { car = c.aheadIdx, phase = 'tow', side = side })
            S.last[i] = CODE.slingshot
            return { target = 0, caut = -0.5 * book.slingshot, aggr = 0.1, code = CODE.slingshot }
        end
        return nil
    end

    if g.phase == 'entry' and g.inside ~= 0 and closeIn and keepingUp then
        local insideOpen = c.dLat * g.inside < 0.3
        if insideOpen and closing and (book.lunge or 0) > 0 and tier >= MIN_TIER.lunge and roll < eager * (0.4 + 0.6 * risk) * book.lunge then
            start(i, 'lunge', { car = c.aheadIdx, side = g.inside })
            S.last[i] = CODE.lunge
            return { target = g.inside * c.off * 1.4, geo = g.inside, caut = -0.5 * book.lunge, aggr = 0.2, hold = 1.0, code = CODE.lunge }
        elseif not insideOpen and (book.switchback or 0) > 0 and tier >= MIN_TIER.switchback and roll < eager * book.switchback then
            start(i, 'switchback', { car = c.aheadIdx, side = g.inside, phase = 'wide' })
            S.last[i] = CODE.switchback
            return { target = -g.inside * c.off * 0.9, geo = -g.inside, caut = 0.05, aggr = 0, hold = 0.8, code = CODE.switchback }
        end
    end
    return nil
end

-- the launcher / quick-race meter is at or above `minMeter` (racecraft's opening-lap road-space gate reuses it, so the
-- difficulty number stays the one place these unlocks are read from)
function S.meterOK(minMeter)
    local ok = false
    pcall(function() ok = (Career.meter or 100) >= minMeter end)
    return ok
end

function S.clear(i)
    if plan[i] then plan[i] = nil end
    S.last[i] = 0
end

function S.byTypeString()
    local parts = {}
    for _, k in ipairs({ 'lunge', 'switchback', 'slingshot', 'setup' }) do
        if S.byType[k] then parts[#parts + 1] = k .. ':' .. S.byType[k] .. (k ~= 'setup' and ('/' .. (S.byTypeOK[k] or 0)) or '') end
    end
    return table.concat(parts, ' ')
end

function S.describe(i)
    local p = plan[i]
    if not p then return nil end
    return p.name .. (p.phase and (' ' .. p.phase) or '')
end

function S.reset()
    plan, cool, stalk, tierCache, tierAt = {}, {}, {}, {}, {}
    pending = {}
    S.last = {}
    S.attempts, S.ok, S.byType, S.byTypeOK = 0, 0, {}, {}
end

return S
