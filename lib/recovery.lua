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

local MOVE_SPEED  = 30.0
local STOP_SPEED  = 5.0
local STUCK_TIME  = 2.0       -- engage a touch sooner, so AC can't retire a car in the gap
local GIVEUP_TIME = 45.0      -- absolute backstop: only after this long total do we ever hand a car back to AC
local POST_REPAIR_HOLD = 15.0 -- once we've REPAIRED a car, if it STILL won't move in this long it's wedged -> let it go
local NEAR_MAX    = 150.0     -- engage a STOPPED car this far off the line. Raised a lot: cars that fly
                             -- deep into a runoff/barrier (30-100 m off) used to be beyond this and were
                             -- skipped entirely -- never repositioned, never retired, frozen off-track all
                             -- race. They're stopped, so we grab them and force them back (or retire if chronic).
local ABORT_DIST  = 250.0    -- only give up on a truly absurd reading (a projection glitch), not a real crash
local GAS         = 0.28
local STEER_GAIN  = 2.0
local TARGET_AHEAD= 0.002
local FLIP_INTERVAL = 0.8
local FLIP_WORSE  = 0.12
local REJOIN_DIST = 9.0       -- hand back sooner (the AI returns to the line + accelerates faster than a crawl)
local REJOIN_FACE = 0.7
local REJOIN_SPEED= 12.0
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

R.count = 0    -- how many cars are being actively recovered right now (for UI)

