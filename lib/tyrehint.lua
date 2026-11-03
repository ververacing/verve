-- AI tyre hint on cold tyres (2026-10-10). AC's AI brakes and corners as if its tyres were at operating temperature.
-- On the opening lap and on an out-lap after a stop they are not. (A repositioned car keeps its temperatures: AC
-- resets a teleported car's tyres to ambient, but recovery.lua's applyTemps puts the saved ones back.) PC #2 measured
-- it on the released build: every F2004 that left the track at Imola's Tosa on lap 0 had tyres 32-56 C below optimum
-- (64-83 C against 115-120 C), with Verve on AND off - a reviewer's "half the grid goes off at turn 6, no matter the
-- aggression". Not an Imola rule: it is the tyres.
--
-- CSP exposes the grip the AI assumes, per car and live:
--   physics.setAITyresHint(car, value)     the car's ai.ini [TYRES] HINT
-- R.COLD_TYRE > 0 lowers it in proportion to how cold the tyres are, and hands the car's own value back as they
-- come in:   hint = base * (1 - COLD_TYRE * c),   c = clamp((optimum - core) / COLD_SPAN, 0, 1)
-- Default OFF. The base/apply machinery is the same one the learned pace map will push with later (owner's idea,
-- backlog 2026-10-10 11:50). Lives on the racecraft table so --racecraft {"COLD_TYRE":0.15} reaches it.
--
-- (R.HINT_SHIP, 0.16.x, decisions 47/48) CLEAN-AIR HINT. The same writer also RAISES the hint for GT cars at high
-- levels, and fades it out as the car closes on the one ahead:
--   hint = base * (1 + (mult(level, class) - 1) * f) * (1 - COLD_TYRE * c)
-- mult: 1.0 at a launcher meter <= HINT_RAMP_LO (90), linear to HINT_CLASS[class] (gt 1.2) at 100, then on to
-- HINT_CLASS_TOP (gt 1.3) across 100-120 (a meter above 100, or the Above-expert slider R.HINT_ABOVE for cars whose
-- own level is >= 99.5). Driven by the field-wide METER, not each car's level, so the driver-profile spread moves
-- as one. Only a class from real metadata gets it (Classes.guessed: a physics-guessed 'gt' stays 1.0).
-- f: 0..1 from R.timeGapAhead - full at >= HINT_FAR_S of clear road on my line, none at <= HINT_NEAR_S or alongside
-- anyone; the PLAYER ahead uses the tight HINT_PLAYER_NEAR_S / FAR_S window, so a chasing AI keeps its grip until
-- it is on the human's gearbox. The hint term moves HINT_RATE per 1 Hz tick and is re-asserted every second while
-- mult > 1: exactly the cadence of the diag rows that tested it (AB_5arm, HH_fadedA 2026-10-31).
-- Measured (spa12, 18 GT3, level 100, n=4): faded x1.2 med-best -3.9 s vs x1.0, h40 8 vs 6, incidents 16.2 vs 20.2;
-- plain x1.1 -3.65 s, h40 16. SF70H fails at x1.05+ (F1 sgfnk 2026-10-31): formula stays 1.0.
local R = require('lib.racecraft')
local Classes = require('lib.classes')
local Career = require('lib.career')
local Difficulty = require('lib.difficulty')

local T = {}
R.COLD_TYRE = 0      -- 0 = off. 0.15 = up to 15 % less assumed tyre grip at full coldness (harness A/B)
R.COLD_SPAN = 40     -- degrees C below optimum for the full effect
R.COLD_LAPS = 2      -- the cut applies only on a session's first COLD_LAPS laps and on an out-lap: tyres cold BY CIRCUMSTANCE.
                     -- Against the data optimum all race it never ended where tyres never reach it - GT3 at Monza runs 72-80 C
                     -- v 85-95 C, so the AI lost ~4 % grip all race (suite rc16a 2026-10-10: top-3 +3.0 s/lap)
