-- Verve  -- original AC AI enhancer (human pace variability + tyre/weather awareness +
-- self-recovery). Not affiliated with other AI mods. Uses only CSP public physics APIs.
-- v0.1: the "human + robust" layer. Racecraft (our own overtaking/defending) is a later milestone.

local Human    = require('lib.human')
local Recovery = require('lib.recovery')
local Classes  = require('lib.classes')

local settings = ac.storage({
    enabled     = true,
    controlGrip = true,   -- set AI grip = base + human variability (the pace/human layer)
    humanVar    = true,   -- personality/drift/fade/pressure/slipstream
    humanErrors = true,   -- occasional gentle bobbles
    classPhys   = true,   -- cold-tyre warm-up / wet / dirty air
    recovery    = true,   -- un-stick spun/beached cars
    intensity   = 0.5,    -- variability scale
    baseGrip    = 1.00,   -- base extra-AI-grip (1.0 = no grip cheat / more human; 1.2 = stock AC)
})

-- ---- detect other AI-control mods that also drive physics.setExtraAIGrip (would fight ours) ----
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
    if not settings.enabled then return end
    local ok, sim = pcall(ac.getSim)
    if not ok or not sim then return end

    -- push toggles into the human module
    Human.ENABLED       = settings.humanVar
    Human.INTENSITY     = settings.intensity
    Human.HUMAN_ERRORS  = settings.humanErrors
    Human.CLASS_PHYSICS  = settings.classPhys

    local n = 0
    if settings.controlGrip then
        for i = 1, sim.carsCount - 1 do
            pcall(function()
                local car = ac.getCar(i)
                if not car or not car.isAIControlled then return end
                local gOff, cOff = Human.getModifiers(i)
                physics.setExtraAIGrip(i, clamp(settings.baseGrip + gOff, 0.5, 1.5))
                physics.setAICaution(i, clamp(1.0 + cOff, 0.0, 16.0))
                n = n + 1
            end)
        end
    end
    managed = n

    Recovery.ENABLED = settings.recovery
    if settings.recovery then Recovery.update(dt) end
end

ac.onSessionStart(function()
    pcall(Classes.reset)
end)

-- ------------------------------- UI -------------------------------
local function toggle(label, key, help)
    if ui.checkbox(label, settings[key]) then settings[key] = not settings[key] end
    if help and ui.itemHovered() then ui.setTooltip(help) end
end

function script.windowMain()
    ui.pushFont(ui.Font.Title)
    ui.text('Verve')
    ui.popFont()
    ui.sameLine()
    ui.textColored('AI that feels human', rgbm(0.6, 0.6, 0.6, 1))

    ui.separator()
    if ui.checkbox('Enable Verve', settings.enabled) then settings.enabled = not settings.enabled end
    ui.newLine()

    if otherAI then
        ui.textColored('Heads up: "' .. otherAI .. '" is installed.', rgbm(1, 0.7, 0.2, 1))
        ui.textWrapped('It also controls AI grip, so running both fights over the same setting. ' ..
            'Turn off "Control AI grip" below to defer to it (Verve still does self-recovery), ' ..
            'or disable the other app to let Verve drive.')
        ui.separator()
    end

    ui.text('Behaviour')
    toggle('Human pace variability', 'humanVar',
        'Per-driver personality, slow pace drift, tyre fade, pressure, slipstream.')
    toggle('Class-aware physics', 'classPhys',
        'Cold-tyre warm-up, wet-weather caution, and dirty-air grip loss following in corners. Scaled by car class.')
    toggle('Human errors', 'humanErrors',
        'Occasional gentle bobbles on forgiving cars. Never on Formula/Prototype/Hypercar. Grip-slewed so it will not spin cars.')
    toggle('Self-recovery', 'recovery',
        'Un-sticks spun/beached AI that are not wrecked: gentle throttle + steer back to the line, reverses off walls and out of car-to-car locks. Never touches the race start or pit exit.')
    toggle('Control AI grip', 'controlGrip',
        'Verve sets each AI car grip = base + variability. Turn OFF to defer grip to another AI mod (recovery still works).')

    ui.newLine()
    ui.text('Tuning')
    local iv = ui.slider('Variability intensity##iv', settings.intensity, 0.0, 1.5, '%.2f')
    if iv ~= settings.intensity then settings.intensity = iv end
    if ui.itemHovered() then ui.setTooltip('0 = robotic, 0.5 = subtle (default), 1.5 = dramatic') end
    local bg = ui.slider('Base AI grip##bg', settings.baseGrip, 0.85, 1.20, '%.2f')
    if bg ~= settings.baseGrip then settings.baseGrip = bg end
    if ui.itemHovered() then ui.setTooltip('1.00 = no grip cheat (more human). 1.20 = stock AC AI. Pace still scales with the race difficulty %.') end

    ui.newLine()
    ui.separator()
    ui.textColored('Status', rgbm(0.6, 0.6, 0.6, 1))
    if not settings.enabled then
        ui.text('Verve is OFF.')
    else
        ui.text(string.format('AI cars managed: %d', managed))
        ui.text(string.format('Recovering right now: %d', Recovery.count or 0))
        pcall(function()
            local fc = ac.getSim().focusedCar
            if fc and fc >= 0 then
                ui.text('Focused car class: ' .. tostring(Classes.keyOf(fc)))
            end
        end)
    end
end
