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
--   'smart'  spend when it pays and the battery can afford it, save when it cannot:
--              battery below R.ERS_LO                           -> the most conservative program
--              opening lap, or attacking / defending (Verve)    -> the most aggressive program
--              otherwise                                        -> the program the car started in
--            with R.ERS_HOLD seconds between changes so a car never flickers between programs.
-- Program ranking is by NAME when every program on the car has a recognisable name, else by INDEX (last = most
-- aggressive, the usual convention in car mods).
-- The switches live on the racecraft table so --racecraft {"ERS_MODE":"smart"} reaches them with no harness change.
local R = require('lib.racecraft')
local Recovery = require('lib.recovery')

local E = {}
R.ERS_MODE = 'off'   -- 'off' | 'max' | 'smart'   (harness A/B; default off)
R.ERS_LO = 0.20      -- 'smart': below this battery fraction, drop to the most conservative program
R.ERS_HOLD = 2.0     -- s: minimum time between program changes on one car
R.ERS_REC = -1       -- >= 0: force MGU-K recovery 0-10 on every AI hybrid (-1 = leave the car's own)

local info = {}      -- [car] = false (no programs to choose) | { id, n, hi, lo, def, t, byName }
local acc = 0

local function score(name)
    local n = string.lower(tostring(name or ''))
    if n == '' then return nil end
    if n:find('none') or n:find('no ') or n:find('off') or n:find('zero') then return 0 end
    if n:find('charg') or n:find('build') or n:find('harvest') or n:find('save') or n:find('low') or n:find('eco') then return 1 end
    if n:find('hot') or n:find('qual') or n:find('attack') or n:find('overtake') or n:find('boost') or n:find('max') or n:find('full') then return 4 end
    if n:find('high') or n:find('push') then return 3 end
    if n:find('bal') or n:find('med') or n:find('norm') or n:find('stand') or n:find('race') or n:find('default') then return 2 end
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
    local hi, lo = n - 1, 0
    if all then
        hi = 0; for p = 0, n - 1 do if sc[p] >= sc[hi] then hi = p end end          -- ties: the higher index
        lo = n - 1; for p = n - 1, 0, -1 do if sc[p] <= sc[lo] then lo = p end end  -- ties: the lower index
    end
    local f = { id = id, n = n, hi = hi, lo = lo, def = c.mgukDelivery or 0, t = -1e9, byName = all }
    info[i] = f
    return f
end

function E.update(sim, dt)
    local mode = R.ERS_MODE
    local deliver = (mode == 'max' or mode == 'smart')
    local rl = tonumber(R.ERS_REC) or -1
    if not deliver and rl < 0 then return end
    acc = acc + (dt or 0)
    if acc < 0.25 then return end                  -- 4 Hz is plenty for a program choice
    acc = 0
    local now = os.clock()
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and c.isAIControlled and not c.isInPitlane then
            local id = ''; pcall(function() id = ac.getCarID(i) or '' end)
            local f = info[i]
            if f == nil or (f and f.id ~= id) then f = study(i, c, id) end
            if f then
                if deliver then
                    local want = f.def
                    if mode == 'max' then
                        want = f.hi
                    else
                        local st = (R.last and R.last[i] and R.last[i].state) or 0
                        if (c.kersCharge or 1) < (tonumber(R.ERS_LO) or 0.2) then want = f.lo
                        elseif (c.lapCount or 0) < 1 or st == 1 or st == 2 then want = f.hi end
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
