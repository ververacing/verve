-- Verve / human.lua
-- Subtle human-like variability, returned as additive (gripOffset, cautionOffset) for an AI car.
-- The app adds these to a base grip/caution and pushes them via physics.setExtraAIGrip /
-- setAICaution. Grip here is REAL tyre grip, so the grip channel is SLEW-LIMITED: it moves
-- gradually, letting the AI bleed speed instead of snapping mid-corner (that was the cause of
-- solo spins in earlier prototypes). Caution is the safe "back off" channel.
--
-- Two buckets: VARIABILITY (personality/drift/fade/pressure/mistakes/slipstream) scaled by
-- INTENSITY, and PHYSICS (cold-tyre warm-up, wet, dirty air) at full strength, each scaled by
-- the car's class. Everything pcall-guarded; player and slow/recovering cars are skipped.

local Classes = require('lib.classes')
local Drivers = require('lib.drivers')
local Troublespots = require('lib.troublespots')
local H = {}

-- driven by the app each frame:
H.ENABLED       = true
H.INTENSITY     = 0.5      -- variability scale (0 = none, 1 = subtle, 1.5 = strong)
H.HUMAN_VAR     = true     -- personality / drift / fade / pressure / slipstream
H.HUMAN_ERRORS  = true     -- occasional gentle bobbles
H.CLASS_PHYSICS = true     -- cold-tyre warm-up / wet / dirty air
H.WILD_ERR      = 1.5      -- mistake-rate multiplier for a wild profile (the Wrecking Crew; off with Racecraft.WILD=false); lockups allowed; 1 = off
-- RainFX (CSP preview builds) models wet grip physically and puts cars on rain tyres: Verve's own wet rule, written for
-- installs without rain physics, then stacks on top (Spa GT3 in the wet ran +35 % on lap time, real is +10-15 %; 2026-09-18).
-- When the module is enabled these scale the grip cut and the extra caution; both are harness switches until the A/B is in.
H.RAINFX_GRIP   = 0.0      -- x the wet grip cut when RainFX is on (0 = physics already does it)
H.RAINFX_CAUT   = 0.5      -- x the wet caution when RainFX is on
H.WARMUP_MODE   = 'min'    -- 'min': cold-tyre penalty = the smaller of the temperature model and the laps model (after WARMUP_LAPS
                           -- of a stint the tyres are as warm as they get). 'temp': temperature only - which never reached zero for
                           -- GT3 AI at 10 C ambient: a permanent 44 % cold-tyre tax on every car, all race (found 2026-09-20)
H.wu = {}                  -- per car: the warm-up fraction last applied (diag)
H.DIRTY_CAUT_X  = 1.0      -- x the dirty-air caution (harness A/B 2026-09-20: an attacking veteran carried +0.12 of it on top of
                           -- a cancelled attack term, running MORE cautious than a car alone; 0 = dirty air costs grip only)
