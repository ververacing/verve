-- Verve  -- original AC AI enhancer (human pace variability + tyre/weather awareness +
-- self-recovery + our own racecraft). Not affiliated with other AI mods. CSP public APIs only.

local Human     = require('lib.human')
local Recovery  = require('lib.recovery')
local Classes   = require('lib.classes')
local Racecraft = require('lib.racecraft')
local Overrides = require('lib.overrides')
local Update    = require('lib.update')
local Drivers   = require('lib.drivers')
local Troublespots = require('lib.troublespots')
local Feed      = require('lib.feed')
local Career    = require('lib.career')       -- recognises AC career events; reads the launcher's difficulty numbers
local Difficulty = require('lib.difficulty')  -- makes those numbers real (AC ignores them on some installs)
local Telemetry = require('lib.telemetry')
local Fault     = require('lib.fault')        -- who caused each contact, and the time penalty it costs (owner's ask 2026-09-17)
local Strategy  = require('lib.strategy')     -- planned manoeuvres (racecraft drives it; Verve owns the toggle + status)    -- opt-in anonymous race reports         -- structured race feed (opt-in; consumed by Verve Booth / Race Engineer)
Racecraft.penCap = Fault.penCap            -- penalty throttle caps, read by racecraft's throttle setter (shared table)
Fault.attach(Recovery.recentDrops, Feed.event)
local Diag = nil; pcall(function() Diag = require('diag') end)   -- LOCAL dev diagnostics; absent in the shipped build
-- LOCAL test harness (tools/harness.py writes harness.lua right before launching a run, and it self-expires):
-- can put the player's car on autopilot, override settings for the run, and label the diagnostics file.
-- Never shipped; ignored unless the file is fresh, so a stale one can't hijack a real race.
local Harness = nil
pcall(function()
    local h = require('harness')
    if type(h) == 'table' and type(h.expires) == 'number' and h.expires > os.time() then Harness = h end
    -- trouble-spot overrides apply at LOAD: the session reset (which loads the learned map) can run before the first update
    if Harness and type(Harness.troublespots) == 'table' then for k, v in pairs(Harness.troublespots) do Troublespots[k] = v end end
end)
local harnessApplied, autopilotArmed, harnessT = false, false, 0
local shiftSet = {}                              -- per car: shift thresholds applied (see Racecraft.SHIFT_UP)
local harnessStartT, harnessStarted = 0, false   -- "press Drive" on AC's pre-session screen (ac.tryToStart)
local harnessEndT = 0                            -- seconds a timed session (practice/quali) has been over
local harnessDoneT, harnessQuit = 0, false       -- race-over timer / already asked AC to quit

-- defaults for the global settings (also used for "reset to defaults")
-- Core behaviour (humanVar, classPhys, racecraft, recovery, crashRepair, troubleSpots) is what Verve IS: it's
-- always on when Verve is enabled and has no user toggle (the keys remain so a test harness can A/B them).
-- The user-facing options are the ones a player might genuinely want different.
local DEFAULTS = {
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
    crashRepair = true, troubleSpots = true, raceFeed = false, showAdvanced = false,
    careerCurve = true, shareData = false, strategy = true,
    intensity = 0.5, rcIntensity = 0.7, baseGrip = 1.20,
}
local CORE = { 'humanVar', 'classPhys', 'racecraft', 'recovery', 'crashRepair', 'troubleSpots' }

-- S = persisted store; G = working copy the game actually reads (so "session-only" edits can
-- be live without being saved until the user commits).
local S = ac.storage({
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
    crashRepair = true, troubleSpots = true, raceFeed = false, showAdvanced = false,
    careerCurve = true, shareData = false, strategy = true,
    intensity = 0.5, rcIntensity = 0.7, baseGrip = 1.20,
    autosave = true, schema = 1,
})
-- settings migration: 0.12 made crash repair + trouble spots core (they were opt-in experiments; a day-long
-- A/B showed crash repair is the single biggest thing Verve does). A stored "false" from an older install
-- would silently keep them off, so bump them once.
if (S.schema or 1) < 2 then S.crashRepair = true; S.troubleSpots = true; S.schema = 2 end
local drsCd = {}
local G = {}
for k in pairs(DEFAULTS) do G[k] = S[k] end
for _, k in ipairs(CORE) do G[k] = true end   -- core is always on (a harness override can still flip it for a run)

local function setG(k, v) G[k] = v; if S.autosave then S[k] = v end end
local function commitGlobals() for k in pairs(DEFAULTS) do S[k] = G[k] end end
local function revertGlobals() for k in pairs(DEFAULTS) do G[k] = S[k] end end
local function resetGlobals() for k, v in pairs(DEFAULTS) do G[k] = v; if S.autosave then S[k] = v end end end
local function globalsDirty() for k in pairs(DEFAULTS) do if G[k] ~= S[k] then return true end end return false end

-- detect other AI-control mods that also drive physics.setExtraAIGrip
local otherAI = nil
do
    pcall(function()
        local base = ac.getFolder(ac.FolderID.ACApps) .. '/lua/'
        for _, name in ipairs({ 'AIWhisperer', 'AIFlood', 'BrokenCarsKicker', 'SmartAI' }) do
            if io.dirExists(base .. name) then otherAI = name; break end
        end
    end)
end

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local managed = 0

-- Session reset: everything per-session starts over. Called from ac.onSessionStart AND from the restart
-- detector below -- AC's "Restart session" does NOT fire onSessionStart, and without a reset the modules
-- carried stale state into the new start (recovery saw a field that "had moved" now sitting still on the
-- grid and crash-repaired every car in the first 8 s of the re-run -- seen 2026-09-13, Imola career).
local telemetryCtx   -- defined below (needs the modules)
local function sessionReset(restart)
    pcall(function() local okS, simR = pcall(ac.getSim); if okS and simR then Telemetry.abort(restart and 'restart' or 'session change', simR, telemetryCtx()) end end)
    pcall(Career.reset)
    pcall(Difficulty.reset)
    harnessStarted, harnessStartT, autopilotArmed, harnessT, harnessEndT = false, 0, false, 0, 0
    pcall(Classes.reset)
    pcall(Human.reset)            -- per-track distances
    pcall(Racecraft.reset)
    shiftSet = {}
    pcall(Fault.reset)
    -- driver profiles are session-only: wipe every race. NOT on a restart: the picks should survive it, and
    -- the AI-level overrides persist in physics across a restart, so the remembered base levels stay valid
    if not restart then pcall(Drivers.reset) end
    pcall(Recovery.reset)         -- clear per-car recovery + pit-rescue state
    pcall(Troublespots.reset)     -- save the old track's learned hot spots, load the new track's
    pcall(Feed.reset)
    if Diag then pcall(Diag.reset) end
end

-- Restart detector: the field had been moving, and now EVERY car is stationary on lap 0 in the grid zone
-- (just before the line). That only happens on a restart -- a real-race pile-up never stops all cars at
-- once inside the last 8% of the lap with nobody past the line.
local fieldMoved, racedT = false, 0
local function detectRestart(sim, dt)
    local anyMoving, allGrid = false, true
    for i = 0, sim.carsCount - 1 do
        local c = ac.getCar(i)
        if c then
            if (c.speedKmh or 0) > 30 then anyMoving = true end
            local sp = c.splinePosition or 0
            if (c.lapCount or 0) > 0 or (c.speedKmh or 0) > 1 or not (sp > 0.92 or sp < 0.03) then allGrid = false end
        end
    end
    -- arm only after the field has genuinely raced (a quali->race transition briefly shows moving cars,
    -- then a stationary grid: that is not a restart -- seen 2026-09-14 as duplicate diag files)
    if anyMoving then racedT = racedT + (dt or 0); if racedT > 10 then fieldMoved = true end
    elseif allGrid and fieldMoved then
        fieldMoved = false; racedT = 0
        pcall(function() ac.log('Verve: session restart detected, resetting') end)
        sessionReset(true)
    end
end

function script.update(dt)
    if Harness then
        if not harnessApplied then
            harnessApplied = true
            if type(Harness.settings) == 'table' then
                for k, v in pairs(Harness.settings) do if DEFAULTS[k] ~= nil then G[k] = v end end   -- session only, never saved
            end
            if type(Harness.recovery) == 'table' then for k, v in pairs(Harness.recovery) do Recovery[k] = v end end
            if type(Harness.racecraft) == 'table' then for k, v in pairs(Harness.racecraft) do Racecraft[k] = v end end
            if type(Harness.fault) == 'table' then for k, v in pairs(Harness.fault) do Fault[k] = v end end
            if Diag and Harness.label then Diag.label = tostring(Harness.label) end
        end
        -- AC loads to a pre-session screen and waits for the Drive button; nothing (not even the AI grid)
        -- moves until it's pressed. Press it a few seconds after load, and keep trying until it takes.
        local okS, simH = pcall(ac.getSim)
        if okS and simH and not harnessStarted then
            harnessStartT = harnessStartT + dt
            if harnessStartT > 4.0 and simH.isInMainMenu then
                harnessStartT = 0
                pcall(function() harnessStarted = ac.tryToStart(true) == true end)
                if harnessStarted then pcall(function() ac.log('Verve harness: pressed Drive') end) end
            elseif harnessStartT > 4.0 and not simH.isInMainMenu then
                harnessStarted = true      -- already driving (someone pressed it, or no such screen this session)
            end
        end
        -- WEEKEND: a timed practice / qualifying session is over -> advance to the next session (AC waits
        -- for a click on the results screen otherwise). The race session ends itself.
        if okS and simH and (simH.raceSessionType == ac.SessionType.Practice or simH.raceSessionType == ac.SessionType.Qualify)
           and simH.isSessionStarted and (simH.sessionTimeLeft or 1) <= 0 then
            harnessEndT = harnessEndT + dt
            if harnessEndT > 8.0 then
                harnessEndT = -20.0     -- (don't hammer it: retry every ~28 s)
                pcall(function() ac.log('Verve harness: session over, advancing'); ac.tryToSkipSession() end)
            end
        end
        -- RACE OVER (every car parked in the pits and still, well into a race session): quit AC gracefully
        -- so it autosaves the replay -- a killed process saves nothing, and the produced broadcasts
        -- need the replay.
        if Harness.shutdownAtEnd and okS and simH and simH.raceSessionType == ac.SessionType.Race and simH.isSessionStarted then
            local allParked, anyLap = true, false
            for i = 0, simH.carsCount - 1 do
                local c = ac.getCar(i)
                if c then
                    if not (c.isInPitlane and (c.speedKmh or 0) < 1) then allParked = false end
                    if (c.lapCount or 0) >= 1 then anyLap = true end
                end
            end
            if allParked and anyLap then
                harnessDoneT = harnessDoneT + dt
                if harnessDoneT > 20.0 and not harnessQuit then
                    harnessQuit = true
                    pcall(function() ac.log('Verve harness: race over, shutting AC down (replay autosave)'); ac.shutdownAssettoCorsa() end)
                end
            else
                harnessDoneT = 0
            end
        end
        if Harness.autopilot and not autopilotArmed then
            -- armed 2 s after the Drive press (the countdown), not after the session starts: armed at the green
            -- light the player car sat driverless for 2 s and the car behind ran into it (2026-09-16)
            if okS and simH and (harnessStarted or simH.isSessionStarted) then
                harnessT = harnessT + dt
                if harnessT > 2.0 then
                    autopilotArmed = true
                    pcall(function() physics.setCarAutopilot(true, true) end)
                    -- chase camera for unattended runs: markedly lighter on the GPU than the cockpit view
                    pcall(function() ac.setCurrentCamera(ac.CameraMode.Drivable); ac.setCurrentDrivableCamera(ac.DrivableCamera.Chase) end)
                    -- randomised driver profiles, the way a real grid will be run (same as the UI button)
                    if Harness.randomizeDrivers then
                        pcall(function()
                            Drivers.randomizeGrid()
                            local parts = {}
                            for i = 1, simH.carsCount - 1 do
                                local k = Drivers.profileOf(i)
                                parts[#parts + 1] = string.format('%d=%s', i, k and Drivers.nameOf(k) or '-')
                            end
                            ac.log('Verve harness: driver profiles ' .. table.concat(parts, ', '))
                        end)
                    end
                    -- fixed grid profiles ({all=key, slots={[i]=key}}), e.g. a Rookie field with one star at the back
                    if type(Harness.profiles) == 'table' then
                        pcall(function()
                            Drivers.applyFixed(Harness.profiles)
                            ac.log('Verve harness: fixed profiles all=' .. tostring(Harness.profiles.all))
                        end)
                    end
                end
            end
        end
    end
    if not G.enabled then
        -- (local dev diagnostics still log a DISABLED race, so a baseline run can be compared)
        if Diag then pcall(function() Diag.update(dt, { managed = 0 }) end) end
        return
    end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end

    detectRestart(sim, dt)                    -- "Restart session" doesn't fire onSessionStart; catch it ourselves
    Career.detect()                           -- once per session: is this a career event? what did the launcher configure?
    Difficulty.CAREER_CURVE = G.careerCurve
    Drivers.LOCKED = Career.active            -- career: the difficulty curve sets the field; profiles are off
    Drivers.autoMatch()                       -- once per session: AC driver names that match the roster get their profile
    Human.ENABLED       = true
    Human.HUMAN_VAR     = G.humanVar
    Human.INTENSITY     = G.intensity
    Human.HUMAN_ERRORS  = G.humanErrors
    Human.CLASS_PHYSICS = G.classPhys
    Racecraft.ENABLED     = G.racecraft
    Strategy.ENABLED      = G.strategy ~= false
    Racecraft.INTENSITY   = G.rcIntensity
    Racecraft.VARIABILITY = G.intensity     -- spreads per-driver aggression across the field
    Overrides.autosave    = S.autosave
    Racecraft.beginFrame()

    local behaviourOn = G.humanVar or G.classPhys or G.racecraft
    local n = 0
    local diagPer = {}    -- per-car values we applied this frame (only read by the local diagnostics logger)
    -- start at 0 so the player's own car is managed WHEN (and only when) it's under AI control
    -- (Ctrl+C takeover): the isAIControlled gate below means we never touch it while you drive.
    for i = 0, sim.carsCount - 1 do
        pcall(function()
            local car = ac.getCar(i)
            if not car or not car.isAIControlled then return end
            if car.isInPitlane then return end          -- never touch a car doing a pit stop (player or AI)
            Drivers.applyPace(i, Difficulty.levelFor(i)) -- configured/career difficulty, then the driver profile's pace on top
            -- shift-point study (harness A/B): R.SHIFT_UP > 0 sets the AI's shift thresholds once per car (stops CSP's own dynamic logic)
            if Racecraft.SHIFT_UP > 0 and not shiftSet[i] and (car.rpmLimiter or 0) > 0 then
                shiftSet[i] = true
                -- a value <= 1.5 is a fraction of THIS car's limiter (0.90 as a raw number short-shifted four models to half revs, 2026-09-17)
                local up, down = Racecraft.SHIFT_UP, Racecraft.SHIFT_DOWN
                if up <= 1.5 then up = up * car.rpmLimiter end
                if down <= 1.5 then down = down * car.rpmLimiter end
                pcall(physics.setAIShiftingThresholds, i, up, down)
            end
            local gOff, cOff = Human.getModifiers(i)
            local gripApplied = nil
            if G.controlGrip then
                local grip = G.baseGrip + gOff
                -- launch assist: a brief traction boost off a standing start (AC's AI bogs down off the
                -- line), fading out as the car gets up to speed. Only at the very start of lap 1.
                if (car.lapCount or 0) == 0 and (car.splinePosition or 1) < 0.012 then
                    local s = car.speedKmh or 0
                    if s < 90 then grip = grip + 0.07 * clamp(1 - s / 90, 0, 1) end
                end
                gripApplied = clamp(grip, 0.5, 1.6)
                physics.setExtraAIGrip(i, gripApplied)
            end
            local rcCaut = Racecraft.evaluate(i, dt)
            local cautApplied = clamp(1.0 + cOff + rcCaut, 0.0, 16.0)
            if behaviourOn then
                physics.setAICaution(i, cautApplied)
            end
            if Diag then diagPer[i] = { hG = gOff, hC = cOff, grip = gripApplied, rc = rcCaut, caut = cautApplied } end
            -- Formula DRS discipline: close DRS when the game says it isn't available (outside a
            -- zone / not within range). Toggle-based with a cooldown so it doesn't flip-flop.
            if G.drsDiscipline and Classes.keyOf(i) == 'formula' and car.drsPresent
               and car.drsActive and not car.drsAvailable then
                local nowc = os.clock()
                if (drsCd[i] or 0) < nowc then
                    local c = ac.overrideCarControls(i)
                    if c then c.drs = true end
                    drsCd[i] = nowc + 1.0
                end
            end
            if G.controlGrip or behaviourOn then n = n + 1 end
        end)
    end
    managed = n

    Recovery.ENABLED = G.recovery
    Recovery.CRASH_REPAIR = G.crashRepair
    if G.recovery then Recovery.update(dt) end
    Troublespots.ENABLED = G.troubleSpots
    Troublespots.update(dt)

    if Diag then pcall(function()
        Diag.update(dt, {
            managed = managed, attacking = Racecraft.attacking, defending = Racecraft.defending,
            recovering = Recovery.count, crashRepairs = Recovery.repairedCount,
            limpRepairs = Recovery.limpCount, retired = Recovery.retiredCount,
            hotSpots = Troublespots.hotCount(), crashRisk = Troublespots.crashiness(), isOval = Racecraft.isOval,
            peak = Troublespots.peakHeat(), storeLen = Troublespots.storeLen, saveOk = Troublespots.lastSaveOk,
            per = diagPer, rc = Racecraft.last, recState = Recovery.stateOf, cv2 = Racecraft.cv2, episodes = Strategy.episodes,
            recentDrops = Recovery.recentDrops, dropN = Recovery.dropN, dropOK = Recovery.dropOK, dropsOff = Recovery.dropsOff,
            mvN = Strategy.attempts, mvOK = Strategy.ok, mvT = Strategy.byTypeString(), gateN = Recovery.gateMoves,
            fwdSign = (Recovery.fwdSign and Recovery.fwdSign() or 0), dropFlips = Recovery.dropFlips,
            suspPits = Recovery.suspPitCount, faults = Fault.count, penalties = Fault.penCount,
        })
    end) end
    Feed.ENABLED = G.raceFeed
    if G.raceFeed then pcall(Feed.update, dt, { rc = Racecraft.last, recState = Recovery.stateOf, recentDrops = Recovery.recentDrops }) end
    pcall(Fault.update, dt)
    Telemetry.ENABLED = G.shareData == true
    Telemetry.VERSION = Update.LOCAL_VERSION or '0.0.0'
    Telemetry.UNATTENDED = Harness ~= nil and Harness.autopilot == true
    if Telemetry.ENABLED then pcall(Telemetry.update, dt, telemetryCtx()) end
end

-- everything the anonymous race report needs from the other modules (no names, no paths)
telemetryCtx = function()
    local settings = {}
    for _, k in ipairs({ 'humanErrors', 'drsDiscipline', 'controlGrip', 'careerCurve', 'intensity', 'rcIntensity', 'baseGrip' }) do
        local v = G[k]; settings[#settings + 1] = string.format('"%s":%s', k, type(v) == 'number' and string.format('%.2f', v) or tostring(v == true))
    end
    local pu, au = 0, 0
    pcall(function() pu, au = Drivers.counts() end)
    local playerModel = ''; pcall(function() playerModel = ac.getCarID(0) or '' end)
    local cspBuild = nil; pcall(function() cspBuild = ac.getPatchVersionCode() end)
    return {
        classOf = Classes.keyOf, recState = Recovery.stateOf, levelOf = Difficulty.levelFor,
        meter = Career.meter, isCareer = Career.active, careerEvent = Career.active and (Career.series .. '/' .. Career.event) or nil,
        laps = Career.laps, playerModel = playerModel, cspBuild = cspBuild,
        retiredByVerve = Recovery.retiredCount, crashRepairs = Recovery.repairedCount, limpRepairs = Recovery.limpCount, suspPits = Recovery.suspPitCount,
        drops = Recovery.dropN, dropsOk = Recovery.dropOK, troubleSpots = Troublespots.hotCount(),
        faults = Fault.count, penalties = Fault.penCount,
        profilesUsed = pu, archetypesUsed = au,
        appliedJson = string.format('{"meter":%d,"career":%s,"curve":%s,"ramp":%.2f}', Career.meter or 100, tostring(Career.active), tostring(G.careerCurve == true), Career.ramp or 0),
        settingsJson = '{' .. table.concat(settings, ',') .. '}',
    }
end
ac.onRelease(function() pcall(function() local okS, simR = pcall(ac.getSim); if okS and simR then Telemetry.abort('quit', simR, telemetryCtx()) end end) end)

ac.onSessionStart(function()
    -- harness: every session of a weekend needs its own Drive press + autopilot arming
    fieldMoved, racedT = false, 0
    sessionReset()
end)

-- ------------------------------- UI -------------------------------
local CLASS_OPTS = { 'auto', 'formula', 'formula_jr', 'prototype', 'hypercar', 'gt', 'road', 'touring', 'vintage', 'drift', 'kart', 'rally', 'nascar' }

local function toggle(label, key, help)
    if ui.checkbox(label, G[key]) then setG(key, not G[key]) end
    if help and ui.itemHovered() then ui.setTooltip(help) end
end

local function comboFor(tag, previewText, currentKey, opts, onPick)
    ui.setNextItemWidth(120)
    ui.combo(tag, previewText, nil, function()
        for _, opt in ipairs(opts) do
            if ui.selectable(opt, opt == currentKey) then onPick(opt) end
        end
    end)
end

-- searchable, class-filtered driver dropdown for one grid slot (index). Type to narrow the list.
local driverFilter = {}
local function driverComboFor(idx)
    local cls = Classes.keyOf(idx)
    local curKey = Drivers.profileOf(idx)
    local preview = curKey and Drivers.nameOf(curKey) or '- driver -'
    ui.setNextItemWidth(150)
    ui.combo('##drv' .. idx, preview, nil, function()
        local typed = ui.inputText('search##ds' .. idx, driverFilter[idx] or '')
        if type(typed) == 'string' then driverFilter[idx] = typed end
        local fl = (driverFilter[idx] or ''):lower()
        if ui.selectable('- none -', curKey == nil) then Drivers.setProfile(idx, nil) end
        for _, d in ipairs(Drivers.rosterFor(cls)) do
            if fl == '' or d.name:lower():find(fl, 1, true) then
                if ui.selectable(d.name, d.key == curKey) then Drivers.setProfile(idx, d.key) end
            end
        end
    end)
end

-- DRIVER is per grid SLOT (every individual racer), so identical cars can each get a different
-- driver. One row per car on the grid, labelled by number + its in-game driver name.
local function driverGridList()
    local sim = ac.getSim()
    if not sim then ui.textWrapped('No session yet. Open Verve on the grid before the lights.'); return end
    if sim.carsCount <= 0 then ui.textWrapped('No cars in this session.'); return end
    for i = 0, sim.carsCount - 1 do          -- slot 0 is the player's car (for Ctrl+C takeover)
        local drv = 'Car ' .. (i + 1)
        pcall(function() local d = ac.getDriverName(i); if type(d) == 'string' and #d > 0 then drv = d end end)
        ui.text(string.format('%2d.', i + 1))
        ui.sameLine()
        driverComboFor(i)
        -- AC's own driver label. Once a profile is picked the AI is renamed to it, so this reads the same;
        -- when no profile is set it's just AC's label (Content Manager's name) and does nothing.
        -- (sameLine only when a label follows -- a dangling sameLine pulled the NEXT row up onto this one)
        if i == 0 then ui.sameLine(); ui.textColored(drv .. '  (you)', rgbm(0.6, 0.6, 0.6, 1))
        elseif not Drivers.profileOf(i) then ui.sameLine(); ui.textColored(drv, rgbm(0.5, 0.5, 0.5, 1)) end
    end
end

-- CLASS is a per-MODEL physics setting (all cars of a model share it) -- one compact row per model.
local function classOverrideList()
    local seen, models = {}, {}
    pcall(function()
        local sim = ac.getSim()
        if not sim then return end
        for i = 0, sim.carsCount - 1 do
            local id = nil
            pcall(function() id = ac.getCarID(i) end)
            if id and not seen[id] then
                seen[id] = true
                local nm = id
                pcall(function() nm = ac.getCarName(i) or id end)
                models[#models + 1] = { id = id, idx = i, name = nm }
            end
        end
    end)
    table.sort(models, function(a, b) return a.name < b.name end)

    if #models == 0 then
        ui.textWrapped('No cars in this session.')
    else
        for _, m in ipairs(models) do
            local auto = Classes.autoKeyOf(m.idx)
            local curClass = Overrides.classOverride(m.id) or 'auto'
            local classPreview = (curClass == 'auto') and (auto and ('auto (' .. auto .. ')') or 'auto') or curClass
            ui.text(m.name)
            ui.sameLine()
            comboFor('##cls' .. m.id, classPreview, curClass, CLASS_OPTS, function(opt) Overrides.setClass(m.id, opt) end)
            ui.sameLine()
            if ui.button('Reset##r' .. m.id) then Overrides.resetCar(m.id) end
        end
    end

    -- saved overrides for models NOT in this race (shown separately so the list isn't confusing)
    local others = {}
    for _, id in ipairs(Overrides.ids()) do if not seen[id] then others[#others + 1] = id end end
    if #others > 0 then
        ui.newLine()
        ui.textColored('Saved overrides for other cars (not in this race):', rgbm(0.55, 0.55, 0.55, 1))
        table.sort(others)
        for _, id in ipairs(others) do
            local curClass = Overrides.classOverride(id) or 'auto'
            local classPreview = (curClass == 'auto') and 'auto' or curClass
            ui.text(id)
            ui.sameLine()
            comboFor('##clsO' .. id, classPreview, curClass, CLASS_OPTS, function(opt) Overrides.setClass(id, opt) end)
            ui.sameLine()
            if ui.button('Reset##rO' .. id) then Overrides.resetCar(id) end
        end
    end
end

function script.windowMain()
    ui.pushFont(ui.Font.Title)
    ui.textColored('Verve', rgbm(0.98, 0.85, 0.02, 1))   -- brand yellow (#FBDA06 on near-black)
    ui.popFont()
    ui.sameLine()
    ui.textColored('AI that feels human', rgbm(0.6, 0.6, 0.6, 1))

    Update.check()
    if Update.latest then
        ui.textColored('Update available: v' .. Update.latest .. (Update.summary and ('  -  ' .. Update.summary) or ''), rgbm(0.98, 0.85, 0.02, 1))
        if Update.downloadUrl then
            if ui.button('Get the update##upd') then pcall(function() os.openURL(Update.downloadUrl) end) end
            ui.sameLine(); ui.textColored(Update.downloadUrl, rgbm(0.5, 0.5, 0.5, 1))
        end
    end

    ui.separator()
    if ui.checkbox('Enable Verve', G.enabled) then setG('enabled', not G.enabled) end

    -- manual escape hatch: unstick YOUR car (repair + drop back on the racing line facing forward)
    if ui.button('Reset my car (unstick)') then
        -- Always the player's own car (index 0 in single-player), NOT the focused camera car -- otherwise
        -- watching another driver would reset THAT opponent.
        pcall(function() Recovery.forceRecover(0) end)
    end
    if ui.itemHovered() then ui.setTooltip('Stuck, beached, or wedged in the pits? Repairs your car and drops it back on the racing line facing forward. Press it WHILE stuck -- a car that has already retired can\'t be brought back.') end

    -- save / session-only bar
    local as = S.autosave
    if ui.checkbox('Auto-save changes', as) then
        S.autosave = not as
        Overrides.setAutosave(S.autosave)
        if S.autosave then commitGlobals() end
    end
    if ui.itemHovered() then ui.setTooltip('On: every change saves instantly. Off: changes are LIVE for this race but only persist when you press Save.') end
    if not S.autosave then
        if globalsDirty() or Overrides.dirty() then
            if ui.button('Save changes') then commitGlobals(); Overrides.save() end
            ui.sameLine()
            if ui.button('Revert') then revertGlobals(); Overrides.revert() end
            ui.sameLine()
            ui.textColored('unsaved (live this race)', rgbm(1, 0.7, 0.2, 1))
        else
            ui.textColored('all saved', rgbm(0.5, 0.75, 0.45, 1))
        end
    end
    ui.newLine()

    if otherAI then
        ui.textColored('Heads up: "' .. otherAI .. '" is installed.', rgbm(1, 0.7, 0.2, 1))
        ui.textWrapped('It also controls AI grip, so running both fights over the same setting. ' ..
            'Turn off "Control AI grip" below to defer to it (Verve still self-recovers), ' ..
            'or disable the other app to let Verve drive.')
        ui.separator()
    end

    ui.text('What Verve does (always on)')
    ui.textWrapped('Human pace variability  -  class-aware tyre, wet and dirty-air physics  -  racecraft (overtaking, defending, blue flags, yellow flags)  -  self-recovery with crash repair (a stuck car is repaired and set back on the racing line; genuinely wrecked cars retire)  -  trouble-spot learning per track.')
    if ui.itemHovered() then ui.setTooltip('These are Verve. They can\'t be half-enabled: turn Verve off to get stock AC.') end

    ui.newLine()
    ui.text('Options')
    toggle('Human errors', 'humanErrors', 'Occasional gentle bobbles on forgiving cars. Never on Formula/Prototype/Hypercar. Grip-slewed so it will not spin cars.')
    toggle('Career: scale difficulty across the series', 'careerCurve', 'In AC career events the difficulty meter picks a pace band and each event moves you through it: soft first series, a real fight at the end, never leaving the band. Off = every career event at the meter\'s flat level. (Outside career the meter always applies as set.)')
    toggle('Tactics: set-up passes, late-brake lunges, switchbacks', 'strategy', 'Planned manoeuvres on top of the reactive racecraft, per class (a GT driver out-brakes, a formula driver sets it up on the straight, a stock car slingshots). Unlocked from 90 on the difficulty meter; a driver\'s pace rating decides how much of the playbook they use (a Rookie never switchbacks, a Veteran does).')
    toggle('Send anonymous race stats to improve Verve', 'shareData', 'After each race, send one small anonymous summary (track, cars, laps, difficulty, finishers, incidents, repairs, your positions and lap times). No names, no gamer tag, no paths, no hardware ids. Off by default.')
    toggle('Formula DRS discipline', 'drsDiscipline', 'On Formula cars, close DRS when the game says it is not available (outside a DRS zone or not within range). In-zone DRS is left to the game.')
    if ui.checkbox('Advanced', G.showAdvanced) then setG('showAdvanced', not G.showAdvanced) end
    if G.showAdvanced then
        toggle('Control AI grip', 'controlGrip', 'Verve sets each AI car grip = base + variability. Turn OFF to defer grip to another AI mod (recovery still works).')
        toggle('Race feed (for Verve Booth / Race Engineer)', 'raceFeed', 'Writes a structured, timestamped race feed (positions, gaps, overtakes, incidents, pits, and Verve\'s own decisions) to Documents/Assetto Corsa/verve_feed/ for companion tools. Off unless you use them.')
    end

    ui.newLine()
    ui.text('Tuning')
    local iv = ui.slider('Variability intensity##iv', G.intensity, 0.0, 1.5, '%.2f')
    if iv ~= G.intensity then setG('intensity', iv) end
    if ui.itemHovered() then ui.setTooltip('Per-driver spread: pace/consistency differences AND how much drivers vary in aggression, so the field isn\'t uniform. 0 = robotic/identical, 0.5 = subtle (default), 1.5 = dramatic.') end
    local rc = ui.slider('Racecraft intensity##rc', G.rcIntensity, 0.0, 1.5, '%.2f')
    if rc ~= G.rcIntensity then setG('rcIntensity', rc) end
    if ui.itemHovered() then ui.setTooltip('How hard the field attacks/defends. 0 = passive, 0.7 = default, 1.5 = elbows out.') end
    local bg = ui.slider('Base AI grip##bg', G.baseGrip, 0.85, 1.50, '%.2f')
    if bg ~= G.baseGrip then setG('baseGrip', bg) end
    if ui.itemHovered() then ui.setTooltip('Grip the AI has for its own racing line. 1.20 = stock AC AI (default; line speeds are calibrated for this). Below that = more human/on-the-edge but they wash wide if too low. Above 1.20 = extra stick + speed (keeps them planted / competitive at lower difficulty). Pace also scales with the race difficulty %.') end

    ui.newLine()
    ui.separator()
    ui.textColored('Drivers (per grid slot)', rgbm(0.6, 0.6, 0.6, 1))
    ui.textWrapped('Give any individual racer its own driver -- a real racer or a generic archetype -- and each grid slot is separate, so even a grid of identical cars can be all different drivers. Each gets that driver\'s pace, aggression and risk. Session-only, resets each race. Tip: pause on the grid with ESC to set up, or just hit Randomize.')
    if Career.active then
        ui.textColored('Career event: driver profiles are off. The career difficulty curve sets the field (see Options).', rgbm(0.8, 0.7, 0.4, 1))
        ui.textColored(Difficulty.describe(), rgbm(0.6, 0.6, 0.6, 1))
    else
        if ui.button('Randomize driver grid') then Drivers.randomizeGrid() end
        if ui.itemHovered() then ui.setTooltip('Assign every AI car a unique driver from its class (overflow uses the Rookie / Midfielder / Veteran archetypes). Session-only, resets each race.') end
        ui.sameLine()
        if ui.button('Clear drivers') then Drivers.clearAll() end
        driverGridList()
    end
    ui.newLine()
    ui.textColored('Car class (per model -- physics)', rgbm(0.6, 0.6, 0.6, 1))
    ui.textWrapped('Auto-detected from each car and drives its physics (warm-up, wet, mistakes). Override if it guesses wrong -- applies to every car of that model.')
    classOverrideList()
    ui.newLine()
    if ui.button('Reset settings to defaults') then resetGlobals() end
    ui.sameLine()
    if ui.button('Clear all car overrides') then Overrides.resetAll() end

    ui.newLine()
    ui.separator()
    ui.textColored('Status', rgbm(0.6, 0.6, 0.6, 1))
    if not G.enabled then
        ui.text('Verve is OFF.')
    else
        ui.text(string.format('AI cars managed: %d', managed))
        if G.racecraft then
            ui.text(string.format('Attacking: %d   Defending: %d', Racecraft.attacking or 0, Racecraft.defending or 0))
            ui.text('Track read as: ' .. (Racecraft.isOval and 'Oval / speedway (groove racing on)' or 'Road course'))
            if G.strategy ~= false then ui.text(string.format('Planned manoeuvres: %d (%d gained a place)', Strategy.attempts or 0, Strategy.ok or 0)) end
        end
        if G.troubleSpots then
            ui.text(string.format('Trouble spots learned on this track: %d', Troublespots.hotCount()))
            local crash = Troublespots.crashiness()
            if crash > 0.05 then ui.text(string.format('Track crash-risk: %d%% (field calmed to suit)', math.floor(crash * 100 + 0.5))) end
        end
        ui.text(string.format('Recovering right now: %d', Recovery.count or 0))
        if G.crashRepair then
            ui.text(string.format('Crash repairs & rejoined: %d', Recovery.repairedCount or 0))
            ui.text(string.format('Limp repairs (damaged cars re-bodied): %d', Recovery.limpCount or 0))
            ui.text(string.format('Retired (genuinely wrecked): %d', Recovery.retiredCount or 0))
        end
        pcall(function()
            local fc = ac.getSim().focusedCar
            if fc and fc >= 0 then
                local dk = Drivers.profileOf(fc)
                ui.text('Focused car: ' .. tostring(Classes.keyOf(fc)) .. (dk and ('  -  ' .. Drivers.nameOf(dk)) or ''))
            end
        end)
    end
end
