-- (shared with the Verve Broadcast Booth and Race Engineer projects; the schema lives in verve-broadcast/feed/SCHEMA.md)
-- Verve Race Feed (feed/SCHEMA.md, v1) -- a CSP Lua module for Verve.
--
-- Emits a JSON-lines race feed to Documents/Assetto Corsa/verve_feed/<date>_<track>.jsonl: a header,
-- a state snapshot every STATE_EVERY seconds, and discrete events (laps, overtakes, incidents, pits,
-- retirements, yellows, repositions, and Verve's own decisions) as they happen. Built to be required
-- by Verve.lua and fed the same per-frame stats table the diagnostics logger gets:
--
--     local Feed = require('lib.feed')      -- (this file, dropped into Verve/lib/)
--     Feed.update(dt, stats)                -- every frame, after Verve's own update
--     Feed.reset()                          -- on session start
--
-- Everything is pcall-guarded and costs one string build per second; it never touches physics.

local F = {}
F.ENABLED = true

local STATE_EVERY   = 1.0      -- seconds between state snapshots
local BATTLE_GAP_S  = 1.0      -- a fight is "a battle" once the gap is under this...
local BATTLE_HOLD   = 3        -- ...for this many snapshots
local STUCK_S       = 8.0      -- stationary off the line this long = stuck (and a yellow if on the road)
local INCIDENT_MIN  = 8        -- km/h of new body damage that counts as an incident
local Contacts = require('lib.contacts')
local Classes = require('lib.classes')    -- the header's per-car class (the classifier the app and the reports use)
local feedEvSeen = {}       -- per car: last collision event id already reported

local file, buf, started = nil, {}, false
local lastState, lastFlush = -1e9, -1e9
local namesSent, namesT = '', 0   -- declared before F.reset so its reset reaches them (it used to set two globals)
local t0 = 0
local prev = {}                -- per-car last snapshot { lap, pos, dmg, pit, ret, spline, lat, spd, st, yl, bl, rec }
local prevOrder = nil
local lapStart, bestLap, overallBest = {}, {}, nil
local stuckSince, stuckReported = {}, {}
local battles = {}             -- "a-b" -> { t0, n, active }
local trackLen = 4500

local function now() return os.clock() - t0 end

local function esc(s) return tostring(s):gsub('\\', '\\\\'):gsub('"', '\\"') end

local function emit(line)
    buf[#buf + 1] = line
end

local function flush()
    if not file or #buf == 0 then return end
    local ok = pcall(function()
        local f = io.open(file, 'a')
        if f then f:write(table.concat(buf, '\n'), '\n'); f:close() end
    end)
    if ok then buf = {} end
end

local function event(t, typ, fields)
    emit(string.format('{"v":1,"t":%.1f,"type":"%s"%s}', t, typ, fields and (',' .. fields) or ''))
end

local function lat01(pos)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(pos); if tc then x = tc.x end end)
    return x
end

local function newFile(sim)
    local dir = nil
    pcall(function() dir = ac.getFolder(ac.FolderID.Documents) .. '/Assetto Corsa/verve_feed' end)
    if not dir then return end
    pcall(function() io.createDir(dir) end)
    local track = 'track'; pcall(function() track = ac.getTrackFullID('/') or track end)
    file = string.format('%s/%s_%s.jsonl', dir, os.date('%Y%m%d_%H%M%S'), tostring(track):gsub('[^%w]', '_'))
    buf = {}
    pcall(function() if sim.trackLengthM and sim.trackLengthM > 200 then trackLen = sim.trackLengthM end end)
    local cars = {}
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c then
            local model, name = '', ''
            pcall(function() model = ac.getCarID(i) or '' end)
            pcall(function() name = ac.getDriverName(i) or '' end)
            local cls = ''; pcall(function() cls = Classes.keyOf(i) or '' end)
            cars[#cars + 1] = string.format('{"i":%d,"model":"%s","class":"%s","driver":"%s","player":%s}', i, esc(model), esc(cls), esc(name), tostring(i == 0))
        end
    end
    local amb, road, laps = 0, 0, 0
    pcall(function() amb = sim.ambientTemperature or 0; road = sim.roadTemperature or 0; laps = sim.raceSessionLaps or sim.sessionLaps or 0 end)
    emit(string.format('{"v":1,"t":0,"type":"header","track":"%s","layout":"","laps":%d,"ambient":%d,"road":%d,"cars":[%s]}',
        esc(track), laps, math.floor(amb), math.floor(road), table.concat(cars, ',')))
end

function F.reset()
    feedEvSeen = {}
    namesSent, namesT = '', 0
    flush()
    file = nil; started = false
    prev = {}; prevOrder = nil; lapStart = {}; bestLap = {}; overallBest = nil
    stuckSince = {}; stuckReported = {}; battles = {}
    lastState = -1e9
    lastFlush = -1e9   -- the new file's clock starts at 0: a stale value held a weekend race's writes for as long as the last session ran
    F.startSent = false
end

-- stats: the same table Verve passes to the diagnostics logger (rc = Racecraft.last, recState = Recovery.stateOf)
-- the header is written at session start, before driver profiles rename the cars: re-emit the names when they settle
local function namesEvent(sim, t)
    local parts = {}
    for i = 0, sim.carsCount - 1 do local n = ''; pcall(function() n = ac.getDriverName(i) or '' end); parts[#parts + 1] = string.format('"%d":"%s"', i, esc(n)) end
    local body = table.concat(parts, ',')
    if body ~= namesSent then namesSent = body; event(t, 'names', '"names":{' .. body .. '}') end
end

function F.update(dt, stats)
    if not F.ENABLED then return end
    local ok, sim = pcall(ac.getSim); if not ok or not sim then return end
    if not started then
        t0 = os.clock(); started = true
        pcall(newFile, sim)
    end
    local t = now()
    if t - lastState < STATE_EVERY then
        if t - lastFlush > 5 then lastFlush = t; flush() end
        return
    end
    if t < 3.0 then return end   -- a new session's first frames still show the old session's cars (weekend race, 2026-09-26)
    lastState = t
    stats = stats or {}
    if t - namesT >= 5 then namesT = t; pcall(namesEvent, sim, t) end   -- every 5 s, written only when a name changed
    local rc = stats.rc or {}

    -- gather
    local cars, running = {}, {}
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c then
            local st = {}
            if stats.recState then pcall(function() st = stats.recState(i) or {} end) end
            local r = rc[i] or {}
            local dmg = 0
            pcall(function() local d = c.damage; if d then for k = 0, 4 do local v = d[k]; if type(v) == 'number' and v > dmg then dmg = v end end end end)
            local e = {
                i = i, lap = c.lapCount or 0, pos = c.racePosition or 0, spline = c.splinePosition or 0, spd = c.speedKmh or 0,
                pit = c.isInPitlane == true, ret = c.isRetired == true, dmg = dmg, lat = lat01(c.position),
                st = r.state or 0, yl = r.yield == true, bl = (r.block or 0) ~= 0, rec = st.rec == true, park = st.parked == true, mv = r.mv or 0,
                tyre = (c.wheels and c.wheels[0] and c.wheels[0].tyreCoreTemperature) or 0,
            }
            cars[#cars + 1] = e
            if not e.ret and not e.park then running[#running + 1] = e end
        end
    end
    table.sort(running, function(a, b) return a.pos < b.pos end)

    -- race start: the first race-session car moving, leader on lap 0-1 (the old test, 'no previous order', only ever fired
    -- from a weekend's stale first frames, and never in a plain race)
    if not F.startSent and #running > 0 and running[1].lap <= 1 then   -- <= 1: a grid before the line can cross it first
        local isRace = false; pcall(function() isRace = sim.raceSessionType == ac.SessionType.Race end)
        if isRace then for _, c in ipairs(running) do if c.spd > 30 then event(t, 'race_start'); F.startSent = true; break end end end
    end

    -- state snapshot with time gaps
    local parts = {}
    local gapAhead = {}
    for k, c in ipairs(running) do
        local g = 'null'
        if k > 1 then
            local a = running[k - 1]
            local d = (a.spline - c.spline) + math.max(0, a.lap - c.lap)
            if d < 0 then d = d + 1 end
            if c.spd > 5 then local gs = d * trackLen / (c.spd / 3.6); gapAhead[c.i] = gs; g = string.format('%.2f', gs) end
        end
        local stName = (c.st == 1) and 'attack' or ((c.st == 2) and 'defend' or 'cruise')
        parts[#parts + 1] = string.format('{"i":%d,"pos":%d,"lap":%d,"spline":%.4f,"spd":%d,"gap_ahead_s":%s,"pit":%s,"ret":%s,"dmg":%d,"tyre":%d,"verve":{"state":"%s","yield":%s,"block":%s,"recovering":%s}}',
            c.i, c.pos, c.lap, c.spline, math.floor(c.spd), g, tostring(c.pit), tostring(c.ret), math.floor(c.dmg), math.floor(c.tyre),
            stName, tostring(c.yl), tostring(c.bl), tostring(c.rec))
    end
    local leaderLap = (#running > 0) and running[1].lap or 0
    emit(string.format('{"v":1,"t":%.1f,"type":"state","leader_lap":%d,"running":%d,"cars":[%s]}', t, leaderLap, #running, table.concat(parts, ',')))

    -- per-car events
    for _, c in ipairs(cars) do
        local i, p = c.i, prev[c.i]
        if p then
            if c.lap > p.lap then
                local lt = t - (lapStart[i] or t)
                lapStart[i] = t
                if p.lap >= 1 and lt > 20 then
                    local best = lt < (bestLap[i] or 1e9)
                    if best then bestLap[i] = lt end
                    event(t, 'lap', string.format('"car":%d,"lap":%d,"time_s":%.1f,"best":%s', i, p.lap + 1, lt, tostring(best)))
                    if not overallBest or lt < overallBest then
                        overallBest = lt
                        if p.lap >= 2 then event(t, 'fastest_lap', string.format('"car":%d,"lap":%d,"time_s":%.1f', i, p.lap + 1, lt)) end
                    end
                end
            end
            local dd = c.dmg - p.dmg
            if dd < INCIDENT_MIN and Contacts.available then     -- no damage jump: a collision event in the last second counts instead
                local ev = Contacts.recent(i, 1.0)
                if ev and ev.id ~= feedEvSeen[i] and ev.drop >= 3 then dd = math.max(INCIDENT_MIN, ev.drop); feedEvSeen[i] = ev.id end
            end
            if dd >= INCIDENT_MIN and not c.pit then
                local contact = {}
                -- WHO HAD THE CORNER: the closest other car by on-track gap in the second BEFORE the hit (the previous
                -- state), its nose ahead of mine or not, its lateral offset from me (+ = to my right) and my closing
                -- speed on it. A first "steward's call" for the broadcast; the 4 Hz traces stay in the diag files.
                local other, otherGap, otherSd = -1, 1e9, 0
                for _, o in ipairs(cars) do
                    local po = prev[o.i]
                    if o.i ~= i and po then
                        local sd = ((po.spline - p.spline + 0.5) % 1) - 0.5      -- signed: + = they were ahead of me
                        local d = math.abs(sd) * trackLen
                        if (o.dmg - po.dmg >= INCIDENT_MIN and d < 50) or d < 15 then contact[#contact + 1] = tostring(o.i) end
                        if d < otherGap and d < 30 and not po.ret then other, otherGap, otherSd = o.i, d, sd end
                    end
                end
                local who = ''
                if other >= 0 then
                    local po = prev[other]
                    who = string.format(',"other":%d,"noseAhead":%s,"dLat":%.2f,"closing":%d',
                        other, tostring(otherSd > 0), po.lat - p.lat, math.floor(p.spd - po.spd))
                end
                event(t, 'incident', string.format('"car":%d,"spline":%.4f,"severity":%d,"contact":[%s],"solo":%s,"speed":%d%s',
                    i, p.spline, math.floor(dd), table.concat(contact, ','), tostring(#contact == 0), math.floor(p.spd), who))
            end
            if math.abs(c.lat) > 1.3 and math.abs(p.lat) <= 1.3 and not c.pit then
                event(t, 'off_track', string.format('"car":%d,"spline":%.4f', i, c.spline))
            end
            if c.spd < 3 and not c.pit and not c.ret and t > 30 then
                stuckSince[i] = stuckSince[i] or t
                if t - stuckSince[i] >= STUCK_S and stuckReported[i] ~= stuckSince[i] then
                    stuckReported[i] = stuckSince[i]
                    event(t, 'stuck', string.format('"car":%d,"spline":%.4f', i, c.spline))
                    if math.abs(c.lat) < 1.3 then event(t, 'yellow', string.format('"spline":%.4f,"cars":[%d]', c.spline, i)) end
                end
            else
                stuckSince[i] = nil
            end
            if c.pit and not p.pit then event(t, 'pit_in', string.format('"car":%d,"lap":%d', i, c.lap)) end
            if p.pit and not c.pit then event(t, 'pit_out', string.format('"car":%d,"lap":%d', i, c.lap)) end
            if (c.ret and not p.ret) or (c.park and not p.park) then
                event(t, 'retire', string.format('"car":%d,"lap":%d,"reason":"%s"', i, c.lap, c.park and 'hopeless' or (c.dmg >= 150 and 'damage' or 'ac')))
            end
            -- Verve decisions (edge-triggered; attack/defend only when there's actually a car within reach)
            if c.st == 2 and p.st ~= 2 then event(t, 'verve', string.format('"car":%d,"decision":"defend","detail":"covering the inside line"', i)) end
            if c.st == 1 and p.st ~= 1 and (gapAhead[i] or 9) < 1.5 then event(t, 'verve', string.format('"car":%d,"decision":"attack","detail":"closing in, looking for a way past"', i)) end
            if c.yl and not p.yl then event(t, 'verve', string.format('"car":%d,"decision":"yield","detail":"moving aside for a faster car"', i)) end
            if c.mv ~= 0 and c.mv ~= p.mv then
                local MV = { [1] = { 'switchback', 'wide in, cutting back underneath on the exit' }, [2] = { 'lunge', 'braking late, diving for the inside' },
                             [3] = { 'setup', 'sitting in the tow, setting up the pass' }, [4] = { 'slingshot', 'in the draft, pulling out at the last moment' } }
                local m = MV[c.mv]
                if m then event(t, 'verve', string.format('"car":%d,"decision":"%s","detail":"%s"', i, m[1], m[2])) end
            end
            if c.bl and not p.bl then event(t, 'verve', string.format('"car":%d,"decision":"go_around","detail":"swerving around a stopped car"', i)) end
            if c.rec and not p.rec then event(t, 'verve', string.format('"car":%d,"decision":"crash_repair","detail":"Verve is getting the car going again"', i)) end
        else
            lapStart[i] = t
        end
        prev[i] = c
    end

    -- overtakes
    local order = {}
    for k, c in ipairs(running) do order[k] = c.i end
    if prevOrder then
        local prevPos = {}
        for k, i in ipairs(prevOrder) do prevPos[i] = k end
        local curPos = {}
        for k, i in ipairs(order) do curPos[i] = k end
        for k, i in ipairs(order) do
            local pk = prevPos[i]
            if pk and k < pk then
                for j = k, pk - 1 do
                    local over = prevOrder[j]
                    if over and curPos[over] and curPos[over] > k and (prev[over] and prev[over].spd or 0) > 30 then
                        if (gapAhead[i] or 9) < 2.5 or (gapAhead[over] or 9) < 2.5 then
                            event(t, 'overtake', string.format('"car":%d,"over":%d,"pos":%d,"spline":%.4f', i, over, k, running[k].spline))
                        end
                        if k == 1 then event(t, 'lead_change', string.format('"car":%d,"over":%d', i, over)) end
                    end
                end
            end
        end
    end
    prevOrder = order

    -- battles
    local seen = {}
    for k = 2, #running do
        local a, b = running[k - 1], running[k]
        local g = gapAhead[b.i]
        local key = a.i .. '-' .. b.i
        seen[key] = true
        if g and g < BATTLE_GAP_S and b.spd > 60 then
            local bt = battles[key]
            if not bt then bt = { t0 = t, n = 0, active = false }; battles[key] = bt end
            bt.n = bt.n + 1
            if bt.n == BATTLE_HOLD then bt.active = true; event(bt.t0, 'battle', string.format('"cars":[%d,%d],"pos":%d,"gap_s":%.2f', a.i, b.i, k - 1, g)) end
        elseif battles[key] and (not g or g > 1.5) then
            if battles[key].active then event(t, 'battle_end', string.format('"cars":[%d,%d],"resolved":"%s"', a.i, b.i, 'gap')) end
            battles[key] = nil
        end
    end
    for key, bt in pairs(battles) do
        if not seen[key] then
            if bt.active then
                local a, b = key:match('(%d+)-(%d+)')
                event(t, 'battle_end', string.format('"cars":[%s,%s],"resolved":"pass"', a, b))
            end
            battles[key] = nil
        end
    end

    -- repositions: recovery exposes its recent drops (judged) -- emit once each
    if stats.recentDrops then
        pcall(function()
            for _, d in ipairs(stats.recentDrops() or {}) do
                if not d.fed then d.fed = true; event(t, 'reposition', string.format('"car":%d,"spline":%.4f,"ok":null', d.i, d.spl or 0)) end
            end
        end)
    end

    if t - lastFlush > 5 then lastFlush = t; flush() end
end

-- called when the session ends (or at any time to force a write)
function F.finish()
    local ok, sim = pcall(ac.getSim)
    if ok and sim and started then
        local parts = {}
        for i = 0, sim.carsCount - 1 do
            local c = ac.getCar(i)
            if c then parts[#parts + 1] = string.format('{"pos":%d,"car":%d,"laps":%d,"ret":%s}', c.racePosition or 0, i, c.lapCount or 0, tostring(c.isRetired == true)) end
        end
        event(now(), 'race_end', '"results":[' .. table.concat(parts, ',') .. ']')
    end
    flush()
end

-- other modules' events (lib/fault.lua penalties): typed like the built-in ones, same clock
function F.event(typ, fields) if F.ENABLED then event(now(), typ, fields) end end

return F
