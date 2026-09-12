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
local Troublespots = require('lib.troublespots')

local R = {}
R.ENABLED     = true
R.INTENSITY   = 0.7        -- racecraft "how hard they race" slider
R.VARIABILITY = 0.5        -- variability slider: spreads per-driver aggression across the field
R.attacking = 0
R.defending = 0
R.isOval = false           -- set per session: true if the track turns mostly one way (an oval/speedway)

-- oval groove: on a speedway, stock cars commit to a high or low LANE and run it side-by-side
-- through the banking, instead of all returning to one racing line.
local GROOVE_RANGE  = 0.020  -- a car ahead within this spline gap -> we're in a pack, run a groove
local GROOVE_OFFSET = 0.62   -- how far toward the high/low line to commit (edge-safety still bounds it)
local GROOVE_HOLD   = 3.0    -- s to commit to a chosen lane (sustained, not a dart)

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
local OPENLAP_CAUT   = 0.38  -- extra caution at the very start of a race (eased a touch: starts felt over-cautious)
local OPENLAP_AGGR   = 0.35  -- aggression trimmed by up to this fraction at the start
local OPENLAP_OFFSET = 0.55  -- line-changes trimmed by up to this fraction at the start
local OPENLAP_FADE   = 0.50  -- opening-lap effect gone by this fraction into lap 1 (releases sooner)
-- grid funnel: off the line, hold each car near its own starting lane and let it merge onto the
-- racing line GRADUALLY over the run to turn 1, instead of all 22 diving for the line at once.
local GRID_FADE_END  = 0.05  -- lane-hold fades to the racing line over this fraction of lap 1
local GRID_CAPTURE   = 0.02  -- capture a car's grid lane while it's still within this fraction (near the grid)
local GRID_HOLD      = 1.0   -- how strongly to hold the captured lane (1 = fully)
local ISOLATED_GAP   = 0.030 -- clear track BOTH ways -> nothing to race
local ISOLATED_AGGR  = 0.20  -- aggression trim when isolated
local ISOLATED_CAUT  = 0.10  -- small lift when isolated (no pointless risk)
-- pack leader / clear-ahead: a car with open road ahead can't be passed if it just DRIVES AWAY, so it
-- shouldn't sit in a slow defensive line every corner (that's what stalls the front of a bunch and
-- concertinas everyone behind). It keeps the racing line and gets a small pace stretch to string the
-- field out, instead of the whole crowd circulating nose-to-tail at one pace.
local PACK_LEAD_GAP  = 0.012 -- this much clear track ahead = "drive away" rather than defend a line
local PACK_STRETCH   = 0.14  -- small pace stretch (less caution) for a car leading a pack, to open it up
-- adaptive crash damping: the crashier a track has proven (from its learned trouble-spot history), the
-- calmer the WHOLE field runs -- more caution, less aggression, a bigger opening-lap ease, and the pace
-- stretch pulled back. Self-calibrating: a nasty track (Zandvoort) settles down, a clean one stays racy.
local CRASH_CAUT     = 0.35  -- extra field-wide caution at a fully crash-prone track
local CRASH_AGGR     = 0.35  -- aggression trimmed by up to this fraction at a fully crash-prone track
-- anti rear-end: closing fast while sat DIRECTLY behind the car ahead (not moving alongside to pass)
-- -> ease the final approach so we don't pile into its gearbox in the braking zone. AC's own AI does
-- this badly; this is the biggest cause of the pack "wrecking crew". Even aggressive drivers keep a
-- margin, scaled by Risk. (When a car pulls off-line to pass, it's no longer "behind" -> no back-off.)
local REAREND_GAP    = 0.005 -- only this close behind counts as a rear-end risk
local REAREND_LAT    = 0.28  -- and only when roughly on the same line (directly behind), not alongside
local REAREND_CLOSE  = 8.0   -- km/h of closing speed before we start easing
local REAREND_RANGE  = 26.0  -- full ease by this much closing (close + range)
local REAREND_CAUT   = 1.2   -- how firmly to back off (kept high because a rear-end is a race-ruiner)
-- blockage: a car crawling far below pace just ahead and on my line (a crash / spun / limping car) is
-- an OBSTACLE, not a rival. Don't queue up behind it (anti-rear-end would just brake to a crawl) --
-- sweep around it on the OPEN side of the track. This is "if the line's blocked, take the open road".
local BLOCK_SPEED    = 24.0  -- a car ahead crawling below this (absolute) is a blockage (stalled/crashed)
-- OR a genuinely-slow car (a limper) that I'm arriving on much faster. Both gates matter: the absolute
-- cap keeps this from firing on a car simply BRAKING for a corner (that's ~100+ km/h, not a limper) --
-- without it, a fast car behind treated every braking car as an obstacle and swerved around it into the
-- corner, which was a contact machine at fast tracks.
local BLOCK_LIMP     = 55.0  -- only a car below THIS absolute speed can be a "limper" blockage
local BLOCK_DELTA    = 50.0  -- and I must be at least this much faster than it (clearly arriving on it)
local BLOCK_GAP      = 0.006 -- look this far ahead for the obstacle (start peeling off a bit earlier)
local BLOCK_MARGIN   = 6.0   -- I only need to be a little faster than it (so cars queued behind it still peel off)
local BLOCK_OFFSET   = 0.48  -- swing this far to the open side -- just enough to sneak past, not a huge berth
local BLOCK_HOLD     = 1.5   -- commit to the avoidance side briefly (don't dart back into it)
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
-- opportunistic outside pass: with a real exit-speed run, use more of the track (wider off-line, and
-- allowed closer to the edge) to sweep around a slower car -- rather than a token move on the line.
local OUTSIDE_MIN_ADV = 8.0    -- km/h faster than the car ahead before we start using extra width
local OUTSIDE_RANGE   = 20.0   -- full extra width by this much faster (min_adv + range)
local OUTSIDE_EDGE    = 0.30   -- how much closer to the edge a full speed-run may run (raises EDGE_SOFT)
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
    nascar    = { gap = 1.2,  offset = 1.2, corner = 0.8, defend = 1.1, follow = 1.4 }, -- pack/draft: run right up in the tow, use the whole width (high/low lines), block the draft
}
local curOffset = {}
local gridLat = {}          -- each car's captured starting-lane lateral, for the grid funnel
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
-- Detect an oval/speedway: sample the racing line around the whole lap and measure how one-directional
-- the turning is. An oval turns the same way the entire lap (|sum of turns| ~ total turning); a road
-- course balances left and right (sum near zero). Computed once per session.
local function detectOval()
    local oval = false
    pcall(function()
        local N = 96
        local pts = {}
        for k = 0, N - 1 do
            local p = ac.trackProgressToWorldCoordinate(k / N, false)
            if not p then return end
            pts[k] = p
        end
        local signed, total = 0, 0
        for k = 0, N - 1 do
            local a, b, c = pts[k], pts[(k + 1) % N], pts[(k + 2) % N]
            local v1x, v1z = b.x - a.x, b.z - a.z
            local v2x, v2z = c.x - b.x, c.z - b.z
            local m1 = math.sqrt(v1x * v1x + v1z * v1z)
            local m2 = math.sqrt(v2x * v2x + v2z * v2z)
            if m1 > 1e-3 and m2 > 1e-3 then
                local turn = (v1x * v2z - v1z * v2x) / (m1 * m2)   -- signed turn between segments
                signed = signed + turn
                total = total + math.abs(turn)
            end
        end
        if total > 1e-3 then oval = (math.abs(signed) / total) > 0.6 end   -- mostly one-way = oval
    end)
    return oval
end

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

        local classKey = Classes.keyOf(i)
        local t = TACTICS[classKey] or TACTICS.road
        local crash = Troublespots.crashiness()    -- 0..1: how crash-prone this track has proven

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
        local target, aggr, wide = 0, baseA, 0    -- wide = 0..1 extra track width earned by an exit-speed run

        -- BLOCKAGE detect: scan a short window ahead for the SLOWEST car -- a stalled/crashed/crawling car
        -- is an obstacle, not a rival. Crucially we key off the genuinely-slow car (usually the crash),
        -- not just whoever's nearest (which, once a queue forms, is another queued car), and we only need
        -- to be a little faster than it -- so cars ALREADY crawling in the queue behind it still peel off
        -- and filter past, instead of everyone sitting nose-to-tail. Route to the OPEN side (away from
        -- where the obstacle sits), so a car stopped on the right sends the field around it on the left.
        local blockSide = 0
        do
            local slowIdx, slowSpd = -1, 1e9
            for j = 0, sim.carsCount - 1 do
                if j ~= i then
                    local oc = ac.getCar(j)
                    if oc and oc.splinePosition then
                        local d = oc.splinePosition - mySpline; if d < 0 then d = d + 1 end
                        if d > 0 and d < BLOCK_GAP and (oc.speedKmh or 1e9) < slowSpd then
                            slowSpd = oc.speedKmh or 1e9; slowIdx = j
                        end
                    end
                end
            end
            if slowIdx >= 0 and spd > slowSpd + BLOCK_MARGIN
               and (slowSpd < BLOCK_SPEED or (slowSpd < BLOCK_LIMP and (spd - slowSpd) > BLOCK_DELTA)) then
                local aLat = latOf(ac.getCar(slowIdx).position)
                if math.abs(aLat) > 0.1 then blockSide = -sgn(aLat)                 -- obstacle off to a side -> go the other way (the open track)
                elseif sgn(myLat) ~= 0 then blockSide = -sgn(myLat)                 -- obstacle mid-track -> head toward the roomier half
                else blockSide = (hash01(i * 5 + 2) < 0.5) and -1 or 1 end          -- dead-centre -> pick a side and commit
            end
        end

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
            -- Start MOVING for the pass earlier when there's a genuine speed run on the car ahead -- not
            -- only when almost touching. Fixes a fast car sitting in the slipstream too long before it
            -- commits to the open space beside a slower car (most visible off the start, but present
            -- everywhere). Still needs a real closing-speed advantage, so it isn't a constant weave.
            local runAdv = spd - aheadSpd
            local passActive = (gapA < PASS_GAP) or (gapA < attackGap and runAdv > OUTSIDE_MIN_ADV * 0.6)
            if passActive then
                local myTc = ac.worldCoordinateToTrack(me.position)
                local progZ = myTc and myTc.z or mySpline
                local isCorner, inside = cornerAhead(progZ)
                local dLat = aheadIdx >= 0 and latOf(ac.getCar(aheadIdx).position) or 0
                local off = ATTACK_OFFSET * t.offset
                -- a genuine exit-speed run earns extra width -- and how readily a car takes it scales
                -- with AGGRESSION (the driver profile's aggr, or the Quick Race slider, via baseA): an
                -- aggressive driver pounces on a smaller advantage AND commits harder to it; a cautious
                -- one needs a bigger gap and uses less width. Verstappen takes every opening; Prost picks his.
                local minAdv = OUTSIDE_MIN_ADV * (1.4 - baseA)
                wide = clamp(clamp((spd - aheadSpd - minAdv) / OUTSIDE_RANGE, 0, 1) * (0.5 + baseA), 0, 1.5)
                if isCorner and inside ~= 0 then
                    if dLat * inside < 0.3 then          -- inside is OPEN -> dive in, committing harder with a real run
                        target = inside * off * (0.5 + 0.5 * t.corner) * (1 + 0.7 * wide)
                    else                                 -- inside covered -> go AROUND THE OUTSIDE, wider with a run
                        target = -inside * off * (0.6 + 1.4 * wide)
                    end
                elseif math.abs(dLat) > 0.15 then        -- straight/exit: pass where the defender isn't, wider with a run
                    target = -sgn(dLat) * off * (1 + 1.5 * wide)
                elseif inside ~= 0 then                  -- straight: pre-position for the next corner's inside
                    target = inside * off * 0.5
                end
            end
        elseif state == 2 then
            aggr = math.min(1, baseA + DEFEND_AGGR_ADD)
            caut = CAUTION_DEFEND
            if gapA >= PACK_LEAD_GAP then
                -- clear road ahead: don't defend a slow line -- just drive away on the racing line.
                target = 0
            else
                local myTc = ac.worldCoordinateToTrack(me.position)
                local progZ = myTc and myTc.z or mySpline
                local isCorner, inside = cornerAhead(progZ)
                if isCorner and inside ~= 0 then
                    target = inside * (DEFEND_OFFSET * t.defend)   -- hold the inside line (stable, corner-based)
                end
                -- on straights, keep the racing line -- don't weave to mirror the attacker
            end
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
        local crowdDamp = clamp(1 - math.max(0, crowd - 1) * 0.25, 0.35, 1)   -- eased: was over-damping pull-outs in packs
        -- a car with a genuine speed run (wide > 0) resists the crowd damping, so a fast car CAN still
        -- pull out into open space in a pack instead of being pinned on the line behind a slower car.
        local passResist = clamp(wide, 0, 1)
        crowdDamp = crowdDamp + (1 - crowdDamp) * passResist
        caut = caut * eff

        -- RACE AWARENESS (added after the intensity scale, so safety terms hold at any intensity):
        -- opening-lap caution -- calmer + more spacing off the line, fading across the first lap.
        local openingLap = (myLap == 0 and crowd >= 1) and clamp(1 - mySpline / OPENLAP_FADE, 0, 1) or 0
        if openingLap > 0 then
            caut = caut + OPENLAP_CAUT * openingLap * (1 + crash)   -- crashy tracks get extra start caution (kills the opening-lap pile-ups)
            aggr = aggr * (1 - OPENLAP_AGGR * openingLap)
        end
        -- bring-it-home -- clear track both ways: nothing to race, so ease off a touch.
        if gapA > ISOLATED_GAP and gapB > ISOLATED_GAP then
            aggr = aggr * (1 - ISOLATED_AGGR)
            caut = caut + ISOLATED_CAUT
        -- pack leader -- clear road ahead but a pack right behind: a small pace stretch so the leader
        -- noses away and strings the field out, instead of the front artificially anchoring the bunch.
        elseif gapA > PACK_LEAD_GAP and crowd >= 2 then
            caut = caut - PACK_STRETCH * (1 - crash)   -- don't stretch away (more catching) on a crashy track
        end
        -- trouble-spot learning: a bit more caution approaching a corner this class keeps crashing at.
        caut = caut + Troublespots.cautionAt(mySpline, classKey)
        -- adaptive crash damping: on a track that keeps wrecking cars, calm the whole field (more caution,
        -- less aggression) so the crash RATE falls, not just the after-the-fact repairs.
        if crash > 0 then
            caut = caut + CRASH_CAUT * crash
            aggr = aggr * (1 - CRASH_AGGR * crash)
        end
        -- anti rear-end: closing fast, right behind, and still ON the same line (not pulling out to
        -- pass) -> ease the approach. Risk lowers how much a driver backs off, but never to nothing.
        if gapA < REAREND_GAP and aheadIdx >= 0 and blockSide == 0 then    -- (going around a blockage? don't also brake to a crawl behind it)
            local closing = spd - aheadSpd
            if closing > REAREND_CLOSE and math.abs(myLat - latOf(ac.getCar(aheadIdx).position)) < REAREND_LAT then
                local urgency = clamp((closing - REAREND_CLOSE) / REAREND_RANGE, 0, 1) * clamp(1 - gapA / REAREND_GAP, 0, 1)
                local riskF = prof and clamp(1.0 - 0.6 * prof.risk, 0.4, 1.0) or 0.8
                caut = caut + REAREND_CAUT * urgency * riskF
            end
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

        -- track-edge safety: never push a car further toward an edge it's already near (keeps cars off
        -- kerbs). A car with a real speed run is allowed a bit closer to the edge to finish an outside
        -- pass, but EDGE_HARD still keeps it on the road.
        local edgeSoft = EDGE_SOFT + wide * OUTSIDE_EDGE
        if (target > 0 and myLat > edgeSoft) or (target < 0 and myLat < -edgeSoft) then
            target = target * clamp((EDGE_HARD - math.abs(myLat)) / (EDGE_HARD - edgeSoft), 0, 1)
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

        -- OVAL GROOVE (stock cars on a speedway): in a pack, commit to a high or low LANE and run it
        -- side-by-side through the banking, holding it (not darting back to one line). Take the lane
        -- the car ahead isn't in, else a stable personal groove. Edge-safety below still keeps it off
        -- the wall. This is what turns oval running into real pack racing.
        if R.isOval and classKey == 'nascar' and gapA < GROOVE_RANGE then
            local dLatA = aheadIdx >= 0 and latOf(ac.getCar(aheadIdx).position) or 0
            local side = (math.abs(dLatA) > 0.12) and -sgn(dLatA) or ((hash01(i * 7 + 3) < 0.5) and -1 or 1)
            target = side * GROOVE_OFFSET
            holdSign[i] = side; holdUntil[i] = os.clock() + GROOVE_HOLD    -- commit to the lane
        end

        -- GRID FUNNEL (race start only): hold the car near its own grid lane and merge it onto the
        -- racing line gradually over the run to turn 1, so the field funnels down instead of all
        -- converging at once. Overrides the racecraft offset here (after the deadzone) so the fade
        -- stays smooth. Gated to a packed field (crowd) so it never fires on a lone practice lap.
        if myLap == 0 and crowd >= 1 and mySpline < GRID_FADE_END then
            if gridLat[i] == nil and mySpline < GRID_CAPTURE then gridLat[i] = myLat end
            if gridLat[i] then
                target = clamp(gridLat[i] * GRID_HOLD * clamp(1 - mySpline / GRID_FADE_END, 0, 1), -1, 1)
            end
        end

        -- BLOCKAGE sweep (final word): a stopped/crawling car is on my line just ahead -> commit to the
        -- open side and go around, overriding the normal line, groove and funnel. Kept off the wall by
        -- flipping to the roomier side if the chosen one is already near an edge.
        if blockSide ~= 0 then
            if (blockSide > 0 and myLat > EDGE_SOFT) or (blockSide < 0 and myLat < -EDGE_SOFT) then
                blockSide = -blockSide                                   -- that side's against the edge -> take the other
            end
            target = blockSide * BLOCK_OFFSET
            holdSign[i] = blockSide; holdUntil[i] = os.clock() + BLOCK_HOLD
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
function R.reset()
    curOffset = {}; holdSign = {}; holdUntil = {}; pounceT = {}; commitState = {}; commitUntil = {}; gridLat = {}
    R.isOval = detectOval()     -- classify the track once per session (oval vs road course)
end

return R
