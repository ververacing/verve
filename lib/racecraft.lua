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
-- a touring car dive-bombs the inside). The global racecraft INTENSITY slider scales it all; the
-- Variability slider spreads per-driver aggression so the field isn't uniform. A short "pounce"
-- keeps a car eager to fill a gap right after it opens.

local Classes   = require('lib.classes')
local Drivers   = require('lib.drivers')

local R = {}
R.ENABLED     = true
R.INTENSITY   = 0.7        -- racecraft "how hard they race" slider
R.VARIABILITY = 0.5        -- variability slider: spreads per-driver aggression across the field
R.attacking = 0
R.defending = 0

local AGGR_SPREAD = 0.15   -- per-driver aggression spread (scaled by the Variability slider)
local POUNCE_HOLD = 1.2    -- s a car stays eager to fill a gap after following someone
local POUNCE_CAUT = -0.5   -- extra closing while pouncing (fill the opened space, don't hang back)
-- Move commitment: once a car commits to attacking or defending it holds that INTENT for a
-- short beat instead of re-deciding every frame. A genuine read (re)commits; when the read
-- briefly drops (gap wobbles just past the line, speed dips in dirty air) the car coasts the
-- committed decision until a wider release threshold clears it. Kills frame-to-frame dithering
-- and makes passes / defences decisive instead of hesitant.
local COMMIT_HOLD    = 0.7   -- s to hold a committed attack/defend decision
local COMMIT_RELEASE = 1.5   -- gap must grow past threshold*this to drop the commitment early

-- Race awareness: competent drivers manage risk by CONTEXT, not just the car in front.
--   Opening-lap caution -- cold tyres + a packed grid: calmer, more spacing, less line-swapping
--     off the line, fading across the first lap. Kills first-corner pile-ups.
--   Stakes / bring-it-home -- with clear track both ways there's nothing to win by pushing, so a
--     lone car circulates a touch calmer instead of binning it for no reason.
--   Blue-flag yield -- a car on a higher lap coming through gets let past (move off-line, lift),
--     instead of being fought like a rival.
--   Leave room -- when genuinely alongside (overlapping) and NOT the car with the corner, don't
--     pinch into them; ease off and lift. Pure contact-reducer.
-- All are applied AFTER the racecraft-intensity scale, so the safety holds even at low intensity.
local OPENLAP_CAUT   = 0.45  -- extra caution at the very start of a race
local OPENLAP_AGGR   = 0.40  -- aggression trimmed by up to this fraction at the start
local OPENLAP_OFFSET = 0.55  -- line-changes trimmed by up to this fraction at the start
local OPENLAP_FADE   = 0.60  -- opening-lap effect gone by this fraction into lap 1
local ISOLATED_GAP   = 0.030 -- clear track BOTH ways -> nothing to race
local ISOLATED_AGGR  = 0.20  -- aggression trim when isolated
local ISOLATED_CAUT  = 0.10  -- small lift when isolated (no pointless risk)
local YIELD_GAP      = 0.010 -- a lapping car this close behind -> start moving aside
local YIELD_OFFSET   = 0.45  -- move this far off-line to let the lapper through
local YIELD_AGGR     = 0.45  -- ease off only slightly while being lapped -- you're still racing
local YIELD_LIFT_GAP = 0.004 -- only actually lift once the lapper is THIS close (else keep racing pace)
local YIELD_CAUT     = 0.18  -- small lift as the faster car draws right up (was a big early slowdown)
local ALONGSIDE_GAP  = 0.0025-- on-track gap counting as "alongside" (overlap)
local ALONGSIDE_LAT  = 0.45  -- lateral separation under which two cars overlap
local LEAVEROOM_CAUT = 0.20  -- lift when overlapping and not the car with the corner

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
    formula_jr= { gap = 1.25, offset = 0.9, corner = 0.9, defend = 1.0, follow = 0.85 }, -- low-downforce: slipstream packs, races close (no dirty air)
    prototype = { gap = 1.3,  offset = 0.8, corner = 0.6, defend = 1.0, follow = 0.35 },
    hypercar  = { gap = 1.2,  offset = 0.8, corner = 0.7, defend = 1.0, follow = 0.4 },
    gt        = { gap = 1.0,  offset = 1.0, corner = 1.1, defend = 1.1, follow = 0.9 },  -- out-brakes, close racing
    touring   = { gap = 0.85, offset = 1.1, corner = 1.2, defend = 1.15, follow = 1.05 }, -- dive-bomb, elbows out (moderated so it isn't chaotic)
    road      = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 0.9 },
    vintage   = { gap = 1.1,  offset = 0.9, corner = 0.8, defend = 0.9, follow = 0.8 },  -- momentum, wider lines
    drift     = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 1.0 },
    kart      = { gap = 1.0,  offset = 0.9, corner = 1.2, defend = 1.15, follow = 1.3 }, -- bumper-to-bumper, out-brakes, big slipstream
    rally     = { gap = 1.0,  offset = 1.0, corner = 1.05, defend = 1.0, follow = 0.9 }, -- AWD, races like a grippy road car on tarmac
}
local curOffset = {}
local holdSign, holdUntil = {}, {}
local pounceT = {}
local commitState, commitUntil = {}, {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function sgn(x) if x > 0.1 then return 1 elseif x < -0.1 then return -1 else return 0 end end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end
local function latOf(pos)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(pos); if tc then x = tc.x end end)
    return x
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

        local myLap = me.lapCount or 0

        -- nearest ahead / behind (gap, speed, index)
        local gapA, aheadSpd, aheadIdx = 1e9, 0, -1
        local gapB, behindSpd, behindIdx = 1e9, 0, -1
        local nearGap, nearIdx, nearAhead = 1e9, -1, true   -- closest car by on-track gap (either side)
        local lapperIdx, lapperGap = -1, 1e9                -- nearest car on a higher lap coming through
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
                    local nd = d < b and d or b                       -- true nearest on track
                    if nd < nearGap then nearGap = nd; nearIdx = j; nearAhead = (d <= b) end
                    if b < YIELD_GAP and (oc.lapCount or 0) > myLap and b < lapperGap then lapperIdx = j; lapperGap = b end
                end
            end
        end

        local attackGap = ATTACK_GAP * t.gap
        local defendGap = DEFEND_GAP
        -- baseline aggression: a driver profile sets it directly; otherwise the car's own (slider)
        -- value plus a per-driver spread (scaled by Variability) so the field isn't uniform.
        local prof = Drivers.statsOf(i)
        local baseA
        if prof then
            baseA = clamp(prof.aggr, 0.15, 1.0)
        else
            baseA = me.aiAggression
            if not baseA or baseA < 0 then baseA = AGGR_CRUISE end
            baseA = clamp(baseA, 0.2, 1.0)
            baseA = clamp(baseA + (hash01(i * 11 + 5) * 2 - 1) * AGGR_SPREAD * R.VARIABILITY, 0.15, 1.0)
        end
        local myLat = latOf(me.position)          -- current lateral on track (-1 left .. +1 right)
        local target, aggr = 0, baseA

        -- raw instantaneous reads: is there a fight on right now?
        local rawAttack = (gapA < attackGap and spd >= aheadSpd - FASTER_MARGIN)
        local behindLat = behindIdx >= 0 and latOf(ac.getCar(behindIdx).position) or 0
        local rawDefend = (gapB < defendGap and behindSpd > spd - FASTER_MARGIN
                           and math.abs(behindLat) < OFFLINE_MAX)   -- ignore a car miles off-line

        -- resolve the COMMITTED state (see COMMIT_* notes): a genuine read (re)commits and refreshes
        -- the hold; otherwise coast the last decision until a wider release threshold clears it.
        local nowd = os.clock()
        if rawAttack then
            commitState[i], commitUntil[i], state = 1, nowd + COMMIT_HOLD, 1
        elseif rawDefend then
            commitState[i], commitUntil[i], state = 2, nowd + COMMIT_HOLD, 2
        elseif commitState[i] and (commitUntil[i] or 0) > nowd then
            if commitState[i] == 1 and gapA < attackGap * COMMIT_RELEASE then state = 1
            elseif commitState[i] == 2 and gapB < defendGap * COMMIT_RELEASE then state = 2
            else state = 0; commitState[i] = nil end
        else
            state = 0; commitState[i] = nil
        end

        if state == 1 then
            aggr = math.min(1, baseA + ATTACK_AGGR_ADD)
            caut = CAUTION_ATTACK * clamp(1 - gapA / attackGap, 0, 1) * (t.follow or 1.0)   -- aero cars keep more distance
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
        elseif state == 2 then
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

        local eff = R.INTENSITY

        -- pounce: after following a car, stay eager to fill the space for a moment (fixes the
        -- "slow to pounce when the gap opens" lag). Refreshes while attacking, decays after.
        pounceT[i] = math.max((pounceT[i] or 0) - dt, 0)
        if state == 1 then pounceT[i] = POUNCE_HOLD
        elseif state == 0 and pounceT[i] > 0 and (t.follow or 1) >= 0.7 then
            -- only pounce on a straight/fast bit, never while braking into a corner (that just
            -- bunches the pack up in the braking zone). Close-quarters classes only.
            local st = me.steer
            if type(st) ~= "number" or math.abs(st) < 0.2 then
                caut = caut + POUNCE_CAUT * (pounceT[i] / POUNCE_HOLD)
            end
        end

        -- pack damping: in a crowd (race start, traffic) damp the LINE-CHANGING only, so the field
        -- doesn't all dart around at once. NOT applied to caution/closing -- cars must stay willing
        -- to tuck up and pass in traffic, or the pack over-gaps and concertinas to a crawl.
        local crowdDamp = clamp(1 - math.max(0, crowd - 1) * 0.30, 0.25, 1)
        caut = caut * eff

        -- RACE AWARENESS (added after the intensity scale, so safety terms hold at any intensity):
        -- opening-lap caution -- calmer + more spacing off the line, fading across the first lap.
        local openingLap = (myLap == 0 and crowd >= 1) and clamp(1 - mySpline / OPENLAP_FADE, 0, 1) or 0
        if openingLap > 0 then
            caut = caut + OPENLAP_CAUT * openingLap
            aggr = aggr * (1 - OPENLAP_AGGR * openingLap)
        end
        -- bring-it-home -- clear track both ways: nothing to race, so ease off a touch.
        if gapA > ISOLATED_GAP and gapB > ISOLATED_GAP then
            aggr = aggr * (1 - ISOLATED_AGGR)
            caut = caut + ISOLATED_CAUT
        end

        -- high-speed damping: smaller line changes at speed (a big lateral move at 300 km/h is
        -- what unsettles fast cars). Full effect up to ~180 km/h, tapering to half by ~360.
        local speedDamp = clamp(1 - math.max(0, spd - 180) / 400, 0.5, 1)
        local phaseOff  = 1 - OPENLAP_OFFSET * openingLap        -- less line-swapping at the start
        target = clamp(target * eff * speedDamp * crowdDamp * phaseOff, -1, 1)

        -- leave room -- genuinely alongside (overlapping) and NOT the car with the corner: don't
        -- pinch into them and lift a touch. Can only reduce contact; never forces a move.
        if nearIdx >= 0 and nearGap < ALONGSIDE_GAP and nearAhead then
            local nearLat = latOf(ac.getCar(nearIdx).position)
            if math.abs(nearLat - myLat) < ALONGSIDE_LAT then
                local towardSign = (nearLat >= myLat) and 1 or -1
                if target * towardSign > 0 then target = target * 0.2 end   -- stop leaning into them
                caut = caut + LEAVEROOM_CAUT
            end
        end

        -- blue-flag yield -- a car on a higher lap is coming through: concede the line and lift,
        -- rather than racing the leader. Overrides attack/defend; edge-safety below keeps it honest.
        if lapperIdx >= 0 then
            local lapLat = latOf(ac.getCar(lapperIdx).position)
            target = ((lapLat >= myLat) and -1 or 1) * YIELD_OFFSET   -- move off the racing line, side the lapper isn't
            aggr   = math.min(aggr, YIELD_AGGR)                       -- ease off only a little -- keep racing
            -- keep racing pace until the faster car is right there, then lift just a touch to wave it by
            if lapperGap < YIELD_LIFT_GAP then
                caut = caut + YIELD_CAUT * clamp(1 - lapperGap / YIELD_LIFT_GAP, 0, 1)
            end
            state  = 0
        end

        -- track-edge safety: never push a car further toward an edge it's already near. Stops
        -- Verve from shoving a car onto a kerb at a corner exit (the near-rollover cause).
        if (target > 0 and myLat > EDGE_SOFT) or (target < 0 and myLat < -EDGE_SOFT) then
            target = target * clamp((EDGE_HARD - math.abs(myLat)) / (EDGE_HARD - EDGE_SOFT), 0, 1)
        end

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
function R.reset() curOffset = {}; holdSign = {}; holdUntil = {}; pounceT = {}; commitState = {}; commitUntil = {} end

return R