-- crash repair: repair a stuck car IN PLACE (recovery then drives it out). No teleport, no pit.
local REPAIR_SLOW       = 15.0 -- km/h: below this counts as stuck/crippled
local REPOSITION_DIST   = 9.0  -- metres off the racing line = genuinely OFF-track -> set it back on the line
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
local steerSign, lastErr, checkT = {}, {}, {}
local stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
local repaired, repairRecT = {}, {}
local limpT = {}           -- how long a DAMAGED car has been crawling on-track (blocking traffic)
local limpDone = {}        -- cars already re-bodied for their CURRENT damage (don't re-body until it clears)
local repairN = {}         -- how many times we've crash-repaired each car (for the repeat-offender rule)
local rescued = {}         -- cars we've already spent their one pileup-rescue on (spread + retry)
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
local function endRec(i)
    recT[i] = nil; checkT[i] = nil; lastErr[i] = nil
    stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil
    reported[i] = nil
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
                if ag < 0.004 then return false end                             -- someone right on the spot
                if g < 0 and ag < 0.02 and (oc.speedKmh or 0) > DANGER_SPEED then return false end  -- fast car closing from behind
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
    if not force and not dropSafe(sim, i, progress) then return false end
    -- forward direction from a CENTRED sample (a point behind -> a point ahead), which is far steadier
    -- than a tiny forward-only step and always points along the racing direction.
    local pB = ac.trackProgressToWorldCoordinate((progress - 0.003) % 1, false)
    local p1 = ac.trackProgressToWorldCoordinate((progress + 0.003) % 1, false)
    if not (pB and p1) then return false end
    local fx, fy, fz = p1.x - pB.x, p1.y - pB.y, p1.z - pB.z
    local flen = math.sqrt(fx * fx + fy * fy + fz * fz)
    if flen < 1e-4 then return false end
    fx, fy, fz = fx / flen, fy / flen, fz / flen
    -- The spline tangent gives the LINE the car should sit on, but its sign (which way is "forwards")
    -- can't be trusted -- on some tracks the track spline runs opposite to the racing direction, which
    -- is what dropped cars in facing BACKWARD. So flip it to match the direction this car was actually
    -- racing (recorded while it was up to speed). That's the ground truth for "forwards" here.
    if lastFwd[i] and (fx * lastFwd[i].x + fy * lastFwd[i].y + fz * lastFwd[i].z) < 0 then
        fx, fy, fz = -fx, -fy, -fz
    end
    local dir = vec3(fx, fy, fz)
    local sx, sz = -fz, fx                                   -- level perpendicular to forward
    local a = vec3(center.x + sx * 2.0, center.y + 0.3, center.z + sz * 2.0)
    local b = vec3(center.x - sx * 2.0, center.y + 0.3, center.z - sz * 2.0)
    local pos = (math.abs(latOf(a)) <= math.abs(latOf(b))) and a or b   -- the roomier side (nearer track centre)
    pcall(function()
        physics.setCarPosition(i, pos, dir)
        -- CRUCIAL: setCarPosition sets orientation but NOT velocity, so a car sliding backward from its
        -- crash keeps that momentum -- it lands facing forward but drifting BACKWARD, then recovery fights
        -- it, swings it round and it beaches in the grass. Give it a small FORWARD velocity instead so it
        -- sets off the right way and recovery just has to keep it rolling.
        physics.setCarVelocity(i, dir * 8.0)
    end)
    return true
end

function R.update(dt)
    if not R.ENABLED then R.count = 0; return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end
    local active = 0
    for i = 0, sim.carsCount - 1 do          -- includes the player's car WHEN it's under AI control (Ctrl+C)
        pcall(function()
            local car = ac.getCar(i)
            if not car then return end
            -- Record which way EVERY car is racing (incl. a manually-driven player) while it's up to speed,
            -- so a reset -- the unstick button especially -- can face it the right way. Done before the
            -- AI-control gate, because the player's own car isn't AI-controlled while you drive it.
            if (car.speedKmh or 0) > MOVE_SPEED and car.look then
                lastFwd[i] = vec3(car.look.x, car.look.y, car.look.z)
            end
            if not car.isAIControlled then return end
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
            if spd > MOVE_SPEED then hasMoved[i] = true; repaired[i] = nil; repairRecT[i] = nil end   -- back racing: reset
            if car.isInPitlane then stuckT[i] = 0; endRec(i); return end
            if not hasMoved[i] then return end

            -- LIMPING: a DAMAGED car that's still moving but crawling on-track drags the whole field down
            -- behind it. It never trips the stuck/recovery logic (it IS moving), so handle it here: after a
            -- short grace, give it a fresh body IN PLACE so it rejoins racing pace. Requires real damage
            -- (a big body impact), so it never fires on a healthy car just going slow through a corner; and
            -- not for a genuinely-wrecked (terminal) car, which should retire rather than be patched.
            -- clear the guard only once the body damage is actually GONE (below the trigger). If a re-body
            -- cleared it, the car no longer qualifies anyway; if the re-body didn't take, the damage stays
            -- high and the guard stays set -- so we re-body a given car at most ONCE per damage episode,
            -- never in a loop. (This is what turns the old runaway 180-360 count into a handful.)
            if maxImpact(car) < LIMP_IMPACT then limpDone[i] = nil end
            if R.CRASH_REPAIR and spd > STOP_SPEED and spd < LIMP_SPEED
               and maxImpact(car) >= LIMP_IMPACT and not limpDone[i] and not terminalDamage(car) then
                limpT[i] = (limpT[i] or 0) + dt
                if limpT[i] > LIMP_GRACE then
                    pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)
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
            if not isActive and (nearDist < 3.0 or nearDist > NEAR_MAX) then return end
            if nearDist > ABORT_DIST then endRec(i); return end

            recT[i] = (recT[i] or 0) + dt
            if not reported[i] then          -- log this incident's location for trouble-spot learning (once)
                reported[i] = true
                pcall(function() Troublespots.incident(car.splinePosition, Classes.keyOf(i)) end)
            end
            -- Only hand a car back to AC's retirement once we've genuinely exhausted our options:
            -- either we already REPAIRED it and it STILL won't move after a good while (so it's wedged
            -- in geometry, not just damaged), or an absolute time backstop. Until then we keep blocking
            -- AC's retirement and working the car (backups, repair, driving it out).
            local exhausted = repaired[i] and repairRecT[i] and (recT[i] - repairRecT[i]) > POST_REPAIR_HOLD
            if exhausted or recT[i] > GIVEUP_TIME then
                -- ONE rescue attempt before we EVER let a car retire (this is what breaks a pileup): if it
                -- isn't terminally wrecked, give it a fresh body and force it back onto the racing line at a
                -- STAGGERED point -- a per-car offset so a knot of wedged cars lands strung out over ~15-60 m
                -- instead of restacking on the same spot -- then restart recovery and KEEP protecting it from
                -- AC's retirement while it drives away. Cars in a heap get separated and rejoin, rather than
                -- all timing out together and mass-retiring.
                if R.CRASH_REPAIR and not rescued[i] and not terminalDamage(car) then
                    rescued[i] = true
                    pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)
                    local stagger = (progress + 0.004 + hash01(i * 17) * 0.010) % 1
                    local sc = ac.trackProgressToWorldCoordinate(stagger, false)
                    putBackOnLine(sim, i, stagger, sc or center, true)
                    recT[i] = 0; repaired[i] = nil; repairRecT[i] = nil
                    stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil
                    return
                end
                -- rescue already spent (or genuinely wrecked): hand it to AC. If it actually retires, the
                -- isRetired check at the top of the loop counts it next frame (ground truth).
                endRec(i); return
            end
            active = active + 1

            -- TERMINAL DAMAGE: a genuinely massive shunt ends the car, just like real life. Don't fight
            -- to save it -- stop here so we quit blocking AC and it retires, and we don't waste a wing on
            -- it. (Body damage clears when we repair, so this only ever catches the ORIGINAL big hit,
            -- never a car we've already fixed and sent back out.)
            if R.CRASH_REPAIR and terminalDamage(car) then endRec(i); return end

            -- REPEAT OFFENDER: a car we've already patched up many times that keeps wrecking itself is,
            -- realistically, a broken car -- in real racing it would retire. Stop saving it and let it go,
            -- so it clears the track instead of crash-looping all race (finishing 10+ laps down and piling
            -- up traffic). This is what brings retirements up from zero to a realistic handful, and it
            -- self-scales: a clean track rarely triggers it, a crash-heavy one retires its worst few.
            if R.CRASH_REPAIR and (repairN[i] or 0) >= REPAIR_GIVEUP then endRec(i); return end

            -- HIJACK AC's retirement: while we're working this car, stop AC retiring it and release
            -- its post-incident "brake and wait" so it (and our recovery) can move. We keep calling
            -- these every frame it's in recovery; the moment recovery gives up (GIVEUP_TIME) we stop,
            -- and only THEN does AC retire it -- so retirements become the few genuinely hopeless cars.
            if R.CRASH_REPAIR then
                pcall(function() physics.preventAIFromRetiring(i); physics.setAIStopCounter(i, 0) end)
            end

            -- CRASH REPAIR (opt-in): after a severity-scaled penalty, give the car a fresh wing/body
            -- IN PLACE (setCarBodyDamage 0 -- no teleport, no pit, no fuel reset), so recovery's
            -- driving below can get it going. A car whose SUSPENSION is broken (genuinely too damaged)
            -- isn't fixed by this, stays crippled, and retires -- exactly "repair light, retire heavy".
            if R.CRASH_REPAIR and not repaired[i] and spd < REPAIR_SLOW then
                local penalty = clamp(REPAIR_BASE + maxImpact(car) * REPAIR_PER_IMPACT, REPAIR_MIN, REPAIR_MAX)
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
                    local offTrack = nearDist > REPOSITION_DIST
                    local forceIt = recT[i] > penalty + 6
                    local placed = (not offTrack) or putBackOnLine(sim, i, progress, center, forceIt)
                    if placed then
                        pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)   -- fresh wing/body, in place
                        repaired[i] = true
                        repairRecT[i] = recT[i]                              -- mark when we repaired, for the give-up logic
                        R.repairedCount = (R.repairedCount or 0) + 1
                        repairN[i] = (repairN[i] or 0) + 1                   -- per-car tally, for the repeat-offender retirement
                        stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil  -- fresh start for recovery driving
                    end
                end
            end

            if backupT[i] and backupT[i] > 0 then
                backupT[i] = backupT[i] - dt
                local c = ac.overrideCarControls(i)
                if c then
                    c.requestedGearIndex = -1
                    c.gas = BACK_GAS; c.brake = 0; c.clutch = 0
                    c.steer = clamp(BACK_STEER * (backupSign[i] or 1), -1, 1)
                end
                if backupT[i] <= 0 then
                    backupT[i] = nil; stallRef[i] = car.position; stallT[i] = 0
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

            local target = ac.trackProgressToWorldCoordinate((progress + TARGET_AHEAD) % 1.0, false)
            if not target then return end
            local toT = (target - car.position):normalize()
            local fwd = car.look
            local fdot = fwd:dot(toT)                     -- capture BEFORE cross (cross mutates fwd in place)
            local up  = car.up or vec3(0, 1, 0)
            local right = fwd:cross(up)
            local ldot = right:dot(toT)
            local err  = math.acos(clamp(fdot, -1, 1))

            -- recovered? hand back to the AI once it's pointed forward, moving, and safe -- it returns
            -- to the racing line and gets up to speed far quicker than our gentle crawl.
            if not danger and nearDist < REJOIN_DIST and fdot > REJOIN_FACE and spd > REJOIN_SPEED then
                endRec(i); return
            end

            -- stall detection (a deliberate danger-hold is not "stuck")
            if stallRef[i] == nil then stallRef[i] = car.position; stallT[i] = 0 end
            if danger or car.position:distance(stallRef[i]) > STALL_MOVE then
                stallRef[i] = car.position; stallT[i] = 0
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
                c.requestedGearIndex = 1
                c.clutch = 0
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
                    c.gas = g
                    c.brake = 0
                end
            end
        end)
    end
    R.count = active
end

function R.reset()
    hasMoved, stuckT, recT = {}, {}, {}
    lastFwd = {}
    steerSign, lastErr, checkT = {}, {}, {}
    stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
    repaired, repairRecT = {}, {}
    limpT = {}
    limpDone = {}
    repairN = {}
    rescued = {}
    retiredMark = {}
    reported = {}
    R.count = 0; R.repairedCount = 0; R.limpCount = 0; R.retiredCount = 0
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
        local tc = ac.worldCoordinateToTrack(car.position); if not tc then return end
        local progress = tc.z
        if progress < 0 or progress > 1 then return end
        local center = ac.trackProgressToWorldCoordinate(progress, false); if not center then return end
        -- Repositions onto the racing line at the car's progress -- crucially, this DOES move a car out
        -- of the pit lane (AC's own resetCarState just repairs in place and leaves it stuck in the pits).
        pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)
        putBackOnLine(sim, i, progress, center, true)          -- force: ignores traffic clearance
        recT[i] = nil; stuckT[i] = nil; repaired[i] = nil; repairRecT[i] = nil
        rescued[i] = nil; limpT[i] = nil; limpDone[i] = nil; hasMoved[i] = true
        done = true
    end)
    return done
end

return R
