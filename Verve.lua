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
local Diag = nil; pcall(function() Diag = require('diag') end)   -- LOCAL dev diagnostics; absent in the shipped build

-- defaults for the global settings (also used for "reset to defaults")
local DEFAULTS = {
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
    crashRepair = false, troubleSpots = false,
    intensity = 0.5, rcIntensity = 0.7, baseGrip = 1.20,
}

-- S = persisted store; G = working copy the game actually reads (so "session-only" edits can
-- be live without being saved until the user commits).
local S = ac.storage({
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
    crashRepair = false, troubleSpots = false,
    intensity = 0.5, rcIntensity = 0.7, baseGrip = 1.20,
    autosave = true,
})
local drsCd = {}
local G = {}
for k in pairs(DEFAULTS) do G[k] = S[k] end

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

function script.update(dt)
    if not G.enabled then return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end

    Human.ENABLED       = true
    Human.HUMAN_VAR     = G.humanVar
    Human.INTENSITY     = G.intensity
    Human.HUMAN_ERRORS  = G.humanErrors
    Human.CLASS_PHYSICS = G.classPhys
    Racecraft.ENABLED     = G.racecraft
    Racecraft.INTENSITY   = G.rcIntensity
    Racecraft.VARIABILITY = G.intensity     -- spreads per-driver aggression across the field
    Overrides.autosave    = S.autosave
    Racecraft.beginFrame()

    local behaviourOn = G.humanVar or G.classPhys or G.racecraft
    local n = 0
    -- start at 0 so the player's own car is managed WHEN (and only when) it's under AI control
    -- (Ctrl+C takeover): the isAIControlled gate below means we never touch it while you drive.
    for i = 0, sim.carsCount - 1 do
        pcall(function()
            local car = ac.getCar(i)
            if not car or not car.isAIControlled then return end
            if car.isInPitlane then return end          -- never touch a car doing a pit stop (player or AI)
            Drivers.applyPace(i)                        -- per-slot driver pace via AI level (self-restores when cleared)
            local gOff, cOff = Human.getModifiers(i)
            if G.controlGrip then
                local grip = G.baseGrip + gOff
                -- launch assist: a brief traction boost off a standing start (AC's AI bogs down off the
                -- line), fading out as the car gets up to speed. Only at the very start of lap 1.
                if (car.lapCount or 0) == 0 and (car.splinePosition or 1) < 0.012 then
                    local s = car.speedKmh or 0
                    if s < 90 then grip = grip + 0.07 * clamp(1 - s / 90, 0, 1) end
                end
                physics.setExtraAIGrip(i, clamp(grip, 0.5, 1.6))
            end
            local rcCaut = Racecraft.evaluate(i, dt)
            if behaviourOn then
                physics.setAICaution(i, clamp(1.0 + cOff + rcCaut, 0.0, 16.0))
            end
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
        })
    end) end
end

ac.onSessionStart(function()
    pcall(Classes.reset)
    pcall(Racecraft.reset)
    pcall(Drivers.reset)          -- driver profiles are session-only: wipe every race
    pcall(Recovery.reset)         -- clear per-car recovery + pit-rescue state
    pcall(Troublespots.reset)     -- save the old track's learned hot spots, load the new track's
    if Diag then pcall(Diag.reset) end
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
        ui.sameLine()
        ui.textColored(drv .. (i == 0 and '  (you)' or ''), rgbm(0.6, 0.6, 0.6, 1))
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
    ui.text('Verve')
    ui.popFont()
    ui.sameLine()
    ui.textColored('AI that feels human', rgbm(0.6, 0.6, 0.6, 1))

    Update.check()
    if Update.latest then
        ui.textColored('Update available: v' .. Update.latest .. (Update.summary and ('  -  ' .. Update.summary) or ''), rgbm(0.4, 0.8, 1, 1))
        if Update.downloadUrl then
            if ui.button('Get the update##upd') then pcall(function() os.openURL(Update.downloadUrl) end) end
            ui.sameLine(); ui.textColored(Update.downloadUrl, rgbm(0.5, 0.5, 0.5, 1))
        end
    end

    ui.separator()
    if ui.checkbox('Enable Verve', G.enabled) then setG('enabled', not G.enabled) end

    -- manual escape hatch: unstick YOUR car (repair + drop back on the racing line facing forward)
    if ui.button('Reset my car (unstick)') then
        pcall(function()
            local sim = ac.getSim()
            local idx = (sim and sim.focusedCar and sim.focusedCar >= 0) and sim.focusedCar or 0
            Recovery.forceRecover(idx)
        end)
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

    ui.text('Behaviour')
    toggle('Human pace variability', 'humanVar', 'Per-driver personality, slow pace drift, tyre fade, pressure, slipstream.')
    toggle('Class-aware physics', 'classPhys', 'Cold-tyre warm-up, wet caution, dirty-air grip loss following in corners. Scaled by car class.')
    toggle('Human errors', 'humanErrors', 'Occasional gentle bobbles on forgiving cars. Never on Formula/Prototype/Hypercar. Grip-slewed so it will not spin cars.')
    toggle('Racecraft (overtaking & defending)', 'racecraft', 'AI close up and pressure, pull off-line to pass on straights, and make one clean defensive move. Collision-awareness stays on.')
    toggle('Formula DRS discipline', 'drsDiscipline', 'On Formula cars, close DRS when the game says it is not available (outside a DRS zone or not within range). In-zone DRS is left to the game.')
    toggle('Self-recovery', 'recovery', 'Un-sticks spun/beached AI that are not wrecked. Never touches the race start or pit exit.')
    toggle('Trouble-spot learning (experimental)', 'troubleSpots', 'Learns where cars repeatedly crash on a track and adds a little caution there, so the field stops piling into the same corner. Per track and per class, and REMEMBERED across sessions (the second race on a track already knows its hot spots). Self-corrects as corners calm down. Off by default.')
    toggle('Crash repair (experimental)', 'crashRepair', 'Needs Self-recovery ON. Hijacks AC\'s retirement: while recovery is working a stuck car, AC is told NOT to retire it, and after a short penalty it gets a fresh wing/body IN PLACE (no teleport, no pit) so recovery can drive it out. Only genuinely hopeless cars (broken suspension, or unrecoverable after ~15s) are allowed to retire. No teleporting -- cannot disrupt the pack or a race start. Off by default.')
    toggle('Control AI grip', 'controlGrip', 'Verve sets each AI car grip = base + variability. Turn OFF to defer grip to another AI mod (recovery still works).')

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
    if ui.button('Randomize driver grid') then Drivers.randomizeGrid() end
    if ui.itemHovered() then ui.setTooltip('Assign every AI car a unique driver from its class (overflow uses generic archetypes). Session-only, resets each race.') end
    ui.sameLine()
    if ui.button('Clear drivers') then Drivers.clearAll() end
    driverGridList()
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