R.HINT_SHIP = true   -- DEFAULT 0.16.x (decisions 47/48): the clean-air hint above. false = today's writes exactly
R.HINT_CLASS = { gt = 1.2 }       -- mult at meter 100, per class key; a class not listed stays 1.0 (formula FAILED 2026-10-31)
R.HINT_CLASS_TOP = { gt = 1.3 }   -- mult at hint level 120 (the top of the Above-expert range)
R.HINT_RAMP_LO = 90  -- meter at or below this: 1.0 ("95 means 95": the hint must not make a low level secretly fast)
R.HINT_ABOVE = 100   -- the Above-expert slider (Verve.lua sets it from G.aboveExpert every frame); 100 = off
R.HINT_NEAR_S = 1.0  -- fade window to an AI car ahead on my line (s): f = 0 at or under NEAR, 1 at or over FAR
R.HINT_FAR_S = 2.0
R.HINT_PLAYER_NEAR_S = 0.3   -- the same, to the PLAYER ahead (verve-47 2026-10-31; untested - its own suite cell)
R.HINT_PLAYER_FAR_S = 0.8
R.HINT_FADE = 'gap'  -- (TP 2026-11-01, DESIGN_hint016_tp) the AI-ahead fade: 'gap' = NEAR/FAR on the time gap (as shipped);
                     -- 'ttc' = HINT_TTC_LO/HI on the time to contact (R.timeGapAhead's 4th value), so a steady follower keeps the hint
R.HINT_FLOOR = 0     -- (TP) the AI-ahead f never goes under this (0 = as shipped). The player window and alongside are not floored
R.HINT_TTC_LO = 1.5; R.HINT_TTC_HI = 3.0
R.HINT_TTC_NEAR_S = 0.3; R.HINT_TTC_FAR_S = 0.6   -- (audit C4) 'ttc' mode also caps f by this short time-gap window
R.HINT_RATE_DOWN = 0.10; R.HINT_RATE_UP = 0.02   -- (TP) 'ttc' only: the hint term's fall / rise per 1 Hz tick ('gap' keeps HINT_RATE both ways)
R.HINT_RATE = 0.02   -- the hint term (1 + (mult - 1) * f) moves at most this much per 1 Hz tick
R.TYRE_HINT_FORCE = nil   -- harness: a number replaces mult() for every AI car (ladders on the shipped code)

local base, cur, outLap = {}, {}, {}   -- per car: its own ai.ini HINT, what we last set (only cars we changed), and the
                                       -- lap count it left the pit lane on (its out-lap runs until the next line crossing)
local hMul, hF, hTerm = {}, {}, {}     -- per car (HINT_SHIP): mult, the fade target f, and the slewed applied term
local hA, hP, hS, hT = {}, {}, {}, {}  -- per car: the gaps f was computed from (AI ahead s, player ahead s, alongside, TTC s), for diag
local acc, tick = 0, 0

local function fwin(t, near, far)
    if far <= near then far = near + 0.01 end
    local f = (t - near) / (far - near)
    if f < 0 then return 0 elseif f > 1 then return 1 end
    return f
end

-- the clean-air mult for car i this second (1.0 = no hint)
local function multFor(i)
    local force = tonumber(R.TYRE_HINT_FORCE)
    if force then return force end
    if not Classes.hintEligible(i) then return 1.0 end   -- (audit R2) an exact 'gt3' tag or a user class override; else untested
    local key = Classes.keyOf(i)
    local top = R.HINT_CLASS[key]
    if not top then return 1.0 end
    local meter = tonumber(Career.meter)
    if not meter then return 1.0 end           -- level unknown: Verve stands down (as difficulty.lua does)
    local above = tonumber(R.HINT_ABOVE) or 100
    local hl
    if Career.active and Difficulty.CAREER_CURVE then
        -- (0.16.2) CAREER: the hint follows the FIELD's career base level (how far into the career the event is),
        -- not the launcher meter, so an early event low on the ramp is not given the full clean-air hint. Above-expert
        -- is field-wide here (the base is field-wide), so no per-car own >= 99.5 test.
        local base = Difficulty.careerBase(i)
        if not base then return 1.0 end
        hl = base * 100
        if above > 100 then hl = hl + (above - 100) end
    else
        -- outside career: unchanged from 0.16.1 (rc018 evidence). The meter is the truth; Above-expert only lifts a car
        -- already at the top of the slider.
        hl = meter
        if above > 100 then
            local own = Difficulty.levelFor(i) or Difficulty.stockLevel(i)
            if own and own * 100 >= 99.5 then hl = hl + (above - 100) end
        end
    end
    local lo = tonumber(R.HINT_RAMP_LO) or 90
    if hl <= lo then return 1.0 end
    if hl <= 100 then return 1 + (top - 1) * (hl - lo) / math.max(1, 100 - lo) end
    local hi = R.HINT_CLASS_TOP[key] or top
    return top + (hi - top) * math.min(1, (hl - 100) / 20)
end

-- switched off mid-session (the levers, or Verve itself - Verve.lua's off path calls this): hand every changed car its
-- own value back, once
function T.offTick()
    if next(cur) then
        for i, _ in pairs(cur) do if base[i] then pcall(physics.setAITyresHint, i, base[i]) end end
        cur = {}
    end
    if next(hTerm) then hMul, hF, hTerm, hA, hP, hS, hT = {}, {}, {}, {}, {}, {}, {} end
end

-- (audit A3) a new session: hand any changed car back, then forget every per-car value (keyed by car index, which a
-- new session can reuse for a different car); base is re-read from that car's own ai.ini on its first tick
function T.reset()
    T.offTick()
    base, outLap = {}, {}
    acc, tick = 0, 0
end

function T.update(sim, dt)
    local k = tonumber(R.COLD_TYRE) or 0
    local ship = R.HINT_SHIP == true
    if k <= 0 and not ship then T.offTick(); return end
    acc = acc + (dt or 0)
    if acc < 0.25 then return end              -- 4 Hz: tyre temperature moves slowly
    acc = 0
    tick = tick + 1
    local hintTick = tick % 4 == 0             -- 1 Hz: the fade's cadence
    local span = math.max(1, tonumber(R.COLD_SPAN) or 40)
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and c.isAIControlled and c.isRaceFinished then
            -- (0.16.1, CSP cooldown lap) past the flag: the car's own hint back once, then nothing more is written to it
            if cur[i] and base[i] then pcall(physics.setAITyresHint, i, base[i]) end
            cur[i] = nil; hMul[i], hF[i], hTerm[i], hA[i], hP[i], hS[i], hT[i] = nil, nil, nil, nil, nil, nil, nil
        elseif c and c.isAIControlled and c.wheels then
            if base[i] == nil then
                base[i] = 1.0
                pcall(function() base[i] = ac.INIConfig.carData(i, 'ai.ini'):get('TYRES', 'HINT', 1.0) end)
            end
            local cold = 0
            if k > 0 then
                -- (R.COLD_LAPS) the window: the opening laps, or an out-lap (set every tick in the pit lane, so it holds the lap
                -- count the car rejoins on; a count that went backwards is a new session and clears it)
                local lapN = c.lapCount or 0
                if c.isInPitlane then outLap[i] = lapN elseif outLap[i] and (lapN > outLap[i] or lapN < outLap[i] - 1) then outLap[i] = nil end
                local inWindow = lapN < (tonumber(R.COLD_LAPS) or 2) or outLap[i] ~= nil
                local t, n, opt = 0, 0, 0
                for w = 0, 3 do
                    local wh = c.wheels[w]
                    if wh and type(wh.tyreCoreTemperature) == 'number' then
                        t = t + wh.tyreCoreTemperature; n = n + 1
                        if (wh.tyreOptimumTemperature or 0) > opt then opt = wh.tyreOptimumTemperature end
                    end
                end
                if n > 0 and opt > 0 then
                    cold = inWindow and math.max(0, math.min(1, (opt - t / n) / span)) or 0   -- outside it: the car's own hint
                end
            end
            local push = false
            if hintTick then
                -- never the player's car (car 0), even on the harness autopilot, where it reads isAIControlled (smoke sm16 2026-10-31)
                local m = (ship and i ~= 0) and multFor(i) or 1.0
                if m > 1.0005 then
                    local tA, tP, side, ttc = R.timeGapAhead(i)
                    local f = 0
                    if not side then
                        if R.HINT_FADE == 'ttc' then f = fwin(ttc or 1e9, tonumber(R.HINT_TTC_LO) or 1.5, tonumber(R.HINT_TTC_HI) or 3.0)
                            -- (audit C4) and never right on a gearbox: at equal speed 1.5 m back reads ttc 3 s = f 1, so cap with a short time gap
                            f = math.min(f, fwin(tA, tonumber(R.HINT_TTC_NEAR_S) or 0.3, tonumber(R.HINT_TTC_FAR_S) or 0.6))
                        else f = fwin(tA, R.HINT_NEAR_S, R.HINT_FAR_S) end
                        local fl = tonumber(R.HINT_FLOOR) or 0
                        if f < fl then f = fl end                  -- (TP) the AI-ahead floor, before the player cap
                        local fp = fwin(tP, R.HINT_PLAYER_NEAR_S, R.HINT_PLAYER_FAR_S)
                        if fp < f then f = fp end
                    end
                    -- slewed in HINT units (as tested: the applied hint moved <= 0.02 a second, so 1.0 -> 1.2 takes 10 s)
                    local goal = 1 + (m - 1) * f
                    local h = hTerm[i] or 1                -- start from stock, ramp up
                    local rate = tonumber(R.HINT_RATE) or 0.02
                    local up, down = rate, rate
                    if R.HINT_FADE == 'ttc' then          -- (TP, verve-47) a closing event lasts 1-2 s: fade fast, recover slowly
                        up, down = tonumber(R.HINT_RATE_UP) or rate, tonumber(R.HINT_RATE_DOWN) or rate
                    end
                    if h < goal then h = math.min(h + up, goal) elseif h > goal then h = math.max(h - down, goal) end
                    hMul[i], hF[i], hTerm[i] = m, f, h
                    hA[i], hP[i], hS[i], hT[i] = tA, tP, side, ttc
                    push = true                            -- re-assert every second: CSP can reset a hint
                elseif hTerm[i] then
                    hMul[i], hF[i], hTerm[i], hA[i], hP[i], hS[i], hT[i] = nil, nil, nil, nil, nil, nil, nil
                end
            end
            local want = base[i] * (hTerm[i] or 1) * (1 - k * cold)
            if push or math.abs(want - (cur[i] or base[i])) > 0.004 then
                pcall(physics.setAITyresHint, i, want); cur[i] = want
            end
        end
    end
end

-- diag hooks: the hint Verve is currently applying to car i (nil = the car's own), and the clean-air parts of it
function T.hintOf(i) return cur[i] end
function T.fadeOf(i) return hF[i], hMul[i], hA[i], hP[i], hS[i], hT[i] end

return T