H.rainfx        = nil      -- detected at first use: true when the RainFX module is enabled on this install
-- ac.StateCar.steer is the steering WHEEL angle in DEGREES (car.steerLock: the car's maximum wheel angle, also degrees), not a
-- -1..1 input. The three cornering reads below (tow, dirty air, mistake flavour) divided those degrees by 0.35, so any wheel
-- angle past 0.35 deg counted as full cornering: dirty air on every close follow above 80 km/h, straights included; the tow
-- almost never; every mistake picked as a cornering one (found 2026-09-26). STEER_FRAC reads the angle as a fraction of lock
-- instead, full cornering at STEER_CORNER of lock; a car without a usable steerLock keeps the old reading.
H.STEER_FRAC    = false  -- STATUS 2026-09-28: experimental - the unit bug is real, but the fix showed no gain in its A/Bs, so it stays off
H.STEER_CORNER  = 0.13     -- x lock = full cornering (STEER_FRAC only; not a positive number -> 0.13). A fraction of lock is a
                           -- fraction of the road wheels' maximum angle (~17-23 deg on GT3, ~30 on road cars). Estimated from
                           -- geometry, not yet measured, GT3 (2.7 m wheelbase): ~0.22-0.28 at 80 km/h, ~0.13 at 120, 0.05-0.14
                           -- in 200+ km/h sweepers counting understeer, under 0.02 on a straight; F1 (3.6 m, more grip) reads
                           -- about twice that at speed. Dirty air only fires over 80 km/h and the tow over 150, so 0.13 = full
                           -- dirty air up to ~120 km/h on GT3: the unit fix alone (no dirty air on straights, the tow back) at
                           -- about dev0146's corner dose. A/B arm 0.35 (the -1..1 reading the code was written for) also cuts
                           -- corner dirty air 50-80 %, most in the fast corners where following is hardest. Longer term,
                           -- lateral g (car.acceleration.x) would track aero load better than the steering angle.
H.DIRTY_LAT = 0            -- >0 (from lap 1): dirty air fades out as the car ahead moves off my line - full within DIRTY_LAT/2 of it, none
                           -- beyond DIRTY_LAT (track half-widths; 0.35 = about one car width on a 12 m road); pit-lane and parked cars
                           -- (under 30 km/h) make no wake. 0 = today (spline gap only, every car)

-- VISIBLE MISTAKES (H.MISTAKE_V2; owner 2026-09-28). Off = the bobble model below (MISTAKES / pickMistake), unchanged. On: ONE event of
-- ~0.3-1.0 s (late brake + lock + run wide / missed apex / snap-and-lift) at a rate per LAP set by the driver's pace (Rookie 1 in 2 laps,
-- Midfielder 4, Veteran 9, the top of a roster 15; consistency and risk against the archetype line move it up to +-25 %; an unprofiled car
-- reads its applied level as pace, so a car at 100 is a Veteran); rare offs, very rare spins. Levers: a grip dip returned outside the grip
-- slew, caution, and racecraft's brake hint / throttle limit / spline offset through H.mv. Race sessions only, never lap 0, never slot 0.
-- A wild profile (the Wrecking Crew) is never a roster's top, reports tier 'wild' and keeps H.WILD_ERR on this rate too.
H.MISTAKE_V2 = false
H.NERVES_V2 = false        -- nerves x NERVES_K x (1 - cons); pressure only from a rival on the road (not pit lane, parked or lapped)
H.NERVES_K = 2.0
H.MV_RACE_ONLY = true
H.MV_PACE = { 0.30, 0.60, 0.85, 0.95 }       -- anchors: Rookie, Midfielder, Veteran (drivers.lua archetypes), a top name
H.MV_LAPS = { 2, 4, 9, 15 }                  -- laps per visible mistake at each anchor (log-interpolated; ends held)
H.MV_OFF_P = { 0.06, 0.025, 0.010, 0.005 }   -- P(a lock-up or a missed apex becomes an off)
H.MV_SPIN_P = { 0.005, 0, 0, 0 }             -- P(a lift becomes a spin), robust classes only
H.MV_CR = 0.25             -- consistency and risk against the archetype line at the same pace move the rate by up to this fraction
H.MV_TOP_FRAC = 0.10       -- the top this fraction of a roster bucket by pace gets the last anchor (15 laps)
H.MV_ARCH = { { 0.30, 0.60, 0.50 }, { 0.60, 0.35, 0.80 }, { 0.85, 0.20, 0.95 } }   -- pace, risk, cons of the archetypes (the line)
H.MV_RATE_X = 1.0
H.MV_PRESS = 1.0           -- a rival right behind: rate x (1 + this x pressure x (1 - cons))
H.MV_CLASS_RATE = { drift = 0 }
H.MV_BIG_CLASS = { formula = 0.5, prototype = 0.5, hypercar = 0.5, nascar = 0, drift = 0 }   -- x the off and spin odds
H.MV_MIN_LAP = 1
H.MV_GAP_S = 8             -- s between two mistakes by one car
H.MV_ARM_S = 10            -- s a drawn mistake waits for a moment (its own kind for the first half; a forced kind all of it)
H.MV_LAP_S = 110           -- s per lap, only for a car with no spline
H.MV_W_LOCK = 40
H.MV_W_APEX = 35
H.MV_W_LIFT = 25
H.MV_SEV_SKILL = 1.5
H.MV_AHEAD_M = 20          -- no lock-up with a car this close ahead (twice this for the late-brake set-up)
H.MV_SIDE_M = 6
H.MV_SIDE_LAT = 0.5
H.MV_BRAKE_IN = 0.5
H.MV_LOCK_KMH = 110
H.MV_APEX_KMH = 60
H.MV_LIFT_KMH = 50
H.MV_LOCK_BH = 0.06        -- brake hint x (1 + this + LOCK_BH_SEV x severity): a HIGHER hint brakes later (racecraft.lua brake guard)
H.MV_LOCK_BH_SEV = 0.08
H.MV_LOCK_GRIP = 0.04
H.MV_LOCK_GRIP_SEV = 0.05
H.MV_LOCK_HOLD = 0.5
H.MV_LOCK_LOOK_M = 60
H.MV_WIDE = 0.25
H.MV_WIDE_SEV = 0.35
H.MV_WIDE_S = 1.3
H.MV_GATHER = 0.12
H.MV_APEX_S = 1.0
H.MV_APEX_S_SEV = 0.6
H.MV_APEX_CAUT = 0.15
H.MV_APEX_CAUT_SEV = 0.25
H.MV_APEX_GRIP = 0.015
H.MV_SNAP = 0.03
H.MV_SNAP_SEV = 0.03
H.MV_SNAP_S = 0.25
H.MV_SNAP_RAMP = 0.15      -- s the lift's grip dip takes to build (0.08 = the design's snap; see the probe gate)
H.MV_LIFT_CAP_FIRST = false   -- the lift's throttle cap from 0 s and its dip from 0.1 s (the fallback if lifts spin cars)
H.MV_LIFT_THR = 0.40
H.MV_LIFT_THR_SEV = 0.25
H.MV_LIFT_S = 0.35
H.MV_LIFT_S_SEV = 0.45
H.MV_BIG_BH = 0.12
H.MV_BIG_GRIP = 0.06
H.MV_SPIN_GRIP = 0.12
H.MV_SPIN_S = 0.6
H.MV_GRIP_FLOOR = -0.24
H.MV_TS_W = 0.5            -- trouble-spot heat weight of an off a visible mistake started (Verve.lua wraps Troublespots.incident)
H.MV_TS_WIN = 15           -- s after a mistake ends that an incident near it still counts as its off
H.MV_FORCE_KIND = nil      -- probe only: 'lockup' / 'apex' / 'lift' (no other kind fires)
H.mv = {}                  -- per car: this frame's levers for racecraft (R.humanMv); cleared in place, never reassigned
H.mvSk = {}
H.mvN = {}
H.mvDrop = {}
H.mvNear = {}
H.mvTop = {}
H.feedEvent = nil          -- Feed.event (set by Verve.lua)
H.busy = nil               -- (set by Verve.lua) true while recovery drives a car or ramps it back up

-- amplitudes
local PERSONALITY_AMP = 0.020
local DRIFT_AMP       = 0.025
local CAUTION_AMP     = 0.05
local FADE_MAX_GRIP    = 0.015     -- halved: AC already models physical tyre wear; don't double-count it into late-race run-wides
local FADE_MAX_CAUTION = 0.15      -- raised: as tyres fade late in a stint, back OFF more (drive within the worn grip) instead of running at the limit and sliding off -- targets the last-few-laps crash cluster
local STINT_LAPS       = 25
local PRESSURE_GAP    = 0.0035
local PRESSURE_NERVES = 0.02
local MISTAKE_RATE    = 0.02
local MISTAKE_BASE    = 0.003
local MISTAKE_CRASHY  = 0.70     -- on a track proven treacherous (trouble-spot crashiness), drivers stop taking
                                 -- liberties: mistake FREQUENCY drops by up to this fraction, and severity softens.
                                 -- Data: ~95% of offs on such tracks are SOLO (no contact) -- a gentle bobble that's
                                 -- harmless at Silverstone is an off at a banked, no-margin Zandvoort corner.
