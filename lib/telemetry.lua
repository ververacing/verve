-- Verve / lib/telemetry.lua  --  OPT-IN anonymous race reports ("Send anonymous race stats to improve Verve").
--
-- Off by default. When on, ONE small JSON row is sent at the end of each race session (or, if the session was
-- quit / restarted / the game crashed, at the next launch with an abort reason). It describes what was run
-- (track, cars, laps, difficulty, weather, settings), how the field did (finishers, retirements, incidents,
-- repairs, lap-time spread) and how the human did (positions, laps, incidents) -- and nothing about who: no
-- names, no gamer tag, no paths, no hardware ids. `install_id` is a random string generated once.
-- The endpoint accepts inserts only (the key below can neither read nor change anything).
local T = {}
T.ENABLED = false
T.VERSION = '0.0.0'          -- set by Verve.lua from update.lua
T.UNATTENDED = false         -- harness/autopilot run: flagged so human statistics can exclude it

local URL = 'https://qcdnlochctwfsvslnqxo.supabase.co/rest/v1/race_reports'
local KEY = 'sb_publishable_eaoWTXUhM7jcbZ8vBRhtYw_bPIcJa8W'

local Contacts = require('lib.contacts')
-- launcher assists (damage / fuel rate) on builds that expose ac.getAssists(); nil elsewhere
local function assist(k) local v = nil; pcall(function() local a = ac.getAssists and ac.getAssists(); if a then v = a[k] end end); return v end
local S = ac.storage({ installId = '', pending = '', sent = 0 })
if S.installId == '' then
    local chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    local id = {}
    math.randomseed(os.time() + math.floor(os.clock() * 1000))
    for _ = 1, 20 do local k = math.random(#chars); id[#id + 1] = chars:sub(k, k) end
    S.installId = table.concat(id)
end

-- ------------------------------------------------------------------ per-session stats (1 Hz sampling)
local st = nil
local lastT = -1e9
local sentThis = false
local sessionIdx = nil
local flagT = 0

local function newStats(sim)
    local s = { t0 = os.time(), laps = {}, lastPrev = {}, inc = {}, incContact = 0, incSolo = 0, incLap1 = 0,
                dmgPrev = {}, pits = {}, wasInPit = {}, startPos = {}, leadCar = nil, leadChanges = 0,
                fps = 0, fpsN = 0, maxDmg = {}, finished = {}, samples = 0,
                leaderLaps = 0, sawGreen = false }
    for i = 0, sim.carsCount - 1 do s.laps[i] = {}; s.inc[i] = 0; s.pits[i] = 0; s.maxDmg[i] = 0 end
    return s
end

local function maxDamage(car)
    local m = 0
    pcall(function() local d = car.damage; if d then for k = 0, 4 do local v = d[k]; if type(v) == 'number' and v > m then m = v end end end end)
    return m
end

local function sample(sim)
    st.samples = st.samples + 1
    if sim.isSessionStarted then st.sawGreen = true end
    -- damage off in the launcher: damage never jumps, so incidents come from CSP's collision state instead; with damage
    -- on the damage path stays (comparable with every row sent so far). The row carries damage_setting either way.
    if st.damageOff == nil then st.damageOff = (assist('damageRate') == 0) end
    if st.damageOff and Contacts.available then
        local evs, last = Contacts.since(st.contactCursor or 0); st.contactCursor = last
        for _, e in ipairs(evs) do
            local c = ac.getCar(e.car)
            if c and not c.isInPitlane and st.inc[e.car] ~= nil and e.drop >= 3 then
                st.inc[e.car] = st.inc[e.car] + 1
                if e.other >= 0 then st.incContact = st.incContact + 1 else st.incSolo = st.incSolo + 1 end
                if e.lap <= 1 then st.incLap1 = st.incLap1 + 1 end
            end
        end
    end
    pcall(function() if sim.fps and sim.fps > 0 then st.fps = st.fps + sim.fps; st.fpsN = st.fpsN + 1 end end)
    local leader = nil
    local inPits = 0
    for i = 0, sim.carsCount - 1 do local c0 = ac.getCar(i); if c0 and c0.isInPitlane then inPits = inPits + 1 end end
    local massPit = inPits > sim.carsCount / 2
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c then
            if (c.lapCount or 0) > st.leaderLaps then st.leaderLaps = c.lapCount end
            -- laps
            local prev = c.previousLapTimeMs
            if type(prev) == 'number' and prev > 0 and prev ~= st.lastPrev[i] then
                st.lastPrev[i] = prev
                if prev > 10000 then st.laps[i][#st.laps[i] + 1] = prev / 1000 end
            end
            -- start positions (first sample once the race is on)
            if st.startPos[i] == nil and (c.lapCount or 0) <= 1 and sim.isSessionStarted and (c.racePosition or 0) > 0 then st.startPos[i] = c.racePosition end
            -- incidents: damage jumps; contact if another car is within 20 m
            local dmg = maxDamage(c)
            local pd = st.dmgPrev[i]
            if not st.damageOff and pd ~= nil and dmg - pd >= 8 and not c.isInPitlane then
                st.inc[i] = st.inc[i] + 1
                local near = false
                for j = 0, sim.carsCount - 1 do
                    if j ~= i then local o = ac.getCar(j); if o and o.position:distance(c.position) < 20 then near = true; break end end
                end
                if near then st.incContact = st.incContact + 1 else st.incSolo = st.incSolo + 1 end
                if (c.lapCount or 0) <= 1 then st.incLap1 = st.incLap1 + 1 end
            end
            st.dmgPrev[i] = dmg
            if dmg > st.maxDmg[i] then st.maxDmg[i] = dmg end
            -- pit stops (entering the box)
            local inPit = false; pcall(function() inPit = c.isInPit == true end)
            -- a real stop, not the session-end teleport (everyone lands in the pits at once) or a finished car
            if inPit and not st.wasInPit[i] and (c.lapCount or 0) >= 1 and not c.isRaceFinished and not massPit then st.pits[i] = st.pits[i] + 1 end
            st.wasInPit[i] = inPit
            if c.racePosition == 1 then leader = i end
            if c.isRaceFinished then st.finished[i] = true end
        end
    end
    if leader ~= nil and st.leadCar ~= nil and leader ~= st.leadCar then st.leadChanges = st.leadChanges + 1 end
    if leader ~= nil then st.leadCar = leader end
end

local function median(t)
    if #t == 0 then return nil end
    local c = {}; for k, v in ipairs(t) do c[k] = v end; table.sort(c)
    return c[math.floor((#c + 1) / 2)]
end
local function minOf(t) local m = nil; for _, v in ipairs(t) do if m == nil or v < m then m = v end end; return m end

local function jsonEscape(s) return (tostring(s):gsub('[%c"\\]', function(ch) return string.format('\\u%04x', ch:byte()) end)) end
local function jnum(v) if type(v) ~= 'number' or v ~= v or v == math.huge or v == -math.huge then return 'null' end; return string.format('%.3f', v):gsub('%.?0+$', '') end
local function jint(v) if type(v) ~= 'number' or v ~= v or v == math.huge or v == -math.huge then return 'null' end; return string.format('%d', math.floor(v + 0.5)) end
local function jstr(v) if v == nil then return 'null' end; return '"' .. jsonEscape(v) .. '"' end
local function jbool(v) if v == nil then return 'null' end; return v and 'true' or 'false' end

-- build the report row (a JSON object string) from the current stats + the context Verve hands us
function T.buildReport(sim, ctx, completed, abortReason)
    ctx = ctx or {}
    local n = sim.carsCount
    local classes, models, detail = {}, {}, {}
    local running, retired, aiBest, aiMed, meds = 0, 0, nil, {}, {}
    for i = 0, n - 1 do
        local c = ac.getCar(i)
        local model = ''; pcall(function() model = ac.getCarID(i) or '' end)
        local cls = ctx.classOf and ctx.classOf(i) or 'unknown'
        classes[cls] = (classes[cls] or 0) + 1
        models[#models + 1] = jstr(model)
        local best, med = minOf(st.laps[i]), median(st.laps[i])
        local ret = c and c.isRetired == true or false
        local rs = ctx.recState and ctx.recState(i) or {}
        local parked = rs.parked == true
        if ret or parked then retired = retired + 1 else running = running + 1 end
        if i > 0 and best then aiBest = (aiBest == nil or best < aiBest) and best or aiBest end
        if i > 0 and med then aiMed[#aiMed + 1] = med end
        if med then meds[#meds + 1] = med end
        local lvl = ctx.levelOf and ctx.levelOf(i) or nil
        detail[#detail + 1] = string.format('{"i":%d,"model":%s,"class":%s,"level":%s,"best":%s,"median":%s,"laps":%d,"inc":%d,"pits":%d,"ret":%s,"parked":%s,"maxdmg":%s}',
            i, jstr(model), jstr(cls), jnum(lvl), jnum(best), jnum(med), #st.laps[i], st.inc[i], st.pits[i], jbool(ret), jbool(parked), jnum(st.maxDmg[i]))
    end
    table.sort(meds)
    local spread = nil
    if #meds >= 4 and meds[1] > 0 then spread = (meds[math.ceil(#meds * 0.9)] - meds[math.max(1, math.floor(#meds * 0.1))]) / meds[1] * 100 end
    local clsParts = {}; for k, v in pairs(classes) do clsParts[#clsParts + 1] = string.format('%s:%d', jstr(k), v) end
    local p = ac.getCar(0)
    local pBest, pMed = minOf(st.laps[0]), median(st.laps[0])
    local totalInc, totalPits = 0, 0
    for i = 0, n - 1 do totalInc = totalInc + st.inc[i]; totalPits = totalPits + st.pits[i] end
    local track, layout = '', ''
    pcall(function() track = ac.getTrackID() or ''; layout = ac.getTrackLayout() or '' end)
    local stype = 'other'
    pcall(function()
        local tt = sim.raceSessionType
        stype = (tt == ac.SessionType.Race and 'race') or (tt == ac.SessionType.Qualify and 'qualify') or (tt == ac.SessionType.Practice and 'practice') or (tt == ac.SessionType.Hotlap and 'hotlap') or 'other'
    end)
    local wet = false; pcall(function() wet = (sim.rainIntensity or 0) > 0.05 end)
    local fields = {
        '"install_id":' .. jstr(S.installId),
        '"verve_version":' .. jstr(T.VERSION),
        '"schema_version":2',
        '"csp_build":' .. jint(ctx.cspBuild),
        '"session_type":' .. jstr(stype),
        '"unattended":' .. jbool(T.UNATTENDED),
        '"track":' .. jstr(track), '"layout":' .. jstr(layout),
        '"track_length_m":' .. jint(sim.trackLengthM),
        '"laps":' .. jint(ctx.laps), '"cars":' .. jint(n),
        '"car_classes":{' .. table.concat(clsParts, ',') .. '}',
        '"car_models":[' .. table.concat(models, ',') .. ']',
        '"player_car":' .. jstr(ctx.playerModel), '"player_class":' .. jstr(ctx.classOf and ctx.classOf(0) or nil),
        '"is_wet":' .. jbool(wet),
        '"ambient_c":' .. jint(sim.ambientTemperature), '"road_c":' .. jint(sim.roadTemperature),
        '"time_of_day":' .. jstr(sim.timeHours and string.format('%02d:00', sim.timeHours) or nil),
        '"ai_level":' .. jint(ctx.meter),
        '"ai_level_applied":' .. (ctx.appliedJson or 'null'),
        '"is_career":' .. jbool(ctx.isCareer), '"career_event":' .. jstr(ctx.careerEvent),
        '"running_end":' .. jint(running), '"retired":' .. jint(retired),
        '"retired_by_verve":' .. jint(ctx.retiredByVerve), '"frozen_cars":' .. jint(ctx.frozen),
        '"incidents":' .. jint(totalInc), '"incidents_contact":' .. jint(st.incContact), '"incidents_solo":' .. jint(st.incSolo), '"incidents_lap1":' .. jint(st.incLap1),
        '"crash_repairs":' .. jint(ctx.crashRepairs), '"limp_repairs":' .. jint(ctx.limpRepairs),
        '"repositions":' .. jint(ctx.drops), '"repositions_ok":' .. jint(ctx.dropsOk),
        '"lead_changes":' .. jint(st.leadChanges), '"pit_stops":' .. jint(totalPits),
        '"ai_best_lap_s":' .. jnum(aiBest), '"ai_median_lap_s":' .. jnum(median(aiMed)), '"field_spread_pct":' .. jnum((function() local r = false; pcall(function() r = sim.raceSessionType == ac.SessionType.Race end); return r and spread or nil end)()),
        '"player_start_pos":' .. jint(st.startPos[0]), '"player_finish_pos":' .. jint(p and p.racePosition or nil),
        '"player_laps":' .. jint(#st.laps[0]), '"player_best_lap_s":' .. jnum(pBest), '"player_median_lap_s":' .. jnum(pMed),
        '"player_incidents":' .. jint(st.inc[0]), '"player_max_damage":' .. jint(st.maxDmg[0]), '"player_pit_stops":' .. jint(st.pits[0]),
        '"player_finished":' .. jbool(st.finished[0] == true),
        '"completed":' .. jbool(completed), '"abort_reason":' .. jstr(abortReason),
        '"duration_s":' .. jint(os.time() - st.t0),
        '"leader_laps":' .. jint(st.leaderLaps),
        '"left_before_green":' .. jbool(not st.sawGreen),
        '"profiles_used":' .. jint(ctx.profilesUsed), '"archetypes_used":' .. jint(ctx.archetypesUsed),
        '"trouble_spots":' .. jint(ctx.troubleSpots),
        '"fps_avg":' .. jnum(st.fpsN > 0 and st.fps / st.fpsN or nil),
        '"damage_setting":' .. jnum(assist('damageRate')),
        '"fuel_setting":' .. jnum(assist('fuelRate')),
        '"contacts_seen":' .. jint(Contacts.count),
        '"verve_ms_avg":' .. jnum(ctx.verveMs), '"lua_errors":' .. jint(ctx.luaErrors),
        '"session_key":' .. jstr(S.installId .. '-' .. tostring(st.t0) .. '-' .. tostring(ctx.track or '')),   -- for server-side de-duplication
        '"settings":' .. (ctx.settingsJson or 'null'),
        '"cars_detail":[' .. table.concat(detail, ',') .. ']',
    }
    return '{' .. table.concat(fields, ',') .. '}'
end

-- a column the server does not know yet (PGRST204 'Could not find the ... column'): drop it from the row and resend once,
-- so a client can be ahead of the database schema (session_key, 2026-09-19: every send failed for a day before this)
local function withoutColumn(body, col)
    local out = body:gsub(',"' .. col .. '":"[^"]*"', ''):gsub(',"' .. col .. '":%b{}', ''):gsub(',"' .. col .. '":%b[]', ''):gsub(',"' .. col .. '":[^,}]*', '')
    return out
end
local function post(body, onDone, tries)         -- tries: unknown columns already dropped from this row
    pcall(function()
        web.post(URL, { ['apikey'] = KEY, ['Authorization'] = 'Bearer ' .. KEY, ['Content-Type'] = 'application/json', ['Prefer'] = 'return=minimal' }, body,
            function(err, res)
                local ok = (not err) and res and res.status and res.status >= 200 and res.status < 300
                local rejected = (not ok) and res and res.status and res.status >= 400 and res.status < 500
                pcall(function() ac.log(string.format('Verve telemetry: %s (%s) %s', ok and 'sent' or 'failed', tostring(err or (res and res.status)), rejected and tostring(res.body):sub(1, 200) or '')) end)
                if rejected and (tries or 0) < 8 then       -- one unknown column per reply: drop it and resend (bounded)
                    local col = tostring(res.body):match("Could not find the '([%w_]+)' column")
                    if col then post(withoutColumn(body, col), onDone, (tries or 0) + 1); return end
                end
                if rejected then S.pending = '' end        -- malformed row: drop it, don't retry forever
                if onDone then onDone(ok) end
            end)
    end)
end

-- a report that could not be sent right away (quit/crash) waits in storage for the next launch
local function flushPending()
    if S.pending ~= '' and T.ENABLED then
        local body = S.pending
        S.pending = ''
        post(body, function(ok) if ok then S.sent = (S.sent or 0) + 1 end end)
    end
end
local flushed = false

-- Verve calls this at session change / app release with the reason; the current race becomes a pending row
function T.abort(reason, sim, ctx)
    if not st or sentThis or not T.ENABLED then return end
    if st.samples < 30 then st = nil; return end           -- nothing worth reporting
    pcall(function()
        local body = T.buildReport(sim, ctx, false, reason)
        sentThis = true
        S.pending = body
        post(body, function(ok) if ok then S.pending = ''; S.sent = (S.sent or 0) + 1 end end)
    end)
end

function T.reset() st = nil; sentThis = false; flagT = 0; lastT = -1e9 end

function T.update(dt, ctx)
    if not T.ENABLED then return end
    local ok, sim = pcall(ac.getSim); if not ok or not sim then return end
    if not flushed then flushed = true; flushPending() end
    if sim.isReplayActive then return end
    local idx = sim.currentSessionIndex or 0
    if sessionIdx ~= idx then sessionIdx = idx; T.reset() end
    if not sim.isSessionStarted then return end
    if st == nil then st = newStats(sim) end
    local now = os.clock()
    if now - lastT >= 1.0 then lastT = now; pcall(sample, sim) end
    if sentThis then return end
    -- race over: every car finished or is parked and still, for 15 s
    local isRace = false; pcall(function() isRace = sim.raceSessionType == ac.SessionType.Race end)
    if not isRace then return end
    local over = true
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c and not c.isRaceFinished and not c.isRetired and not (c.isInPitlane and (c.speedKmh or 0) < 1) then over = false; break end
    end
    if over then
        flagT = flagT + dt
        if flagT > 15 then
            sentThis = true
            pcall(function()
                local leaderLaps = 0
                for i = 0, sim.carsCount - 1 do local c = ac.getCar(i); if c and (c.lapCount or 0) > leaderLaps then leaderLaps = c.lapCount end end
                local real = leaderLaps >= 1 and (os.time() - st.t0) >= 60     -- a 15 s 'finished' race is a restart artefact
                local body = T.buildReport(sim, ctx, real, real and nil or 'restart')
                post(body, function(ok2) if ok2 then S.sent = (S.sent or 0) + 1 else S.pending = body end end)
            end)
        end
    else
        flagT = 0
    end
end

function T.sentCount() return S.sent or 0 end

return T
