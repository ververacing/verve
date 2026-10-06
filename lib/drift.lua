-- Verve / drift.lua
-- (0.16 MVP, default OFF: Racecraft.DRIFT_AI) AI drifting. AC's own AI cannot drift: it drives the racing line on grip, and with
-- its 120% grip a drift car never even steps out. With the switch on, Verve takes the pedals and the wheel of drift-class AI
-- cars through each corner - a handbrake flick to start the slide, the throttle to hold an angle, the front wheels to steer
-- the slide along the AI line - then straightens the car and hands it back. AC still drives the straights, the braking zones
-- and (outside a slide) the gearbox.
-- Harness: --racecraft {"DRIFT_AI":true} switches it on, "DRIFT":{...} tunes any key of D.P; {"DRIFT_MEASURE":true} measures
-- the same angles without touching the cars (the baseline arm).
-- Angles: every signed angle is measured about the car's (or the world's) up axis with ONE cross-product convention, and the
-- corner's own turning sense (sg = +1 or -1, from the AI line) turns them into "into the corner" units, so nothing depends on
-- AC's handedness. The steering sign and gain are learnt per car from AC's own driving (front-wheel direction vs car.steer).

local Classes = require('lib.classes')

local D = {}

D.P = {
    angle = 30,        -- held drift angle, degrees: the nose this far into the corner from the direction of travel
    angleMax = 62,     -- past this: off the throttle, extra counter-steer
    angleAbort = 105,  -- past this (a spin): let go, AC takes over
    snap = 25,         -- snapped this far the other way: let go
    grip = 1.0,        -- extra AI grip while sliding (AC's AI default 1.2 keeps a drift car glued; 1.0 = the car's own tyres)
    minKmh = 35,       -- no drift below this; a slide that falls under 0.6x of it ends
    turnIn = 30,       -- degrees of turning in the look-ahead that make a corner worth a drift
    lookS = 1.0,       -- corner look-ahead, seconds of travel (15-45 m)
    nearS = 0.45,      -- ... and the corner must have started within this (6-20 m)
    -- the start (first live race, 5 Oct: a 0.2 s pull with 6 deg of lock at 90 km/h never broke the rear loose - 157 of 177 failed):
    flick = 0.5,       -- longest handbrake pull, seconds; it ends as soon as the car has rotated flickEnd degrees
    flickEnd = 8,
    flickGas = 1.0,    -- revs up with the clutch in during the pull, so letting the clutch out kicks the rears loose
    kickT = 0.25,      -- full throttle this long after the pull (the clutch kick), then the throttle cascade
    initMax = 0.8,     -- no rotation this long after the pull: the attempt failed, AC drives the corner
    initSteer = 0.35,  -- front wheels into the corner during the pull, fading out over the first 12 degrees of the slide (AC's
                       -- steering follows a request within a frame, so a strong turn-in can be caught; the mock's slow rack could not)
    initGrip = 0,      -- >0: extra AI grip during the start only (0 = grip). Every key needs a non-nil default: the harness only sets known keys
    kick = 0,          -- >0: a yaw couple during the pull, N per kg of the car each axle (front pushed in, rear out; physics.addForce),
                       -- until the car has rotated flickEnd or kickT_max; works whatever AC's assists do (owner yes 6 Oct; it invalidates the
                       -- AI's lap). 0 = off. v3 (5 Oct): the pull scrubbed 77 -> 45 km/h and the car barely yawed.
    kickMax = 0.3,     -- longest kick, seconds
    lostAngle = 5, lostT = 0.5,   -- a held slide under lostAngle degrees for lostT s is LOST: hand the car straight back to AC (v3 kept
                       -- steering a car that had straightened as if it were sliding: 30-60 deg off its line, 23-29 incidents v stock 7)
    -- throttle, a cascade that adapts to the car's power: the angle error asks for a rotation rate (rateK deg/s per degree,
    -- capped at rateMax), and the throttle integrates toward whatever gives that rate (kir per deg/s per s, kpr per deg/s now)
    rateK = 2.0, rateMax = 60, kpr = 0.004, kir = 0.012, gStart = 0.45,
    kPath = 0.6,       -- steering: front wheels off the direction of travel, per radian of heading error to the AI line
    pathMax = 0.12,    -- cap on that, radians: in a slide, steering in pulls the NOSE round (a spin), it barely tightens the line
    wideE = 0.10, wideW = 0.20, wideCut = 0.4,   -- held slide running wide (line this far inside the travel, radians): ease the throttle, up to wideCut
    kRate = 0.15,      -- steering: counter-steer ahead of the rotation, seconds (where the slide will be, not where it is)
    lookPath = 0.55,   -- steering target on the AI line, seconds ahead (8-40 m)
    maxWheel = 0.70,   -- front-wheel angle cap, radians (the car's own lock caps it as well)
    exitTurn = 12,     -- the slide ends when less turning than this (degrees) is left within 0.7 s
    exitAngle = 7,     -- hand back once the car is this straight
    exitMax = 1.5,     -- ... or after this long straightening
    cool = 0.5,        -- seconds after a slide before the next may start
    entryMu = 0,       -- >0: brake to the corner's drift speed sqrt(entryMu * g * R) before the flick (R = tightest radius in the next
                       -- 40 m of the AI line); 0 = off (AC's own braking only). A slide carries less speed than grip: the MVP runs wide.
    entryMax = 1.2,    -- longest braking-in, seconds
    autoFlip = true,   -- a sustained input-sign disagreement inverts the steering input (st.flip counts them either way)
    holdGear = false,  -- keep the gear through a slide (one upshift on the limiter, one downshift when it bogs); off: AC's gearbox
    trafficS = 0.9,    -- a car within this many seconds of travel (12 m at least), within 25 degrees of our travel: no slide, AC drives
    nearM = 8,         -- no slide STARTS with any car this close in any direction (alongside / right behind)
    minLap = 1,        -- no slides before this lap (Verve's lap count): the probe's v1 start made 16 of its 26 incidents in the
                       -- opening-lap pack (stock AI: 4 of 7)
    noAssist = true,   -- drift cars race without AI stability control and TC while the switch is on (per car, physics.setAssists;
                       -- CSP 0.3.0-p440 turns the AI stability assist on exactly when a car slides). Never car 0 (= the player's global
                       -- assists). There is no per-car getter, so the originals are not restored until the session ends.
    preGrip = true,    -- grip goes to P.grip about a second BEFORE the corner (CSP smooths the AI grip multiplier: v1 dropped it
                       -- only once sliding, so its starts ran on 1.2)
    all = false,       -- every AI car, not only the drift class (testing)
    trace = 'auto',    -- 5 Hz rows for the diag file: 'auto' = only when Verve's dev diag logger is there (never in the shipped build)
}
D.ON, D.MEASURE, D.busy, D.TRACE = false, false, 0, false
D.cpu = { n = 0, sum = 0, max = 0 }   -- this module's own frame cost while active (ms), reported in the diag block
D.trace, D.traceDrop = {}, 0
D.errN, D.lastErr = 0, nil

local function newStats()
    return { fr = 0, ini = 0, hold = 0, spin = 0, fail = 0, exit = 0, trans = 0, snap = 0, slow = 0, flip = 0, traffic = 0, lost = 0, kickT = 0, aSum = 0, aT = 0, aMax = 0,
             slideT = 0, cornerT = 0, cornerSlideT = 0, offT = 0, noComb = 0 }
end
D.st = newStats()

local S = {}        -- per car: m (0 AC drives, 1 start, 2 hold, 3 straighten), timers, controller and calibration state
local trk = nil     -- the AI line: N samples (x, z), cumulative turning, length
local trkWait = 0   -- seconds before the next try when the line could not be read
local atan2, abs, sqrt, floor, min, max = math.atan2, math.abs, math.sqrt, math.floor, math.min, math.max
local DEG, RAD = 180 / math.pi, math.pi / 180
local CX, CZ, CN = {}, {}, 0   -- every car's position this frame (traffic check)
local scanT, anyDrift = 0, false   -- is a drift-class car on the grid at all (rechecked every 10 s): if not, the module sleeps
local clock = os.preciseClock or os.clock
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end

-- signed angle from a to b about the axis u (one convention for everything)
local function sang(ax, ay, az, bx, by, bz, ux, uy, uz)
    local cx, cy, cz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
    return atan2(cx * ux + cy * uy + cz * uz, ax * bx + ay * by + az * bz)
end

-- the AI line, read a slice per frame (in one frame it cost 45 ms on Highlands, 5 Oct): returns the line when done, else nil;
-- the second value is true when it can't be read (try again later)
local bld = nil
local function buildTrack(perFrame)
    if not bld then
        local sim = ac.getSim()
        local L = sim and sim.trackLengthM or 0
        if not L or L < 100 then return nil, true end
        bld = { N = floor(min(4000, max(300, L / 2))), L = L, px = {}, pz = {}, k = 0 }
    end
    local b = bld
    local N, px, pz = b.N, b.px, b.pz
    local stop = min(N, b.k + perFrame)
    for k = b.k, stop - 1 do
        local p = ac.trackProgressToWorldCoordinate(k / N, false)
        if not p then bld = nil; return nil, true end
        px[k], pz[k] = p.x, p.z
    end
    b.k = stop
    if stop < N then return nil, false end
    bld = nil
    local L = b.L
    local cum = { [0] = 0 }
    for k = 0, N - 1 do
        local a, c = (k - 1) % N, (k + 1) % N
        local ax, az = px[k] - px[a], pz[k] - pz[a]
        local bx, bz = px[c] - px[k], pz[c] - pz[k]
        cum[k + 1] = cum[k] + atan2(az * bx - ax * bz, ax * bx + az * bz)   -- = sang(a, b, world up)
    end
    return { N = N, L = L, ds = L / N, px = px, pz = pz, cum = cum }
end

-- turning of the AI line between d0 and d1 metres ahead of spline position sp (radians, convention sense)
local function turnAhead(sp, d0, d1)
    local N, cum = trk.N, trk.cum
    local base = (sp % 1) * N
    local a, b = floor(base + d0 / trk.ds), floor(base + d1 / trk.ds)
    if b <= a then return 0 end
    return (cum[b % N] + floor(b / N) * cum[N]) - (cum[a % N] + floor(a / N) * cum[N])
end

local function newCar()
    return { m = 0, t = 0, cool = 0, sg = 1, I = 0, gI = nil, aPrev = nil, daF = 0, u = 0, g0 = 0, gT = 0, flick = true,
             sw = 0, ss = 0, wn = 0, yv = 0, yn = 0, wpd = nil, cal = nil, kIn = 1, kGood = 0, kBad = 0, tr = 0 }
end

-- learn the steering: front-wheel angle per degree of car.steer while AC drives (fallback: the yaw sense at ~12:1)
local function learn(s, car, dt)
    local st, v = car.steer or 0, car.speedKmh or 0
    local up, lk = car.up, car.look
    if s.lx and dt > 0 and abs(st) > 20 and v > 15 then
        local yaw = sang(s.lx, s.ly, s.lz, lk.x, lk.y, lk.z, up.x, up.y, up.z) / dt
        if abs(yaw) > 0.05 then s.yv = s.yv + ((yaw * st > 0) and 1 or -1); s.yn = s.yn + 1 end
    end
    s.lx, s.ly, s.lz = lk.x, lk.y, lk.z
    if abs(st) > 20 and v > 15 then
        local w0, w1 = car.wheels[0].look, car.wheels[1].look
        local w = 0.5 * (sang(lk.x, lk.y, lk.z, w0.x, w0.y, w0.z, up.x, up.y, up.z) + sang(lk.x, lk.y, lk.z, w1.x, w1.y, w1.z, up.x, up.y, up.z))
        s.sw = s.sw + w * st; s.ss = s.ss + st * st; s.wn = s.wn + 1
    end
    if s.wn >= 40 then
        local g = s.sw / s.ss
        if abs(g) >= 0.0004 and abs(g) <= 0.005 then s.wpd, s.cal = g, 'wheel'; return end
    end
    if s.yn >= 40 and abs(s.yv) >= 0.5 * s.yn then s.wpd, s.cal = (s.yv > 0 and 1 or -1) * RAD / 12, 'yaw' end
end

local function setComb(c, v) c.combineAxis = v end
local function release(i, s)
    pcall(function()
        local c = ac.overrideCarControls(i)
        if c then
            c.steer = math.huge; c.requestedGearIndex = 0; c.clutch = 1
            c.gas = 0; c.brake = 0; c.handbrake = 0
            c.combineAxis = true            -- last: a CSP without the field errors here, after the rest is already neutral
        end
    end)
    pcall(physics.setExtraAIGrip, i, 1.2)   -- AC's default; Verve's own grip (when it manages grip) is back next frame
    s.m, s.t, s.cool = 0, 0, D.P.cool
end

local function addTrace(row)
    local tr = D.trace
    if #tr >= 3000 then D.traceDrop = D.traceDrop + 1; return end
    tr[#tr + 1] = row
end

local function sessMs() return ac.getSim().currentSessionTime end
local function simT()
    local ok, v = pcall(sessMs)
    if ok and type(v) == 'number' and v > -1e9 and v < 1e10 then return v / 1000 end
    return os.clock()
end

-- the tightest radius of the AI line in the next 40 m (5 m chunks), metres
local function tightR(sp)
    local kmax = 0
    for c = 0, 7 do
        local k = abs(turnAhead(sp, 5 * c, 5 * c + 5)) / 5
        if k > kmax then kmax = k end
    end
    return kmax > 1e-4 and 1 / kmax or 1e4
end

-- a car close ahead in our direction of travel (positions from this frame); with near > 0 also any car that close at all
local function trafficAhead(i, pos, vel, spd, P, near)
    local reach = max(12, P.trafficS * spd)
    local n2 = (near or 0) * (near or 0)
    for j = 0, CN - 1 do
        local x = CX[j]
        if j ~= i and x then
            local dx, dz = x - pos.x, CZ[j] - pos.z
            local d2 = dx * dx + dz * dz
            if d2 < n2 then return true end
            if d2 < reach * reach and d2 > 0.01 and (dx * vel.x + dz * vel.z) > 0.9 * sqrt(d2) * max(spd, 1) then return true end
        end
    end
    return false
end

-- the throttle cascade (see D.P): wanted rotation rate from the angle error, throttle integrating toward that rate
function D.gasLaw(s, P, aDeg, dt, ePath)
    local want = clamp(P.rateK * (P.angle - aDeg), -P.rateMax, P.rateMax)
    local err = want - s.daF * DEG
    s.gI = clamp((s.gI or P.gStart) + P.kir * err * dt, 0, 1)
    local wide = clamp((ePath - P.wideE) / P.wideW, 0, 1)        -- 0 on the line .. 1 well outside it: shed speed
    return clamp(s.gI + P.kpr * err, 0, 1) * (1 - P.wideCut * wide)
end

-- (P.kick) a yaw couple: the front axle pushed toward the inside of the corner, the rear axle toward the outside, F newtons each,
-- in world coordinates. inside = sg x (up x look): +90 degrees from the nose in the corner's own sense (the sang convention).
function D.kick(i, car, sg, F)
    local up, lk, w = car.up, car.look, car.wheels
    local ix = sg * (up.y * lk.z - up.z * lk.y)
    local iy = sg * (up.z * lk.x - up.x * lk.z)
    local iz = sg * (up.x * lk.y - up.y * lk.x)
    local f0, f1, r0, r1 = w[0].position, w[1].position, w[2].position, w[3].position
    physics.addForce(i, vec3((f0.x + f1.x) * 0.5, (f0.y + f1.y) * 0.5, (f0.z + f1.z) * 0.5), false, vec3(ix * F, iy * F, iz * F), false)
    physics.addForce(i, vec3((r0.x + r1.x) * 0.5, (r0.y + r1.y) * 0.5, (r0.z + r1.z) * 0.5), false, vec3(-ix * F, -iy * F, -iz * F), false)
end

local function carStep(i, car, dt, P, st)
    local s = S[i]
    if not s then s = newCar(); S[i] = s end
    local v = car.speedKmh or 0
    local up, lk, vel = car.up, car.look, car.velocity
    local spd = sqrt(vel.x * vel.x + vel.y * vel.y + vel.z * vel.z)
    local sp = car.splinePosition or 0
    if s.m == 0 then learn(s, car, dt) end
    s.cool = max(0, s.cool - dt)
    local ang = spd > 2 and sang(vel.x, vel.y, vel.z, lk.x, lk.y, lk.z, up.x, up.y, up.z) or 0   -- travel -> nose
    local turnIn = P.turnIn * RAD
    local far = turnAhead(sp, 0, clamp(spd * P.lookS, 15, 45))
    local near = turnAhead(sp, 0, clamp(spd * P.nearS, 6, 20))
    if (car.wheelsOutside or 0) >= 3 then st.offT = st.offT + dt end
    if D.ON and P.noAssist and not s.ast and i > 0 then              -- once per car per session
        s.ast = true
        if pcall(physics.setAssists, { stability = 0, tractionControl = 'off' }, i) then st.noAst = (st.noAst or 0) + 1 end
    end
    if D.ON and P.preGrip and s.m == 0 and v >= P.minKmh and abs(far) >= 0.5 * turnIn then   -- a corner is coming: real grip now
        pcall(physics.setExtraAIGrip, i, P.grip); s.pre = true
    elseif s.pre and s.m == 0 then s.pre = nil end
    if abs(far) >= turnIn and v >= P.minKmh then                     -- cornering time, both arms
        st.cornerT = st.cornerT + dt
        if (far > 0 and 1 or -1) * ang * DEG >= 15 then st.cornerSlideT = st.cornerSlideT + dt end
    end
    if not D.ON then                                                  -- measure only: a 2 Hz row in corners
        if D.TRACE and abs(far) >= turnIn and v >= P.minKmh then
            s.tr = s.tr + dt
            if s.tr >= 0.5 then
                s.tr = 0
                addTrace(string.format('{"ev":"drift","ts":%.2f,"car":%d,"m":0,"a":%.1f,"v":%.0f,"sp":%.4f,"st":%.0f}', simT(), i, (far > 0 and 1 or -1) * ang * DEG, v, sp, car.steer or 0))
            end
        end
        return
    end
    if s.m == 0 then
        if s.wpd and s.cool <= 0 and v >= P.minKmh and abs(far) >= turnIn and abs(near) >= 0.35 * turnIn and far * near > 0
           and (car.lapCount or 0) >= P.minLap and not trafficAhead(i, car.position, vel, spd, P, P.nearM) then
            s.m, s.t, s.sg = 1, 0, (far > 0 and 1 or -1)
            s.gI = s.gI and (0.5 * s.gI + 0.5 * P.gStart) or P.gStart   -- half of what the last slide settled on
            s.aPrev, s.daF, s.flick, s.u = nil, 0, true, 0
            s.g0, s.gT = (car.gear or 0), 0
            s.vIn = P.entryMu > 0 and sqrt(P.entryMu * 9.81 * tightR(sp)) or nil   -- m/s to brake down to before the flick
            s.brk = (s.vIn and spd > s.vIn + 1) and 0 or nil
            st.ini = st.ini + 1
        else
            return
        end
    end
    -- a slide is in progress: this car is ours this frame
    local sg = s.sg
    local a = sg * ang                                                -- drift angle, radians, + = nose into the corner
    local aDeg = a * DEG
    if s.aPrev and dt > 0 then s.daF = 0.7 * s.daF + 0.3 * (a - s.aPrev) / dt end
    s.aPrev = a
    if aDeg > P.angleAbort then st.spin = st.spin + 1; release(i, s); return end
    if aDeg < -P.snap and s.m >= 2 then st.snap = st.snap + 1; release(i, s); return end
    if v < 0.6 * P.minKmh then st.slow = st.slow + 1; release(i, s); return end
    if trafficAhead(i, car.position, vel, spd, P) then st.traffic = st.traffic + 1; release(i, s); return end
    local dP = clamp(spd * P.lookPath, 8, 40)
    local k = floor((sp % 1) * trk.N + dP / trk.ds) % trk.N
    local pos = car.position
    local ePath = sg * sang(vel.x, 0, vel.z, trk.px[k] - pos.x, 0, trk.pz[k] - pos.z, 0, 1, 0)   -- + = the line is inside our travel
    local steerPath = clamp(P.kPath * ePath, -P.pathMax, P.pathMax)
    local gas, brake, hb, clutch, wheel = 0, 0, 0, 1, 0
    s.t = s.t + dt
    if s.m == 1 and s.brk then                                        -- braking in (P.entryMu): AC steers, we brake, no flick yet
        s.brk = s.brk + dt
        if spd <= s.vIn + 0.5 or s.brk > P.entryMax then s.brk, s.t = nil, 0
        else
            local c = ac.overrideCarControls(i)
            if not c then release(i, s); return end
            if not pcall(setComb, c, false) then st.noComb = st.noComb + 1; release(i, s); return end
            c.steer, c.gas, c.brake, c.handbrake, c.clutch, c.requestedGearIndex = math.huge, 0, clamp((spd - s.vIn) * 0.25, 0.2, 0.9), 0, 1, 0
            st.brakeIn = (st.brakeIn or 0) + dt
            return
        end
    end
    if s.m == 1 then                                                  -- start: pull until it rotates, clutch kick, then the hold law
        if s.flick and s.t < P.flick and aDeg < P.flickEnd then
            hb, clutch, gas, wheel = 1, 0, P.flickGas, P.initSteer
            if P.kick > 0 and s.t < P.kickMax then pcall(D.kick, i, car, sg, P.kick * (car.mass or 1200)); st.kickT = st.kickT + dt end
        else
            if s.flick then s.flick, s.t, s.gI = false, 0, max(s.gI or 0, 0.8) end   -- the pull is over: the power phase's clock
            gas = s.t < P.kickT and 1 or D.gasLaw(s, P, aDeg, dt, 0)  -- no wide cut while the slide builds
            wheel = -a + steerPath - P.kRate * s.daF + P.initSteer * clamp(1 - aDeg / 12, 0, 1)
        end
        if aDeg >= 0.35 * P.angle then s.m, s.t = 2, 0; st.hold = st.hold + 1
        elseif not s.flick and s.t > P.initMax then st.fail = st.fail + 1; release(i, s); return end
    elseif s.m == 2 then                                              -- hold: throttle on the angle, wheels on the line
        gas = D.gasLaw(s, P, aDeg, dt, ePath)
        wheel = -a + steerPath - P.kRate * s.daF
        if aDeg > P.angleMax then gas, wheel = 0, -a - 0.15 end
        st.aSum, st.aT, st.aMax = st.aSum + aDeg * dt, st.aT + dt, max(st.aMax, aDeg)
        if abs(aDeg) < P.lostAngle then s.lostT = (s.lostT or 0) + dt else s.lostT = 0 end
        if s.lostT > P.lostT then s.lostT = 0; st.lost = st.lost + 1; release(i, s); return end   -- the slide is gone: AC drives
        local rem = sg * turnAhead(sp, 0, clamp(spd * 0.7, 10, 30))
        if rem < P.exitTurn * RAD then s.m, s.t = 3, 0 end
    else                                                              -- straighten: ease the throttle, wheels along the travel
        gas = clamp(0.5 - 0.0125 * aDeg, 0.15, 0.8)
        wheel = -a + steerPath - P.kRate * s.daF
        if s.cool <= 0 and abs(far) >= turnIn and abs(near) >= 0.35 * turnIn and far * near > 0 and (far > 0 and 1 or -1) ~= sg then
            s.sg, s.m, s.t, s.flick = -sg, 1, 0, false                -- the next corner turns the other way: swing straight into it
            s.aPrev, s.daF, s.u = nil, 0, 0
            st.trans = st.trans + 1
        elseif abs(aDeg) < P.exitAngle or s.t > P.exitMax then
            st.exit = st.exit + 1; release(i, s); return
        end
    end
    if abs(aDeg) >= 15 then st.slideT = st.slideT + dt end
    st.fr = st.fr + 1
    -- the steering: wanted front-wheel angle (corner sense) -> car.steer degrees -> input
    wheel = clamp(wheel, -P.maxWheel, P.maxWheel)
    local lock = car.steerLock or 0
    if lock < 90 then lock = 450 end
    local want = sg * wheel / s.wpd                                  -- car.steer degrees we want
    local u = clamp(s.kIn * want / lock, -1, 1)
    -- input sign check: a steering wish held one way for 0.6 s that car.steer still points against. The rack lags a quick
    -- counter-steer, so a single disagreeing frame means nothing; P.autoFlip lets a sustained one invert the input.
    if abs(u) > 0.25 and want * (s.want or 0) > 0 then s.kT = (s.kT or 0) + dt else s.kT = 0 end
    if s.kT > 0.6 and abs(car.steer or 0) > 10 then
        if (car.steer or 0) * want > 0 then s.kGood = s.kGood + 1 else s.kBad = s.kBad + 1 end
        if s.kBad >= 15 and s.kGood == 0 then
            st.flip = st.flip + 1; s.kGood, s.kBad = 0, 0
            if P.autoFlip then s.kIn = -s.kIn end
        end
    end
    s.u, s.want = u, want
    local c = ac.overrideCarControls(i)
    if not c then release(i, s); return end
    local okC = pcall(setComb, c, false)
    if not okC then st.noComb = st.noComb + 1; release(i, s); return end
    c.steer, c.gas, c.brake, c.handbrake, c.clutch = u, gas, brake, hb, clutch
    if P.holdGear and s.g0 >= 1 then
        local rpm, lim = car.rpm or 0, car.rpmLimiter or 0
        if lim > 0 and rpm > 0.97 * lim then s.gT = s.gT + dt elseif lim > 0 and rpm < 0.45 * lim then s.gT = s.gT - dt else s.gT = 0 end
        if s.gT > 0.8 then s.g0, s.gT = s.g0 + 1, 0 elseif s.gT < -0.5 and s.g0 > 1 then s.g0, s.gT = s.g0 - 1, 0 end
        c.requestedGearIndex = s.g0
    else
        c.requestedGearIndex = 0
    end
    pcall(physics.setExtraAIGrip, i, (s.m == 1 and P.initGrip > 0 and P.initGrip) or P.grip)
    if D.TRACE then
        s.tr = s.tr + dt
        if s.tr >= 0.2 then
            s.tr = 0
            local w0 = car.wheels[0].look
            local wm = sg * sang(lk.x, lk.y, lk.z, w0.x, w0.y, w0.z, up.x, up.y, up.z) * DEG
            addTrace(string.format('{"ev":"drift","ts":%.2f,"car":%d,"m":%d,"a":%.1f,"da":%.0f,"g":%.2f,"hb":%d,"u":%.2f,"st":%.0f,"w":%.1f,"wt":%.1f,"e":%.1f,"v":%.0f,"gear":%d,"rpm":%.0f,"sp":%.4f,"cal":"%s","kin":%d,"ag":%.2f,"ahb":%.2f,"acl":%.2f}',
                simT(), i, s.m, aDeg, s.daF * DEG, gas, hb, u, car.steer or 0, wm, wheel * DEG, ePath * DEG, v, car.gear or 0, car.rpm or 0, sp, s.cal or '', s.kIn,
                car.gas or -1, car.handbrake or -1, car.clutch or -1))   -- what AC actually applied (CSP smooths AI inputs)
        end
    end
end

local lastOpts = nil
function D.update(dt, opts, on, measure, diagOn)
    if type(opts) == 'table' and opts ~= lastOpts then
        for k, v in pairs(opts) do if D.P[k] ~= nil then D.P[k] = v end end
        lastOpts = opts
    end
    D.ON, D.MEASURE = on == true, measure == true
    if not (D.ON or D.MEASURE) then if D.busy > 0 then D.off() end; return end
    local P = D.P
    scanT = scanT - dt
    if scanT <= 0 then                                               -- no drift car on the grid: nothing below runs
        scanT, anyDrift = 10, P.all == true
        if not anyDrift then
            local sim0 = ac.getSim()
            for j = 0, sim0.carsCount - 1 do if Classes.keyOf(j) == 'drift' then anyDrift = true; break end end
        end
    end
    if not anyDrift then if D.busy > 0 then D.off() end; return end
    D.TRACE = (P.trace == 'auto' and diagOn == true) or P.trace == true
    local t0 = clock()
    if not trk then
        trkWait = trkWait - dt
        if trkWait > 0 then return end
        local t, failed = buildTrack(100)
        if failed then trkWait = 5; return end
        if not t then return end                                       -- still reading the line (a slice per frame)
        trk = t
    end
    local st = D.st
    local sim = ac.getSim()
    CN = sim.carsCount
    for j = 0, CN - 1 do
        local c = ac.getCar(j)
        if c and not c.isInPitlane then local p = c.position; CX[j], CZ[j] = p.x, p.z else CX[j] = nil end
    end
    local busy = 0
    for i = 0, sim.carsCount - 1 do
        local car = ac.getCar(i)
        local s = S[i]
        if car and car.isAIControlled and not car.isInPitlane and not car.isRetired and (P.all or Classes.keyOf(i) == 'drift') then
            local ok, e = pcall(carStep, i, car, dt, P, st)
            s = S[i]
            if not ok then
                D.errN, D.lastErr = D.errN + 1, tostring(e)
                if s and s.m > 0 then release(i, s) end
            end
            if s and s.m > 0 then busy = busy + 1 end
        elseif s and s.m > 0 then
            release(i, s)
        end
    end
    D.busy = busy
    local ms = (clock() - t0) * 1000
    local cp = D.cpu
    cp.n, cp.sum = cp.n + 1, cp.sum + ms
    if ms > cp.max then cp.max = ms end
end

function D.off()
    for i, s in pairs(S) do if s.m > 0 then release(i, s) end end
    D.busy = 0
end

function D.reset()
    D.off()
    S, trk, trkWait, lastOpts, scanT, anyDrift, bld = {}, nil, 0, nil, 0, false, nil
    D.cpu = { n = 0, sum = 0, max = 0 }
    D.st, D.trace, D.traceDrop, D.errN, D.lastErr = newStats(), {}, 0, 0, nil
end

-- diag: the session line's "drift" block, and the trace rows since the last write
function D.statsJson()
    local s = D.st
    local cal = {}
    for i, c in pairs(S) do
        if c.wpd then cal[#cal + 1] = string.format('[%d,"%s",%.5f,%d,%d]', i, c.cal or '', c.wpd, c.kIn, c.wn) end
    end
    return string.format('{"on":%s,"meas":%s,"fr":%d,"ini":%d,"hold":%d,"spin":%d,"fail":%d,"exit":%d,"trans":%d,"snap":%d,"slow":%d,"flip":%d,"traffic":%d,' ..
        '"aMean":%.1f,"aMax":%.1f,"slideT":%.1f,"cornerT":%.1f,"cornerSlideT":%.1f,"offT":%.1f,"noComb":%d,"err":%d,"tDrop":%d,' ..
        '"brakeIn":%.1f,"noAst":%d,"lost":%d,"kickT":%.1f,"cpuN":%d,"cpuAvgMs":%.4f,"cpuMaxMs":%.3f,"cars":%s,"cal":[%s]}',
        tostring(D.ON), tostring(D.MEASURE), s.fr, s.ini, s.hold, s.spin, s.fail, s.exit, s.trans, s.snap, s.slow, s.flip, s.traffic,
        s.aT > 0 and s.aSum / s.aT or 0, s.aMax, s.slideT, s.cornerT, s.cornerSlideT, s.offT, s.noComb, D.errN, D.traceDrop,
        s.brakeIn or 0, s.noAst or 0, s.lost or 0, s.kickT or 0, D.cpu.n, D.cpu.n > 0 and D.cpu.sum / D.cpu.n or 0, D.cpu.max, tostring(anyDrift), table.concat(cal, ','))
end

function D.flush(buf)
    local tr = D.trace
    for k = 1, #tr do buf[#buf + 1] = tr[k] end
    D.trace = {}
end

return D