-- Mistakes come in human FLAVOURS instead of one generic grip dip. Each is small and
-- recoverable; most add a touch of caution too (the driver lifts to gather it), which makes
-- them read as human AND keeps a bobble from turning into a crash. grip/caut are amplitudes,
-- dur is seconds, w is the pick weight. Class only changes how OFTEN a car errs (the rate),
-- not how big the error is.
local MISTAKES = {
    { kind = "missApex", grip = 0.025, caut = 0.00, dur = 1.2, w = 40 }, -- carried a bit much speed, ran wide
    { kind = "wideExit", grip = 0.030, caut = 0.02, dur = 0.9, w = 25 }, -- on the power early, drifted out
    { kind = "twitch",   grip = 0.035, caut = 0.05, dur = 0.6, w = 20 }, -- caught a wobble and gathered it
    { kind = "lockup",   grip = 0.045, caut = 0.06, dur = 0.5, w = 15 }, -- brief brake lock, released
}
local WARMUP_LAPS     = 2.0      -- takes a bit longer to come up to temperature (like a real out-lap or two)
-- Cold tyres now genuinely bite for the AI, like they do for you -- it follows the car's real tyre
-- temperature, so on cold rubber it has LESS grip (slips a little, not planted) AND drives more carefully
-- (it "knows" the tyres are cold), then comes up to full pace as they warm. This closes the early-race
-- gap where the AI cornered on rails while you were sliding. The heavy caution keeps the lower grip from
-- turning into cold-tyre crashes.
local WARMUP_MAX_GRIP = 0.10     -- cold-tyre grip loss (was 0.06 -- too small to feel)
local WARMUP_MAX_CAUT = 0.28     -- and it backs off more when cold, so it doesn't run wide on the low grip
local WET_MAX_GRIP    = 0.06
local WET_MAX_CAUT    = 0.30
local TOW_GAP         = 0.0030
local TOW_MIN_KMH     = 150
local TOW_GRIP        = 0.015
local TOW_CAUT        = 0.05
local DIRTY_GAP       = 0.0030
local DIRTY_MIN_KMH   = 80
-- TRACK-LENGTH SCALING: the three gaps above are spline fractions tuned on ~4.5 km circuits; a fraction is
-- a different distance on every track (a tow at 13 m is a tow everywhere), so they're re-derived from
-- METRES each session. Same values at 4.5 km.
local REF_LEN = 4500
local scaled  = false
local function scaleToTrack(len)
    local tl = (type(len) == 'number' and len > 200) and len or REF_LEN
    PRESSURE_GAP = 16 / tl; TOW_GAP = 13.5 / tl; DIRTY_GAP = 13.5 / tl
end
local DIRTY_MAX_GRIP  = 0.015       -- dirty air is mostly a BACK-OFF (caution), only a little grip loss --
local DIRTY_MAX_CAUT  = 0.20        -- a following car keeps distance instead of sliding off (fragile-car crashes)
local GRIP_MIN, GRIP_MAX = -0.16, 0.03
local GRIP_SLEW       = 0.04     -- max grip change per second (anti-snap)

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end

-- (0.15, code review) a per-session salt, so grid slot 7 isn't the same driver every race: personality, consistency and the
-- bobble phase are re-drawn at each session start. H.SESSION_SALT = false = the fixed per-slot draw (harness A/B pinning).
H.SESSION_SALT = true
H.salt = 0
local pers, cons, phase = {}, {}, {}
local function seed(i)
    if pers[i] ~= nil then return end
    local k = i * 3 + H.salt * 61
    pers[i]  = (hash01(k + 1) * 2 - 1) * PERSONALITY_AMP
    cons[i]  = 0.6 + hash01(k + 2) * 0.8
    phase[i] = hash01(k + 3) * 6.2831853
end

local stintStart, lastT = {}, {}
local mistakeUntil, mistakeGrip, mistakeCaut = {}, {}, {}
local pressCache, pressCacheT = {}, {}
local smoothedGrip, slewT = {}, {}

-- Pick a mistake flavour, lightly biased by context: under pressure a driver is likelier to
-- lock up under braking; mid-corner they're likelier to miss the apex or run wide on exit.
local function pickMistake(p, cornering, avoidSharp)
    local total, adj = 0, {}
    for idx, m in ipairs(MISTAKES) do
        local w = m.w
        if m.kind == "lockup" then w = avoidSharp and 0 or (w * (1 + 1.2 * (p or 0))) end
        if m.kind == "missApex" or m.kind == "wideExit" then w = w * (0.6 + 0.8 * (cornering or 0)) end
        adj[idx] = w; total = total + w
    end
    local r = math.random() * total
    for idx, m in ipairs(MISTAKES) do
        r = r - adj[idx]
        if r <= 0 then return m end
    end
    return MISTAKES[1]
end

local function tyreWear01(car)
    local ok, w = pcall(function()
        if not car.wheels then return nil end
        local s, n = 0, 0
        for j = 0, 3 do
            local wh = car.wheels[j]
            if wh and wh.tyreWear ~= nil then s = s + wh.tyreWear; n = n + 1 end
        end
        if n == 0 then return nil end
        return s / n
    end)
    if ok then return w end
    return nil
end

local function stintProgressLaps(i, car)
    local lc = car.lapCount or 0
    if stintStart[i] == nil then stintStart[i] = lc end
    local inPit = false
    pcall(function() inPit = (car.isInPitlane == true) or (car.isInPit == true) end)
    if inPit then stintStart[i] = lc end
    local frac = 0
    pcall(function() if car.splinePosition then frac = clamp(car.splinePosition, 0, 1) end end)
    return math.max(0, (lc - stintStart[i]) + frac)
end

local function fadeFrac(i, car)
    local w = tyreWear01(car)
    if w ~= nil then return math.max(0, math.min(1, w)) end
    return math.max(0, math.min(1, stintProgressLaps(i, car) / STINT_LAPS))
end

local function warmupFrac(i, car)
    local byTemp = nil
    pcall(function()
        if not car.wheels then return end
        local s, n = 0, 0
        for j = 0, 3 do
            local wh = car.wheels[j]
            local t = wh and (wh.tyreCoreTemperature or wh.tyreTemperature)
            if t ~= nil then s = s + t; n = n + 1 end
        end
        if n > 0 then
            local avg = s / n
            if avg > 0 and avg < 200 then byTemp = clamp((80 - avg) / 50, 0, 1) end
        end
    end)
    local byLaps = clamp(1 - (stintProgressLaps(i, car) / WARMUP_LAPS), 0, 1)
    if byTemp ~= nil then
        if H.WARMUP_MODE == 'temp' then return byTemp end
        return math.min(byTemp, byLaps)
    end
    return byLaps
