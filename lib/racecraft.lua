-- Verve / racecraft.lua  (v0.5)
-- Our own racecraft from CSP AI primitives. Per AI car we read the gap to the nearest car
-- ahead/behind (+ their lateral position on track) and the shape of the track just ahead, then:
--   ATTACK  -- car in range & keeping up: tuck in (less caution), raise aggression, and pick a
--             passing line -- dive up the INSIDE of the corner ahead if it's open, else pass on
--             the side the defender isn't (slipstream out on straights).
--   DEFEND  -- faster car behind: ONE move to cover the vulnerable side (inside of the corner
--             ahead, or the side the attacker is on) and hold.
--   CRUISE  -- clear track: back to the racing line.
--
-- Track frame (ac.worldCoordinateToTrack): X = -1 left .. +1 right, Z = progress. Same sign as
-- setAISplineOffset, so lateral reads and offsets share one frame -- no handedness guessing.
-- Offset is slew-limited (anti-dart) and collision-awareness stays ON, so cars position not ram.
--
-- Per-CLASS tactics tune HOW each class races (an F1 slipstreams from far and passes precisely;
-- a touring car dive-bombs the inside). Per-car LEVEL (chill/clean/intense) and the global
-- racecraft INTENSITY scale the whole thing on top.

local Classes   = require('lib.classes')
local Overrides = require('lib.overrides')

local R = {}
R.ENABLED   = true
R.INTENSITY = 0.7
R.attacking = 0
R.defending = 0

local ATTACK_GAP   = 0.008
local PASS_GAP     = 0.0035
local DEFEND_GAP   = 0.005
local FASTER_MARGIN= 3.0
local ATTACK_OFFSET= 0.35
local DEFEND_OFFSET= 0.30
local EDGE_SOFT    = 0.5       -- start easing the offset once the car is this far toward an edge
local EDGE_HARD    = 0.9       -- fully suppressed by here (keeps cars off kerbs -> no trip/rollover)
local CAUTION_ATTACK = -0.6
local CAUTION_DEFEND = -0.25
-- aggression = the car's own slider value (car.aiAggression) plus a small delta when fighting,
-- so the Quick Race aggression slider stays meaningful instead of being overwritten.
local ATTACK_AGGR_ADD = 0.25
local DEFEND_AGGR_ADD = 0.12
local AGGR_CRUISE  = 0.55       -- fallback baseline only if the car's aggression can't be read
local OFFSET_SLEW  = 0.8        -- units/sec offset may move (lower = smoother, less skittish)
local DEADZONE     = 0.12       -- ignore tiny offsets (stay on the line)
local SIDE_HOLD    = 1.2        -- s to hold a chosen side before allowing a flip (anti-dart)
local OFFLINE_MAX  = 0.75      -- don't defend against a car this far off the racing line
local SPEED_MIN    = 30.0
local CROWD_GAP    = 0.006     -- cars within this spline gap count as "in the pack"
local SAMPLE_D     = 0.004     -- spline fraction between racing-line samples (~20m on a 5km track)
local CORNER_TURN  = 0.01      -- min (1 - dot) between tangents to count as "a corner ahead" (~8 deg)

-- per-class racecraft tactics: gap = striking range, offset = how far off-line, corner = how hard
-- it commits to an inside dive (vs a straight slipstream pass), defend = defensive firmness.
-- follow = how close it tucks in behind (high-downforce cars keep MORE distance -> dirty air
-- costs them front grip, so tucking right up makes them twitchy/crash-prone).
local TACTICS = {
    formula   = { gap = 1.3,  offset = 0.7, corner = 0.5, defend = 1.0, follow = 0.25 }, -- slipstream from far, precise, keeps well back (dirty air + fragile)
    prototype = { gap = 1.3,  offset = 0.8, corner = 0.6, defend = 1.0, follow = 0.35 },
    hypercar  = { gap = 1.2,  offset = 0.8, corner = 0.7, defend = 1.0, follow = 0.4 },
    gt        = { gap = 1.0,  offset = 1.0, corner = 1.1, defend = 1.1, follow = 0.9 },  -- out-brakes, close racing
    touring   = { gap = 0.85, offset = 1.2, corner = 1.4, defend = 1.2, follow = 1.2 },  -- dive-bomb, elbows out
    road      = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 0.9 },
    vintage   = { gap = 1.1,  offset = 0.9, corner = 0.8, defend = 0.9, follow = 0.8 },  -- momentum, wider lines
    drift     = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 1.0 },
}
local LEVELMULT = { chill = 0.4, clean = 1.0, intense = 1.5 }

