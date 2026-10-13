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
S.episodes     = {}     -- judged manoeuvres for the diagnostics log (drained by diag): { i, name, dur, pos0, pos1, won, target, phases }
local VERDICT_T = 20.0  -- s after the move to judge it: ahead of the car we attacked (or a place gained) = success
S.lapsOf = nil          -- (VERDICT_V2) racecraft sets Recovery.lapsOf: Verve's own lap count (AC's drops a lap after a teleport)
local CODE = { switchback = 1, lunge = 2, setup = 3, slingshot = 4 }
local MIN_TIER = { setup = 1, lunge = 1, slingshot = 1, switchback = 2 }
local COOLDOWN = 12.0   -- s after a manoeuvre before the same car plans another (7 -> 12: one move per car per lap was too many)
S.EAGER_SCALE = 0.5     -- attempt-rate scale (GT3 A/B 2026-09-14: +83% overtaking but +80% incidents at 1.0). Harness: --strategy
S.PACK_MAX = 3          -- no planned moves inside a pack this big (the opening-lap melee is where the extra incidents were). Harness: --strategy
local SAMPLE_D = 0.004  -- spline fraction between racing-line samples (matches racecraft)
local TURN     = 0.01   -- (1 - dot) between tangents that counts as "turning"
-- PASSING PACKAGE (owner decisions 3 and 4, 2026-09-28). Every switch defaults to 0.14.8's behaviour. Harness: --strategy {...}
S.VERDICT_V2 = true     -- INSTRUMENTATION ONLY (no driving change; S.ok, the UI count, the diag 'mv' rows): a plan cleared because the car
                        -- left ATTACK or aborted is judged like a finished one, and a win = the car attacked was on my lap when the move
                        -- began and is behind me on the road at the verdict (a lapped target, or a place gained on another car, is not)
S.CLEAR_COOL = 0        -- s of cooldown after a cleared plan (0 = today: none; a plan that runs its course gets COOLDOWN)
S.SETUP_X = 0.0         -- DEFAULT 0.15 (was 1.0). x the playbook's set-up caution; 0 = no set-up plans and no 'still serving the set-up' wait (road space instead)
S.SETUP_RUN = 0         -- km/h, >0: a set-up ends once the car closes this fast on the car ahead (road space takes over)
S.TIER_MODE = 1         -- DEFAULT 0.15. 0 = today (S.tierOf: slider >= 90, profile pace). 1 = whatever the slider, every car plans (tier 1); its own pace
                        -- (Drivers.paceOf) >= MOVE_T2 adds the switchback; no new plan on a lapped car letting me by. Manoeuvres only:
                        -- S.tierOf and the star rules in racecraft are untouched
S.MOVE_T2 = 0.75
S.CLUMSY = 1.0          -- TIER_MODE 1: x (1 - moveSkill). A Rookie's lunge commits 70 % as long, 1.0x off-line (not 1.4x), 60 % of the
                        -- brake relief, gathers up +0.45 (not +0.3) and gives up at 1.0x attack range (not 1.5x). 0 = everyone like a Veteran
S.PICK_MOMENT = 0.5     -- DEFAULT 0.15. 0-1, TIER_MODE 1: a skilled driver's lunge odds follow his run: x(1 - P) at +0 km/h .. x(1 + P) at +10 (a Rookie's do not)
S.SAMPLE_M = 18         -- DEFAULT 0.15. m between corner-geometry samples (0 = today's lap fraction 0.004: 18 m at 4.5 km, 28 m at Spa, 8 m on a 2 km track)

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
-- (S.TIER_MODE 1) the manoeuvre tier from the car's OWN pace, whatever the slider: every car plans (tier 1); own pace >= MOVE_T2 adds the
-- switchback (tier 2). Drivers.paceOf: the profile's pace, else the applied level read as pace (a car at 100 reads 0.90).
function S.moveSkill(i) return clamp((Drivers.paceOf(i) - 0.30) / 0.55, 0, 1) end   -- Rookie 0, Midfielder 0.55, Veteran / a car at 100: 1
function S.moveTier(i)
    if not S.ENABLED then return 0 end
    return (Drivers.paceOf(i) >= S.MOVE_T2) and 2 or 1
end

-- Track geometry around the car: is it turning HERE and is it turning AHEAD? From that, a corner phase:
--   entry (straight now, corner ahead) / mid (turning, more to come) / exit (turning, straight ahead) / straight
-- plus the inside sign (+1 = right in the track frame) of the corner in play (the next one on entry/straight,
-- the current one on mid/exit). Racing-line geometry only, so it doesn't depend on steering units.
local function turnAt(prog, sd)
    local p0 = ac.trackProgressToWorldCoordinate((prog - sd) % 1, false)
    local p1 = ac.trackProgressToWorldCoordinate(prog % 1, false)
    local p2 = ac.trackProgressToWorldCoordinate((prog + sd) % 1, false)
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
        local sd = SAMPLE_D
        if S.SAMPLE_M > 0 then                                  -- (S.SAMPLE_M) metres, like racecraft's cornerAhead
            if not S.lenM then local L = ac.getSim().trackLengthM; S.lenM = (type(L) == 'number' and L > 200) and L or 4500 end
            sd = S.SAMPLE_M / S.lenM
        end
        local tNow, inNow = turnAt(prog, sd)
        local tAhead, inAhead = turnAt(prog + 2 * sd, sd)
        local now, ahead = tNow >= TURN, tAhead >= TURN
        if now and ahead then g.phase = 'mid'; g.inside = inNow or inAhead or 0
        elseif now then g.phase = 'exit'; g.inside = inNow or 0
        elseif ahead then g.phase = 'entry'; g.inside = inAhead or 0
        else
            local tFar, inFar = turnAt(prog + 4 * sd, sd)     -- a corner a bit further out: pre-position for it
            g.inside = (tFar >= TURN) and (inFar or 0) or 0
        end
    end)
    return g
