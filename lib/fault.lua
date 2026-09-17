-- lib/fault.lua -- who caused the contact, and what it costs them.
--
-- Every car keeps a 4 Hz trace of the last 4 s: the car ahead on its line (gap, closing speed, both brakes), the nearest
-- car at all (distance, side offset) and its own lateral. A damage jump of 8+ is a contact; contacts within 1.5 s and
-- 1 % of a lap are one INCIDENT. The rules below (the same ones tools/fault_live.py ran offline on 2026-09-17) name a
-- verdict, a culprit and a confidence; a strike is confidence x severity. A car's strikes above the first full point cost
-- it PEN_S seconds each, served in the race: an AI car gets a throttle cap for long enough to lose about that much, the
-- player gets AC's own slow-down penalty (cut the gas for N seconds). Owner's ask 2026-09-17: "any car including the
-- user's car gets some kind of time penalty for causing crashes."
--
-- Conservative by design: about half of all contacts stay "racing incident, nobody charged". Harness switches: F.ENABLED
-- (judge and log), F.ENFORCE (also serve the penalties). Verdicts go to ac.log, the race feed ("penalty" events) and the
-- diagnostics summary.

local F = {}
F.ENABLED  = false
F.ENFORCE  = false
F.PEN_S    = 5        -- seconds per strike point above the first
F.AI_CAP   = 0.55     -- throttle cap while an AI car serves its penalty
F.AI_CAP_X = 1.8      -- seconds of cap per penalty second (a half-throttle car loses roughly 0.55 s a second at speed)
F.FREE     = 1.0      -- strike points every car gets before penalties start (a first racing contact is free)

local TICK, RING, DMG_JUMP, INC_T, INC_S = 0.25, 16, 8, 1.5, 0.010
local ring, dmgLast, lastT = {}, {}, 0
local pending = {}          -- contacts waiting to be grouped: { t, car, lap, spline, dmg, rows }
local strikes = {}          -- car -> strike points
local charged = {}          -- car -> penalty seconds handed out so far (whole points served)
F.penCap = {}               -- car -> { cap, till } read by racecraft's throttle setter (shared table, no upvalue there)
F.log = {}                  -- last verdicts for the UI: { t, verdict, culprit, conf, detail }
F.count, F.penCount = 0, 0
local drops = nil           -- Recovery.recentDrops (set by Verve.lua)
local feedEvent = nil       -- Feed.event (set by Verve.lua)

local function maxDmg(c)
    local m, d = 0, c.damage
    if d then for k = 0, 4 do local v = d[k]; if type(v) == 'number' and v > m then m = v end end end
    return m
end

local function latOf(pos)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(pos); if tc then x = tc.x end end)
    return x
end

function F.attach(recentDrops, feedEv) drops, feedEvent = recentDrops, feedEv end

function F.reset()
    ring, dmgLast, pending, strikes, charged = {}, {}, {}, {}, {}
    for k in pairs(F.penCap) do F.penCap[k] = nil end     -- in place: racecraft holds a reference to this table
    F.log, F.count, F.penCount, lastT = {}, 0, 0, 0
end

function F.strikesOf(i) return strikes[i] or 0 end

