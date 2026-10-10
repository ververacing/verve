-- AI battery deployment: MGU-K delivery and recovery for AI hybrid cars (2026-10-10, owner: "get that battery
-- deployment figured out" before the Singapore GP; reviewer 8 Oct: "MGU-K compatibility").
--
-- AC's AI starts in one delivery program and never manages the battery the way a driver does: it does not save
-- where saving is cheap, spend where spending pays, or spend to make or stop a pass. CSP exposes per-car control
-- that works on AI cars (the ac.* versions take no index and are player-only):
--   physics.setMGUKDelivery(car, program)   program 0 .. mgukDeliveryCount-1
--   physics.setMGUKRecovery(car, level)     0 .. 10
-- and readable state: mgukDelivery, mgukDeliveryCount, mgukRecovery, kersCharge (0..1), and
-- ac.getMGUKDeliveryName(car, program) for the program names. diag.lua logs all of it per car (kc/dl/dn/mr in
-- every snapshot, plus one "ers" event per hybrid with its program names) so the ranking below can be checked
-- against what the cars actually ship.
--
-- HARNESS SWITCH FIRST - R.ERS_MODE, default 'off' = AC decides, exactly as before this file existed:
--   'max'    every AI hybrid in its most aggressive program all race. A direction test: is there pace in it at
--            all, and does the battery last? Not a candidate default.
--   'race'   every AI hybrid in its sustainable RACE program (Balanced high / HIGH) all race - the probe found
--            every AI car parked in a LOW program (SF70H and RSS 'Balanced low', VRC 'LOW'), so this alone may be
--            most of the gap.
--   'smart'  'race' plus spend and save:
--              battery below R.ERS_LO                           -> the FLOOR (Charging / NODEPLOY)
--              opening lap, or attacking / defending (Verve)    -> ATTACK (Overtake where the car has one)
--              otherwise                                        -> RACE
--            with R.ERS_HOLD seconds between changes so a car never flickers between programs.
-- Program ranking is by NAME when every program on the car has a recognisable name, else by INDEX (last = most
-- aggressive, the usual convention in car mods).
-- The switches live on the racecraft table so --racecraft {"ERS_MODE":"smart"} reaches them with no harness change.
local R = require('lib.racecraft')
local Recovery = require('lib.recovery')

local E = {}
R.ERS_MODE = 'off'   -- 'off' | 'race' | 'smart' | 'max'   (harness A/B; default off)
R.ERS_LO = 0.20      -- 'smart': below this battery fraction, drop to the most conservative program
R.ERS_HOLD = 2.0     -- s: minimum time between program changes on one car
R.ERS_REC = -1       -- >= 0: force MGU-K recovery 0-10 on every AI hybrid (-1 = leave the car's own)
R.ERS_SPLIT = 0      -- 1: only ODD-indexed AI cars get ERS_MODE; even ones keep AC's program as a same-race control
                     -- (race-to-race noise is ~0.4 s at the front, larger than the effect being looked for)

local info = {}      -- [car] = false (no programs to choose) | { id, n, hi, lo, def, t, byName }
local acc = 0

local function score(name)
    -- Names seen in the probe (2026-10-10): SF70H Charging / Balanced low / Balanced high / Linear / Overtake /
    -- Top Speed / Hotlap; RSS Formula Hybrid 2020 the same without Linear; VRC Formula Alpha 2026 LOW / MEDIUM / HIGH
    -- / NODEPLOY. Order of the tests matters: "Balanced low" must read as low, "NODEPLOY" as none.
    local n = string.lower(tostring(name or ''))
    if n == '' then return nil end
    if n:find('nodeploy') or n:find('no deploy') or n:find('no%-deploy') or n:find('none') or n:find('zero')
       or n:find('charg') or n:find('harvest') or n:find('build') then return 0 end
    if n:find('low') or n:find('save') or n:find('eco') then return 1 end
    if n:find('linear') or n:find('bal') or n:find('med') or n:find('norm') or n:find('stand') or n:find('race') or n:find('default') then
        if n:find('high') then return 3 end
        return 2
    end
    if n:find('high') or n:find('push') then return 3 end
    if n:find('overtake') or n:find('attack') or n:find('boost') then return 4 end
    if n:find('top') or n:find('hot') or n:find('qual') or n:find('max') or n:find('full') then return 5 end
    return nil
end

local function study(i, c, id)
    local n = c.mgukDeliveryCount or 0
    if n < 2 then info[i] = false; return false end
    local sc, all = {}, true
    for p = 0, n - 1 do
        local nm; pcall(function() nm = ac.getMGUKDeliveryName(i, p) end)
        sc[p] = score(nm); if sc[p] == nil then all = false end
    end
    -- three roles, not one high/low: a sustainable RACE program, an ATTACK program for passes, the FLOOR for a flat
    -- battery, plus TOP (the most extreme) for the 'max' direction test. By index when the names do not all read.
    local race, atk, lo, top = math.max(0, n - 2), n - 1, 0, n - 1
    if all then
        local best = -1; for p = 0, n - 1 do if sc[p] > best then best = sc[p] end end
        local floor = 99; for p = 0, n - 1 do if sc[p] < floor then floor = sc[p] end end
        top = 0; for p = 0, n - 1 do if sc[p] >= sc[top] then top = p end end              -- last of the best
        atk = nil; for p = 0, n - 1 do if sc[p] == 4 then atk = p; break end end             -- Overtake if the car has one
        if not atk then atk = top end
        lo = nil; for p = 0, n - 1 do if sc[p] == floor then lo = p; break end end
        race = nil; for p = n - 1, 0, -1 do if sc[p] == 3 then race = p; break end end       -- Balanced high / HIGH
        if not race then race = c.mgukDelivery or 0 end
    end
    local f = { id = id, n = n, race = race, atk = atk, lo = lo, top = top, def = c.mgukDelivery or 0, t = -1e9, byName = all }
    info[i] = f
    return f
end

function E.update(sim, dt)
    local mode = R.ERS_MODE
    local deliver = (mode == 'max' or mode == 'smart' or mode == 'race')
    local rl = tonumber(R.ERS_REC) or -1
    if not deliver and rl < 0 then return end
    acc = acc + (dt or 0)
    if acc < 0.25 then return end                  -- 4 Hz is plenty for a program choice
    acc = 0
    local now = os.clock()
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and c.isAIControlled and not c.isInPitlane and not ((tonumber(R.ERS_SPLIT) or 0) > 0 and i % 2 == 0) then
            local id = ''; pcall(function() id = ac.getCarID(i) or '' end)
            local f = info[i]
            if f == nil or (f and f.id ~= id) then f = study(i, c, id) end
            if f then
                if deliver then
                    local want = f.def
                    if mode == 'max' then
                        want = f.top
                    elseif mode == 'race' then
                        want = f.race
                    else
                        local st = (R.last and R.last[i] and R.last[i].state) or 0
                        if (c.kersCharge or 1) < (tonumber(R.ERS_LO) or 0.2) then want = f.lo
                        elseif (c.lapCount or 0) < 1 or st == 1 or st == 2 then want = f.atk
                        else want = f.race end
                    end
                    local rec = false
                    pcall(function() rec = (Recovery.stateOf(i) or {}).rec end)
                    if rec then want = f.def end           -- a car Verve is recovering keeps its own program
                    if want ~= c.mgukDelivery and now - f.t >= (tonumber(R.ERS_HOLD) or 2) then
                        pcall(physics.setMGUKDelivery, i, want); f.t = now
                    end
                end
                if rl >= 0 and c.mgukRecovery ~= math.floor(rl) then pcall(physics.setMGUKRecovery, i, math.floor(rl)) end
            end
        end
    end
end

return E
