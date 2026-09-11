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
local NEAR_MAX    = 45.0      -- start recovering cars this far off the line (wide first-corner shunts)
local ABORT_DIST  = 85.0      -- and keep working them from this far out
local GAS         = 0.28
local STEER_GAIN  = 2.0
local TARGET_AHEAD= 0.002
local FLIP_INTERVAL = 0.8
local FLIP_WORSE  = 0.12
local REJOIN_DIST = 9.0       -- hand back sooner (the AI returns to the line + accelerates faster than a crawl)
local REJOIN_FACE = 0.7
local REJOIN_SPEED= 12.0
local ACCEL_GAS   = 0.7       -- once pointed forward and clear, accelerate back up to speed
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
-- "genuinely wrecked" is judged by actual DAMAGE, not just closing speed: a very hard body impact OR
-- broken suspension. A light touch (even at 150+ km/h) does neither, so it keeps racing.
local TERMINAL_IMPACT   = 160.0-- km/h of collision severity that counts as a race-ending body hit
local TERMINAL_SUSP     = 0.5  -- suspension damage (0..1) that counts as genuinely broken
-- repair "penalty" time scales with how bad the crash was (bigger hit = longer)
local REPAIR_BASE       = 2.0  -- base repair seconds (on top of the ~2.5s recovery already waited)
local REPAIR_PER_IMPACT = 0.05 -- extra seconds per km/h of impact (bigger shunt = longer penalty)
local REPAIR_MIN        = 2.0  -- clamp low = catch cars sooner, before AC's own retirement fires
local REPAIR_MAX        = 9.0

local hasMoved, stuckT, recT = {}, {}, {}
local steerSign, lastErr, checkT = {}, {}, {}
local stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
local repaired, repairRecT = {}, {}
R.repairedCount = 0    -- cars repaired + set back on track this session (for UI)

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end
local function endRec(i)
    recT[i] = nil; checkT[i] = nil; lastErr[i] = nil
    stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil
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

-- Is the car GENUINELY wrecked (race-ending in real life)? By actual damage, not just closing speed:
-- a very hard body impact OR broken suspension. A light touch does neither.
local function terminalDamage(car)
    local body, susp = maxImpact(car), 0
    pcall(function()
        if car.wheels then
            for k = 0, 3 do
                local w = car.wheels[k]
                if w and type(w.suspensionDamage) == 'number' and w.suspensionDamage > susp then susp = w.suspensionDamage end
            end
        end
    end)
    return body >= TERMINAL_IMPACT or susp >= TERMINAL_SUSP
end

function R.update(dt)
    if not R.ENABLED then R.count = 0; return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end
    local active = 0
    for i = 0, sim.carsCount - 1 do          -- includes the player's car WHEN it's under AI control (Ctrl+C)
        pcall(function()
            local car = ac.getCar(i)
            if not car or not car.isAIControlled then return end
            local retired = false
            pcall(function() retired = (car.isRetired == true) end)
            if retired then endRec(i); return end               -- AC has already killed it; can't help, don't cycle on it
            local spd = car.speedKmh or 0
            if spd > MOVE_SPEED then hasMoved[i] = true; repaired[i] = nil; repairRecT[i] = nil end   -- back racing: reset
            if car.isInPitlane then stuckT[i] = 0; endRec(i); return end
            if not hasMoved[i] then return end

            local isActive = (recT[i] or 0) > 0
            if not isActive then
                if spd > STOP_SPEED then stuckT[i] = 0; return end
                stuckT[i] = (stuckT[i] or 0) + dt
                if stuckT[i] < STUCK_TIME then return end
            end

            local tc = ac.worldCoordinateToTrack(car.position)
            if not tc then return end
            local progress = tc.z
            if progress < 0 or progress > 1 then return end
            local center = ac.trackProgressToWorldCoordinate(progress, false)
            if not center then return end
            local nearDist = car.position:distance(center)
            if not isActive and (nearDist < 3.0 or nearDist > NEAR_MAX) then return end
            if nearDist > ABORT_DIST then endRec(i); return end

            recT[i] = (recT[i] or 0) + dt
            -- Only hand a car back to AC's retirement once we've genuinely exhausted our options:
            -- either we already REPAIRED it and it STILL won't move after a good while (so it's wedged
            -- in geometry, not just damaged), or an absolute time backstop. Until then we keep blocking
            -- AC's retirement and working the car (backups, repair, driving it out).
            local exhausted = repaired[i] and repairRecT[i] and (recT[i] - repairRecT[i]) > POST_REPAIR_HOLD
            if exhausted or recT[i] > GIVEUP_TIME then endRec(i); return end
            active = active + 1

            -- TERMINAL DAMAGE: a genuinely massive shunt ends the car, just like real life. Don't fight
            -- to save it -- stop here so we quit blocking AC and it retires, and we don't waste a wing on
            -- it. (Body damage clears when we repair, so this only ever catches the ORIGINAL big hit,
            -- never a car we've already fixed and sent back out.)
            if R.CRASH_REPAIR and terminalDamage(car) then endRec(i); return end

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
                    pcall(function() physics.setCarBodyDamage(i, vec4(0, 0, 0, 0)) end)   -- fresh wing/body, in place
                    repaired[i] = true
                    repairRecT[i] = recT[i]                              -- mark when we repaired, for the give-up logic
                    R.repairedCount = (R.repairedCount or 0) + 1
                    stallRef[i] = nil; stallT[i] = nil; backupT[i] = nil  -- fresh start for recovery driving
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
                    c.gas = (fdot > 0.5) and ACCEL_GAS or GAS     -- accelerate once pointed forward
                    c.brake = 0
                end
            end
        end)
    end
    R.count = active
end

function R.reset()
    hasMoved, stuckT, recT = {}, {}, {}
    steerSign, lastErr, checkT = {}, {}, {}
    stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}
    repaired, repairRecT = {}, {}
    R.count = 0; R.repairedCount = 0
end

return R
