-- Verve / classes.lua
-- Car-class detection + per-class physics multipliers. Class scales how the human layer treats
-- each car so classes FEEL different:
--   mistake = whether/how often it bobbles (0 = never, e.g. high-downforce open-wheelers)
--   warmup  = how much cold tyres hurt (F1 slicks >> vintage bias-ply)
--   wet     = how much a wet track hurts (aero slicks worst)
--   dirty   = grip lost following through a corner (aero wake)
--
-- Detection order: (1) user override (per car, from the UI); (2) car TAGS (real metadata, the
-- reliable signal for well-tagged mods); (3) car-id keywords; (3b) physics signals from the
-- car's data files (downforce/aids/tyres/steer-lock/drivetrain); (4) "road" default.
-- Unknown -> road is safe: its mistakes are gentle and grip-slew-limited, so a misclassify can't
-- spin a car, and the per-car override in the UI fixes anything the auto-detector gets wrong.

local Overrides = require('lib.overrides')

local M = {}

M.MULT = {
    formula   = { mistake = 0.0, warmup = 1.6, wet = 1.5, dirty = 1.0 },
    formula_jr= { mistake = 0.4, warmup = 0.7, wet = 1.1, dirty = 0.2 },   -- low-downforce open-wheeler (Formula Ford/Vee): momentum, races close
    prototype = { mistake = 0.3, warmup = 1.3, wet = 1.4, dirty = 0.9 },
    hypercar  = { mistake = 0.3, warmup = 1.2, wet = 1.3, dirty = 0.9 },
    gt        = { mistake = 1.0, warmup = 1.0, wet = 1.0, dirty = 0.4 },
    road      = { mistake = 0.9, warmup = 1.0, wet = 1.0, dirty = 0.2 },
    touring   = { mistake = 1.1, warmup = 0.8, wet = 0.9, dirty = 0.2 },
    vintage   = { mistake = 1.0, warmup = 0.6, wet = 0.9, dirty = 0.1 },
    drift     = { mistake = 0.0, warmup = 0.5, wet = 1.0, dirty = 0.0 },
    kart      = { mistake = 1.0, warmup = 0.3, wet = 1.0, dirty = 0.0 },   -- no downforce, tyres warm instantly, spin-prone but low-speed
    rally     = { mistake = 1.0, warmup = 0.5, wet = 0.75, dirty = 0.15 }, -- AWD, good in the wet, slidey but catchable
}
M.DEFAULT = "road"
M.LIST = { "formula", "formula_jr", "prototype", "hypercar", "gt", "road", "touring", "vintage", "drift", "kart", "rally" }

-- (2) tags: real category metadata. Low false-positive, so checked first.
local function classifyTags(i)
    local hit = nil
    pcall(function()
        local t = ac.getCarTags(i)
        if not t then return end
        local s = ""
        for _, v in ipairs(t) do s = s .. "#" .. tostring(v):lower() end
        if s:find("drift") then hit = "drift"
        elseif s:find("kart") then hit = "kart"
        elseif s:find("rally") or s:find("wrc") then hit = "rally"
        elseif s:find("formula") or s:find("open" ) then hit = "formula"
        elseif s:find("hypercar") or s:find("lmh") or s:find("lmdh") then hit = "hypercar"
        elseif s:find("prototype") or s:find("lmp") or s:find("groupc") or s:find("group c") then hit = "prototype"
        elseif s:find("gt3") or s:find("gte") or s:find("gt2") or s:find("gt4") then hit = "gt"
        elseif s:find("touring") or s:find("dtm") or s:find("btcc") or s:find("tcr") then hit = "touring"
        elseif s:find("vintage") or s:find("classic") or s:find("historic") then hit = "vintage"
        end
    end)
    return hit
end

