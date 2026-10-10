-- AI tyre hint on cold tyres (2026-10-10). AC's AI brakes and corners as if its tyres were at operating temperature.
-- On the opening lap, an out-lap after a stop, and after a reposition (AC resets a teleported car's tyres to ambient,
-- see recovery.lua) they are not. PC #2 measured it on the released build: every F2004 that left the track at
-- Imola's Tosa on lap 0 had tyres 32-56 C below optimum (64-83 C against 115-120 C), with Verve on AND off - a
-- reviewer's "half the grid goes off at turn 6, no matter the aggression". Not an Imola rule: it is the tyres.
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

local base, cur = {}, {}   -- per car: its own ai.ini HINT, and what we last set (only cars we changed)
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
            local t, n, opt = 0, 0, 0
            for w = 0, 3 do
                local wh = c.wheels[w]
                if wh and type(wh.tyreCoreTemperature) == 'number' then
                    t = t + wh.tyreCoreTemperature; n = n + 1
                    if (wh.tyreOptimumTemperature or 0) > opt then opt = wh.tyreOptimumTemperature end
                end
            end
            if n > 0 and opt > 0 then
                local cold = math.max(0, math.min(1, (opt - t / n) / span))
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