end

local function start(i, name, fields)
    local p = { name = name, t0 = os.clock(), pos0 = 0 }
    for k, v in pairs(fields) do p[k] = v end
    pcall(function()
        local c = ac.getCar(i); p.pos0 = c and c.racePosition or 0
        local tc = (type(p.car) == 'number' and p.car >= 0) and ac.getCar(p.car) or nil
        if c and tc and c.splinePosition and tc.splinePosition then   -- (VERDICT_V2) the target is on my lap, ahead of me on the road
            local d = ((S.lapsOf and S.lapsOf(p.car) or tc.lapCount or 0) + tc.splinePosition) - ((S.lapsOf and S.lapsOf(i) or c.lapCount or 0) + c.splinePosition)
            p.sameLap = d > 0 and d < 0.5
        end
    end)
    plan[i] = p
    if name ~= 'setup' then S.attempts = S.attempts + 1 end     -- set-up is the patient phase before a move, not a move
    S.byType[name] = (S.byType[name] or 0) + 1
    return p
end
-- queue a started move for its verdict (set-ups are not moves). how: 'run' = it ran its course, 'left' = the car left ATTACK,
-- 'abort' = PASS_ABORT, 'clear' = any other S.clear
local function verdict(i, p, how)
    if p.name ~= 'setup' and (p.pos0 or 0) > 0 then
        pending[#pending + 1] = { i = i, target = p.car, pos0 = p.pos0, at = os.clock() + VERDICT_T, name = p.name, dur = os.clock() - p.t0,
                                  phases = p.log or '', how = how, sameLap = p.sameLap }
    end
end
local function finish(i)
    local p = plan[i]
    if p then verdict(i, p, 'run') end
    plan[i] = nil
    cool[i] = os.clock() + COOLDOWN
end
-- once per frame (from Racecraft.beginFrame): score finished manoeuvres. Today's test ('legacy'): a place gained, or the car attacked is
-- behind me in the classification. S.VERDICT_V2: the car attacked was on my lap when the move began and is behind me on the road now.
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
                local tc = (type(q.target) == 'number' and q.target >= 0) and ac.getCar(q.target) or nil
                local legacy = myPos < q.pos0
                if not legacy and tc and not tc.isRetired and (tc.racePosition or 0) > myPos then legacy = true end   -- we are past the car we attacked
                local past = false
                if q.sameLap and tc and not tc.isRetired and not tc.isInPitlane and c.splinePosition and tc.splinePosition then
                    past = (S.lapsOf and S.lapsOf(q.i) or c.lapCount or 0) + c.splinePosition > (S.lapsOf and S.lapsOf(q.target) or tc.lapCount or 0) + tc.splinePosition
                end
                local won = legacy
                if S.VERDICT_V2 then won = past end
                if won then S.ok = S.ok + 1; S.byTypeOK[q.name] = (S.byTypeOK[q.name] or 0) + 1 end
                S.episodes[#S.episodes + 1] = { i = q.i, name = q.name, dur = q.dur or 0, pos0 = q.pos0, pos1 = myPos, won = won, target = q.target or -1,
                                                phases = q.phases or '', how = q.how or 'run', legacy = legacy }
            end)
            table.remove(pending, k)
        else k = k + 1 end
    end
end