end

local function rainfxOn()
    if H.rainfx == nil then
        H.rainfx = false
        pcall(function()
            local cfg = ac.INIConfig.cspModule(ac.CSPModuleID.RainFX)
            if cfg and cfg:get('BASIC', 'ENABLED', 0) == 1 then H.rainfx = true end
        end)
    end
    return H.rainfx
end
H.rainfxOn = rainfxOn

local function wetness01()
    local w = 0
    pcall(function()
        local sim = ac.getSim()
        if not sim then return end
        local v = sim.rainWetness or sim.roadWetness or sim.rainIntensity or sim.rainWater or 0
        if type(v) == "number" then w = clamp(v, 0, 1) end
    end)
    return w
end

H.wetness01 = wetness01

local function pressure01(i, myCar, now)
    if pressCacheT[i] and (now - pressCacheT[i]) < 0.3 then return pressCache[i] or 0 end
    pressCacheT[i] = now
    local p = 0
    pcall(function()
        local mySpline = myCar.splinePosition
        if mySpline == nil then return end
        local sim = ac.getSim()
        local best = 1e9
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition then
                    local gap = mySpline - oc.splinePosition
                    if gap < 0 then gap = gap + 1 end
                    if gap > 0 and gap < best then best = gap end
                end
            end
        end
        if best < PRESSURE_GAP then p = 1 - (best / PRESSURE_GAP) end
    end)
    pressCache[i] = p
    return p
end

