-- Verve / recovery.lua
-- Un-sticks AI cars that stopped but aren't wrecked: gentle throttle + self-correcting steer
-- toward a point ahead on the racing line. Backwards cars turn around. If a car is recovering
-- but not actually travelling (pinned on a wall, or two cars locked together), it shifts to
-- REVERSE for a randomized burst while turning, then retries forward -- locked pairs desync
-- via per-car randomized backup duration/side/trigger-jitter. Raw input via ac.overrideCarControls.

local R = {}
R.ENABLED = true

local MOVE_SPEED  = 30.0
local STOP_SPEED  = 5.0
local STUCK_TIME  = 2.5
local GIVEUP_TIME = 15.0
local NEAR_MAX    = 22.0
local ABORT_DIST  = 45.0
local GAS         = 0.28
local STEER_GAIN  = 2.0
local TARGET_AHEAD= 0.002
local FLIP_INTERVAL = 0.8
local FLIP_WORSE  = 0.12
local REJOIN_DIST = 5.0
local REJOIN_FACE = 0.7
local REJOIN_SPEED= 12.0
local STALL_MOVE    = 1.0
local STALL_TRIGGER = 1.2
local BACK_GAS      = 0.35
local BACK_STEER    = 0.7
local BACKUP_MIN    = 0.9
local BACKUP_RANGE  = 1.0

R.count = 0    -- how many cars are being actively recovered right now (for UI)

local hasMoved, stuckT, recT = {}, {}, {}
local steerSign, lastErr, checkT = {}, {}, {}
local stallRef, stallT, backupT, backupSign, backupN = {}, {}, {}, {}, {}

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

function R.update(dt)
    if not R.ENABLED then R.count = 0; return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end
    local active = 0
    for i = 1, sim.carsCount - 1 do
        pcall(function()
            local car = ac.getCar(i)
            if not car or not car.isAIControlled then return end
            local spd = car.speedKmh or 0
            if spd > MOVE_SPEED then hasMoved[i] = true end
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
            if recT[i] > GIVEUP_TIME then endRec(i); return end
            active = active + 1

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

            local target = ac.trackProgressToWorldCoordinate((progress + TARGET_AHEAD) % 1.0, false)
            if not target then return end
            local toT = (target - car.position):normalize()
            local fwd = car.look
            local up  = car.up or vec3(0, 1, 0)
            local right = fwd:cross(up)
            local fdot = fwd:dot(toT)
            local ldot = right:dot(toT)
            local err  = math.acos(clamp(fdot, -1, 1))

            if nearDist < REJOIN_DIST and fdot > REJOIN_FACE and spd > REJOIN_SPEED then endRec(i); return end

            if stallRef[i] == nil then stallRef[i] = car.position; stallT[i] = 0 end
            if car.position:distance(stallRef[i]) > STALL_MOVE then
                stallRef[i] = car.position; stallT[i] = 0
            else
                stallT[i] = (stallT[i] or 0) + dt
            end
            if stallT[i] > (STALL_TRIGGER + hash01(i * 3 + 1) * 0.6) then
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
                c.gas = GAS; c.brake = 0; c.clutch = 0; c.steer = steer
            end
        end)
    end
    R.count = active
end

return R