-- (3) id keywords, with digit-guards so gt40/gt350/gt500 don't read as modern GT race cars.
local function classifyId(id)
    id = (id or ""):lower()
    local function has(p) return id:find(p) ~= nil end
    if has("drift") then return "drift" end
    if has("kart") then return "kart" end                                   -- covers gokart, shifter kart
    if has("rally") or has("wrc") then return "rally" end                   -- covers rallye, rallycross, WRC
    if has("499p") or has("valkyrie") or has("glickenhaus") or has("sc63")
       or has("p4%-5") or has("vision_gt") or has("lmdh") or has("_lmh") then return "hypercar" end
    if has("919") or has("_r18") or has("ts040") or has("787b") or has("_c9")
       or has("962") or has("_908") or has("_917") or has("lola_t70") or has("lmp")
       or has("_956") then return "prototype" end
    if has("formula") or id:match("^f1[_%-]") or has("_f1_") or has("tatuus")
       or has("dallara_f3") or has("lotus_25") or has("lotus_49") or has("lotus_72")
       or has("lotus_98t") or has("exos_125") or has("_rb%d%d") or has("sf70h")
       or has("sf15t") or has("_f2004") or has("_f2002") or has("ferrari_f138")
       or has("mp4%-4") or has("williams_fw") or has("mercedes_w0") or has("renault_r2")
       or has("ferrari_312t") or has("maserati_250f") or has("312_67") then return "formula" end
    if id:find("gt3") and not id:find("gt3[0-9]") then return "gt" end
    if has("gte") then return "gt" end
    if id:find("gt4") and not id:find("gt4[0-9]") then return "gt" end
    if id:find("gt2") and not id:find("gt2[0-9]") then return "gt" end
    if has("dtm") or has("btcc") or has("touring") or has("clio_cup") or has("_tcr")
       or has("m235i_racing") or has("190_evo") or has("e30_dtm") or has("e30_gra")
       or has("_appk") or has("cortina") or has("hillman_imp") then return "touring" end
    if has("_356") or has("250f") or has("_312_67") or has("fiat_600") or has("tz2")
       or has("_tz_") or has("cobra") or has("gt40") or has("300sl") or has("_289")
       or has("historic") or has("vintage") or has("_50s") or has("_60s")
       or has("bizzarini") or has("_904") or has("healey") then return "vintage" end
    return nil
end

-- (3b) physics signals from the car's own data files. Only used when tags + id keywords both
-- miss, to upgrade the "road" default into a sensible race class. Conservative: non-race cars
-- stay road. All reads guarded; a per-car override in the UI fixes anything this gets wrong.
local function classifyPhysics(i)
    local key = nil
    pcall(function()
        local function g(file, sec, k, d)
            local v = d
            pcall(function() v = ac.INIConfig.carData(i, file):get(sec, k, d) end)
            return v
        end
        local steer = tonumber(g('car.ini', 'CONTROLS', 'STEER_LOCK', 400)) or 400
        local wings = 0
        for w = 0, 3 do if tostring(g('aero.ini', 'WING_' .. w, 'NAME', '')) ~= '' then wings = wings + 1 end end
        local abs  = (tonumber(g('electronics.ini', 'ABS', 'PRESENT', 0)) or 0) > 0
                     or tostring(g('electronics.ini', 'ABS_V2', 'PRESENT', '')) ~= ''
        local tc   = (tonumber(g('electronics.ini', 'TRACTION_CONTROL', 'PRESENT', 0)) or 0) > 0
                     or tostring(g('electronics.ini', 'TRACTION_CONTROL_2', 'PRESENT', '')) ~= ''
        local hasAids = abs or tc
        local tyre = tostring(g('tyres.ini', 'FRONT', 'NAME', '')):lower()
        local slick = tyre:find('slick') ~= nil
        local semi  = tyre:find('semi') ~= nil
        local drive = tostring(g('drivetrain.ini', 'TRACTION', 'TYPE', 'RWD')):upper()

        local downforce = wings >= 2
        local raceish = slick or downforce or steer <= 280
        if not raceish then return end                          -- stays road (default)
        if downforce and steer <= 260 and not hasAids then key = 'formula'
        elseif drive == 'FWD' and (slick or semi) then key = 'touring'
        elseif downforce and not hasAids then key = 'prototype'
        elseif downforce or slick then key = 'gt'
        end
    end)
    return key
end

local autoCache = {}
local idCache = {}

local function carIdOf(i)
    local id = idCache[i]
    if id == nil then
        id = false
        pcall(function() id = ac.getCarID(i) end)
        idCache[i] = id
    end
    return id or nil
end

-- class ignoring any user override (what the auto-detector thinks). Cached.
function M.autoKeyOf(i)
    local c = autoCache[i]
    if c ~= nil then return c end
    local key = classifyTags(i) or classifyId(carIdOf(i)) or classifyPhysics(i) or M.DEFAULT
    -- low-downforce open-wheeler refinement: a "formula" car with little/no wing (Formula Ford,
    -- Vee, junior single-seaters) is a momentum car that races in slipstream packs, not a fragile
    -- F1. Route it to the close-racing formula_jr profile instead.
    if key == "formula" then
        local wings = 0
        pcall(function()
            for w = 0, 3 do
                if tostring(ac.INIConfig.carData(i, 'aero.ini'):get('WING_' .. w, 'NAME', '')) ~= '' then wings = wings + 1 end
            end
        end)
        if wings < 2 then key = "formula_jr" end
    end
    autoCache[i] = key
    return key
end

-- final class: user override wins (checked live so UI edits take effect), else auto.
function M.keyOf(i)
    local id = carIdOf(i)
    if id then
        local ov = Overrides.classOverride(id)
        if ov then return ov end
    end
    return M.autoKeyOf(i)
end

function M.multOf(i)
    return M.MULT[M.keyOf(i)] or M.MULT[M.DEFAULT]
end

function M.reset() autoCache = {}; idCache = {} end

return M
