-- Verve / lib/telemetry.lua  --  OPT-IN anonymous race reports ("Send anonymous race stats to improve Verve").
--
-- Off by default. When on, ONE small JSON row is sent at the end of each race session (or, if the session was
-- quit / restarted / the game crashed, at the next launch with an abort reason). It describes what was run
-- (track, cars, laps, difficulty, weather, settings), how the field did (finishers, retirements, incidents,
-- repairs, lap-time spread) and how the human did (positions, laps, incidents) -- and nothing about who: no
-- names, no gamer tag, no paths, no hardware ids. `install_id` is a random string, created on the FIRST
-- opted-in send (not at load) so declining leaves nothing behind, and described in the consent text.
-- The endpoint accepts inserts only (the key below can neither read nor change anything).
local T = {}
T.ENABLED = false
T.VERSION = '0.0.0'          -- set by Verve.lua from update.lua
T.UNATTENDED = false         -- harness/autopilot run: flagged so human statistics can exclude it
-- (item 11 T1) OFF = the corrected abort_reason: nil on a real finish, 'restart' only on an actual restart.
-- ON restores the pre-fix behaviour, which labelled EVERY race 'restart'. Default OFF deliberately departs
-- from "a switch defaults to today's behaviour": today's behaviour is a mislabel with no measurement resting
-- on it, and defaulting to it would mean the fix never takes effect. The switch exists only so the old label
-- can be restored without a code change if the receiving end turns out to depend on it.
T.ABORT_LEGACY = false

-- (0.16, decision 0031) ONLY A RACE IS REPORTED. The consent text says "after each race", but T.update
-- built stats for ANY started session and T.abort had no session-type check, so quitting a PRACTICE or
-- QUALIFYING session posted a row. Defaults to FALSE on any failure to read the session type: if we cannot
-- tell what this session is, we do not report it.
-- CHECKED BEFORE WRITING THIS, because the harness deliberately exercises the opt-in path on every row
-- (harness.py passes shareData true): the harness writes its race session as TYPE=3 (harness.py:348), which
-- IS ac.SessionType.Race, so harness coverage of this code path is preserved. What the gate does remove is
-- the practice and qualifying sessions of a WEEKEND row, which is exactly the fix.
function T.isRaceSession(sim)
    local isRace = false
    pcall(function() isRace = sim and sim.raceSessionType == ac.SessionType.Race end)
    return isRace
end

local URL = 'https://qcdnlochctwfsvslnqxo.supabase.co/rest/v1/race_reports'
local KEY = 'sb_publishable_eaoWTXUhM7jcbZ8vBRhtYw_bPIcJa8W'

local Contacts = require('lib.contacts')
-- launcher assists (damage / fuel rate) on builds that expose ac.getAssists(); nil elsewhere
local function assist(k) local v = nil; pcall(function() local a = ac.getAssists and ac.getAssists(); if a then v = a[k] end end); return v end
local S = ac.storage({ installId = '', pending = '', sent = 0 })