-- car close AHEAD, on a straight/fast bit -> in the tow
local function slipstream01(i, myCar)
    local t = 0
    pcall(function()
        local spd = myCar.speedKmh or 0
        if spd < TOW_MIN_KMH then return end
        local straight = 1
        local st = myCar.steer
        if type(st) == "number" then straight = 1 - H.cornering01(myCar, st) end   -- see H.STEER_FRAC
        if straight <= 0 then return end
        local mySpline = myCar.splinePosition
        if mySpline == nil then return end
        local sim = ac.getSim()
        local best = 1e9
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition and (oc.lapCount or 0) >= (myCar.lapCount or 0) then   -- a lapped car isn't a rival's wake (AC's count; good enough here)
                    local gap = oc.splinePosition - mySpline
                    if gap < 0 then gap = gap + 1 end
                    if gap > 0 and gap < best then best = gap end
                end
            end
        end
        if best < TOW_GAP then t = (1 - best / TOW_GAP) * straight end
    end)
    return t
end

-- car close AHEAD, through a CORNER, at speed -> dirty air
local function dirtyair01(i, myCar)
    local d = 0
    pcall(function()
        local spd = myCar.speedKmh or 0
        if spd < DIRTY_MIN_KMH then return end
        local st = myCar.steer
        if type(st) ~= "number" then return end
        local corner = H.cornering01(myCar, st)                 -- see H.STEER_FRAC
        if corner <= 0 then return end
        local mySpline = myCar.splinePosition
        if mySpline == nil then return end
        local lat = H.DIRTY_LAT > 0 and (myCar.lapCount or 0) >= 1   -- (H.DIRTY_LAT) the wake is behind a car, not beside it; lap 0 as before
        local a = lat and ac.worldCoordinateToTrack(myCar.position) or nil
        local sim = ac.getSim()
        local best = 1e9
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition and not (lat and (oc.isInPitlane or (oc.speedKmh or 0) < 30)) then
                    local gap = oc.splinePosition - mySpline
                    if gap < 0 then gap = gap + 1 end
                    if a then
                        -- (H.DIRTY_LAT) every car within DIRTY_GAP, each faded by its own offset from my line: the strongest wake wins
                        -- (the nearest car, alongside, must not hide the one right in front a few metres further on)
                        if gap > 0 and gap < DIRTY_GAP then
                            local b = ac.worldCoordinateToTrack(oc.position)
                            local w = 1 - gap / DIRTY_GAP
                            if b then w = w * clamp(1 - (math.abs(a.x - b.x) - 0.5 * H.DIRTY_LAT) / (0.5 * H.DIRTY_LAT), 0, 1) end
                            if w > d then d = w end
                        end
                    elseif gap > 0 and gap < best then best = gap end
                end
            end
        end
        if a then d = d * corner
        elseif best < DIRTY_GAP then d = (1 - best / DIRTY_GAP) * corner end
    end)
    return d
end

-- How hard a car is cornering by its steering: 0 (straight) .. 1 (full cornering); st = car.steer, already a number.
-- Default: the dev0146 reading (the degrees / 0.35). H.STEER_FRAC: the wheel angle as a fraction of lock, full at STEER_CORNER.
local function lockOf(car) return car.steerLock end       -- read under pcall: an older CSP's car state may not have the field
function H.cornering01(car, st, frac)   -- frac: the unit-correct read (fraction of lock) whatever STEER_FRAC says (H.MISTAKE_V2's moments)
    if H.STEER_FRAC or frac then
        local ok, lock = pcall(lockOf, car)
        if ok and type(lock) == "number" and lock > 0 then
            local full = H.STEER_CORNER
            if type(full) ~= "number" or not (full > 0) then full = 0.13 end      -- the default above (NaN too)
            return clamp(math.abs(st) / math.max(lock, 1) / full, 0, 1)
        end
    end
    return clamp(math.abs(st) / 0.35, 0, 1)
end

-- ---- VISIBLE MISTAKES (H.MISTAKE_V2) ----
local function mvAnchor(ys, x, logy)          -- ys at pace x on the H.MV_PACE anchors (log-interpolated when logy; ends held)
    local xs = H.MV_PACE
    if x <= xs[1] then return ys[1] end
    for k = 1, #xs - 1 do
        if x <= xs[k + 1] then
            local f, a, b = (x - xs[k]) / (xs[k + 1] - xs[k]), ys[k], ys[k + 1]
            if logy and a > 0 and b > 0 then return a * (b / a) ^ f end
            return a + (b - a) * f
        end
    end
    return ys[#xs]
end
function H.mvTopOf(prof)                      -- a named driver in the top MV_TOP_FRAC of his roster bucket by pace (never an archetype or a wild row)
    if not prof or not prof.bucket or prof.bucket == 'archetype' or prof.wild or type(prof.pace) ~= 'number' then return false end
    local th = H.mvTop[prof.bucket]
    if th == nil then
        local ps = {}
        for _, d in ipairs(Drivers.DRIVERS or {}) do if d.bucket == prof.bucket and type(d.pace) == 'number' then ps[#ps + 1] = d.pace end end
        table.sort(ps, function(a, b) return a > b end)
        th = ps[math.max(1, math.ceil(H.MV_TOP_FRAC * #ps))] or 9
        H.mvTop[prof.bucket] = th
    end
    return prof.pace >= th
end
-- one car's mistake profile, re-read every 5 s (a profile or a level can change mid-session)
function H.mvSkill(i, prof, now)
    local c = H.mvSk[i]
    if c and now < c.t then return c end
    c = c or {}
    local ar = H.MV_ARCH
    local pace = prof and prof.pace or clamp(Drivers.paceOf(i), ar[1][1], ar[#ar][1])   -- no profile: the applied level read as pace; 100 = a Veteran
    local ra, ca = ar[1][2], ar[1][3]                                                     -- the archetype line (risk, cons) at this pace
    if pace > ar[1][1] then
        ra, ca = ar[#ar][2], ar[#ar][3]
        for k = 1, #ar - 1 do
            if pace <= ar[k + 1][1] then
                local f = (pace - ar[k][1]) / (ar[k + 1][1] - ar[k][1])
                ra = ar[k][2] + (ar[k + 1][2] - ar[k][2]) * f; ca = ar[k][3] + (ar[k + 1][3] - ar[k][3]) * f
                break
            end
        end
    end
    local risk, cons = ra, ca
    if prof then risk, cons = prof.risk or ra, prof.cons or ca end
    local dev = clamp((cons - ca) - (risk - ra), -1, 1)                                  -- steadier and safer than the line at his pace: fewer
    local laps = mvAnchor(H.MV_LAPS, pace, true) * clamp(1 + 2 * H.MV_CR * dev, 1 - H.MV_CR, 1 + H.MV_CR)
    c.top = H.mvTopOf(prof)
    if c.top then laps = math.max(laps, H.MV_LAPS[#H.MV_LAPS]) end
    c.wild = prof ~= nil and prof.wild == true
    if c.wild and Drivers.WILD_ON ~= false and H.WILD_ERR > 0 then laps = laps / H.WILD_ERR end   -- (H.WILD_ERR) the chaos driver, as in the bobble model
    c.pace, c.risk, c.cons, c.prof, c.laps = pace, risk, cons, prof ~= nil, laps
    c.pOff, c.pSpin = mvAnchor(H.MV_OFF_P, pace), mvAnchor(H.MV_SPIN_P, pace)
    c.x = clamp((pace - H.MV_PACE[1]) / (H.MV_PACE[#H.MV_PACE] - H.MV_PACE[1]), 0, 1)
    c.tier = (c.wild and 'wild') or (c.top and 'top') or (pace < 0.45 and 'rookie') or (pace < 0.725 and 'midfield') or (pace < 0.90 and 'veteran') or 'top'
    c.cls = Classes.keyOf(i)
    c.race = true
    if H.MV_RACE_ONLY then pcall(function() c.race = ac.getSim().raceSessionType == ac.SessionType.Race end) end
    c.t = now + 5
    H.mvSk[i] = c
    return c
end
function H.nervesX(i, prof, now) return H.NERVES_K * (1 - H.mvSkill(i, prof, now).cons) end
-- pressure from a RIVAL behind (0..1 over PRESSURE_GAP), cached 0.3 s like pressure01; also notes the nearest car ahead (m), the nearest
-- rival behind and the cars within MV_SIDE_M either way. Pit-lane cars, cars under 30 km/h and cars I have lapped never count.
function H.pressureV2(i, myCar, now)
    local nr = H.mvNear[i]
    if nr and now - nr.t < 0.3 then return nr.p end
    if not nr then nr = { side = {} }; H.mvNear[i] = nr end
    nr.t, nr.p, nr.aheadM, nr.behind, nr.behindM = now, 0, 1e9, -1, 1e9
    local ns = 0
    pcall(function()
        local my = myCar.splinePosition
        if my == nil then return end
        local sim = ac.getSim()
        local len = (sim.trackLengthM or 0) > 200 and sim.trackLengthM or REF_LEN
        local myRD = (myCar.lapCount or 0) + my
        for j = 0, sim.carsCount - 1 do
            local oc = j ~= i and ac.getCar(j)
            if oc and oc.splinePosition and not oc.isInPitlane and (oc.speedKmh or 0) > 30 then
                local b = my - oc.splinePosition; if b < 0 then b = b + 1 end
                local d = 1 - b
                if math.min(b, d) * len < H.MV_SIDE_M then ns = ns + 1; nr.side[ns] = j end
                if d < b then
                    if d * len < nr.aheadM then nr.aheadM = d * len end
                elseif b * len < nr.behindM and myRD - ((oc.lapCount or 0) + oc.splinePosition) < 0.5 then
                    nr.behindM, nr.behind = b * len, j                       -- a rival, not a car I have lapped
                end
            end
        end
        if nr.behindM / len < PRESSURE_GAP then nr.p = 1 - (nr.behindM / len) / PRESSURE_GAP end
    end)
    for k = #nr.side, ns + 1, -1 do nr.side[k] = nil end
    return nr.p
end
local function mvEnv(e, a, h, r)               -- attack a s, hold h s, release r s
    if e < a then return e / a elseif e < a + h then return 1 elseif e < a + h + r then return 1 - (e - a - h) / r end
    return 0
end
local function mvOverlap(car, nr)              -- a car within MV_SIDE_M either way and MV_SIDE_LAT across (read only when a mistake fires)
    if #nr.side == 0 then return false end
    local busy = false
    pcall(function()
        local my = ac.worldCoordinateToTrack(car.position).x
        for _, j in ipairs(nr.side) do
            local oc = ac.getCar(j)
            if oc and math.abs(ac.worldCoordinateToTrack(oc.position).x - my) < H.MV_SIDE_LAT then busy = true; break end
        end
    end)
    return busy
end
local function mvDrop(i, st, why, now)         -- a drawn mistake that never happened: counted, so a rate miss can be told from a moment miss
    H.mvDrop[i] = (H.mvDrop[i] or 0) + 1
    if H.feedEvent then pcall(H.feedEvent, 'mistake_drop', string.format('"car":%d,"kind":"%s","why":"%s","wait_s":%.1f', i, tostring(st.k), why, now - (st.armT or now))) end
    st.k = nil; st.next = now + 2
end
-- One car, one frame. Returns (grip dip >= 0, caution >= 0) and leaves this frame's racecraft levers in H.mv[i]:
-- thr, bh, wide (+ lookM, big; racecraft fills side), lv = valid-until (os.clock)
function H.mistakeV2(i, car, prof, cm, now)
    local st = H.mv[i]
    if not st then st = {}; H.mv[i] = st end
    local sp, ds = car.splinePosition, 0
    if sp and st.sp then ds = sp - st.sp; if ds < -0.5 then ds = ds + 1 end; if ds < 0 or ds > 0.05 then ds = 0 end
    elseif not sp and st.lt and now - st.lt > 0 and now - st.lt <= 0.5 then ds = (now - st.lt) / H.MV_LAP_S end
    st.sp, st.lt = sp, now
    st.thr, st.bh, st.wide = nil, nil, nil
    if i == 0 then return 0, 0 end                                     -- slot 0 (the harness autopilot; a player's own slot): never
    local sk = H.mvSkill(i, prof, now)
    if not sk.race then st.k, st.t0 = nil, nil; return 0, 0 end
    local spd, br, gas, steer = car.speedKmh or 0, car.brake or 0, car.gas or 0, car.steer
    local corner = type(steer) == 'number' and H.cornering01(car, steer, true) or 0
    local frag = math.min(cm.mistake or 1, 1)
    -- 1. idle: the hazard, per lap of progress
    if not st.k and not st.t0 and now >= (st.next or 0) and (car.lapCount or 0) >= H.MV_MIN_LAP and (car.bestLapTimeMs or 0) > 0 then
        if not sk.sent and H.feedEvent then
            sk.sent = true
            pcall(H.feedEvent, 'mistake_model', string.format('"car":%d,"pace":%.2f,"laps_per":%.1f,"rate_x":%.2f,"tier":"%s","top":%s,"profiled":%s,"cons":%.2f,"risk":%.2f',
                i, sk.pace, sk.laps, H.MV_RATE_X * (H.MV_CLASS_RATE[sk.cls] or 1), sk.tier, tostring(sk.top == true), tostring(sk.prof), sk.cons, sk.risk))
        end
        local p = H.pressureV2(i, car, now)
        local perLap = H.MV_RATE_X * (H.MV_CLASS_RATE[sk.cls] or 1) * (1 + H.MV_PRESS * p * (1 - sk.cons)) / sk.laps
        if ds > 0 and math.random() < perLap * ds and not (H.busy and H.busy(i)) then
            local r = math.random() * (H.MV_W_LOCK + H.MV_W_APEX + H.MV_W_LIFT)
            st.k = H.MV_FORCE_KIND or ((r < H.MV_W_LOCK and 'lockup') or (r < H.MV_W_LOCK + H.MV_W_APEX and 'apex') or 'lift')
            st.armT, st.sev = now, math.random() ^ (1 + H.MV_SEV_SKILL * sk.x)
            local bigX = (H.MV_BIG_CLASS[sk.cls] or 1) * (1 - MISTAKE_CRASHY * Troublespots.crashiness())
            st.big = math.random() < sk.pOff * bigX
            st.spin = frag >= 0.9 and math.random() < sk.pSpin * bigX
        end
    end
    -- 2. armed: its own moment for half of MV_ARM_S (a forced kind: all of it), then any
    if st.k and not st.t0 then
        local waited = now - st.armT
        if waited > H.MV_ARM_S then mvDrop(i, st, 'no_moment', now); return 0, 0 end
        H.pressureV2(i, car, now)
        local nr = H.mvNear[i]
        if st.k == 'lockup' and nr.aheadM >= 2 * H.MV_AHEAD_M and br < H.MV_BRAKE_IN and spd > H.MV_LOCK_KMH then
            st.bh = 1 + H.MV_LOCK_BH + H.MV_LOCK_BH_SEV * st.sev + (st.big and H.MV_BIG_BH or 0); st.lv = now + 0.1   -- the late brake, held until the pedal is in
        end
        local ph
        if br > H.MV_BRAKE_IN and spd > H.MV_LOCK_KMH and corner < 0.35 then ph = 'lockup'
        elseif corner >= 0.5 and br < 0.2 and gas < 0.7 and spd > H.MV_APEX_KMH then ph = 'apex'
        elseif gas >= 0.7 and corner >= 0.3 and spd > H.MV_LIFT_KMH then ph = 'lift' end
        if ph and ph ~= st.k and (H.MV_FORCE_KIND or waited < 0.5 * H.MV_ARM_S) then ph = nil end
        if ph == 'lockup' and nr.aheadM < H.MV_AHEAD_M then ph = nil end
        if ph and ph ~= 'lift' and mvOverlap(car, nr) then ph = nil end
        if not ph then return 0, 0 end
        if H.busy and H.busy(i) then mvDrop(i, st, 'busy', now); return 0, 0 end
        local own, sev, big = ph == st.k, st.sev, st.big and ph ~= 'lift'
        st.k, st.t0, st.big, st.side, st.scanT = ph, now, big, nil, nil
        if ph == 'lift' and st.spin then st.k = 'spin' end
        if ph == 'lockup' then
            st.bhv = 1 + H.MV_LOCK_BH + H.MV_LOCK_BH_SEV * sev + (big and H.MV_BIG_BH or 0)
            st.gv = (H.MV_LOCK_GRIP + H.MV_LOCK_GRIP_SEV * sev) * (0.5 + 0.5 * frag) + (big and H.MV_BIG_GRIP or 0)
            st.wv, st.dur = big and 1.0 or (H.MV_WIDE + H.MV_WIDE_SEV * sev), 0.2 + (big and 2.0 or H.MV_WIDE_S)
        elseif ph == 'apex' then
            st.wv, st.cv = big and 1.0 or (H.MV_WIDE + H.MV_WIDE_SEV * sev), H.MV_APEX_CAUT + H.MV_APEX_CAUT_SEV * sev
            st.gv, st.dur = H.MV_APEX_GRIP + (big and H.MV_BIG_GRIP or 0), big and 2.2 or (H.MV_APEX_S + H.MV_APEX_S_SEV * sev)
        elseif st.k == 'spin' then st.gv, st.dur = H.MV_SPIN_GRIP, H.MV_SPIN_S
        else
            st.gv, st.tv = (H.MV_SNAP + H.MV_SNAP_SEV * sev) * frag, H.MV_LIFT_THR - H.MV_LIFT_THR_SEV * sev
            st.dur = H.MV_SNAP_S + H.MV_LIFT_S + H.MV_LIFT_S_SEV * sev
        end
        local est = (st.k == 'spin' and 3.0 or ((ph == 'apex' and 0.3 + 0.5 * sev) or (0.3 + 0.6 * sev))) + (big and 1.5 or 0)
        H.mvN[i] = (H.mvN[i] or 0) + 1
        if H.feedEvent then
            pcall(H.feedEvent, 'mistake', string.format('"car":%d,"kind":"%s","sev":%.2f,"est_cost_s":%.2f,"off":%s,"lap":%d,"spline":%.4f,"pressure":%.2f,"behind":%d,"wait_s":%.1f,"own_moment":%s,"pace":%.2f,"laps_per":%.1f,"tier":"%s"',
                i, st.k == 'apex' and 'missed_apex' or st.k, sev, est, tostring(big), car.lapCount or 0, sp or 0, nr.p, nr.behindM < 60 and nr.behind or -1, waited, tostring(own), sk.pace, sk.laps, sk.tier))
        end
    end
    -- 3. under way: this frame's levers
    if st.t0 then
        local e = now - st.t0
        if e >= st.dur then st.t0, st.k = nil, nil; st.endT = now; st.next = now + H.MV_GAP_S; return 0, 0 end
        local g, c = 0, 0
        if st.k == 'lockup' then
            if e < H.MV_LOCK_HOLD then st.bh = st.bhv end
            g = st.gv * mvEnv(e, 0.08, H.MV_LOCK_HOLD, 0.3)
            if e > 0.2 then st.wide, st.lookM = st.wv, H.MV_LOCK_LOOK_M end
            if e > st.dur - 0.5 then c = H.MV_GATHER end
        elseif st.k == 'apex' then
            st.wide, st.lookM, c = st.wv, 0, st.cv
            g = st.gv * mvEnv(e, 0.2, st.dur - 0.5, 0.3)
        elseif st.k == 'spin' then g = st.gv * mvEnv(e, 0.15, st.dur - 0.45, 0.3)
        else                                                           -- lift: the snap (built over MV_SNAP_RAMP), then a throttle cap
            local e2 = H.MV_LIFT_CAP_FIRST and e - 0.1 or e
            if e2 > 0 then g = st.gv * mvEnv(e2, H.MV_SNAP_RAMP, H.MV_SNAP_S, 0.3) end
            if H.MV_LIFT_CAP_FIRST or e > 0.5 * H.MV_SNAP_S then st.thr = st.tv end
        end
        st.lv = now + 0.1
        return g, c
    end
    return 0, 0
end

function H.reset()     -- session start: re-derive the per-track distances; the visible-mistake state starts over
    scaled = false; H.wu = {}
    H.salt = H.SESSION_SALT and ((os.time() + math.floor(os.clock() * 1000)) % 9973) or 0
    for k in pairs(pers) do pers[k] = nil; cons[k] = nil; phase[k] = nil end   -- re-drawn with the new salt on first use
    for k in pairs(H.mv) do H.mv[k] = nil end          -- in place: racecraft holds this table (R.humanMv)
    H.mvSk, H.mvN, H.mvDrop, H.mvNear = {}, {}, {}, {}
end

-- Returns additive (gripOffset, cautionOffset). Player / slow / recovering cars -> 0,0.
function H.getModifiers(i)
    if not H.ENABLED then return 0, 0 end
    if not scaled then scaled = true; pcall(function() scaleToTrack(ac.getSim().trackLengthM) end) end
    if i == nil or i < 0 then return 0, 0 end
    if i == 0 then local isAI = false; pcall(function() local c = ac.getCar(0); isAI = c ~= nil and c.isAIControlled == true end); if not isAI then return 0, 0 end end
    do
        local ok, spd = pcall(function() local c = ac.getCar(i); return (c and c.speedKmh) or 999 end)
        if ok and spd and spd < 40 then return 0, 0 end
    end
    seed(i)
    local now = os.clock()
    local prof = Drivers.statsOf(i)     -- optional per-slot driver profile (nil = normal system)

    local vGrip, vCaut = 0, 0
    if H.HUMAN_VAR then
        -- a driver profile pins consistency (metronomic vs streaky) and cancels the random pace
        -- bias (pace is handled deterministically via the car's AI level in the director).
        local consDiv = prof and (0.4 + 1.2 * prof.cons) or cons[i]
        local dwv = 0.6 * math.sin(now * 0.050 + phase[i]) + 0.4 * math.sin(now * 0.017 + phase[i] * 1.7)
        dwv = dwv / consDiv
        vGrip = (prof and 0 or pers[i]) + dwv * DRIFT_AMP
        vCaut = -dwv * CAUTION_AMP
    end
    local pGrip, pCaut, mvG, mvC = 0, 0, 0, 0   -- mvG / mvC: H.MISTAKE_V2's dip and caution (full strength, outside the slew)

    pcall(function()
        local car = ac.getCar(i)
        if not car then return end
        local cm = Classes.multOf(i)

        if H.HUMAN_VAR then
            local f = fadeFrac(i, car) ^ 1.3
            vGrip = vGrip - FADE_MAX_GRIP * f
            vCaut = vCaut + FADE_MAX_CAUTION * f

            local p = H.NERVES_V2 and H.pressureV2(i, car, now) or pressure01(i, car, now)
            if p > 0 then vGrip = vGrip - PRESSURE_NERVES * p * (H.NERVES_V2 and H.nervesX(i, prof, now) or 1) end
            if H.HUMAN_ERRORS and H.MISTAKE_V2 and H.INTENSITY > 0 then
                mistakeUntil[i] = nil                              -- the bobble model idles while V2 runs
                local okM, g2, c2 = pcall(H.mistakeV2, i, car, prof, cm, now)   -- a V2 fault can't strip warm-up / wet / dirty air
                if okM then mvG, mvC = g2 or 0, c2 or 0 end
            elseif H.HUMAN_ERRORS then
                local classGate = cm.mistake
                local rate, sevScale, avoidSharp = 0, 1.0, false
                if prof then
                    -- driver RISK drives errors, and works even on classes that never bobble by
                    -- default (e.g. formula). Fragile aero classes (low classGate) get errors far
                    -- LESS often and gentler, so a driver's risk shows as the odd lost place, not a
                    -- spin/DNF -- while the relative order between drivers (Lance > Lewis) is kept.
                    local frag = math.min(classGate, 1)          -- 0 = fragile aero .. 1 = robust
                    rate = (MISTAKE_BASE + MISTAKE_RATE * p) * (0.15 + 1.15 * prof.risk) * (0.30 + 0.70 * frag)
                    sevScale = 0.45 + 0.55 * frag
                    avoidSharp = frag < 0.7                       -- no sharp lockup on fragile cars
                    if prof.wild and Drivers.WILD_ON ~= false and H.WILD_ERR ~= 1 then rate = rate * H.WILD_ERR; avoidSharp = false end   -- (H.WILD_ERR) the chaos driver
                elseif classGate > 0 then
                    rate = (MISTAKE_BASE + MISTAKE_RATE * p) * classGate
                end
                -- Treacherous-track discipline: scale mistakes by how crash-prone the track has proven
                -- (from the learned trouble-spot map). Fewer, gentler bobbles where a bobble = an off.
                local crash = Troublespots.crashiness()
                if crash > 0 then
                    rate = rate * (1 - MISTAKE_CRASHY * crash)
                    sevScale = sevScale * (1 - 0.5 * crash)
                end
                local dtp = lastT[i] and (now - lastT[i]) or 0
                if rate > 0 and dtp > 0 and dtp < 1 and (not mistakeUntil[i] or now > mistakeUntil[i]) then
                    if math.random() < rate * dtp then
                        local st = car.steer
                        local cornering = (type(st) == "number") and H.cornering01(car, st) or 0   -- see H.STEER_FRAC
                        local m = pickMistake(p, cornering, avoidSharp)
                        mistakeUntil[i] = now + m.dur
                        mistakeGrip[i]  = m.grip * sevScale
                        mistakeCaut[i]  = m.caut
                    end
                end
                if mistakeUntil[i] and now < mistakeUntil[i] then
                    vGrip = vGrip - (mistakeGrip[i] or 0)
                    vCaut = vCaut + (mistakeCaut[i] or 0)
                end
            else
                mistakeUntil[i] = nil
            end
            lastT[i] = now

            local tow = slipstream01(i, car)
            if tow > 0 then
                local draft = cm.draft or 1.0                 -- stock/oval cars gain a much bigger tow (pack draft)
                vGrip = vGrip + TOW_GRIP * tow * draft
                vCaut = vCaut - TOW_CAUT * tow * draft
            end
        end

        if H.CLASS_PHYSICS then
            local wu = warmupFrac(i, car)
            H.wu[i] = wu
            if wu > 0 then
                -- Cold tyres genuinely bite, on every track -- the same rubber you're on. (A build briefly
                -- removed the grip cut on "crashy" tracks; the data said cold tyres were NOT the cause of
                -- the offs -- 20 of 23 happened on warm rubber -- so the human version stays.)
                pGrip = pGrip - WARMUP_MAX_GRIP * wu * cm.warmup
                pCaut = pCaut + WARMUP_MAX_CAUT * wu * cm.warmup
            end
            local wet = wetness01()
            if wet > 0 then
                local g, c = 1.0, 1.0
                if rainfxOn() then g, c = H.RAINFX_GRIP, H.RAINFX_CAUT end
                pGrip = pGrip - WET_MAX_GRIP * wet * cm.wet * g; pCaut = pCaut + WET_MAX_CAUT * wet * cm.wet * c
            end
            local da = dirtyair01(i, car)
            if da > 0 and cm.dirty > 0 then pGrip = pGrip - DIRTY_MAX_GRIP * da * cm.dirty; pCaut = pCaut + DIRTY_MAX_CAUT * da * cm.dirty * H.DIRTY_CAUT_X end
        end
    end)

    local k = H.INTENSITY
    local gripTarget = vGrip * k + pGrip
    local cautionOff = vCaut * k + pCaut + mvC
    if gripTarget > GRIP_MAX then gripTarget = GRIP_MAX elseif gripTarget < GRIP_MIN then gripTarget = GRIP_MIN end

    -- slew-limit grip (anti mid-corner snap)
    local sdt = (slewT[i] and (now - slewT[i])) or 0
    slewT[i] = now
    if sdt <= 0 or sdt > 0.5 then sdt = 0.016 end
    local cur = smoothedGrip[i]
    if cur == nil then cur = gripTarget end
    local step = GRIP_SLEW * sdt
    if gripTarget > cur + step then cur = cur + step
    elseif gripTarget < cur - step then cur = cur - step
    else cur = gripTarget end
    smoothedGrip[i] = cur
    if mvG ~= 0 then return math.max(cur - mvG, H.MV_GRIP_FLOOR), cautionOff end   -- a mistake's dip: fast, outside the slew
    return cur, cautionOff
end

return H
