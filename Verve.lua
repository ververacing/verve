-- Verve  -- original AC AI enhancer (human pace variability + tyre/weather awareness +
-- self-recovery + our own racecraft). Not affiliated with other AI mods. CSP public APIs only.

local Human     = require('lib.human')
local Recovery  = require('lib.recovery')
local Classes   = require('lib.classes')
local Racecraft = require('lib.racecraft')
local Overrides = require('lib.overrides')

-- defaults for the global settings (also used for "reset to defaults")
local DEFAULTS = {
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
    intensity = 0.5, rcIntensity = 0.7, baseGrip = 1.20,
}

-- S = persisted store; G = working copy the game actually reads (so "session-only" edits can
-- be live without being saved until the user commits).
local S = ac.storage({
    enabled = true, controlGrip = true, humanVar = true, humanErrors = true,
    classPhys = true, racecraft = true, recovery = true, drsDiscipline = true,
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
    Racecraft.ENABLED   = G.racecraft
    Racecraft.INTENSITY = G.rcIntensity
    Overrides.autosave  = S.autosave
    Racecraft.beginFrame()

    local behaviourOn = G.humanVar or G.classPhys or G.racecraft
    local n = 0
    for i = 1, sim.carsCount - 1 do
        pcall(function()
            local car = ac.getCar(i)
            if not car or not car.isAIControlled then return end
            local gOff, cOff = Human.getModifiers(i)
            if G.controlGrip then
                physics.setExtraAIGrip(i, clamp(G.baseGrip + gOff, 0.5, 1.5))
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
    if G.recovery then Recovery.update(dt) end
end

ac.onSessionStart(function()
    pcall(Classes.reset)
    pcall(Racecraft.reset)
end)

-- ------------------------------- UI -------------------------------
local CLASS_OPTS = { 'auto', 'formula', 'prototype', 'hypercar', 'gt', 'road', 'touring', 'vintage', 'drift' }
local LEVEL_OPTS = { 'chill', 'clean', 'intense' }

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

local function renderCarRow(id, name, idx)
    local auto = idx and Classes.autoKeyOf(idx) or nil
    local curClass = Overrides.classOverride(id) or 'auto'
    local classPreview = (curClass == 'auto') and (auto and ('auto (' .. auto .. ')') or 'auto') or curClass
    ui.text(name)
    comboFor('##cls' .. id, classPreview, curClass, CLASS_OPTS, function(opt) Overrides.setClass(id, opt) end)
    ui.sameLine()
    local lvl = Overrides.level(id)
    comboFor('##lvl' .. id, lvl, lvl, LEVEL_OPTS, function(opt) Overrides.setLevel(id, opt) end)
    ui.sameLine()
    if ui.button('Reset##r' .. id) then Overrides.resetCar(id) end
end

local function carReviewList()
    -- cars actually in this session (live auto-detect)
    local inSession, session = {}, {}
    pcall(function()
        local sim = ac.getSim()
        if not sim then return end
        for i = 1, sim.carsCount - 1 do
            local id = nil
            pcall(function() id = ac.getCarID(i) end)
            if id and not inSession[id] then
                inSession[id] = true
                local nm = id
                pcall(function() nm = ac.getCarName(i) or id end)
                session[#session + 1] = { id = id, idx = i, name = nm }
            end
        end
    end)
    table.sort(session, function(a, b) return a.name < b.name end)

    if #session > 0 then
        for _, r in ipairs(session) do renderCarRow(r.id, r.name, r.idx) end
    else
        ui.textWrapped('No cars in this session. Open Verve on the grid before the lights.')
    end

    -- saved overrides for cars NOT in this race (shown separately so the list isn't confusing)
    local others = {}
    for _, id in ipairs(Overrides.ids()) do if not inSession[id] then others[#others + 1] = id end end
    if #others > 0 then
        ui.newLine()
        ui.textColored('Saved overrides for other cars (not in this race):', rgbm(0.55, 0.55, 0.55, 1))
        table.sort(others)
        for _, id in ipairs(others) do renderCarRow(id, id, nil) end
    end
end

function script.windowMain()
    ui.pushFont(ui.Font.Title)
    ui.text('Verve')
    ui.popFont()
    ui.sameLine()
    ui.textColored('AI that feels human', rgbm(0.6, 0.6, 0.6, 1))

    ui.separator()
    if ui.checkbox('Enable Verve', G.enabled) then setG('enabled', not G.enabled) end

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
    toggle('Control AI grip', 'controlGrip', 'Verve sets each AI car grip = base + variability. Turn OFF to defer grip to another AI mod (recovery still works).')

    ui.newLine()
    ui.text('Tuning')
    local iv = ui.slider('Variability intensity##iv', G.intensity, 0.0, 1.5, '%.2f')
    if iv ~= G.intensity then setG('intensity', iv) end
    if ui.itemHovered() then ui.setTooltip('0 = robotic, 0.5 = subtle (default), 1.5 = dramatic') end
    local rc = ui.slider('Racecraft intensity##rc', G.rcIntensity, 0.0, 1.5, '%.2f')
    if rc ~= G.rcIntensity then setG('rcIntensity', rc) end
    if ui.itemHovered() then ui.setTooltip('How hard they attack/defend. 0 = passive, 0.7 = default, 1.5 = elbows out. Per-car level multiplies this.') end
    local bg = ui.slider('Base AI grip##bg', G.baseGrip, 0.85, 1.20, '%.2f')
    if bg ~= G.baseGrip then setG('baseGrip', bg) end
    if ui.itemHovered() then ui.setTooltip('Grip the AI has for its own racing line. 1.20 = stock AC AI (default; the line speeds are calibrated for this, so cars hold hard corners). Lower it (toward 1.00) for a more human, on-the-edge feel, but too low makes them wash wide. Pace still scales with the race difficulty %.') end

    ui.newLine()
    ui.separator()
    ui.textColored('Per-car class & racecraft level', rgbm(0.6, 0.6, 0.6, 1))
    ui.textWrapped('Auto-detected from tags/name. Override any car; per-car level scales its racecraft (chill/clean/intense). Available on the grid before the lights.')
    carReviewList()
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
        end
        ui.text(string.format('Recovering right now: %d', Recovery.count or 0))
        pcall(function()
            local fc = ac.getSim().focusedCar
            if fc and fc >= 0 then ui.text('Focused car class: ' .. tostring(Classes.keyOf(fc))) end
        end)
    end
end
