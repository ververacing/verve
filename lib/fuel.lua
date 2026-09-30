-- lib/fuel.lua -- TIMED RACES: AC fuels its AI for 1.2 laps, then empties the tank at every stop. Switch G.timedFuel
-- (default ON since 0.14.6; harness: --settings {"timedFuel":false} to compare).
--
-- What AC does, read from its own log.txt (harness races, 2026-09-26):
--   * as a race session starts, each AI car is fuelled for ([SESSION_n] LAPS + 1) x 1.2 x its fuel per lap ('Race
--     strategy ... race laps:0', 'setting fuel for 1 laps, with mult=1.200000'). A timed race has LAPS=0, so the whole
--     field starts on 1.2 laps. [RACE] RACE_LAPS and VIRTUAL_LAPS play no part in it.
--   * at an AI stop AC SETS the tank to (LAPS - completed + 1) x 1.2 x fuel per lap, which is 0 L in a timed race
--     ('Putting fuel for 0 laps' on lap 1, '-1 laps' on lap 2, each 'filled to 0.000000 L'). The car cannot leave,
--     asks for another stop, and loops: 276 'AI RACE PITSTOP' lines in a 10-minute Spa race. Recovery's box-limbo
--     rescue never fired on it (boxTryN 0).
--   * in a weekend AC applies the race load again as the race session begins, so one write is not enough.
--
-- What this does - only in an offline, non-replay RACE session that is TIMED, with fuel consumption on, and only to
-- cars the AI drives (car 0 only while the autopilot or AC's AI has it; a human's car is never touched):
--   A. GREEN LOAD: from the session start until F.GREEN_S after the green, each tank is held at or above
--      min(maxFuel, (laps + 1) x 1.2 x fuel per lap), laps = ceil(duration / a deliberately FAST lap) (+1 with the
--      additional lap), and AC's laps-before-pitting (car.aiLapsLeft) is raised to what that tank covers: AC planned
--      a 1-lap race, and a car still on that plan comes in after lap 1 whatever it carries. Fuel is never lowered.
--   B. BOX GUARD: after that, an AI car stopped in the pit lane with less than the rest of the race + 1 lap in its
--      tank gets it (capped at maxFuel), its laps-before-pitting set to what that covers and its pit request cleared,
--      so it drives out instead of looping. Once the clock is out a car still racing gets its last lap(s): a stop then
--      (AC's damage-pit teleport, a tank maxFuel capped) is emptied the same way. Repeated every F.BOX_GAP_S while AC
--      keeps emptying it, within F.BOX_HOLD_S of the car stopping or of AC last emptying its tank: every emptying is
--      a new AC stop and opens a new window, since AC's repeated stops also keep resetting recovery's box-limbo timer
--      (it never took over: boxTryN 0), so a window that closed for good would strand the car. Never a car Verve retired.
-- The fast lap is the quickest of: the car's best lap in an earlier session of the weekend, its best lap in this
-- race, and the track length at its class's F.SPEED - an error means more laps, so more fuel, never a dry tank.
-- Fuel per lap is AC's own estimate (car.fuelPerLap); before AC has one, the load AC gave the car / 1.2 (AC's formula
-- for a 0-lap race; capped at twice the class figure, since a practice-length load is not one lap's worth); with no
-- load either, F.LPKM for the class x F.LPKM_MARGIN. Car 0 always takes the class figure: AC's 1.2-lap race load is
-- the AI's only, so the autopilot's tank still holds the launcher/setup load, which is not a lap's worth of anything.
-- Cost: none with the switch off (Verve.lua does not call it); on, outside a timed race, one session check at 4 Hz.

local Classes  = require('lib.classes')
local Recovery = require('lib.recovery')   -- stateOf(i).parked: never refuel a car Verve retired (recovery needs neither module)

local F = {}
F.MULT         = 1.2      -- AC's own margin: (laps + 1) x MULT x fuel per lap
F.GREEN_S      = 10.0     -- the green load is held until this long after the green (AC re-applies its own at the start)
F.TICK_S       = 0.25     -- work at 4 Hz, not every frame
F.SLACK_L      = 1.0      -- write only when a tank is this far under its target (a held tank burns: no write per frame)
F.STOP_KMH     = 2.0      -- "stopped" in the pit lane
F.BOX_GAP_S    = 3.0      -- seconds between two top-ups of the same car (AC emptied it again)
F.BOX_HOLD_S   = 60.0     -- top-ups this long after a car stops or AC empties its tank again (AC's stop takes ~20 s)
F.REEMPTY      = 0.5      -- a stopped car's tank below this share of the most it held since its window opened: AC emptied it
F.MIN_LAP_S    = 20.0     -- floor on the lap estimate (a wrong track length cannot ask for a thousand laps)
F.SPEED = { gt = 190, formula = 250, formula_jr = 210, prototype = 210, hypercar = 210, touring = 175, road = 165,
            nascar = 300, kart = 100 }   -- km/h: a FAST average lap per class (too fast = more laps = more fuel)
F.SPEED_DEFAULT = 190     -- any other class (vintage, rally, drift): GT pace, quicker than all of them
F.LPKM = { gt = 0.60, formula = 0.60, prototype = 0.65, hypercar = 0.65, touring = 0.50, road = 0.45, nascar = 0.80,
           kart = 0.15 }                 -- litres per km, only when AC has no estimate and no load to read
F.LPKM_DEFAULT = 0.60
F.LPKM_MARGIN  = 1.15
F.loadN, F.boxFixN, F.boxReN = 0, 0, 0   -- session tallies for the diagnostics (fuelLoadN: green-load writes; fuelBoxN:
                                         -- pit visits fixed; fuelReN: AC emptied a tank again after a top-up, same visit)
F.active = false          -- this session is one the switch acts in
-- (0.15, player-settings check 2026-09-29) FUEL RATE: AC fuels its AI - and refills it at a stop - with its own litres per lap, which
-- ignore the launcher's fuel-rate multiplier. At rate 3 an 8-lap Monza race started on 37.6 L burning 8.5 L a lap: every car made
-- 3-4 stops. F.RATE_LAPPED: in a LAPPED race with fuel rate > 1, the same green load and box guard as a timed race, with the laps
-- from the session. In both kinds the litres per lap are x the fuel rate (1 = no change).
F.RATE_LAPPED = true

local st = {}             -- per-session state (F.reset)

function F.reset()
    st = { now = 0, tick = 0, sawPre = false, greenT = nil, doneA = false, fpl = {}, prevBest = nil, visit = {},
           fuelOnT = -1e9, fuelOn = true, lo = nil, hi = nil, laps = 0, rate = 1, mode = nil, lapsRace = 0 }
    F.loadN, F.boxFixN, F.boxReN, F.active = 0, 0, 0, false
end
F.reset()

local function getf(o, k) return o[k] end
local function field(o, k)                        -- a newer CSP field, read without erroring on an older build
    local ok, v = pcall(getf, o, k)
    if ok and type(v) == 'number' then return v end
    return nil
end

-- The current session if it is a TIMED race (a duration, no lap count), else nil. Verve.lua's harness code uses it too.
function F.timedSession(sim)
    local ss = nil
    pcall(function()
        if sim.raceSessionType ~= ac.SessionType.Race then return end
        local s = ac.getSession(sim.currentSessionIndex or 0)
        if s and (s.durationMinutes or 0) > 0 and (s.isTimedRace == true or (s.laps or 0) == 0) then ss = s end
    end)
    return ss
end

local function lappedSession(sim)                 -- (F.RATE_LAPPED) the current session if it is a LAPPED race
    local ss = nil
    pcall(function()
        if sim.raceSessionType ~= ac.SessionType.Race then return end
        local s = ac.getSession(sim.currentSessionIndex or 0)
        if s and (s.laps or 0) > 0 and s.isTimedRace ~= true then ss = s end
    end)
    return ss
end

local function gate(sim)
    if sim.isOnlineRace or sim.isReplayOnlyMode then return nil end
    if st.now - st.fuelOnT > 10 then              -- fuel consumption off: nothing burns (re-read now and then: menu-editable)
        st.fuelOnT = st.now
        local on, rate = true, 1
        pcall(function() local a = ac.getAssists(); if a and type(a.fuelRate) == 'number' then on = a.fuelRate > 0; rate = a.fuelRate end end)
        st.fuelOn, st.rate = on, math.max(1, rate)
    end
    if not st.fuelOn then return nil end
    local ss = F.timedSession(sim)
    if ss then st.mode = 'timed'; return ss end
    if F.RATE_LAPPED and st.rate > 1 then ss = lappedSession(sim); if ss then st.mode = 'lapped'; st.lapsRace = ss.laps or 0; return ss end end
    return nil
end

local function eligible(car) return car ~= nil and car.isAIControlled == true and not car.isRemote end

-- best lap (ms) per car index over the EARLIER sessions of this weekend (their leaderboards); {} in a single race
local function earlierBests(sim)
    local best = {}
    pcall(function()
        for k = 0, (sim.currentSessionIndex or 0) - 1 do
            local s = ac.getSession(k)
            local lb = s and s.leaderboard
            if lb then
                for n = 0, #lb do                      -- (0-based; one extra index reads nil either way #lb counts)
                    local e = lb[n]
                    local ms = e and e.bestLapTimeMs
                    local ci = e and e.car and e.car.index
                    if type(ci) == 'number' and type(ms) == 'number' and ms > 0 and (best[ci] == nil or ms < best[ci]) then best[ci] = ms end
                end
            end
        end
    end)
    return best
end

local function lapEst(i, car, trackM)                -- seconds, deliberately fast
    local est = trackM / ((F.SPEED[Classes.keyOf(i)] or F.SPEED_DEFAULT) / 3.6)
    local b = st.prevBest and st.prevBest[i]
    if b and b / 1000 < est then est = b / 1000 end
    local own = car.bestLapTimeMs
    if type(own) == 'number' and own > 0 and own / 1000 < est then est = own / 1000 end
    return math.max(est, F.MIN_LAP_S)
end

local fplBase
local function fplOf(i, car, trackM)                 -- litres per lap, at the launcher's fuel rate (AC's own figures ignore it)
    return fplBase(i, car, trackM) * (st.rate or 1)
end
fplBase = function(i, car, trackM)
    local f = field(car, 'fuelPerLap')
    if f and f > 0 then st.fpl[i] = f; return f end
    if st.fpl[i] then return st.fpl[i] end           -- first reading kept: our own top-ups must not feed back into it
    local cls = (F.LPKM[Classes.keyOf(i)] or F.LPKM_DEFAULT) * F.LPKM_MARGIN * trackM / 1000
    local loaded = car.fuel or 0
    local div = (st.mode == 'lapped') and F.MULT * ((st.lapsRace or 0) + 1) or F.MULT   -- (review) a lapped race's AC load is (LAPS+1) x 1.2 laps
    f = (loaded > 0 and i ~= 0) and math.min(loaded / div, 2 * cls) or cls   -- (car 0: never AC's race load)
    st.fpl[i] = f
    return f
end

local function tankFor(car, laps, fpl)
    local t = (laps + 1) * F.MULT * fpl
    local mx = car.maxFuel or 0
    if mx > 0 and t > mx then t = mx end
    return t
end

local function lapsCovered(fuel, fpl, cap)            -- laps a tank covers at AC's margin, 1..cap
    local n = math.floor(fuel / (F.MULT * fpl))
    if n > cap then n = cap end
    return n < 1 and 1 or n
end

local function greenLoad(sim, ss, trackM)
    local dur, extra = (ss.durationMinutes or 0) * 60, ss.hasAdditionalLap and 1 or 0
    for i = 0, sim.carsCount - 1 do
        local car = ac.getCar(i)
        if eligible(car) then
            local fpl = fplOf(i, car, trackM)
            local laps = (st.mode == 'lapped') and ((ss.laps or 0) + extra) or (math.ceil(dur / lapEst(i, car, trackM)) + extra)
            local target = tankFor(car, laps, fpl)
            local fuel = car.fuel or 0
            if fuel + F.SLACK_L < target and pcall(physics.setCarFuel, i, target) then
                F.loadN = F.loadN + 1; fuel = target
                st.lo = math.min(st.lo or target, target); st.hi = math.max(st.hi or target, target)
                if laps > st.laps then st.laps = laps end
            end
            local want = lapsCovered(fuel, fpl, laps + 1)
            local left = field(car, 'aiLapsLeft')
            if left == nil or left < want then pcall(physics.setAILapsToComplete, i, want) end   -- only ever raised
        end
    end
end

local function boxGuard(sim, ss, trackM)
    local dur = (ss.durationMinutes or 0) * 60
    local left = (sim.sessionTimeLeft or 0) / 1000
    if left <= 0 or left > dur + 120 then left = dur - (st.greenT or 0) end
    if left < 0 then left = 0 end                    -- the clock is out: a car still racing needs its last lap(s) (+extra, +1)
    local extra = ss.hasAdditionalLap and 1 or 0
    for i = 0, sim.carsCount - 1 do
        local car = ac.getCar(i)
        if car and car.isInPitlane then
            if (car.speedKmh or 0) < F.STOP_KMH and eligible(car) and not car.isRaceFinished and not car.isRetired then
                local v = st.visit[i]
                local fuel = car.fuel or 0
                if not v then v = { t0 = st.now, last = -1e9, fixed = false, hi = fuel }; st.visit[i] = v end
                if fuel > v.hi then v.hi = fuel end
                if v.hi > F.SLACK_L and fuel < F.REEMPTY * v.hi then  -- AC's stop emptied it (a parked car burns nothing):
                    v.t0 = st.now; v.hi = fuel                        -- a new stop, a new window
                    if v.fixed then F.boxReN = F.boxReN + 1 end       -- (again, after a top-up: the loop)
                end
                local fpl = fplOf(i, car, trackM)
                local laps = (st.mode == 'lapped') and (math.max(0, (ss.laps or 0) - (car.lapCount or 0)) + extra)
                    or (math.ceil(left / lapEst(i, car, trackM)) + extra)
                local target = tankFor(car, laps, fpl)
                if fuel + F.SLACK_L < target and st.now - v.t0 < F.BOX_HOLD_S and st.now - v.last >= F.BOX_GAP_S then
                    local rs = Recovery.stateOf(i)
                    if not (rs and rs.parked) then
                        v.last = st.now
                        local want = lapsCovered(target, fpl, laps + 1)
                        if pcall(physics.setCarFuel, i, target) and target > v.hi then v.hi = target end
                        pcall(physics.setAILapsToComplete, i, want)
                        pcall(physics.setAIPitStopRequest, i, false)   -- (else it asks for the next stop from its box)
                        if not v.fixed then
                            v.fixed = true; F.boxFixN = F.boxFixN + 1
                            pcall(function() ac.log(string.format('Verve fuel: car %d stopped in the pits on %.1f L with %.0f s to go: %.1f L, %d laps to its next stop', i, fuel, left, target, want)) end)
                        end
                    end
                end
            end
        elseif st.visit[i] then
            st.visit[i] = nil                            -- out of the pit lane: the next visit starts fresh
        end
    end
end

function F.update(sim, dt)
    dt = dt or 0
    st.now = st.now + dt
    if not sim.isSessionStarted then st.sawPre = true; st.greenT = nil      -- before the green (grid, countdown)
    elseif st.sawPre then st.greenT = (st.greenT or 0) + dt end             -- (loaded mid-race: no green load, box guard only)
    st.tick = st.tick + dt
    if st.tick < F.TICK_S then return end
    st.tick = 0
    local ss = gate(sim)
    F.active = ss ~= nil
    if not ss then return end
    local trackM = sim.trackLengthM or 0
    if trackM < 100 then trackM = 5000 end
    if st.sawPre and (st.greenT or 0) < F.GREEN_S then
        if not st.prevBest then st.prevBest = earlierBests(sim) end
        greenLoad(sim, ss, trackM)
    elseif sim.isSessionStarted then
        if st.sawPre and not st.doneA then
            st.doneA = true
            pcall(function() ac.log(string.format('Verve fuel: %s race (%.0f min / %d laps, fuel rate %.1f): %d green loads written (%.1f-%.1f L, up to %d laps)',
                st.mode or '?', ss.durationMinutes or 0, ss.laps or 0, st.rate or 1, F.loadN, st.lo or 0, st.hi or 0, st.laps)) end)
        end
        if st.mode ~= 'lapped' then boxGuard(sim, ss, trackM) end   -- (review) lapped: AC refills a positive amount; the guard was built for its 0 L loop
    end
end

return F