-- one 4 Hz sample per car: { t, ahead, gap, dlat, spd, aspd, brake, abrake, near, nearD, nearLong, nearLat, lat }
local function sample(sim, now)
    local tl = (sim.trackLengthM and sim.trackLengthM > 200) and sim.trackLengthM or 7000
    local n = sim.carsCount
    local spl, lat, dmg = {}, {}, {}
    for i = 0, n - 1 do
        local c = ac.getCar(i)
        if c then spl[i] = c.splinePosition or 0; lat[i] = latOf(c.position); dmg[i] = maxDmg(c) end
    end
    for i = 0, n - 1 do
        local c = ac.getCar(i)
        if c and spl[i] then
            local best, bestGap = -1, 30.0
            local near, nearD, nearLong = -1, 30.0, 0
            for j = 0, n - 1 do
                if j ~= i and spl[j] then
                    local g = (spl[j] - spl[i]) % 1
                    local sg = g < 0.5 and g or g - 1
                    local gm = sg * tl
                    if sg >= 0 and gm < bestGap and math.abs(lat[j] - lat[i]) < 0.3 then best, bestGap = j, gm end
                    if math.abs(gm) < 40 then
                        local o = ac.getCar(j)
                        local d = o and o.position:distance(c.position) or 99
                        if d < nearD then near, nearD, nearLong = j, d, gm end
                    end
                end
            end
            local r = ring[i]
            if best >= 0 or near >= 0 then
                if not r then r = {}; ring[i] = r end
                local a = best >= 0 and ac.getCar(best) or nil
                r[#r + 1] = { now, best, best >= 0 and bestGap or 99, best >= 0 and (lat[best] - lat[i]) or 0,
                    c.speedKmh or 0, a and a.speedKmh or 0, (c.brake or 0) * 100, a and (a.brake or 0) * 100 or 0,
                    near, nearD, nearLong, near >= 0 and (lat[near] - lat[i]) or 0, lat[i] }
                if #r > RING then table.remove(r, 1) end
            else
                ring[i] = nil
            end
            local prev = dmgLast[i]
            if prev and dmg[i] - prev >= DMG_JUMP and r and #r > 0 then
                local rows = {}
                for k, v in ipairs(r) do rows[k] = v end
                pending[#pending + 1] = { t = now, car = i, lap = c.lapCount or 0, spline = spl[i], dmg = dmg[i] - prev, rows = rows }
                ring[i] = {}
            end
            dmgLast[i] = dmg[i]
        end
    end
end

-- the rules, first fit wins. Returns verdict, culprit (car | {a, b} | 'system' | nil), confidence, detail
local function judge(inc, now)
    local cars = {}
    for _, c in ipairs(inc) do cars[c.car] = true end
    local t0 = inc[1].t
    local dropHit = nil
    if drops then
        pcall(function()
            for _, d in ipairs(drops() or {}) do
                if cars[d.i] and t0 - d.t >= 0 and t0 - d.t <= 12 then dropHit = d.i; return end
            end
        end)
    end
    if dropHit then return 'dropped_into', 'system', 1.0, string.format('car %d repositioned just before', dropHit) end
    -- rear-end: A's last rows show B ahead on the same line, close, closing
    local best = nil
    for _, c in ipairs(inc) do
        local r = c.rows
        if #r >= 3 then
            for k = #r - 2, #r do
                local x = r[k]
                if x[2] >= 0 and cars[x[2]] and math.abs(x[4]) < 0.3 and x[3] <= 6 and x[5] - x[6] >= 8 then
                    local conf
                    if x[7] < 40 then conf = (x[8] > 60) and 0.6 or 0.8 else conf = 0.7 end
                    if not best or conf > best[3] then
                        best = { 'rear_end', c.car, conf, string.format('car %d into %d at +%d km/h, gap %d m, brake %d%% (theirs %d%%)',
                            c.car, x[2], math.floor(x[5] - x[6]), math.floor(x[3]), math.floor(x[7]), math.floor(x[8])) }
                    end
                end
            end
        end
    end
    if best and #inc <= 2 then return best[1], best[2], best[3], best[4] end
    -- hit a stopped / crawling car
    for _, c in ipairs(inc) do
        local x = c.rows[#c.rows]
        if x and cars[x[2]] and x[6] < 25 and x[5] > 60 then
            return 'hit_stopped', c.car, 0.6, string.format('car %d at %d km/h into car %d at %d km/h', c.car, math.floor(x[5]), x[2], math.floor(x[6]))
        end
    end
    -- squeeze: alongside, and one car's OWN lateral moved toward the other by 0.15+ over the last second
    for _, c in ipairs(inc) do
        local r = c.rows
        if #r >= 5 then
            local last, prev = r[#r], r[#r - 4]
            local other = last[9]
            if cars[other] and math.abs(last[11]) < 5 and last[10] < 3 and prev[9] == other then
                local toward = (last[12] >= 0) and 1 or -1                  -- the other car is on this side of me
                local mine = (last[13] - prev[13]) * toward                -- my own lateral change toward it
                local ro = nil
                for _, c2 in ipairs(inc) do if c2.car == other then ro = c2.rows end end
                local theirs = 0
                if ro and #ro >= 5 then theirs = (ro[#ro][13] - ro[#ro - 4][13]) * -toward end
                if mine >= 0.15 and theirs >= 0.15 then
                    return 'squeeze', { c.car, other }, 0.35, string.format('cars %d and %d moved into each other side by side', c.car, other)
                elseif mine >= 0.15 then
                    return 'squeeze', c.car, 0.7, string.format('car %d moved %.2f of the track into car %d alongside', c.car, mine, other)
                end
            end
        end
    end
    if #inc >= 3 then
        if best then return 'pileup', best[2], best[3] * 0.8, string.format('%d cars; clearest rear-ender charged: %s', #inc, best[4]) end
        return 'pileup', nil, 0.0, string.format('%d cars, no clear culprit', #inc)
    end
    if best then return best[1], best[2], best[3], best[4] end
    return 'racing', nil, 0.0, 'no rule fits'
end

local function serve(i, seconds, now)
    local c = ac.getCar(i)
    if not c then return end
    if c.isAIControlled then
        F.penCap[i] = { cap = F.AI_CAP, till = now + seconds * F.AI_CAP_X }
    elseif i == 0 then
        pcall(function() physics.setCarPenalty(ac.PenaltyType.SlowDown, math.floor(seconds)) end)
    end
end

local function settle(inc, now)
    local sev = 0
    for _, c in ipairs(inc) do if c.dmg > sev then sev = c.dmg end end
    local w = (sev < 20) and 0.5 or ((sev < 60) and 1.0 or 1.5)
    local verdict, culprit, conf, detail = judge(inc, now)
    F.count = F.count + 1
    local who = 'nobody'
    if culprit == 'system' then who = 'system'
    elseif type(culprit) == 'table' then who = string.format('cars %d and %d', culprit[1], culprit[2])
    elseif culprit then who = string.format('car %d', culprit) end
    pcall(function() ac.log(string.format('Verve fault: lap %d %s -> %s (%.1f) %s', inc[1].lap, verdict, who, conf, detail)) end)
    F.log[#F.log + 1] = { t = now, verdict = verdict, who = who, conf = conf, detail = detail }
    if #F.log > 30 then table.remove(F.log, 1) end
    if culprit and culprit ~= 'system' then
        local list = (type(culprit) == 'table') and culprit or { culprit }
        for _, i in ipairs(list) do
            strikes[i] = (strikes[i] or 0) + conf * w
            local due = math.max(0, math.floor(strikes[i] - F.FREE + 0.5)) * F.PEN_S
            local extra = due - (charged[i] or 0)
            if extra > 0 then
                charged[i] = due
                F.penCount = F.penCount + 1
                pcall(function() ac.log(string.format('Verve penalty: car %d +%d s (%s, strikes %.1f)%s', i, extra, verdict, strikes[i], F.ENFORCE and '' or ' [not enforced]')) end)
                if feedEvent then pcall(feedEvent, 'penalty', string.format('"car":%d,"seconds":%d,"verdict":"%s","strikes":%.1f,"enforced":%s', i, extra, verdict, strikes[i], tostring(F.ENFORCE))) end
                if F.ENFORCE then serve(i, extra, now) end
            end
        end
    end
end

function F.update(dt)
    if not F.ENABLED then return end
    local now = os.clock()
    if now - lastT < TICK then return end
    lastT = now
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end
    pcall(sample, sim, now)
    -- expire served caps
    for i, p in pairs(F.penCap) do if now > p.till then F.penCap[i] = nil end end
    -- group contacts older than INC_T into incidents and judge them
    if #pending > 0 and now - pending[1].t > INC_T then
        local inc, rest = { pending[1] }, {}
        for k = 2, #pending do
            local c = pending[k]
            local dup = false
            for _, x in ipairs(inc) do if x.car == c.car then dup = true end end
            if not dup and math.abs(c.t - inc[#inc].t) <= INC_T and math.abs(c.spline - inc[#inc].spline) <= INC_S then inc[#inc + 1] = c
            else rest[#rest + 1] = c end
        end
        pending = rest
        pcall(settle, inc, now)
    end
end

function F.status()
    return { count = F.count, penalties = F.penCount, strikes = strikes, charged = charged }
end

return F