local curOffset, idCache = {}, {}
local holdSign, holdUntil = {}, {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function sgn(x) if x > 0.1 then return 1 elseif x < -0.1 then return -1 else return 0 end end
local function latOf(pos)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(pos); if tc then x = tc.x end end)
    return x
end
local function carId(i)
    local id = idCache[i]
    if id == nil then id = false; pcall(function() id = ac.getCarID(i) end); idCache[i] = id end
    return id or nil
end

-- corner ahead: returns (isCorner, insideSign) using three racing-line samples + a lateral probe
local function cornerAhead(prog)
    local isCorner, insideSign = false, 0
    pcall(function()
        local p0 = ac.trackProgressToWorldCoordinate(prog % 1, false)
        local p1 = ac.trackProgressToWorldCoordinate((prog + SAMPLE_D) % 1, false)
        local p2 = ac.trackProgressToWorldCoordinate((prog + 2 * SAMPLE_D) % 1, false)
        if not (p0 and p1 and p2) then return end
        local v1 = (p1 - p0):normalize()
        local v2 = (p2 - p1):normalize()
        if (1 - v1:dot(v2)) < CORNER_TURN then return end             -- basically straight
        isCorner = true
        local centripetal = (v2 - v1)                                 -- points toward the inside (v1,v2 unchanged by dot)
        if centripetal:length() < 1e-4 then return end
        local latHere  = latOf(p1)
        local latInside = latOf(p1 + centripetal:normalize() * 3.0)   -- 3 m toward the inside
        insideSign = (latInside >= latHere) and 1 or -1               -- track frame: +1 = right
    end)
    return isCorner, insideSign
end

