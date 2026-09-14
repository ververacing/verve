-- Verve / lib/career.lua
-- Knows what was launched: reads cfg/race.ini (the launcher's output) and recognises AC's own CAREER events
-- by matching track / layout / car / grid / laps against content/career/*/event*/event.ini, confirmed by the
-- opponents' names. Exposes the configured difficulty (the launcher's meter and every car's AI_LEVEL) so the
-- difficulty module can make those numbers real -- AC itself ignores them on at least some installs
-- (calibrated 2026-09-13: 60..100 gave identical lap times).
local C = {}
C.active = false        -- a career event is running
C.series, C.event = nil, nil
C.eventLevel = nil      -- the event's own AI_LEVEL (AC's built-in ramp: ~80 at Novice 1 up to ~97 at the top)
C.ramp = 0              -- 0..1 position of this event on that ramp (across every installed career event)
C.meter = 100           -- [RACE] AI_LEVEL of the launched race (the launcher's difficulty slider)
C.carLevels = {}        -- [i] = AI_LEVEL of CAR_i from race.ini (nil if absent)
C.track, C.layout, C.model, C.cars, C.laps = nil, nil, nil, 0, 0
C.sessionType = nil
C.info = ''

local scanned = false
local rampMin, rampMax = nil, nil
local events = {}       -- { {series=, event=, track=, layout=, model=, cars=, laps=, level=, names={...}} }
local detectedFor = nil -- session index the detection ran for

-- tiny INI parser: sections -> key -> value (last wins), keys upper-cased
local function parseIni(text)
    local out, cur = {}, nil
    if type(text) ~= 'string' then return out end
    for line in text:gmatch('[^\r\n]+') do
        local s = line:match('^%s*%[([^%]]+)%]')
        if s then cur = s:upper(); out[cur] = out[cur] or {}
        elseif cur then
            local k, v = line:match('^%s*([^=;#]+)%s*=%s*(.-)%s*$')
            if k then out[cur][k:upper():gsub('%s+$', '')] = v end
        end
    end
    return out
end

local function listDir(dir)
    local names = {}
    pcall(function()
        local r = io.scanDir(dir, '*', function(name) names[#names + 1] = name end)
        if type(r) == 'table' and #names == 0 then for _, n in ipairs(r) do names[#names + 1] = n end end
    end)
    return names
end

local function scanCareer()
    if scanned then return end
    scanned = true
    pcall(function()
        local root = ac.getFolder(ac.FolderID.Root) .. '/content/career'
        for _, series in ipairs(listDir(root)) do
            if series:match('^series%d+$') then
                local sdir = root .. '/' .. series
                local oppNames = {}
                local opp = parseIni(io.load(sdir .. '/opponents.ini', ''))
                for sec, kv in pairs(opp) do
                    if sec:match('^AI%d+$') and kv.NAME then oppNames[kv.NAME:lower()] = true end
                end
                for _, ev in ipairs(listDir(sdir)) do
                    if ev:match('^event%d+$') then
                        local ini = parseIni(io.load(sdir .. '/' .. ev .. '/event.ini', ''))
                        local race = ini.RACE
                        if race and race.TRACK then
                            local names = {}
                            for k in pairs(oppNames) do names[k] = true end
                            for sec, kv in pairs(ini) do
                                if sec:match('^CAR_%d+$') and kv.DRIVER_NAME and #kv.DRIVER_NAME > 0 then names[kv.DRIVER_NAME:lower()] = true end
                            end
                            local level = tonumber(race.AI_LEVEL) or 0
                            events[#events + 1] = {
                                series = series, event = ev,
                                track = (race.TRACK or ''):lower(), layout = (race.CONFIG_TRACK or ''):lower(),
                                model = (race.MODEL or ''):lower(), cars = tonumber(race.CARS) or 0,
                                laps = tonumber(ini.SESSION_0 and ini.SESSION_0.LAPS) or 0,
                                level = level, names = names,
                            }
                            if level > 0 then
                                rampMin = rampMin and math.min(rampMin, level) or level
                                rampMax = rampMax and math.max(rampMax, level) or level
                            end
                        end
                    end
                end
            end
        end
    end)
end

-- Read the launched race. Called once per session (cheap); safe to call every frame.
function C.detect()
    local sim = ac.getSim(); if not sim then return end
    local idx = sim.currentSessionIndex or 0
    if detectedFor == idx then return end
    detectedFor = idx
    C.active, C.series, C.event, C.eventLevel, C.ramp = false, nil, nil, nil, 0
    C.meter, C.carLevels = 100, {}
    pcall(function()
        local ini = parseIni(io.load(ac.getFolder(ac.FolderID.Cfg) .. '/race.ini', ''))
        local race = ini.RACE or {}
        C.track = (race.TRACK or ''):lower(); C.layout = (race.CONFIG_TRACK or ''):lower()
        C.model = (race.MODEL or ''):lower(); C.cars = tonumber(race.CARS) or sim.carsCount
        C.laps = tonumber(ini.SESSION_0 and ini.SESSION_0.LAPS) or 0
        C.sessionType = ini.SESSION_0 and ini.SESSION_0.TYPE or nil
        C.meter = tonumber(race.AI_LEVEL) or 100
        local raceNames = {}
        for sec, kv in pairs(ini) do
            local n = sec:match('^CAR_(%d+)$')
            if n then
                n = tonumber(n)
                if kv.AI_LEVEL then C.carLevels[n] = tonumber(kv.AI_LEVEL) end
                if kv.DRIVER_NAME and #kv.DRIVER_NAME > 0 and n > 0 then raceNames[#raceNames + 1] = kv.DRIVER_NAME:lower() end
            end
        end
        scanCareer()
        for _, e in ipairs(events) do
            if e.track == C.track and e.layout == C.layout and e.model == C.model and e.cars == C.cars then
                -- the same track/car/grid could be a quick race: require the launcher's opponent names
                local hit = 0
                for _, nm in ipairs(raceNames) do if e.names[nm] then hit = hit + 1 end end
                if hit >= 1 or #raceNames == 0 then
                    C.active, C.series, C.event, C.eventLevel = true, e.series, e.event, e.level
                    if rampMin and rampMax and rampMax > rampMin then
                        C.ramp = math.max(0, math.min(1, (e.level - rampMin) / (rampMax - rampMin)))
                    end
                    break
                end
            end
        end
    end)
    if C.active then
        C.info = string.format('Career %s/%s (event level %d, ramp %.2f, meter %d)', C.series, C.event, C.eventLevel or 0, C.ramp, C.meter)
    else
        C.info = string.format('Not a career event (meter %d)', C.meter)
    end
    pcall(function() ac.log('Verve career: ' .. C.info) end)
end

function C.reset() detectedFor = nil end

return C