-- (0.16, decisions 0031 and 0032) CREATED ON THE FIRST OPTED-IN SEND, NOT AT LOAD. It used to be generated
-- the moment this module loaded, so a player who never turned sharing on still had a persistent random id
-- written to their storage. Nothing was sent, but creating an identifier for someone who declined is not what
-- the consent text describes. The owner chose (decision 0032) to KEEP the id - it is what lets repeat reports
-- from one install be grouped, without which the data cannot tell one person's fifty races from fifty people's
-- one - and to DESCRIBE it in the consent text instead. Called from buildReport, which only runs when a report
-- is actually being built and sent.
function T.ensureInstallId()
    if S.installId ~= '' then return S.installId end
    local chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
    local id = {}
    math.randomseed(os.time() + math.floor(os.clock() * 1000))
    for _ = 1, 20 do local k = math.random(#chars); id[#id + 1] = chars:sub(k, k) end
    S.installId = table.concat(id)
    return S.installId
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
                leaderLaps = 0, sawGreen = false,
                -- mirror of everything the report reads off the live grid, kept current while the race runs so
                -- an abort reports the race that happened rather than the session that replaced it
                mRet = {}, mPark = {}, mPos = {}, mCls = {}, mTrack = nil, mLayout = nil, mLen = nil }
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
    if st.mTrack == nil then
        pcall(function() st.mTrack = ac.getTrackID() or ''; st.mLayout = ac.getTrackLayout() or '' end)
        st.mLen = sim.trackLengthM
    end
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
            st.mRet[i] = (c.isRetired == true)
            st.mPos[i] = c.racePosition or st.mPos[i]
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
    if type(ctx) == 'function' then ctx = ctx() end
    ctx = ctx or {}
    -- the mirror tables come from newStats, but buildReport runs inside pcall: a session shape that predates
    -- them (a resumed session, a hot reload mid-race - CSP reloads this app on any file write) would lose the
    -- WHOLE report to a nil index, silently. Local aliases cost nothing and fail visibly instead.
    local mRet, mPark, mPos, mCls = st.mRet or {}, st.mPark or {}, st.mPos or {}, st.mCls or {}
    local n = sim.carsCount
    local classes, models, detail = {}, {}, {}
    local running, retired, aiBest, aiMed, meds = 0, 0, nil, {}, {}
    for i = 0, n - 1 do
        local c = ac.getCar(i)
        local model = ''; pcall(function() model = ac.getCarID(i) or '' end)
        local cls = mCls[i] or (ctx.classOf and ctx.classOf(i)) or 'unknown'
        classes[cls] = (classes[cls] or 0) + 1
        models[#models + 1] = jstr(model)
        local best, med = minOf(st.laps[i]), median(st.laps[i])
        -- prefer the in-race mirror: on an abort the live grid is already the NEXT session
        local ret = mRet[i]
        if ret == nil then ret = c and c.isRetired == true or false end
        local rs = ctx.recState and ctx.recState(i) or {}
        local parked = mPark[i]
        if parked == nil then parked = rs.parked == true end
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
    if st.mTrack then track = st.mTrack; layout = st.mLayout or layout end   -- the track the race was run on
    local stype = 'other'
    pcall(function()
        local tt = sim.raceSessionType
        stype = (tt == ac.SessionType.Race and 'race') or (tt == ac.SessionType.Qualify and 'qualify') or (tt == ac.SessionType.Practice and 'practice') or (tt == ac.SessionType.Hotlap and 'hotlap') or 'other'
    end)
    local wet = false; pcall(function() wet = (sim.rainIntensity or 0) > 0.05 end)
    -- Which weather system this race ACTUALLY ran under (Pure and Sol change how a car goes round). First the
    -- session's race.ini request, which is what CSP keys on; with no key there, CSP uses its WeatherFX module
    -- config, so report THAT - on a Pure install a missing key still means Pure, and a null here was being read
    -- as "stock" (review 2026-10-10). The type falls back to the sim's own, set by the controller that ran.
    local wCtrl, wType = nil, nil
    pcall(function()
        local c = ac.INIConfig.raceConfig()
        wCtrl = c:get('LIGHTING', '__CM_WEATHER_CONTROLLER', '')
        wType = tonumber(c:get('LIGHTING', '__CM_WEATHER_TYPE', ''))
        if wCtrl == '' then wCtrl = nil end
    end)
    if wCtrl == nil then
        pcall(function()
            local cfg = ac.INIConfig.cspModule(ac.CSPModuleID.WeatherFX)
            local ctrl = cfg and tostring(cfg:get('BASIC', 'CONTROLLER', '')) or ''
            local impl = cfg and tostring(cfg:get('BASIC', 'IMPLEMENTATION', '')) or ''
            if ctrl ~= '' then wCtrl = ctrl .. ' (config)'
            elseif impl ~= '' and impl ~= 'base' then wCtrl = impl .. ' (implementation)' end
        end)
    end
    if wType == nil then pcall(function() wType = tonumber(sim.weatherType) end) end
    local fields = {
        '"install_id":' .. jstr(T.ensureInstallId()),
        '"verve_version":' .. jstr(T.VERSION),
        '"schema_version":2',
        '"csp_build":' .. jint(ctx.cspBuild),
        '"session_type":' .. jstr(stype),
        '"unattended":' .. jbool(T.UNATTENDED),
        '"track":' .. jstr(track), '"layout":' .. jstr(layout),
        '"track_length_m":' .. jint(st.mLen or sim.trackLengthM),
        '"laps":' .. jint(ctx.laps), '"cars":' .. jint(n),
        '"car_classes":{' .. table.concat(clsParts, ',') .. '}',
        '"car_models":[' .. table.concat(models, ',') .. ']',
        '"player_car":' .. jstr(ctx.playerModel), '"player_class":' .. jstr(mCls[0] or (ctx.classOf and ctx.classOf(0)) or nil),
        '"is_wet":' .. jbool(wet),
        '"weather_controller":' .. jstr(wCtrl), '"weather_type":' .. jint(wType),
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
        '"player_start_pos":' .. jint(st.startPos[0]),
        '"player_finish_pos":' .. jint(mPos[0] or (p and p.racePosition) or nil),
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
        '"tyre_wear_setting":' .. jnum(assist('tyresWear')),   -- (0.15) the column existed, the Lua never sent it (null in all 1005 reports)
        '"contacts_seen":' .. jint(Contacts.count),
        '"verve_ms_avg":' .. jnum(ctx.verveMs), '"lua_errors":' .. jint(ctx.luaErrors),
        '"session_key":' .. jstr(S.installId .. '-' .. tostring(st.t0) .. '-' .. tostring(ctx.track or '')),   -- for server-side de-duplication
        '"settings":' .. (ctx.settingsJson or 'null'),
        '"cars_detail":[' .. table.concat(detail, ',') .. ']',
    }
    -- (owner item 34) module:line of the first swallowed error this session, sent ONLY when present and never the
    -- message text (Verve.lua extracts it; the limit is written into that extraction).
    if ctx.firstErrAt then fields[#fields + 1] = '"first_err_at":' .. jstr(ctx.firstErrAt) end
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
                -- (0.16, decision 0031) LOG THE STATUS AND THE PostgREST CODE, NEVER THE BODY. This used to
                -- write up to 200 characters of the server's reply into the player's AC log, which is a file
                -- they may share when reporting a bug. The body is still READ below to recover a dropped
                -- column name - using it is fine, logging it is not.
                local prcode = ''
                if rejected then pcall(function() prcode = tostring(res.body):match('"code"%s*:%s*"([%w_]+)"') or 'unknown' end) end
                pcall(function() ac.log(string.format('Verve telemetry: %s (%s)%s', ok and 'sent' or 'failed', tostring(err or (res and res.status)), rejected and (' PostgREST ' .. prcode) or '')) end)
                if rejected and (tries or 0) < 8 then       -- one unknown column per reply: drop it and resend (bounded)
                    local col = tostring(res.body):match("Could not find the '([%w_]+)' column")
                    if col then post(withoutColumn(body, col), onDone, (tries or 0) + 1); return end
                end
                if rejected then S.pending = '' end        -- malformed row: drop it, don't retry forever
                if onDone then onDone(ok, rejected) end   -- (0.16) `rejected` lets a caller tell "retry later" from "this row is malformed, drop it"
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
    if not T.isRaceSession(sim) then st = nil; return end  -- (0.16, decision 0031) never a practice/qualifying row
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
    -- (0.16, decision 0031) after the pending flush and the session-change reset, so a leftover race row from
    -- a previous launch still goes out and a session change still resets - but no practice or qualifying
    -- session ever builds stats. With st left nil, T.abort also returns early, which is belt and braces.
    if not T.isRaceSession(sim) then return end
    if st == nil then st = newStats(sim) end
    local now = os.clock()
    if now - lastT >= 1.0 then
        lastT = now; pcall(sample, sim)
        local c = ctx
        if type(c) == 'function' then c = c() end            -- (Verve passes the builder: once a second, not every frame; an error in it
        if st and c and c.recState then                      -- is not caught here, so the caller's pcall counts it) mirror 'parked' live
            pcall(function()
                for i = 0, sim.carsCount - 1 do
                    local rs = c.recState(i)
                    if rs then st.mPark[i] = rs.parked == true end
                    if st.mCls[i] == nil and c.classOf then st.mCls[i] = c.classOf(i) end
                end
            end)
        end
    end
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
            if type(ctx) == 'function' then ctx = ctx() end    -- (outside the pcall below, so an error reaches the caller's count)
            sentThis = true
            pcall(function()
                local leaderLaps = 0
                for i = 0, sim.carsCount - 1 do local c = ac.getCar(i); if c and (c.lapCount or 0) > leaderLaps then leaderLaps = c.lapCount end end
                local real = leaderLaps >= 1 and (os.time() - st.t0) >= 60     -- a 15 s 'finished' race is a restart artefact
                -- (item 11 T1, 2026-10-22) `real and nil or 'restart'` ALWAYS yields 'restart': with real true
                -- it is `nil or 'restart'`, with real false it is `false or 'restart'`. So every normally
                -- finished race has been reported abort_reason "restart" since v0.14.1 (76f3f92), and anything
                -- filtering that field discards the real finishes. `completed` was always correct, so the data
                -- is recoverable - key on it, not on this field, for anything already collected.
                local body = T.buildReport(sim, ctx, real, (not real) and 'restart' or (T.ABORT_LEGACY and 'restart' or nil))
                post(body, function(ok2, rejected) if ok2 then S.sent = (S.sent or 0) + 1 elseif not rejected then S.pending = body end end)   -- a 4xx-rejected row is dropped, not re-queued
            end)
        end
    else
        flagT = 0
    end
end

function T.sentCount() return S.sent or 0 end

return T