-- run the current plan; returns the override or nil when it ends
local function run(i, p, c, g, book)
    local now = os.clock()
    local age = now - p.t0
    -- episode log: phase / corner phase / gap (m) / their lateral offset, sampled when something changes (diag reads it after the verdict)
    local tag = string.format('%s:%s:%d:%d', tostring(p.phase or '-'), g.phase, math.floor((c.gapA or 0) * 100000), math.floor((c.dLat or 0) * 100))
    if tag ~= p.lastTag then p.lastTag = tag; p.log = (p.log or '') .. string.format('%.1f ', age) .. tag .. ' ' end
    -- abort if the TARGET got away or we are past it -- measured on the target itself, not on whoever is 'ahead on my line'
    -- now: a switchback moves wide on purpose, which changed aheadIdx and killed every switchback 0.6-1.8 s in (Monza 12 laps
    -- 2026-09-17: 31 episodes logged, no switchback ever reached its cross phase)
    local tgtGap = c.gapA
    local cl = p.cl or 0                                   -- (S.CLUMSY, TIER_MODE 1) 0 = today
    if type(p.car) == 'number' and p.car >= 0 then
        local tc = ac.getCar(p.car)
        if tc and tc.splinePosition then tgtGap = (tc.splinePosition - (c.prog % 1)) % 1 end
    end
    if tgtGap > c.attackGap * (1.5 - 0.5 * cl) or tgtGap > 0.5 then finish(i); return nil end   -- got away (or we are past it: gap wraps to ~1)
    if p.name == 'lunge' then
        if age < 1.3 * (1 - 0.3 * cl) then
            return { target = p.side * c.off * (1.4 - 0.4 * cl), caut = -0.5 * (book.lunge or 1) * (1 - 0.4 * cl), aggr = 0.2, hold = 1.0, code = CODE.lunge }
        elseif age < 2.2 then                                -- gather it up: brake a touch more, hold the inside
            return { target = p.side * c.off * 0.7, caut = 0.3 + 0.15 * cl, aggr = 0, code = CODE.lunge }
        end
        finish(i); return nil
    elseif p.name == 'switchback' then
        if p.phase == 'wide' then
            if g.phase == 'exit' or (g.phase == 'straight' and age > 1.0) then p.phase = 'cross'; p.tCross = now
            elseif age > 6.0 then finish(i); return nil end
            -- wide in, no extra risk on entry (the whole point is the exit)
            return { target = -p.side * c.off * 0.9, caut = 0.05, aggr = 0, hold = 0.8, code = CODE.switchback }
        else
            if now - p.tCross < 1.8 then
                return { target = p.side * c.off * 1.3, caut = -0.45 * (book.switchback or 1), aggr = 0.2, hold = 1.6, code = CODE.switchback }
            end
            finish(i); return nil
        end
    elseif p.name == 'setup' then
        -- in the tow, on the line, until the corner count is served (or the gap opens; S.SETUP_RUN: a real run); ends by itself
        if (S.SETUP_RUN > 0 and c.spd - c.aheadSpd >= S.SETUP_RUN) or (stalk[i] and stalk[i].corners or 0) >= (book.setupCorners or 1) or age > 12.0 then plan[i] = nil; return nil end
        return { target = 0, caut = -0.15 * (book.setup or 1) * S.SETUP_X, aggr = 0, code = CODE.setup }
    elseif p.name == 'slingshot' then
        if p.phase == 'tow' then
            if c.gapA < c.passGap * 0.7 or age > 2.5 then p.phase = 'swing'; p.tSwing = now end
            return { target = 0, caut = -0.5 * (book.slingshot or 1), aggr = 0.1, code = CODE.slingshot }
        else
            if now - p.tSwing < 2.0 then
                return { target = p.side * c.off * 1.4, caut = -0.3, aggr = 0.2, hold = 2.0, code = CODE.slingshot }
            end
            finish(i); return nil
        end
    end
    finish(i); return nil
end

