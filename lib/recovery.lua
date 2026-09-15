local Classes = require('lib.classes')
local Troublespots = require('lib.troublespots')
-- Verve / recovery.lua
-- Un-sticks AI cars that stopped but aren't wrecked: gentle throttle + self-correcting steer
-- toward a point ahead on the racing line. Backwards cars turn around. If a car is recovering
-- but not actually travelling (pinned on a wall, or two cars locked together), it shifts to
-- REVERSE for a randomized burst while turning, then retries forward -- locked pairs desync
-- via per-car randomized backup duration/side/trigger-jitter. Raw input via ac.overrideCarControls.

local R = {}
R.ENABLED = true
R.CRASH_REPAIR = false    -- experimental: repair a stuck car ON TRACK (no pit) and set it back on the racing line
-- DRIVE = take the controls of a stuck AI car ourselves (gas/steer/reverse bursts via ac.overrideCarControls).
-- OFF by default now. The 1 Hz rejoin traces showed every car we had ever driven ending up in NEUTRAL at
-- the rev limiter, throttle pinned, wheel at full lock, for 20-30 s after we handed it back -- the override
-- struct is persistent and AC's own AI never got its gearbox back. 0 of 260 repositioned cars on an F1
-- grid rejoined. Without our driving, the only things touching a stuck car are the reposition (an AI-aware
-- teleport + a push) and AC's AI -- and the reposition judges itself (see DROP_*). The reverse-burst
-- un-jamming this loses was never shown to work in the logs; if a car is wedged, the reposition moves it.
R.DRIVE = false