function R.evaluate(i, dt)
    if not R.ENABLED then return 0 end
    local caut, state = 0, 0
    pcall(function()
        local me = ac.getCar(i)
        if not me or not me.isAIControlled then return end
        local spd = me.speedKmh or 0
        if spd < SPEED_MIN or me.isInPitlane then return end
        local mySpline = me.splinePosition
        if mySpline == nil then return end

        local t = TACTICS[Classes.keyOf(i)] or TACTICS.road

        -- nearest ahead / behind (gap, speed, index)
        local gapA, aheadSpd, aheadIdx = 1e9, 0, -1
        local gapB, behindSpd, behindIdx = 1e9, 0, -1
        local crowd = 0
        local sim = ac.getSim()
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition then
                    local d = oc.splinePosition - mySpline; if d < 0 then d = d + 1 end
                    if d > 0 and d < gapA then gapA = d; aheadSpd = oc.speedKmh or 0; aheadIdx = j end
                    local b = mySpline - oc.splinePosition; if b < 0 then b = b + 1 end
                    if b > 0 and b < gapB then gapB = b; behindSpd = oc.speedKmh or 0; behindIdx = j end
                    if d < CROWD_GAP or b < CROWD_GAP then crowd = crowd + 1 end
                end
            end
        end

        local attackGap = ATTACK_GAP * t.gap
        local defendGap = DEFEND_GAP
        -- baseline aggression = the car's own (slider) value; Verve adds a bit when fighting
        local baseA = me.aiAggression
        if not baseA or baseA < 0 then baseA = AGGR_CRUISE end
        baseA = clamp(baseA, 0.2, 1.0)
        local myLat = latOf(me.position)          -- current lateral on track (-1 left .. +1 right)
        local target, aggr = 0, baseA

        if gapA < attackGap and spd >= aheadSpd - FASTER_MARGIN then
            state = 1
            aggr = math.min(1, baseA + ATTACK_AGGR_ADD)
            caut = CAUTION_ATTACK * (1 - gapA / attackGap) * (t.follow or 1.0)   -- aero cars keep more distance
            if gapA < PASS_GAP then
                local myTc = ac.worldCoordinateToTrack(me.position)
                local progZ = myTc and myTc.z or mySpline
                local isCorner, inside = cornerAhead(progZ)
                local dLat = aheadIdx >= 0 and latOf(ac.getCar(aheadIdx).position) or 0
                local off = ATTACK_OFFSET * t.offset
                if isCorner and inside ~= 0 then
                    if dLat * inside < 0.3 then          -- defender not covering the inside -> dive in
                        target = inside * off * (0.5 + 0.5 * t.corner)
                    else                                 -- inside covered -> set up the switchback outside
                        target = -inside * off * 0.6
                    end
                elseif math.abs(dLat) > 0.15 then        -- straight: pass where the defender isn't
                    target = -sgn(dLat) * off
                elseif inside ~= 0 then                  -- straight: pre-position for the next corner's inside
                    target = inside * off * 0.5
                end
            end
        elseif gapB < defendGap and behindSpd > spd - FASTER_MARGIN then
            -- only defend against a real threat that's on a plausible line (not a car miles off-line)
            local aLat = behindIdx >= 0 and latOf(ac.getCar(behindIdx).position) or 0
            if math.abs(aLat) < OFFLINE_MAX then
                state = 2
                aggr = math.min(1, baseA + DEFEND_AGGR_ADD)
                caut = CAUTION_DEFEND
                local myTc = ac.worldCoordinateToTrack(me.position)
                local progZ = myTc and myTc.z or mySpline
                local isCorner, inside = cornerAhead(progZ)
                if isCorner and inside ~= 0 then
                    target = inside * (DEFEND_OFFSET * t.defend)   -- hold the inside line (stable, corner-based)
                end
                -- on straights, keep the racing line -- don't weave to mirror the attacker
            end
        end

        -- per-car level x global intensity
        local lv = LEVELMULT[Overrides.level(carId(i))] or 1.0
        local eff = R.INTENSITY * lv
        -- pack damping: in a crowd (race start, traffic) damp the LINE-CHANGING only, so the field
        -- doesn't all dart around at once. NOT applied to caution/closing -- cars must stay willing
        -- to tuck up and pass in traffic, or the pack over-gaps and concertinas to a crawl.
        local crowdDamp = clamp(1 - math.max(0, crowd - 1) * 0.30, 0.25, 1)
        caut = caut * eff
        -- high-speed damping: smaller line changes at speed (a big lateral move at 300 km/h is
        -- what unsettles fast cars). Full effect up to ~180 km/h, tapering to half by ~360.
        local speedDamp = clamp(1 - math.max(0, spd - 180) / 400, 0.5, 1)
        target = clamp(target * eff * speedDamp * crowdDamp, -1, 1)

        -- track-edge safety: never push a car further toward an edge it's already near. Stops
        -- Verve from shoving a car onto a kerb at a corner exit (the near-rollover cause).
        if (target > 0 and myLat > EDGE_SOFT) or (target < 0 and myLat < -EDGE_SOFT) then
            target = target * clamp((EDGE_HARD - math.abs(myLat)) / (EDGE_HARD - EDGE_SOFT), 0, 1)
        end
        aggr = baseA + (aggr - baseA) * lv

        -- deadzone + side-hold: ignore tiny offsets (stay on the line), and hold the chosen side
        -- briefly so the car doesn't dart back and forth when the other car moves around.
        if math.abs(target) < DEADZONE then
            target = 0
        else
            local nowc = os.clock()
            local want = target > 0 and 1 or -1
            if holdSign[i] == nil or (want ~= holdSign[i] and nowc > (holdUntil[i] or 0)) then
                holdSign[i] = want; holdUntil[i] = nowc + SIDE_HOLD
            end
            target = math.abs(target) * (holdSign[i] or want)
        end

        -- slew the offset (anti-dart)
        local cur = curOffset[i] or 0
        local step = OFFSET_SLEW * (dt > 0 and dt < 0.5 and dt or 0.016)
        if target > cur + step then cur = cur + step
        elseif target < cur - step then cur = cur - step
        else cur = target end
        curOffset[i] = cur

        physics.setAISplineOffset(i, clamp(cur, -1, 1), false)
        physics.setAIAggression(i, clamp(aggr, 0, 1))
    end)
    if state == 1 then R.attacking = R.attacking + 1
    elseif state == 2 then R.defending = R.defending + 1 end
    return caut
end

function R.beginFrame() R.attacking = 0; R.defending = 0 end
function R.reset() curOffset = {}; idCache = {}; holdSign = {}; holdUntil = {} end

return R
