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
-- RainFX (CSP preview builds) models wet grip physically and puts cars on rain tyres: Verve's own wet rule, written for
-- installs without rain physics, then stacks on top (Spa GT3 in the wet ran +35 % on lap time, real is +10-15 %; 2026-09-18).
-- When the module is enabled these scale the grip cut and the extra caution; both are harness switches until the A/B is in.
H.RAINFX_GRIP   = 0.0      -- x the wet grip cut when RainFX is on (0 = physics already does it)
H.RAINFX_CAUT   = 0.5      -- x the wet caution when RainFX is on
H.rainfx        = nil      -- detected at first use: true when the RainFX module is enabled on this install

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

local pers, cons, phase = {}, {}, {}
local function seed(i)
    if pers[i] ~= nil then return end
    pers[i]  = (hash01(i * 3 + 1) * 2 - 1) * PERSONALITY_AMP
    cons[i]  = 0.6 + hash01(i * 3 + 2) * 0.8
    phase[i] = hash01(i * 3 + 3) * 6.2831853
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
    if byTemp ~= nil then return byTemp end
    return clamp(1 - (stintProgressLaps(i, car) / WARMUP_LAPS), 0, 1)
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
        if type(st) == "number" then straight = clamp(1 - math.abs(st) / 0.35, 0, 1) end
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
        local corner = clamp(math.abs(st) / 0.35, 0, 1)
        if corner <= 0 then return end
        local mySpline = myCar.splinePosition
        if mySpline == nil then return end
        local sim = ac.getSim()
        local best = 1e9
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition then
                    local gap = oc.splinePosition - mySpline
                    if gap < 0 then gap = gap + 1 end
                    if gap > 0 and gap < best then best = gap end
                end
            end
        end
        if best < DIRTY_GAP then d = (1 - best / DIRTY_GAP) * corner end
    end)
    return d
end

function H.reset() scaled = false end     -- session start: re-derive the per-track distances

-- Returns additive (gripOffset, cautionOffset). Player / slow / recovering cars -> 0,0.
function H.getModifiers(i)
    if not H.ENABLED then return 0, 0 end
    if not scaled then scaled = true; pcall(function() scaleToTrack(ac.getSim().trackLengthM) end) end
    if i == nil or i < 1 then return 0, 0 end
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
    local pGrip, pCaut = 0, 0

    pcall(function()
        local car = ac.getCar(i)
        if not car then return end
        local cm = Classes.multOf(i)

        if H.HUMAN_VAR then
            local f = fadeFrac(i, car) ^ 1.3
            vGrip = vGrip - FADE_MAX_GRIP * f
            vCaut = vCaut + FADE_MAX_CAUTION * f

            local p = pressure01(i, car, now)
            if p > 0 then vGrip = vGrip - PRESSURE_NERVES * p end
            if H.HUMAN_ERRORS then
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
                        local cornering = (type(st) == "number") and clamp(math.abs(st) / 0.35, 0, 1) or 0
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
            if da > 0 and cm.dirty > 0 then pGrip = pGrip - DIRTY_MAX_GRIP * da * cm.dirty; pCaut = pCaut + DIRTY_MAX_CAUT * da * cm.dirty end
        end
    end)

    local k = H.INTENSITY
    local gripTarget = vGrip * k + pGrip
    local cautionOff = vCaut * k + pCaut
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
    return cur, cautionOff
end

return H