local MOVE_SPEED  = 30.0
local STOP_SPEED  = 5.0
local STUCK_TIME  = 2.0       -- engage a touch sooner, so AC can't retire a car in the gap
local STUCK_ONLINE = 8.0      -- a LONE car stopped ON the racing line gets this long to sort itself out before we drive it
local CLEAR_AROUND = 8.0      -- metres: another STOPPED car this close = a knot (see KNOT_T)
local KNOT_T       = 6.0      -- a knotted car gets this long, then it's staggered off the line (not driven -- see below)
local RAMP_TOPSPEED = 1e9     -- (no top-speed cap during the rejoin ramp: with one, cars crawled at 0-30 km/h and wandered off)
-- REPOSITIONING JUDGES ITSELF. The whole point of putting a car back on the line is that it REJOINS; if
-- it just gets hit again there, the reposition was harm, not help. Every drop is scored (did the car
-- reach DROP_OK_SPEED on the road within DROP_JUDGE_T?) and after a trial batch with a poor rate the
-- session stops repositioning and falls back to AC's own retirement -- a clear track beats a wreck on
-- the line. Data that forced this: 12:13-13:45 (a GT grid) 22 of 40 drops rejoined; 15:52-21:07 (an
-- 18-car mixed-F1 grid) 1 of 253 did, and every failed drop was a car parked on the racing line to be
-- collected by the next arrival. Per grid, per track, per day -- so it's measured, not assumed.
local DROP_JUDGE_T  = 30.0    -- seconds a drop has to prove itself
local DROP_OK_SPEED = 60.0    -- km/h on the road within that time = rejoined
local DROP_TRIAL    = 4       -- judge at least this many drops before deciding
local DROP_MIN_RATE = 0.30    -- below this success rate, stop repositioning for the session
local STOP_RELEASE = 4.0      -- seconds of post-incident "brake and wait" we allow before releasing AC's stop counter
local REPAIR_NEW_SPOT = 0.15  -- a repair counts as a NEW incident if the car has travelled this much of a lap since the last...
local REPAIR_NEW_T    = 60.0  -- ...OR this many seconds have passed. (Distance alone let a car loop in ONE corner for
                              -- five minutes -- 5 repairs, never a "new" incident, never retired. That's not a
                              -- repair-light/retire-heavy policy, that's a demolition derby.)
local GIVEUP_TIME = 45.0      -- absolute backstop: only after this long total do we ever hand a car back to AC
local POST_REPAIR_HOLD = 15.0 -- once we've REPAIRED a car, if it STILL won't move in this long it's wedged -> let it go
local PARK_TIME   = 75.0      -- total seconds we'll work one stuck episode (across every retry) before the car is
                              -- declared hopeless and parked in the pits. Recovery's median is ~24 s; this is the tail.
local TEMP_HOLD   = 1.5       -- seconds to keep re-applying the saved tyre temperatures after a teleport
local HOPELESS_T  = 20.0      -- a car we've given up on that's still stationary after this long is parked (instant clear).
                              -- Leaving it "for AC to retire" froze cars in the gravel for 20 MINUTES (08:15 race):
                              -- the stopped-car protection kept re-shielding it, and AC's own timer is minutes anyway.
local MAX_RESCUES = 3         -- pileup rescues (teleport back onto the line) per stuck episode (was one per RACE)
local RESCUE_FORCE_T = 20.0   -- wait up to this long for a traffic gap before FORCING a rescue drop (was 6: at a busy
                              -- corner there's a car every few seconds, the wait expired, and the drop landed
                              -- a car on the line in front of a six-car train)
local REJOIN_RAMP = 3.0       -- seconds of throttle ramp after a teleport (a car floored on cool tyres spun within 8 s)
local REJOIN_THROTTLE_CUT = 0.40 -- throttle starts at (1 - this) of full and ramps up over REJOIN_RAMP. Eased from a
                              -- 6 s / 35 % ramp under which cars never got going at all (0 of 30 rejoined)
local PIT_STUCK_T = 15.0      -- stopped in the pit LANE (not the box) this long -> it's done, let AC retire it
local BOX_LIMBO_T = 75.0      -- stationary in the BOX this long mid-race (AC damage-pit, never retired) -> retired
local boxT = {}
local DANGER_MAX  = 5.0       -- longest a recovering car waits for traffic before it goes anyway (on a busy straight
                              -- "someone's coming" is ALWAYS true -- one car waited 80 s on the line and got parked for it)
local WHEEL_BITS  = { [0] = 4, [1] = 8, [2] = 16, [3] = 32 }   -- ac.Wheel bit masks: FL, FR, RL, RR (Front = 12 = 4|8)
local NEAR_MAX    = 150.0     -- engage a STOPPED car this far off the line. Raised a lot: cars that fly
                             -- deep into a runoff/barrier (30-100 m off) used to be beyond this and were
                             -- skipped entirely -- never repositioned, never retired, frozen off-track all
                             -- race. They're stopped, so we grab them and force them back (or retire if chronic).
local ABORT_DIST  = 250.0    -- only give up on a truly absurd reading (a projection glitch), not a real crash
local GAS         = 0.28
local STEER_GAIN  = 2.0
local TARGET_AHEAD= 0.002     -- (spline fraction; re-derived from TARGET_AHEAD_M per track -- see scaleToTrack)
local FLIP_INTERVAL = 0.8
local FLIP_WORSE  = 0.12
local REJOIN_DIST = 9.0       -- hand back sooner (the AI returns to the line + accelerates faster than a crawl)
local REJOIN_FACE = 0.7
local REJOIN_SPEED= 12.0
local REJOIN_HANDBACK = 40.0  -- km/h: at this speed a car is racing, not recovering -- always hand it back
local ACCEL_GAS   = 0.7       -- once pointed forward and clear, accelerate back up to speed
local DIRT_GAS    = 0.9       -- off-track (gravel/dirt): power through instead of bogging to a stop
local OFFLINE_POWER = 4.0     -- metres off the line past which we use the dirt/gravel power-out throttle
local DANGER_GAP  = 0.006     -- fast car within this spline gap behind -> hold, don't rejoin into it
local DANGER_SPEED= 45.0      -- km/h: a car above this counts as "traffic" to watch for
local STALL_MOVE    = 1.0
local STALL_TRIGGER = 1.2
local BACK_GAS      = 0.35
local BACK_STEER    = 0.7
local BACKUP_MIN    = 0.9
local BACKUP_RANGE  = 1.0
-- TRACK-LENGTH SCALING: the spline-fraction distances below were tuned on ~4.5 km circuits; a fraction is a
-- different length on every track, so they're re-derived from METRES each session (see scaleToTrack).
local REF_LEN       = 4500
local trackLen      = REF_LEN
local scaled        = false
local DROP_NEAR, DROP_BEHIND = 0.004, 0.02    -- dropSafe: a car ON the spot / a fast car closing from this far behind
local TANGENT_STEP  = 0.003                   -- putBackOnLine: half-span of the centred tangent sample
local STAGGER_BASE, STAGGER_RANGE = 0.004, 0.010   -- pileup rescue: strung-out drop points
local function scaleToTrack(len)
    trackLen = (type(len) == 'number' and len > 200) and len or REF_LEN
    local function m(x) return x / trackLen end
    TARGET_AHEAD = m(9); DANGER_GAP = m(27); DROP_NEAR = m(18); DROP_BEHIND = m(90)
    TANGENT_STEP = m(13.5); STAGGER_BASE = m(18); STAGGER_RANGE = m(45)
end

R.count = 0    -- how many cars are being actively recovered right now (for UI)

-- crash repair: repair a stuck car IN PLACE (recovery then drives it out). No teleport, no pit.
local REPAIR_SLOW       = 15.0 -- km/h: below this counts as stuck/crippled
-- "Off track" is judged in the TRACK FRAME (lateral 0 = centre, 1 = edge), not in metres from the racing
-- line: 9 m from the line is the far side of the tarmac on a 20 m-wide oval or Paul Ricard's runoff, and
-- three car-widths into the grass on a kart track. The metre test is kept only as a backstop for a car
-- thrown so far that the track-frame projection is no longer trustworthy.
local OFF_LAT           = 1.02 -- beyond the edge by this much (track frame) = off the road
local REPOSITION_FAR    = 25.0 -- metres from the line where it's certainly off, whatever the projection says
-- limping repair: a BODY-DAMAGED car still crawling ON-track (not stuck) drags the whole field. Only
-- BODY damage -- re-bodying clears body damage but NOT suspension, so triggering on suspension just
-- re-fires forever (a kerb-riding car never stops qualifying). Suspension limpers are left to the
-- blockage go-around (traffic routes around them) rather than pointlessly re-bodied.
local LIMP_SPEED    = 100.0    -- km/h: below this while damaged = limping
local LIMP_IMPACT   = 30.0     -- km/h body impact that counts as performance-hurting damage. Lowered so a
                              -- damaged car gets a fresh body IN PLACE sooner -- before AC decides to send it
                              -- to the pits (where it strands). The once-per-episode guard stops it spamming.
local LIMP_GRACE    = 6.0      -- seconds limping before we give it a fresh body
-- "genuinely wrecked" is judged by actual DAMAGE, not just closing speed: a very hard body impact OR
-- broken suspension. A light touch (even at 150+ km/h) does neither, so it keeps racing.
local TERMINAL_IMPACT   = 160.0-- km/h of collision severity that counts as a race-ending body hit
local TERMINAL_SUSP     = 0.5  -- suspension damage (0..1) that counts as genuinely broken
-- repair "penalty" time scales with how bad the crash was (bigger hit = longer)
local REPAIR_BASE       = 2.0  -- base repair seconds (on top of the ~2.5s recovery already waited)
local REPAIR_PER_IMPACT = 0.05 -- extra seconds per km/h of impact (bigger shunt = longer penalty)
local REPAIR_MIN        = 2.0  -- clamp low = catch cars sooner, before AC's own retirement fires
local REPAIR_MAX        = 9.0
local REPAIR_GIVEUP     = 6    -- after THIS many crash-repairs, a car is a hopeless repeat offender ->
                              -- let it retire (clears the track; brings retirements to a realistic handful)

local hasMoved, stuckT, recT = {}, {}, {}
local lastFwd = {}         -- each car's forward direction while it was last up to racing speed (ground-truth "forwards")
local fwdVotes, trackFwdSign = 0, 0   -- field-wide vote: does +spline run WITH the racing direction (+1) or against it (-1)?
local FWD_VOTES_MIN, FWD_VOTES_LOCK = 20, 200
local steerSign, lastErr, checkT = {}, {}, {}
local stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
local repaired, repairRecT = {}, {}
local limpT = {}           -- how long a DAMAGED car has been crawling on-track (blocking traffic)
local limpDone = {}        -- cars already re-bodied for their CURRENT damage (don't re-body until it clears)
local repairN = {}         -- how many times we've crash-repaired each car (for the repeat-offender rule)
local rescued = {}         -- cars we've already spent their one pileup-rescue on (spread + retry)
local handedBack = {}      -- cars we've given up on -> AC owns them; don't re-arm recovery until they move
local retiredMark = {}     -- cars we've already counted as a retirement (count once)
local reported = {}        -- have we logged this incident to trouble-spots yet? (once per episode)
R.repairedCount = 0    -- CRASH repairs: stuck/beached cars fixed + put back on track this session (for UI)
R.limpCount = 0        -- LIMP repairs: damaged movers given a fresh body so they stop blocking (for UI)
R.retiredCount = 0     -- cars we handed to AC as genuinely wrecked (terminal) this session (for UI)

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end
local knot = {}            -- cars stopped in a heap with another stopped car -> straight to a staggered reposition
local lastRepairT = {}     -- os.clock() of each car's last repair (see REPAIR_NEW_T)
local overriding = {}      -- cars whose controls we've written this episode (need a release when we're done)
local hopeless = {}        -- os.clock() when we gave up on a car for good this episode (no protection, no re-arming)
local pendingDrop = {}     -- drops to verify: { pos, dir, t, tries } -- was the car actually set down facing forward?
R.dropFlips = 0            -- diagnostics: drops that needed a second attempt to face forward

-- HAND THE CONTROLS BACK. ac.overrideCarControls() is a persistent per-car struct that physics keeps
-- reading; nothing resets it when we stop writing. So the LAST values we wrote stayed applied to every
-- car we ever drove: steering forced to our final angle (often full lock), first gear (or reverse)
-- forced, and -- the killer -- clutch = 0, which in this API means the pedal PRESSED, combined as
-- min(AC's, ours): the car had NO DRIVE. The 1 Hz drop traces showed exactly that: full throttle,
-- full lock, 0 km/h for 12-20 s, then a lurch off the road. That is why 253 of 254 repositioned cars
-- on the F1 grid never rejoined, and it means our own recovery driving never had drive either.
-- Per the API docs: steer = math.huge leaves AC's steering, gear 0 keeps AC's gear, clutch 1 (pedal up)
-- leaves AC's clutch, and gas/brake/handbrake 0 contribute nothing to the max-combine.
local function releaseControls(i)
    if not overriding[i] then return end
    overriding[i] = nil
    pcall(function()
        local c = ac.overrideCarControls(i)
        if c then
            c.steer = math.huge; c.requestedGearIndex = 0; c.clutch = 1
            c.gas = 0; c.brake = 0; c.handbrake = 0
        end
    end)
end
local drops = {}           -- recent repositions being judged: { i, t, ok, spl }
local dropFailed = {}      -- cars whose last reposition did NOT rejoin: no second drop -- they retire
R.dropN, R.dropOK = 0, 0   -- session tally (for the UI / diagnostics)
R.DROP_API = 'car'         -- 'car' = physics.setCarPosition, 'ai' = physics.setAICarPosition (A/B 2026-09-14: same lap counting; 'car' rejoined cleaner)
R.gateMoves = 0            -- drops moved back before the last timing split so AC counts the lap (see gateSafe)
local GATE_MARGIN = 0.006  -- how far before the split to drop (~25 m on a 4 km track): the car must CROSS it

-- LAP-COUNT SAFE DROP. AC's lap counter needs the car to pass at least one timing split after a teleport; a car
-- dropped past the last split of the lap never does, and the next line crossing starts a lap instead of
-- completing one -- the car reads a lap down for the rest of the race (Zandvoort A/B 2026-09-14: 0 of 15 such
-- drops counted, every drop before a split did, whichever teleport API was used). So: past the last split ->
-- drop just before it. A few seconds of road instead of a lost lap. Splits come from sim.lapSplits (CSP).
local function gateSafe(sim, progress)
    -- (sim.lapSplits is a C array: 0-based, `#` gives the count; it is NOT a Lua table -- a type() check skipped it
    -- and the 2026-09-14 19:26 verification race gated nothing)
    local lastGate = 0
    pcall(function()
        local splits = sim.lapSplits
        local n = #splits
        for k = 0, n - 1 do
            local s = splits[k]
            if type(s) == 'number' and s > 0.02 and s < 0.98 and s > lastGate then lastGate = s end
        end
    end)
    if lastGate <= 0 or progress < lastGate - GATE_MARGIN * 0.5 then return progress, false end   -- a split still ahead: fine
    return lastGate - GATE_MARGIN, true
end

-- Verve's own lap count: AC drops the lap after a teleport about half the time (2026-09-14: 13 of 24 repositions),
-- leaving the car "a lap down" in AC's eyes for the rest of the race. Count start-line crossings ourselves while
-- the car is moving forward, and let racecraft trust this instead of car.lapCount.
local ownLaps, ownSpline = {}, {}
local function trackLaps(i, car)
    local sp = car.splinePosition
    if type(sp) ~= 'number' then return end
    local last = ownSpline[i]
    if last ~= nil and last > 0.9 and sp < 0.1 and (car.speedKmh or 0) > 20 then ownLaps[i] = (ownLaps[i] or 0) + 1 end
    ownSpline[i] = sp
    -- never fall below AC's own count (it can only be higher than ours if we missed a crossing)
    local acLaps = car.lapCount or 0
    if (ownLaps[i] or 0) < acLaps then ownLaps[i] = acLaps end
end
function R.lapsOf(i)
    local car = ac.getCar(i)
    if not car then return 0 end
    return math.max(ownLaps[i] or 0, car.lapCount or 0)
end
R.dropsOff = false         -- repositioning switched off for this session (rate too poor)

-- may this car be repositioned automatically right now?
local function dropsAllowed(i)
    if dropFailed[i] then return false end
    if R.dropsOff then return false end
    return true
end

-- score the pending drops; switch repositioning off for the session if the rate is poor
local function judgeDrops(now)
    local keep = {}
    for _, d in ipairs(drops) do
        if d.ok == nil then
            local c = ac.getCar(d.i)
            if c and (c.speedKmh or 0) > DROP_OK_SPEED then
                d.ok = true; R.dropOK = R.dropOK + 1
            elseif now - d.t > DROP_JUDGE_T or (c and c.isRetired) then
                d.ok = false; dropFailed[d.i] = true
            end
        end
        if d.ok == nil or now - d.t < DROP_JUDGE_T + 30 then keep[#keep + 1] = d end   -- (kept a bit longer for the diag trace)
    end
    drops = keep
    local judged = 0
    for _, d in ipairs(drops) do if d.ok ~= nil then judged = judged + 1 end end
    judged = math.max(judged, R.dropN - #drops)   -- (older ones dropped from the list were judged too)
    if not R.dropsOff and R.dropN >= DROP_TRIAL and judged >= DROP_TRIAL and (R.dropOK / R.dropN) < DROP_MIN_RATE then
        R.dropsOff = true
        pcall(function() ac.log(string.format('Verve: repositioning off for this session (%d of %d rejoined)', R.dropOK, R.dropN)) end)
    end
end
function R.recentDrops() return drops end   -- (diagnostics)
function R.fwdSign() return trackFwdSign, fwdVotes end   -- (diagnostics)

local function endRec(i)
    releaseControls(i)
    recT[i] = nil; checkT[i] = nil; lastErr[i] = nil; knot[i] = nil
    stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil
    -- NOTE: `reported` is intentionally NOT cleared here. Clearing it every time a recovery attempt
    -- ends let one wreck be re-reported as a fresh incident each cycle (dozens of "incidents" from a
    -- single crash, poisoning the trouble-spot map). It's cleared only when the car genuinely moves
    -- again (a real new episode), below.
end
-- Give up on a car for good: hand it back to AC and DON'T re-arm recovery on it until it actually moves
-- again (or the session resets). Without this, a stuck car re-qualifies the very next frame -- restarting
-- recovery and its retirement-prevention in a loop.
local parked = {}          -- cars we've RETIRED ourselves (parked in the pits for good) -- never touched again
local dmgBase = {}         -- car.damage reading at each car's last repair (see effImpact)
local episodeT = {}        -- seconds spent working a car's CURRENT stuck episode, across every retry
local lastRepairSpl = {}   -- where each car was last repaired (repairs in the same spot are ONE incident)
local rescueN, rescueWaitT = {}, {}   -- rescues used this episode / seconds waited for a safe drop
local rejoinUntil = {}     -- throttle-ramp deadline after a teleport
local pitStuckT = {}       -- seconds stopped in the pit lane (outside the box)
local dangerT = {}         -- seconds a recovering car has been holding for traffic (capped by DANGER_MAX)
local overridesCleared = false   -- one-time (re)load self-heal: drop any throttle/top-speed limits we left on cars

-- throttle allowed right now for a car that was just set back on the track (1 = no limit)
local function rampLimit(i)
    local ru = rejoinUntil[i]
    if not ru then return 1 end
    local rem = ru - os.clock()
    if rem <= 0 then rejoinUntil[i] = nil; return 1 end
    return clamp(1 - REJOIN_THROTTLE_CUT * rem / REJOIN_RAMP, 0.3, 1)
end
local pendingTemps = {}    -- tyre temperatures to keep re-applying for a moment after a teleport
local tyreErrLogged = false
local apiLogged = false     -- one-time log of which reposition API this CSP build gave us

-- Re-apply saved tyre temperatures. A single call right after setCarPosition didn't stick (the logs
-- still showed 12 °C on every repositioned car): the teleport's own reset lands on a later physics
-- step. So we schedule the temperatures and push them every frame for TEMP_HOLD seconds.
local function applyTemps(i, temps)
    local ok, err = pcall(function()
        for k = 0, 3 do
            if temps[k] then physics.setTyresTemperature(i, WHEEL_BITS[k], temps[k], 15) end   -- 15 = every layer + core
        end
    end)
    if not ok and not tyreErrLogged then
        tyreErrLogged = true
        pcall(function() ac.log('Verve: setTyresTemperature failed: ' .. tostring(err)) end)
    end
end
local function giveUp(i)
    handedBack[i] = true
    endRec(i)
end
-- Retire a car OURSELVES: teleport it to its pit box and hold it there (brakes on, no throttle). The old
-- way -- stop protecting it and wait for AC to retire it -- left wrecks sitting on the track for 100-200 s
-- (AC only retires a car after a long stop, and never one that's upright and "fine"), and every second
-- a hulk sits at a corner it collects the next car through. A real wreck is craned off; this is that.
-- Implementation: hold the car still and STOP protecting it -- AC retires a stationary, unprotected AI in
-- ~20 s through its own retirement (its own bookkeeping, its own pit box). We briefly teleported hopeless
-- cars to the pits ourselves; AC didn't know those boxes were occupied, and a car it sent in for repairs
-- then spent eight minutes crashing into two "retired" cars at pit exit. Native retirement it is; the
-- yellow flag + go-around cover the ~20 s the wreck sits there.
local function parkInPits(i)
    if parked[i] then return end
    parked[i] = true
    -- Move it to its pit box NOW. AC's own retirement of a stationary car took 160-540 s in the 07:05 race
    -- (a wreck sat in view for six laps; a "frozen" car at the pit exit for seven minutes). Its box is where
    -- AC's own retirement puts it anyway; AC's bookkeeping catches up when its timer fires.
    pcall(function() physics.teleportCarTo(i, ac.SpawnSet.Pits) end)
    pcall(function() physics.setAIStopCounter(i, 36000) end)      -- stay put (AC's own "brake and wait")
    pcall(function() physics.setAIThrottleLimit(i, 0) end)        -- and no throttle, so it can't creep off
    if not retiredMark[i] then retiredMark[i] = true; R.retiredCount = (R.retiredCount or 0) + 1 end
    endRec(i)
end

-- worst impact recorded across the car's damage zones (km/h). Index range read defensively.
local function maxImpact(car)
    local m = 0
    pcall(function()
        local d = car.damage
        if d then
            for k = 0, 4 do local v = d[k]; if type(v) == 'number' and v > m then m = v end end
            for k = 1, 5 do local v = d[k]; if type(v) == 'number' and v > m then m = v end end
        end
    end)
    return m
end

-- worst suspension damage (0..1) across the car's wheels
local function maxSusp(car)
    local susp = 0
    pcall(function()
        if car.wheels then
            for k = 0, 3 do
                local w = car.wheels[k]
                if w and type(w.suspensionDamage) == 'number' and w.suspensionDamage > susp then susp = w.suspensionDamage end
            end
        end
    end)
    return susp
end

-- Is the car GENUINELY wrecked (race-ending in real life)? By actual damage, not just closing speed:
-- a very hard body impact OR broken suspension. A light touch does neither.
local function terminalDamage(car)
    return maxImpact(car) >= TERMINAL_IMPACT or maxSusp(car) >= TERMINAL_SUSP
end

-- `car.damage` is a RECORD of the worst collision per zone -- it never goes back down, not even when we
-- give the car a fresh body (verified over 294 repairs in the logs: it dropped on-track exactly once).
-- So every rule that read it saw a repaired car as "still wrecked" forever: the damaged-car yield kept
-- it off the racing line for the rest of the race, the limp logic thought it never healed, and the
-- repair penalty kept growing. Track the reading at the last repair and use damage SINCE then.
local function effImpact(car, i) return math.max(0, maxImpact(car) - (dmgBase[i] or 0)) end
local function repairBody(i, car)
    pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)
    dmgBase[i] = maxImpact(car)
end

local function latOf(p)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(p); if tc then x = tc.x end end)
    return x
end

-- Is it SAFE to drop a car back onto the line at track progress `prog`? Only blocked by a car that's
-- basically on the spot, or a FAST car closing on it from just behind (would collect it). A car ahead,
-- or a slow/distant one, doesn't block -- so this succeeds far more often than a blanket "spot clear",
-- which is why beached cars used to never actually get repositioned.
local function dropSafe(sim, i, prog)
    for j = 0, sim.carsCount - 1 do
        if j ~= i then
            local oc = ac.getCar(j)
            if oc and oc.splinePosition then
                local g = oc.splinePosition - prog
                if g > 0.5 then g = g - 1 elseif g < -0.5 then g = g + 1 end   -- signed: >0 ahead, <0 behind
                local ag = math.abs(g)
                if ag < DROP_NEAR then return false end                         -- someone right on the spot
                if g < 0 and ag < DROP_BEHIND and (oc.speedKmh or 0) > DANGER_SPEED then return false end  -- fast car closing from behind
            end
        end
    end
    return true
end

-- Put an OFF-TRACK (beached) car back on the racing line at its own progress, facing forward, just
-- off to the roomier side. A beached car can't drive itself across the gravel, so this is what actually
-- gets it to REJOIN. Gated by dropSafe unless `force` (a last-resort so a car is never abandoned).
local function putBackOnLine(sim, i, progress, center, force)
    if not center then return false end
    local gated
    progress, gated = gateSafe(sim, progress)
    if gated then
        center = ac.trackProgressToWorldCoordinate(progress, false)
        if not center then return false end
        R.gateMoves = R.gateMoves + 1
    end
    if not force and not dropSafe(sim, i, progress) then return false end
    -- forward direction from a CENTRED sample (a point behind -> a point ahead), which is far steadier
    -- than a tiny forward-only step and always points along the racing direction.
    local pB = ac.trackProgressToWorldCoordinate((progress - TANGENT_STEP) % 1, false)
    local p1 = ac.trackProgressToWorldCoordinate((progress + TANGENT_STEP) % 1, false)
    if not (pB and p1) then return false end
    local fx, fy, fz = p1.x - pB.x, p1.y - pB.y, p1.z - pB.z
    local flen = math.sqrt(fx * fx + fy * fy + fz * fz)
    if flen < 1e-4 then return false end
    fx, fy, fz = fx / flen, fy / flen, fz / flen
    -- The spline tangent gives the LINE the car should sit on, but its sign (which way is "forwards")
    -- can't be trusted -- on some tracks the track spline runs opposite to the racing direction, which
    -- is what dropped cars in facing BACKWARD. So flip it to match the direction this car was actually
    -- racing (recorded while it was up to speed). That's the ground truth for "forwards" here.
    -- Prefer the TRACK's voted direction (every car running forwards on the road agrees on it within
    -- seconds of the start); fall back to this car's own last forward heading only before the vote locks.
    if trackFwdSign ~= 0 then
        if trackFwdSign < 0 then fx, fy, fz = -fx, -fy, -fz end
    elseif lastFwd[i] and (fx * lastFwd[i].x + fy * lastFwd[i].y + fz * lastFwd[i].z) < 0 then
        fx, fy, fz = -fx, -fy, -fz
    end
    local dir = vec3(fx, fy, fz)
    -- Drop point: 2 m off the line toward the centre of the road. (An "edge of the road" drop was tried
    -- for one race -- 0 of 30 rejoined -- but the morning's 50-70 % rejoin rate was with this one.)
    local sx, sz = -fz, fx                                   -- level perpendicular to forward
    local a = vec3(center.x + sx * 2.0, center.y + 0.3, center.z + sz * 2.0)
    local b = vec3(center.x - sx * 2.0, center.y + 0.3, center.z - sz * 2.0)
    local pos = (math.abs(latOf(a)) <= math.abs(latOf(b))) and a or b   -- the roomier side (nearer track centre)
    -- Report honestly: if the physics call throws, this returns FALSE so callers don't count a repair or
    -- a "rejoin" that never happened. (setCarPosition sets orientation but NOT velocity, so a car sliding
    -- backward from its crash keeps that momentum -- we give it a small forward velocity so it sets off
    -- the right way and recovery just keeps it rolling.)
    -- Teleporting a car resets its tyres to AMBIENT temperature. The logs were unambiguous: on a 12 °C
    -- day, 56 of the last 56 repositioned cars re-crashed within 40 s -- they were set down on ice-cold
    -- rubber and spun at the very next corner, which is where the endless stuck -> reposition -> stuck
    -- loop came from. Tyres don't go cold in an instant, so snapshot each wheel's core temperature and
    -- put it back after the move: the car rejoins on the rubber it actually had.
    local temps = {}
    pcall(function()
        local car = ac.getCar(i)
        if car and car.wheels then
            for k = 0, 3 do
                local w = car.wheels[k]
                local t = w and (w.tyreCoreTemperature or w.tyreTemperature)
                if type(t) == 'number' and t > 0 then temps[k] = t end
            end
        end
    end)
    -- Move it with the AI-aware call. physics.setAICarPosition exists specifically for AI cars: it moves
    -- the AI DRIVER's state along with the body. The generic setCarPosition moved the car but left the
    -- AI driver behind: the 1 Hz traces after every drop showed the AI at full throttle in NEUTRAL at
    -- the rev limiter, hunting 1st <-> N, steering at full lock, for 20-30 s -- a driver that no longer
    -- knew where it was. Falls back to the generic call only if the AI one isn't available.
    -- THE API'S `dir` IS THE OPPOSITE OF THE CAR'S NOSE. Verified, not assumed: with the heading check
    -- below, 21 of 21 drops in one race read "backwards" (dot -1.00) when passed the forward direction,
    -- twice in a row, and every one faced forward once the direction was reversed. So the physics call gets
    -- the reversed vector; the push (velocity) stays along the true forward direction. The check below is
    -- kept as a safety net (and will log if a CSP build ever changes the convention).
    local apiDir = vec3(-fx, -fy, -fz)
    local okp = pcall(function()
        local moved
        if R.DROP_API == 'car' then moved = pcall(physics.setCarPosition, i, pos, apiDir)
        else moved = pcall(physics.setAICarPosition, i, pos, apiDir) end
        if not moved then physics.setCarPosition(i, pos, apiDir) end
        if not apiLogged then
            apiLogged = true
            pcall(function() ac.log('Verve: reposition uses ' .. (moved and 'physics.setAICarPosition' or 'physics.setCarPosition (AI variant unavailable)')) end)
        end
        physics.setCarVelocity(i, dir * 8.0)
        physics.setAIStopCounter(i, 0)               -- a teleport can re-trigger the AI's post-incident "brake and wait"
        pcall(physics.setAINoInput, i, false, false) -- and make sure the AI's input isn't in its "parked" state after the move
    end)
    if okp and next(temps) ~= nil then
        applyTemps(i, temps)
        pendingTemps[i] = { temps = temps, untilT = os.clock() + TEMP_HOLD }
    end
    if okp then
        rejoinUntil[i] = os.clock() + REJOIN_RAMP            -- rejoin gently (see REJOIN_RAMP)
        drops[#drops + 1] = { i = i, t = os.clock(), ok = nil, spl = progress }   -- judged over the next DROP_JUDGE_T
        pendingDrop[i] = { pos = pos, dir = dir, apiDir = apiDir, t = os.clock(), tries = 0 }   -- verify its heading next frame
        R.dropN = R.dropN + 1
    end
    return okp
end

function R.update(dt)
    if not R.ENABLED then R.count = 0; return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end
    local active = 0
    if not scaled then scaled = true; pcall(function() scaleToTrack(sim.trackLengthM) end) end   -- per-track distances (self-heals after a hot-reload)
    if #drops > 0 then pcall(judgeDrops, os.clock()) end
    if not overridesCleared then
        -- After a (re)load our per-car tables are empty but the limits we set on the PHYSICS side persist: a
        -- car mid throttle-ramp would stay at 40% throttle for the rest of the race. Clear them all once.
        overridesCleared = true
        for i = 0, sim.carsCount - 1 do
            pcall(function()
                local c = ac.getCar(i)
                if c and c.isAIControlled and not c.isRetired then physics.setAIThrottleLimit(i, 1); physics.setAITopSpeed(i, 1e9) end
            end)
            overriding[i] = true; releaseControls(i)      -- and any stale control override from before the (re)load
        end
    end
    for i = 0, sim.carsCount - 1 do          -- includes the player's car WHEN it's under AI control (Ctrl+C)
        pcall(function()
            local car = ac.getCar(i)
            if not car then return end
            trackLaps(i, car)
            -- Record which way EVERY car is racing (incl. a manually-driven player) while it's up to speed,
            -- so a reset -- the unstick button especially -- can face it the right way. Done before the
            -- AI-control gate, because the player's own car isn't AI-controlled while you drive it.
            -- ...but only while it's actually travelling FORWARDS on the road. A car sliding backwards out of
            -- a crash does 40 km/h too, and recording its heading then poisoned every later reset: the
            -- 07:38 race's player car was set down backwards three times in a row, and car 11 sat at one
            -- corner for 14 minutes being set down backwards, because each backwards roll re-poisoned it.
            -- Every valid sample also votes on the TRACK's spline direction (see trackFwdSign), which is
            -- what resets actually use: the convention is per track, not per car.
            if (car.speedKmh or 0) > MOVE_SPEED and car.look then
                local fwdOK = true
                pcall(function()
                    local v = car.velocity
                    if v then fwdOK = (v.x * car.look.x + v.y * car.look.y + v.z * car.look.z) > 0 end
                end)
                if fwdOK and math.abs(latOf(car.position)) < 1.0 then
                    lastFwd[i] = vec3(car.look.x, car.look.y, car.look.z)
                    if math.abs(fwdVotes) < FWD_VOTES_LOCK then
                        pcall(function()
                            local sp = car.splinePosition
                            if type(sp) ~= 'number' then return end
                            local pB = ac.trackProgressToWorldCoordinate((sp - TANGENT_STEP) % 1, false)
                            local p1 = ac.trackProgressToWorldCoordinate((sp + TANGENT_STEP) % 1, false)
                            if not (pB and p1) then return end
                            local d = (p1.x - pB.x) * car.look.x + (p1.y - pB.y) * car.look.y + (p1.z - pB.z) * car.look.z
                            if d > 0 then fwdVotes = fwdVotes + 1 elseif d < 0 then fwdVotes = fwdVotes - 1 end
                            if fwdVotes >= FWD_VOTES_MIN then trackFwdSign = 1 elseif fwdVotes <= -FWD_VOTES_MIN then trackFwdSign = -1 end
                        end)
                    end
                end
            end
            if not car.isAIControlled then return end
            if parked[i] then return end                -- retired by us: sitting in its pit box, leave it be
            local pt = pendingTemps[i]
            if pt then
                if os.clock() < pt.untilT then applyTemps(i, pt.temps) else pendingTemps[i] = nil end
            end
            if rejoinUntil[i] then
                local lim = rampLimit(i)                      -- (returns 1 and clears itself when the ramp ends)
                pcall(function() physics.setAIThrottleLimit(i, lim); physics.setAIStopCounter(i, 0) end)   -- (and keep it un-parked while it rejoins)
            end
            -- VERIFY THE DROP'S HEADING. Cars kept being set down BACKWARDS at some corners even with a
            -- track-wide direction vote, so trust nothing: a beat after the move, read the car's actual nose
            -- against the direction we asked for. Backwards -> apply the move again; still backwards -> apply
            -- it with the direction REVERSED (whatever the API's convention, one of the two is right), and
            -- log which worked so the convention is known, not assumed.
            local pd = pendingDrop[i]
            if pd then
                local age = os.clock() - pd.t
                if age > 0.25 and pd.tries < 2 and car.look then
                    local d = car.look.x * pd.dir.x + car.look.y * pd.dir.y + car.look.z * pd.dir.z
                    if d < 0 then
                        pd.tries = pd.tries + 1
                        -- attempt 2: the API vector again (a transient); attempt 3: the opposite convention
                        local useDir = (pd.tries == 1) and pd.apiDir or pd.dir
                        pcall(function()
                            if R.DROP_API == 'car' or not pcall(physics.setAICarPosition, i, pd.pos, useDir) then physics.setCarPosition(i, pd.pos, useDir) end
                            physics.setCarVelocity(i, useDir * 8.0)
                            physics.setAIStopCounter(i, 0)
                        end)
                        R.dropFlips = R.dropFlips + 1
                        pcall(function() ac.log(string.format('Verve: car %d set down BACKWARDS (dot %.2f); attempt %d with dir %s', i, d, pd.tries + 1, pd.tries == 1 and 'as asked' or 'REVERSED')) end)
                        pd.t = os.clock()
                    else
                        if pd.tries > 0 then pcall(function() ac.log(string.format('Verve: car %d faces forward after attempt %d', i, pd.tries + 1)) end) end
                        pendingDrop[i] = nil
                    end
                elseif age > 2.0 then
                    pendingDrop[i] = nil
                end
            end
            -- GIVEN UP ON and still sitting there: park it (instant clear) rather than leave a frozen car
            if hopeless[i] and spd < STOP_SPEED and (os.clock() - hopeless[i]) > HOPELESS_T then parkInPits(i); return end
            local retired = false
            pcall(function() retired = (car.isRetired == true) end)
            if retired then
                -- count the ACTUAL retirement (any cause: our give-up, terminal, or AC itself), once per car.
                -- This is ground truth -- far more honest than counting our own "give up" decisions, which
                -- don't always end in a retirement.
                if not retiredMark[i] then retiredMark[i] = true; R.retiredCount = (R.retiredCount or 0) + 1 end
                endRec(i); return
            end
            local spd = car.speedKmh or 0
            if spd > MOVE_SPEED then
                hasMoved[i] = true; repaired[i] = nil; repairRecT[i] = nil   -- back racing: reset
                handedBack[i] = nil; reported[i] = nil                       -- genuinely moving again -> a future stop is a NEW episode
                episodeT[i] = nil
                rescueN[i] = nil; rescueWaitT[i] = nil; rescued[i] = nil   -- rescues are per EPISODE (a lap-8 crash gets them again)
                hopeless[i] = nil
                -- A car doing racing speed is NOT in recovery, whatever the rejoin checks below say. Without
                -- this, a car that got going with traffic close behind ("danger") never handed back: recovery
                -- kept dragging the brake on a car at 180 km/h, its clock kept running, and after 45 s it was
                -- "rescued" -- teleported -- or parked mid-race. Up to speed = AC's AI owns it again.
                if spd > REJOIN_HANDBACK and (recT[i] or 0) > 0 then endRec(i) end
            end
            -- NOTE: we deliberately DO let a given-up car re-enter recovery. An earlier build stopped
            -- re-arming ("handed back to AC") and the data was unambiguous: far-off recoveries fell from
            -- 11/11 to 3/8 and retirements jumped 3 -> 7, because AC won't retire an upright car and
            -- so the abandoned ones just sat. The re-try loop is what actually gets cars back; the
            -- incident double-counting it used to cause is fixed separately (`reported` isn't cleared
            -- per attempt any more). `handedBack` is kept purely as a diagnostic flag.
            if car.isInPitlane then
                stuckT[i] = 0; endRec(i)
                -- STRANDED IN THE PIT LANE (crashed at the pit exit, wedged on the pit wall): give it a moment
                -- to sort itself out, protected; if it's still stuck after PIT_STUCK_T it's done -- let AC
                -- retire it. (Sending it back to its box to try again looped it into the parked cars next
                -- door for eight minutes.) In the BOX it's doing a stop: leave it alone.
                local inBox = false; pcall(function() inBox = (car.isInPit == true) end)
                -- LIMBO IN THE BOX: AC sent a damaged AI car to its box (its own damage-pit teleport) and then never
                -- retired it -- our protection blocks AC's retirement -- so it sat there "running" for 40 laps
                -- (Zandvoort + Silverstone GPs, 2026-09-14). A real stop is under a minute; longer than that in
                -- a race with laps on the board is a retirement: mark it so bookkeeping, feed and reports agree.
                if inBox and spd < STOP_SPEED and (car.lapCount or 0) >= 1 and car.isAIControlled then
                    boxT[i] = (boxT[i] or 0) + dt
                    if boxT[i] > BOX_LIMBO_T then parkInPits(i); boxT[i] = 0 end
                else
                    boxT[i] = 0
                end
                if not inBox and spd < STOP_SPEED and not terminalDamage(car) then
                    pitStuckT[i] = (pitStuckT[i] or 0) + dt
                    pcall(function() physics.preventAIFromRetiring(i) end)
                    if pitStuckT[i] > PIT_STUCK_T then
                        -- Wedged at the pit exit (AC's own damage-pit teleport sent it out and it hit the exit
                        -- wall -- 07:05 race, car 16, 18 km/h of damage). It's a stuck car like any other: set it
                        -- on the track at its own progress, traffic-aware. Only if that's not available/failed
                        -- for long enough does it retire. (Parking it here left a "frozen" car in view for 7 min.)
                        if dropsAllowed(i) and (rescueN[i] or 0) < MAX_RESCUES then
                            local progress = car.splinePosition
                            local center = (type(progress) == 'number' and progress >= 0 and progress <= 1)
                                           and ac.trackProgressToWorldCoordinate(progress, false) or nil
                            if center and putBackOnLine(sim, i, progress, center, pitStuckT[i] > PIT_STUCK_T + RESCUE_FORCE_T) then
                                rescueN[i] = (rescueN[i] or 0) + 1; rescued[i] = true
                                repairBody(i, car)
                                pitStuckT[i] = 0
                            end
                        elseif pitStuckT[i] > PIT_STUCK_T + 40 then
                            parkInPits(i)
                        end
                    end
                else
                    pitStuckT[i] = 0
                end
                return
            end
            if not hasMoved[i] then return end

            -- STOPPED ANYWHERE (a jam, a post-incident wait): AC retires an AI car that hasn't moved for
            -- ~20 s wherever it is -- one pileup took four HEALTHY cars that were simply queued behind the
            -- mess. Keep every stopped, non-wrecked car alive, and after a short (human) post-incident
            -- pause release AC's "brake and wait" so the queue can actually get going again.
            if R.CRASH_REPAIR and spd < STOP_SPEED and not terminalDamage(car) and not hopeless[i] then
                pcall(function() physics.preventAIFromRetiring(i) end)
                -- (AC's own post-incident "brake and wait" is left alone: releasing it early sent queued cars
                -- into each other. A car that's genuinely stuck reaches recovery below, which releases it then.)
            end

            -- LIMPING: a DAMAGED car that's still moving but crawling on-track drags the whole field down
            -- behind it. It never trips the stuck/recovery logic (it IS moving), so handle it here: after a
            -- short grace, give it a fresh body IN PLACE so it rejoins racing pace. Requires real damage
            -- (a big body impact), so it never fires on a healthy car just going slow through a corner; and
            -- not for a genuinely-wrecked (terminal) car, which should retire rather than be patched.
            -- clear the guard only once the body damage is actually GONE (below the trigger). If a re-body
            -- cleared it, the car no longer qualifies anyway; if the re-body didn't take, the damage stays
            -- high and the guard stays set -- so we re-body a given car at most ONCE per damage episode,
            -- never in a loop. (This is what turns the old runaway 180-360 count into a handful.)
            if effImpact(car, i) < LIMP_IMPACT then limpDone[i] = nil end
            -- (No upper speed gate: a damaged F1 car is "limping" at 180 km/h too. With the old < 100 km/h
            -- window fast classes never qualified, so their damage was never patched.)
            if R.CRASH_REPAIR and spd > STOP_SPEED
               and effImpact(car, i) >= LIMP_IMPACT and not limpDone[i] and not terminalDamage(car) then
                limpT[i] = (limpT[i] or 0) + dt
                if limpT[i] > LIMP_GRACE then
                    repairBody(i, car)
                    limpT[i] = 0
                    limpDone[i] = true
                    R.limpCount = (R.limpCount or 0) + 1
                end
            else
                limpT[i] = 0
            end

            local isActive = (recT[i] or 0) > 0
            if not isActive then
                if spd > STOP_SPEED then stuckT[i] = 0; return end
                stuckT[i] = (stuckT[i] or 0) + dt
                if stuckT[i] < STUCK_TIME then return end
            end

            -- Use car.splinePosition for the car's track progress -- AC tracks it reliably even when the
            -- car is flung far off into a runoff. Projecting the world position onto the spline (the old
            -- way) returns garbage for a deep-off car, which is exactly why those wrecks were judged
            -- "impossibly far" and skipped -- frozen off-track all race. Fall back to the projection only
            -- if splinePosition is somehow unavailable.
            local progress = car.splinePosition
            if type(progress) ~= 'number' or progress < 0 or progress > 1 then
                local tc = ac.worldCoordinateToTrack(car.position)
                progress = tc and tc.z
            end
            if type(progress) ~= 'number' or progress < 0 or progress > 1 then return end
            local center = ac.trackProgressToWorldCoordinate(progress, false)
            if not center then return end
            local nearDist = car.position:distance(center)
            if not isActive and nearDist > NEAR_MAX then return end
            -- ON the line and stopped: give AC's AI (and the queue around it) a while to sort itself out
            -- before we take over -- but DO take over eventually: a car parked on the line is never
            -- handled by AC (it just sits, then gets retired), and the backup bursts un-jam a locked knot.
            if not isActive and nearDist < 3.0 then
                -- Another STOPPED car right next to it = a knot (two cars that tapped and both braked, a
                -- heap). Neither AC's AI (won't drive into the other) nor our recovery driving (nudges them
                -- into each other) untangles a knot -- the 19:59 race was 100 s of that -- and leaving it
                -- to AC parked two cars side by side on the racing line for 32 s until the player arrived
                -- at 267 km/h (20:51). The ONE thing that has worked all day is the staggered reposition,
                -- so a knot goes straight to it after a short pause. A lone stopped car gets STUCK_ONLINE.
                local knotted = false
                for j = 0, sim.carsCount - 1 do
                    if j ~= i then
                        local oc = ac.getCar(j)
                        if oc and (oc.speedKmh or 0) < STOP_SPEED and oc.position:distance(car.position) < CLEAR_AROUND then
                            knotted = true; break
                        end
                    end
                end
                if knotted then
                    if (stuckT[i] or 0) < KNOT_T then return end
                    knot[i] = true
                elseif (stuckT[i] or 0) < STUCK_ONLINE then
                    return
                end
            end
            if nearDist > ABORT_DIST then giveUp(i); return end

            recT[i] = (recT[i] or 0) + dt
            episodeT[i] = (episodeT[i] or 0) + dt
            if not reported[i] then          -- log this incident's location for trouble-spot learning (once)
                reported[i] = true
                pcall(function() Troublespots.incident(car.splinePosition, Classes.keyOf(i)) end)
            end
            -- Only hand a car back to AC's retirement once we've genuinely exhausted our options:
            -- either we already REPAIRED it and it STILL won't move after a good while (so it's wedged
            -- in geometry, not just damaged), or an absolute time backstop. Until then we keep blocking
            -- AC's retirement and working the car (backups, repair, driving it out).
            local exhausted = repaired[i] and repairRecT[i] and (recT[i] - repairRecT[i]) > POST_REPAIR_HOLD
            if knot[i] and (rescueN[i] or 0) >= MAX_RESCUES then knot[i] = nil end   -- no rescues left: drive it like any other
            if exhausted or recT[i] > GIVEUP_TIME or knot[i] then
                -- ONE rescue attempt before we EVER let a car retire (this is what breaks a pileup): if it
                -- isn't terminally wrecked, give it a fresh body and force it back onto the racing line at a
                -- STAGGERED point -- a per-car offset so a knot of wedged cars lands strung out over ~15-60 m
                -- instead of restacking on the same spot -- then restart recovery and KEEP protecting it from
                -- AC's retirement while it drives away. Cars in a heap get separated and rejoin, rather than
                -- all timing out together and mass-retiring.
                if R.CRASH_REPAIR and dropsAllowed(i) and (rescueN[i] or 0) < MAX_RESCUES and not terminalDamage(car) then
                    -- Traffic-aware: wait (protected) for a gap before dropping it on the line, and only
                    -- FORCE the drop after RESCUE_FORCE_T. A forced drop straight in front of a car arriving
                    -- at 150 km/h wrecked both of them.
                    rescueWaitT[i] = (rescueWaitT[i] or 0) + dt
                    local stagger = (progress + STAGGER_BASE + hash01(i * 17) * STAGGER_RANGE) % 1
                    local sc = ac.trackProgressToWorldCoordinate(stagger, false)
                    if putBackOnLine(sim, i, stagger, sc or center, rescueWaitT[i] > RESCUE_FORCE_T) then
                        rescueN[i] = (rescueN[i] or 0) + 1; rescued[i] = true; rescueWaitT[i] = nil; knot[i] = nil
                        repairBody(i, car)
                        releaseControls(i)                            -- the drop hands the car to AC's AI: give it the controls
                        recT[i] = 0; repaired[i] = nil; repairRecT[i] = nil
                        stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil
                    else
                        pcall(function() physics.preventAIFromRetiring(i); physics.setAIStopCounter(i, 0) end)
                    end
                    return
                end
                -- rescue already spent: is it genuinely hopeless? Only once we've been working this car
                -- for PARK_TIME straight (across every retry) or it's wrecked do we park it in the pits.
                -- Otherwise hand it back and let recovery re-arm -- most cars DO get away on a retry.
                -- (A build that parked here on the first exhaustion retired 12 of 18 cars in three laps.)
                -- Wrecked or worked-on-for-ages: retire it. Otherwise hand it back to AC's AI unprotected --
                -- if it can drive off, it will; if it can't, AC retires it in ~20 s. (Retiring every car whose
                -- reposition failed cost six lightly-damaged cars in one race.)
                if terminalDamage(car) or (episodeT[i] or 0) > PARK_TIME then parkInPits(i) else hopeless[i] = hopeless[i] or os.clock(); giveUp(i) end
                return
            end
            active = active + 1

            -- TERMINAL DAMAGE: a genuinely massive shunt ends the car, just like real life. Don't fight
            -- to save it -- stop here so we quit blocking AC and it retires, and we don't waste a wing on
            -- it. (Body damage clears when we repair, so this only ever catches the ORIGINAL big hit,
            -- never a car we've already fixed and sent back out.)
            if R.CRASH_REPAIR and terminalDamage(car) then parkInPits(i); return end

            -- REPEAT OFFENDER: a car we've already patched up many times that keeps wrecking itself is,
            -- realistically, a broken car -- in real racing it would retire. Stop saving it and let it go,
            -- so it clears the track instead of crash-looping all race (finishing 10+ laps down and piling
            -- up traffic). This is what brings retirements up from zero to a realistic handful, and it
            -- self-scales: a clean track rarely triggers it, a crash-heavy one retires its worst few.
            if R.CRASH_REPAIR and (repairN[i] or 0) >= REPAIR_GIVEUP then parkInPits(i); return end

            -- HIJACK AC's retirement: while we're working this car, stop AC retiring it and release
            -- its post-incident "brake and wait" so it (and our recovery) can move. We keep calling
            -- these every frame it's in recovery; the moment recovery gives up (GIVEUP_TIME) we stop,
            -- and only THEN does AC retire it -- so retirements become the few genuinely hopeless cars.
            if R.CRASH_REPAIR and not hopeless[i] then
                pcall(function() physics.preventAIFromRetiring(i); physics.setAIStopCounter(i, 0) end)
            end

            -- CRASH REPAIR (opt-in): after a severity-scaled penalty, give the car a fresh wing/body
            -- IN PLACE (setCarBodyDamage 0 -- no teleport, no pit, no fuel reset), so recovery's
            -- driving below can get it going. A car whose SUSPENSION is broken (genuinely too damaged)
            -- isn't fixed by this, stays crippled, and retires -- exactly "repair light, retire heavy".
            if R.CRASH_REPAIR and not repaired[i] and spd < REPAIR_SLOW then
                local penalty = clamp(REPAIR_BASE + effImpact(car, i) * REPAIR_PER_IMPACT, REPAIR_MIN, REPAIR_MAX)
                if recT[i] > penalty then
                    -- If it's OFF-track, it must actually be put back on the line to count as repaired --
                    -- a beached car can't drive out on gravel. If traffic blocks the drop this frame, we
                    -- DON'T mark it repaired (no false "rejoined"): we keep retrying next frames until the
                    -- spot is safe, and the give-up backstop forces it if a gap never comes.
                    -- A beached car can't drive out of the gravel, so it MUST be repositioned. Respect
                    -- traffic for the first few seconds (don't drop into a passing car), but after that
                    -- FORCE it back on the line -- otherwise, on a busy track, the traffic check never
                    -- clears and the car sits off-track the whole race (the "ran off, never rejoined" bug).
                    -- Each reposition counts as a repair, so a car that keeps going off hits the
                    -- repeat-offender limit and retires cleanly -- no car is ever left in limbo.
                    local offTrack = nearDist > REPOSITION_FAR or (nearDist > 3.0 and math.abs(latOf(car.position)) > OFF_LAT)
                    local forceIt = recT[i] > penalty + 6
                    -- an off-track car that may not be repositioned goes back to AC's AI unprotected: it
                    -- drives out if it can (shallow run-off), else AC retires it
                    if offTrack and not dropsAllowed(i) then hopeless[i] = hopeless[i] or os.clock(); giveUp(i); return end
                    local placed = (not offTrack) or putBackOnLine(sim, i, progress, center, forceIt)
                    if placed then
                        repairBody(i, car)   -- fresh wing/body, in place
                        repaired[i] = true
                        repairRecT[i] = recT[i]                              -- mark when we repaired, for the give-up logic
                        R.repairedCount = (R.repairedCount or 0) + 1
                        -- per-car tally for the repeat-offender retirement -- counting INCIDENTS, not retries: a
                        -- car patched three times while it's still in the same pileup had ONE crash. (Counting
                        -- retries hit the limit inside 90 s and parked four cars from a single lap-1 heap.)
                        local lastSpl = lastRepairSpl[i]
                        local trav = lastSpl and math.abs(progress - lastSpl) or 1
                        if trav > 0.5 then trav = 1 - trav end
                        local nowc = os.clock()
                        if not lastSpl or trav > REPAIR_NEW_SPOT or (nowc - (lastRepairT[i] or 0)) > REPAIR_NEW_T then
                            repairN[i] = (repairN[i] or 0) + 1
                        end
                        lastRepairSpl[i] = progress; lastRepairT[i] = nowc
                        stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil  -- fresh start for recovery driving
                    end
                end
            end

            if not R.DRIVE then return end           -- no manual driving (see R.DRIVE): repositions + AC's AI only

            if backupT[i] and backupT[i] > 0 then
                backupT[i] = backupT[i] - dt
                local c = ac.overrideCarControls(i)
                if c then
                    -- NOTE: do NOT set combineAxis=false here. Exclusive pedal control persists after
                    -- recovery ends, leaving the car with no throttle from anyone once we stop writing ->
                    -- it stalls, re-sticks and retires. One race: 13/18 retired by lap 3. Combined mode
                    -- (CSP's default, max of ours and AC's) is what actually works.
                    overriding[i] = true
                    c.requestedGearIndex = -1
                    c.gas = BACK_GAS; c.brake = 0; c.clutch = 1      -- clutch 1 = pedal UP = drive (see releaseControls)
                    c.steer = clamp(BACK_STEER * (backupSign[i] or 1), -1, 1)
                end
                if backupT[i] <= 0 then
                    backupT[i] = nil; stallRef[i] = vec3(car.position.x, car.position.y, car.position.z); stallT[i] = 0
                    backupSign[i] = -(backupSign[i] or 1)
                end
                return
            end

            -- traffic awareness: a fast car bearing down from behind -> hold, don't pull into it
            local danger = false
            do
                local mySp = car.splinePosition
                if mySp then
                    for j = 0, sim.carsCount - 1 do
                        if j ~= i then
                            local oc = ac.getCar(j)
                            if oc and oc.splinePosition and (oc.speedKmh or 0) > DANGER_SPEED then
                                local gap = mySp - oc.splinePosition; if gap < 0 then gap = gap + 1 end
                                if gap > 0 and gap < DANGER_GAP then danger = true; break end
                            end
                        end
                    end
                end
            end
            -- a hold, not a life sentence: after DANGER_MAX of continuous waiting, go (the yellow flag is
            -- slowing whoever's coming). Resets once the road behind is clear.
            if danger then
                dangerT[i] = (dangerT[i] or 0) + dt
                if dangerT[i] > DANGER_MAX then danger = false end
            else
                dangerT[i] = 0
            end

            local target = ac.trackProgressToWorldCoordinate((progress + TARGET_AHEAD) % 1.0, false)
            if not target then return end
            local toT = (target - car.position):normalize()
            local fwd = vec3(car.look.x, car.look.y, car.look.z)   -- COPY: fwd:cross below mutates in place; don't corrupt the live car.look
            local fdot = fwd:dot(toT)
            local up  = car.up or vec3(0, 1, 0)
            local right = fwd:cross(up)
            local ldot = right:dot(toT)
            local err  = math.acos(clamp(fdot, -1, 1))

            -- recovered? hand back to the AI once it's on the line, pointed forward and moving -- it returns
            -- to the racing line and gets up to speed far quicker than our gentle crawl. Traffic behind is
            -- NOT a reason to keep hold of it: AC's AI handles a car on its line in traffic better than our
            -- brake does ("danger" only matters while we're deciding whether to PULL OUT, below).
            if nearDist < REJOIN_DIST and fdot > REJOIN_FACE and spd > REJOIN_SPEED then
                endRec(i); return
            end

            -- stall detection (a deliberate danger-hold is not "stuck")
            if stallRef[i] == nil then stallRef[i] = vec3(car.position.x, car.position.y, car.position.z); stallT[i] = 0 end
            if danger or car.position:distance(stallRef[i]) > STALL_MOVE then
                stallRef[i] = vec3(car.position.x, car.position.y, car.position.z); stallT[i] = 0
            else
                stallT[i] = (stallT[i] or 0) + dt
            end
            if not danger and stallT[i] > (STALL_TRIGGER + hash01(i * 3 + 1) * 0.6) then
                backupN[i] = (backupN[i] or 0) + 1
                if backupSign[i] == nil then backupSign[i] = (hash01(i * 7) < 0.5) and 1 or -1 end
                backupT[i] = BACKUP_MIN + hash01(i * 13 + backupN[i]) * BACKUP_RANGE
                stallT[i] = 0
                return
            end

            steerSign[i] = steerSign[i] or 1
            checkT[i] = (checkT[i] or 0) + dt
            if checkT[i] >= FLIP_INTERVAL then
                if err > 0.5 and lastErr[i] ~= nil and err > lastErr[i] + FLIP_WORSE then steerSign[i] = -steerSign[i] end
                lastErr[i] = err; checkT[i] = 0
            end

            local steer
            if fdot < -0.1 and math.abs(ldot) < 0.35 then steer = 0.85
            else steer = clamp(STEER_GAIN * ldot, -1, 1) end
            steer = clamp(steer * steerSign[i], -1, 1)

            local c = ac.overrideCarControls(i)
            if c then
                -- (no combineAxis=false here either -- see the note in the backup-burst block above)
                overriding[i] = true
                c.requestedGearIndex = 1
                c.clutch = 1                                      -- pedal UP = drive (see releaseControls)
                c.steer = steer
                if danger then
                    c.gas = 0; c.brake = 0.25                     -- wait for traffic to pass
                else
                    local g = (fdot > 0.5) and ACCEL_GAS or GAS   -- accelerate once pointed forward
                    -- OFF-TRACK: power out of gravel/dirt. The gentle throttle bogs in soft ground and
                    -- stops the car mid-recovery (it "turns into the dirt and stalls"); when it's off the
                    -- surface and pointed anywhere but backwards, give it near-full throttle to carry
                    -- through and reach the tarmac, and don't lift while steering back toward the line.
                    if nearDist > OFFLINE_POWER and fdot > -0.1 then g = math.max(g, DIRT_GAS) end
                    c.gas = math.min(g, rampLimit(i))     -- just set back on the track? ease onto the throttle
                    c.brake = 0
                end
            end
        end)
    end
    R.count = active
end

function R.reset()
    boxT = {}
    ownLaps, ownSpline = {}, {}
    hasMoved, stuckT, recT = {}, {}, {}
    lastFwd = {}
    fwdVotes, trackFwdSign = 0, 0
    steerSign, lastErr, checkT = {}, {}, {}
    stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
    repaired, repairRecT = {}, {}
    limpT = {}
    limpDone = {}
    repairN = {}
    rescued = {}
    handedBack = {}
    retiredMark = {}
    reported = {}
    parked = {}
    dmgBase = {}
    episodeT = {}
    pendingTemps = {}
    lastRepairSpl = {}
    rescueN, rescueWaitT = {}, {}
    rejoinUntil = {}
    pitStuckT = {}
    dangerT = {}
    knot = {}
    lastRepairT = {}
    for i in pairs(overriding) do releaseControls(i) end   -- hand every car's controls back at a session change
    drops = {}; dropFailed = {}; hopeless = {}; pendingDrop = {}
    R.dropN, R.dropOK, R.dropsOff, R.dropFlips, R.gateMoves = 0, 0, false, 0, 0
    scaled = false
    R.count = 0; R.repairedCount = 0; R.limpCount = 0; R.retiredCount = 0
end

-- top-speed cap for a car that was just set back on the track (1e9 = none); racecraft combines it with
-- its yellow-flag cap, since both write physics.setAITopSpeed
function R.rampCap(i)
    if rejoinUntil[i] and rampLimit(i) < 1 then return RAMP_TOPSPEED end
    return 1e9
end

-- body damage SINCE the car's last repair (km/h of impact) -- what the other modules should react to
function R.damageOf(i)
    local car = ac.getCar(i)
    if not car then return 0 end
    return effImpact(car, i)
end

-- per-car recovery state for the diagnostics log (never used for decisions)
function R.stateOf(i)
    return {
        rec = (recT[i] or 0) > 0, recT = recT[i] or 0, repairN = repairN[i] or 0,
        rescued = rescued[i] == true, handedBack = handedBack[i] == true, limpDone = limpDone[i] == true,
        parked = parked[i] == true, dmgBase = dmgBase[i] or 0, episodeT = episodeT[i] or 0,
        rescueN = rescueN[i] or 0, ramp = rampLimit(i), dropFailed = dropFailed[i] == true,
    }
end

-- MANUAL "unstick my car" -- fired by a UI button, not the auto loop. Repairs the car's body, force-
-- places it back on the racing line at its current progress facing forward (with the small forward push
-- so it sets off cleanly), and clears its recovery state so nothing fights the reset. Does NOT touch fuel.
-- Meant to be pressed while stuck (a retired car can't be brought back). Returns true if it repositioned.
function R.forceRecover(i)
    if type(i) ~= 'number' or i < 0 then return false end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return false end
    local done = false
    pcall(function()
        local car = ac.getCar(i); if not car then return end
        -- Same reliable progress source as the automatic path (splinePosition works even deep off-track);
        -- the old world-projection returned garbage for a beached car.
        local progress = car.splinePosition
        if type(progress) ~= 'number' or progress < 0 or progress > 1 then
            local tc = ac.worldCoordinateToTrack(car.position); progress = tc and tc.z
        end
        if type(progress) ~= 'number' or progress < 0 or progress > 1 then return end
        local center = ac.trackProgressToWorldCoordinate(progress, false); if not center then return end
        -- Repositions onto the racing line at the car's progress -- crucially, this DOES move a car out
        -- of the pit lane (AC's own resetCarState just repairs in place and leaves it stuck in the pits).
        repairBody(i, car)
        done = putBackOnLine(sim, i, progress, center, true)   -- honest: false if the physics call failed
        overriding[i] = true; releaseControls(i)             -- whatever we last wrote to its controls, let go
        recT[i] = nil; stuckT[i] = nil; repaired[i] = nil; repairRecT[i] = nil
        rescued[i] = nil; handedBack[i] = nil; limpT[i] = nil; limpDone[i] = nil; hasMoved[i] = true
        dropFailed[i] = nil                                   -- a manual unstick is the driver's call: always allowed
        if parked[i] then     -- un-park: release the brake/throttle hold we put on a car we retired
            parked[i] = nil
            pcall(function() physics.setAIStopCounter(i, 0); physics.setAIThrottleLimit(i, 1) end)
        end
    end)
    return done
end

return R
