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
local R = require('lib.racecraft')

local T = {}
R.COLD_TYRE = 0      -- 0 = off. 0.15 = up to 15 % less assumed tyre grip at full coldness (harness A/B)
R.COLD_SPAN = 40     -- degrees C below optimum for the full effect
R.COLD_LAPS = 2      -- the cut applies only on a session's first COLD_LAPS laps and on an out-lap: tyres cold BY CIRCUMSTANCE.
                     -- Against the data optimum all race it never ended where tyres never reach it - GT3 at Monza runs 72-80 C
                     -- v 85-95 C, so the AI lost ~4 % grip all race (suite rc16a 2026-10-10: top-3 +3.0 s/lap)

local base, cur, outLap = {}, {}, {}   -- per car: its own ai.ini HINT, what we last set (only cars we changed), and the
                                       -- lap count it left the pit lane on (its out-lap runs until the next line crossing)
local acc = 0

function T.update(sim, dt)
    local k = tonumber(R.COLD_TYRE) or 0
    if k <= 0 then
        if next(cur) then      -- switched off mid-session: hand every changed car its own value back, once
            for i, _ in pairs(cur) do if base[i] then pcall(physics.setAITyresHint, i, base[i]) end end
            cur = {}
        end
        return
    end
    acc = acc + (dt or 0)
    if acc < 0.25 then return end              -- 4 Hz: tyre temperature moves slowly
    acc = 0
    local span = math.max(1, tonumber(R.COLD_SPAN) or 40)
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and c.isAIControlled and c.wheels then
            if base[i] == nil then
                base[i] = 1.0
                pcall(function() base[i] = ac.INIConfig.carData(i, 'ai.ini'):get('TYRES', 'HINT', 1.0) end)
            end
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
                local cold = inWindow and math.max(0, math.min(1, (opt - t / n) / span)) or 0   -- outside it: the car's own hint
                local want = base[i] * (1 - k * cold)
                if math.abs(want - (cur[i] or base[i])) > 0.004 then
                    pcall(physics.setAITyresHint, i, want); cur[i] = want
                end
            end
        end
    end
end

-- diag hook: the hint Verve is currently applying to car i (nil = the car's own)
function T.hintOf(i) return cur[i] end

return T