-- c = { dt, gapA, spd, aheadSpd, aheadIdx, prog, dLat, myLat, wide, baseA, prof, classKey, off, passGap, attackGap, isOval, lap, crowd, lapped,
--       wild, wLunge, wCool, wReach, wDive0 }   (wild: racecraft's R.WILD layer, a chaos-driver car only; the w* are its R.WILD_* values)
-- Called by racecraft while a car is in ATTACK. Returns nil (no opinion) or { target, caut, aggr, hold, code }.
function S.evaluate(i, c)
    S.last[i] = 0
    local tier = (S.TIER_MODE == 1) and S.moveTier(i) or S.tierOf(i)
    if c.wild and S.ENABLED and tier < 1 then tier = 1 end   -- the chaos driver always has the lunge (the switchback still needs tier 2)
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
    if cool[i] and now < cool[i] - (c.wild and math.max(0, COOLDOWN - c.wCool) or 0) then return nil end   -- (a wild car: R.WILD_COOL)

    -- plan something? Aggressive drivers try more; a driver's RISK rating feeds the lunge (the risky move).
    -- not on the opening lap, not in a pack: those are where a planned dive turns into a pile-up
    if not (c.wild and c.wDive0) and ((c.lap or 1) == 0 or (c.crowd or 0) >= S.PACK_MAX + (c.wild and 1 or 0)) then return nil end   -- (a wild car: one more in the pack; R.WILD_DIVE0 none of it)
    if c.lapped and S.TIER_MODE == 1 then return nil end   -- a lapped car letting me by: racecraft's free pass, not a planned move
    local risk = c.prof and c.prof.risk or 0.35
    local eager = (0.35 + 0.65 * c.baseA) * S.EAGER_SCALE
    local roll = hash01(i * 13 + st.corners * 7 + math.floor(st.t0))   -- one roll per car-and-corner, not per frame
    local closeIn = c.gapA < c.passGap * 1.5 * (c.wild and c.wReach or 1)   -- (a wild car goes from further back: R.WILD_REACH)
    local keepingUp = c.spd >= c.aheadSpd - 3
    local closing = c.spd >= c.aheadSpd + 2          -- a lunge needs a genuine run, not a parity dive
    local cl, mom = 0, 1                             -- (TIER_MODE 1) clumsiness and picking the moment, from the car's own skill
    if S.TIER_MODE == 1 then
        local sk = S.moveSkill(i)
        cl = S.CLUMSY * (1 - sk)
        if S.PICK_MOMENT > 0 then mom = 1 + S.PICK_MOMENT * sk * (2 * clamp((c.spd - c.aheadSpd) / 10, 0, 1) - 1) end
    end

    -- SET-UP: a NEW car ahead, and this class serves a corner or two in the tow first (S.SETUP_X 0: never)
    if not c.wild and (book.setup or 0) * S.SETUP_X > 0 and tier >= MIN_TIER.setup and st.corners < (book.setupCorners or 0) and closeIn and now - st.t0 < 0.5 then   -- (a wild car never sets it up)
        start(i, 'setup', { car = c.aheadIdx })
        S.last[i] = CODE.setup
        return { target = 0, caut = -0.15 * book.setup * S.SETUP_X, aggr = 0, code = CODE.setup }
    end
    if not c.wild and S.SETUP_X > 0 and st.corners < (book.setupCorners or 0) then return nil end   -- still serving the set-up

    if c.isOval or book.slingshot then
        if (book.slingshot or 0) > 0 and tier >= MIN_TIER.slingshot and g.phase == 'straight' and closeIn and keepingUp and roll < eager * 0.6 then
            local side = c.dLat ~= 0 and -sgn(c.dLat) or ((hash01(i * 3 + 1) < 0.5) and -1 or 1)
            if side == 0 then side = 1 end
            start(i, 'slingshot', { car = c.aheadIdx, phase = 'tow', side = side, cl = cl })
            S.last[i] = CODE.slingshot
            return { target = 0, caut = -0.5 * book.slingshot, aggr = 0.1, code = CODE.slingshot }
        end
        return nil
    end

    if g.phase == 'entry' and g.inside ~= 0 and closeIn and keepingUp then
        local insideOpen = c.dLat * g.inside < 0.3
        if insideOpen and (closing or c.wild) and (book.lunge or 0) > 0 and tier >= MIN_TIER.lunge
           and roll < math.min(0.95, eager * (0.4 + 0.6 * risk) * book.lunge * (c.wild and c.wLunge or 1) * mom) then   -- (a wild car: no run needed, x R.WILD_LUNGE)
            start(i, 'lunge', { car = c.aheadIdx, side = g.inside, cl = cl })
            S.last[i] = CODE.lunge
            return { target = g.inside * c.off * (1.4 - 0.4 * cl), caut = -0.5 * book.lunge * (1 - 0.4 * cl), aggr = 0.2, hold = 1.0, code = CODE.lunge }
        elseif not insideOpen and (book.switchback or 0) > 0 and tier >= MIN_TIER.switchback and roll < eager * book.switchback then
            start(i, 'switchback', { car = c.aheadIdx, side = g.inside, phase = 'wide', cl = cl })
            S.last[i] = CODE.switchback
            return { target = -g.inside * c.off * 0.9, caut = 0.05, aggr = 0, hold = 0.8, code = CODE.switchback }
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

function S.clear(i, why)   -- why: 'left' (the car left ATTACK), 'abort' (PASS_ABORT); S.VERDICT_V2 judges the cleared move
    local p = plan[i]
    if p then
        if S.VERDICT_V2 then verdict(i, p, why or 'clear') end
        plan[i] = nil
        if S.CLEAR_COOL > 0 and p.name ~= 'setup' then cool[i] = os.clock() + S.CLEAR_COOL end
    end
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
    S.lenM = nil
    S.episodes = {}
    S.last = {}
    S.attempts, S.ok, S.byType, S.byTypeOK = 0, 0, {}, {}
end

return S
