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
-- M.DETECT_V2 (default off) switches autoKeyOf to the v2 detector further down (M.V2.detect).
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
    nascar    = { mistake = 0.9, warmup = 0.7, wet = 0.9, dirty = 0.2, draft = 2.0 }, -- stock/oval: robust, packs up in dirty air, HUGE draft
}
M.DEFAULT = "road"
M.LIST = { "formula", "formula_jr", "prototype", "hypercar", "gt", "road", "touring", "vintage", "drift", "kart", "rally", "nascar" }

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
        elseif s:find("nascar") or s:find("stockcar") or s:find("oval") then hit = "nascar"
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
    if has("nascar") or has("stockcar") or has("stock_car") or has("xfinity")
       or has("gen7") or has("gen6") or has("_cot") or has("truck_series") then return "nascar" end
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

-- (v2) detector behind M.DETECT_V2 (default off: with it off autoKeyOf runs exactly the v1 path above).
-- Fixes from the 2026-09-30 inventory of 485 installed cars (v1 agreed with a hand-checked grouping on 53 %, v2 97 %):
--   * tags match as whole words / phrases, not substrings ('F1 classic' is not vintage, 'naturally' is not rally,
--     'open' is not open-wheel, Kunos '#Hypercars' road cars are not LMH racers);
--   * F1 / formula / single-seater tags come before the vintage words, so F1 cars of any year are formula;
--   * road cars stay road: the ui_car.json class (street/road/tuning/...; else ac.getCar(i).isRacingCar) gates the
--     rally / hypercar / single-seater tags, the race-class id keywords and the physics fallback;
--   * physics estimates downforce (sum of CL(ANGLE) * CL_GAIN * CHORD * SPAN over aero.ini wings) instead of
--     counting WING sections (almost every AC car has BODY/FRONT/REAR ones);
--   * formula_jr: junior keywords (F3/F4/Formula Ford/Vee/Tatuus/Abarth/Skip Barber), under ~300 hp, or a pre-wing
--     open-wheeler (no wing downforce and under ~450 hp: 250F, Lotus 25/49, 312/67; winged 70s F1 stays formula).
-- Read once per car (autoKeyOf caches it); every read is guarded. No file-scope locals: all of it lives in M.V2.
M.DETECT_V2 = false
M.V2 = {
    DRIFT = { drift = true, drifting = true, drifter = true },
    NASCAR = { nascar = true, stockcar = true, xfinity = true, arca = true },
    NASCAR_P = { 'stock car', 'truck series', 'cup series' },
    RALLY = { rally = true, wrc = true, rallycross = true, rallye = true, rally1 = true, rally2 = true, rally3 = true, rally4 = true },
    RALLY_P = { 'group b', 'gr b' },
    F_STRONG = { f1 = true, formula = true, formula1 = true, indycar = true, indy = true, f2 = true, f3 = true, f4 = true,
                 f2000 = true, f3000 = true, superformula = true, formulae = true },
    F_STRONG_P = { 'formula 1', 'formula one', 'formula 2', 'formula 3', 'formula 4', 'formula ford', 'formula vee',
                   'formula renault', 'formula abarth', 'formula e', 'super formula' },
    F_GENERIC = { singleseater = true, openwheeler = true, openwheel = true, monoposto = true },
    F_GENERIC_P = { 'single seater', 'open wheeler', 'open wheel' },
    HYPER = { hypercar = true, lmh = true, lmdh = true, gtp = true, hy = true },
    HYPER_P = { 'le mans hypercar' },
    ROADHYPER = { hypercars = true },                  -- Kunos road-hypercar category ('#Hypercars', '#Hypercars R')
    PROTO = { prototype = true, lmp = true, lmp1 = true, lmp2 = true, lmp3 = true, lmpc = true, groupc = true, dpi = true, lmr1 = true },
    PROTO_P = { 'group c', 'proto c', 'prototype c', 'group 6', 'group 7', 'daytona prototype' },
    GT = { gt1 = true, gt2 = true, gt3 = true, gt4 = true, gte = true, gtd = true, gtlm = true, gt300 = true, gt500 = true },
    GT_SUFFIX = { 'gt2', 'gt3', 'gt4', 'gte' },        -- run-together tokens like 'trrgt3'
    GT_RS_P = { 'gt3 rs', 'gt2 rs', 'gt3rs', 'gt2rs' }, -- road cars named GT3 RS / GT2 RS ...
    GT_RS_OK = { rsr = true, cup = true, race = true }, -- ... unless the tags also say race
    TOURING = { touring = true, dtm = true, btcc = true, tcr = true, stw = true, wtcc = true, wtcr = true, supertouring = true,
                classone = true, itc = true, gra = true },
    TOURING_P = { 'super touring', 'group a', 'gr a', 'class one' },
    CUP = { cup = true, supercup = true, trofeo = true },
    VINTAGE = { vintage = true, historic = true, classic = true, ['50s'] = true, ['60s'] = true },
    STREET_UI = { 'street', 'road', 'tuning', 'supercar', 'ev', 'suv', 'pickup', 'track', 'luxury', 'chair', 'sports touring' },
    JR = { f3 = true, f4 = true, f2000 = true, ff1600 = true, vee = true, skipbarber = true, tatuus = true, fabarth = true,
           fa01 = true, fa1 = true, tatuusfa1 = true, t014 = true },
    JR_P = { 'formula 3', 'formula 4', 'formula ford', 'formula vee', 'formula abarth', 'skip barber', 'formula renault 2 0',
             'formula regional', 'formula 2000' },
    JR_HP = 300,           -- open-wheeler under this estimated power -> formula_jr
    JR_NOWING_CLA = 0.4,   -- open-wheeler with less wing downforce than this (m^2) ...
    JR_NOWING_HP = 450,    -- ... and under this power -> formula_jr (pre-wing F1)
    DF_CLA = 0.75,         -- physics fallback: 'real downforce' (m^2)
    FORMULA_KG = 800, FORMULA_STEER = 280,  -- physics: downforce, no aids, light, low steer lock -> formula
    PROTO_CLA = 2.5, PROTO_KG = 1000,       -- physics: big downforce, no aids, under 1000 kg -> prototype
    KART_KG = 250,         -- car.ini TOTALMASS under this -> kart
    VINTAGE_YEAR = 1975,   -- untagged cars older than this default to vintage; GT-tagged ones too (GT40 Mk II)
    MODERN_YEAR = 2000,    -- a vintage/classic tag on a car this new is ignored (copied tags)
    why = {},              -- car index -> which rule decided (tags/ui/id/physics/default), for the UI or diag
}

-- normalised tag set: lowercase, runs of non-alphanumerics -> one space; words and ' phrase ' lookups
function M.V2.toks(list)
    local t = { words = {}, pad = '|' }
    for _, v in ipairs(list or {}) do
        local s = tostring(v or ''):lower():gsub('[^%w]+', ' '):gsub('^ +', ''):gsub(' +$', '')
        if s ~= '' then
            t.pad = t.pad .. ' ' .. s .. ' |'
            for w in s:gmatch('%S+') do t.words[w] = true end
        end
    end
    return t
end

function M.V2.has(t, set, phrases)
    if set then for w in pairs(set) do if t.words[w] then return true end end end
    if phrases then for _, p in ipairs(phrases) do if t.pad:find(' ' .. p .. ' ', 1, true) then return true end end end
    return false
end

-- tags (or the ui class) -> class. 'road' is final (road hypercar category).
function M.V2.fromTokens(t, roadcar, year, drive)
    local V = M.V2
    local has = V.has
    if has(t, V.DRIFT) then return 'drift' end
    for w in pairs(t.words) do if w:sub(-4) == 'kart' then return 'kart' end end     -- kart, gokart, crosskart
    if has(t, V.NASCAR, V.NASCAR_P) then return 'nascar' end
    if not roadcar and has(t, V.RALLY, V.RALLY_P) then return 'rally' end
    if has(t, V.F_STRONG, V.F_STRONG_P) then return 'formula' end
    if not roadcar and has(t, V.HYPER, V.HYPER_P) then return 'hypercar' end
    if has(t, V.PROTO, V.PROTO_P) then return 'prototype' end
    if not roadcar and has(t, V.F_GENERIC, V.F_GENERIC_P) then return 'formula' end
    if has(t, V.ROADHYPER) then return 'road' end
    local gt = has(t, V.GT)
    if not gt then
        for w in pairs(t.words) do
            for _, sfx in ipairs(V.GT_SUFFIX) do
                if #w > #sfx and w:sub(-#sfx) == sfx and not w:sub(-#sfx - 1, -#sfx - 1):find('%d') then gt = true end
            end
        end
    end
    if gt and not (has(t, nil, V.GT_RS_P) and not has(t, V.GT_RS_OK)) then return 'gt' end
    if has(t, V.TOURING, V.TOURING_P) then return 'touring' end
    if has(t, V.CUP) then return drive == 'FWD' and 'touring' or 'gt' end
    if has(t, V.VINTAGE) and not (year >= V.MODERN_YEAR) then return 'vintage' end
    return nil
end

-- v1 id keywords (plain substring finds) with fixes: McLaren F1 is not a formula car, P4/5 is not a hypercar,
-- GT3/GT2 RS road cars are not GT racers, and the race-class keywords need a car that is not a road car.
function M.V2.fromId(id, roadcar)
    id = (id or ''):lower()
    local function has(...)
        for _, p in ipairs({ ... }) do if id:find(p, 1, true) then return true end end
        return false
    end
    if has('drift') then return 'drift' end
    if has('kart') then return 'kart' end
    if has('nascar', 'stockcar', 'stock_car', 'xfinity', 'gen7', 'gen6', '_cot', 'truck_series') then return 'nascar' end
    if not roadcar and has('rally', 'wrc') then return 'rally' end
    if not roadcar and has('499p', 'valkyrie', 'glickenhaus', 'sc63', 'vision_gt', 'lmdh', '_lmh') then return 'hypercar' end
    if has('919', '_r18', 'ts040', '787b', '_c9', '962', '_908', '_917', 'lola_t70', 'lmp', '_956') then return 'prototype' end
    if has('formula', 'tatuus', 'dallara_f3', 'lotus_25', 'lotus_49', 'lotus_72', 'lotus_98t', 'exos_125', 'sf70h', 'sf15t',
           '_f2004', '_f2002', 'ferrari_f138', 'mp4-4', 'williams_fw', 'mercedes_w0', 'renault_r2', 'ferrari_312t',
           'maserati_250f', '312_67') or id:match('^f1[_%-]') or id:find('_rb%d%d')
       or (has('_f1_') and not has('mclaren_f1')) then return 'formula' end
    local s, e = id:find('gt[23]_?rs')
    local rsRoad = s ~= nil and id:sub(e + 1, e + 1) ~= 'r'
    if not roadcar and not rsRoad then
        if has('gt3') and not id:find('gt3%d') then return 'gt' end
        if has('gte') then return 'gt' end
        if has('gt4') and not id:find('gt4%d') then return 'gt' end
        if has('gt2') and not id:find('gt2%d') then return 'gt' end
    end
    if has('dtm', 'btcc', 'touring', 'clio_cup', '_tcr', 'm235i_racing', '190_evo', 'e30_dtm', 'e30_gra', '_appk',
           'cortina', 'hillman_imp') then return 'touring' end
    if has('_356', '250f', '_312_67', 'fiat_600', 'tz2', '_tz_', 'cobra', 'gt40', '300sl', '_289', 'historic', 'vintage',
           '_50s', '_60s', 'bizzarini', '_904', 'healey') then return 'vintage' end
    return nil
end

-- physics signals from the car's data files (data.acd or data/): mass, steer lock, downforce estimate, slicks,
-- aids, drivetrain, peak power (power.lut torque x rpm, times 1 + turbo boost).
function M.V2.physics(i)
    local f = { mass = 0, steer = 400, cla = 0, hp = 0, slick = false, aids = false, drive = 'RWD' }
    local function cfg(file)
        local c = nil
        pcall(function() c = ac.INIConfig.carData(i, file) end)
        return c
    end
    local function g(c, sec, k, d)
        local v = d
        if c then pcall(function() v = c:get(sec, k, d) end) end
        if type(d) == 'number' then return tonumber(v) or d end
        return tostring(v or d)
    end
    local function lut(name)
        local L = nil
        pcall(function()
            if name:sub(1, 1) == '(' then L = ac.DataLUT11.parse(name) else L = ac.DataLUT11.carData(i, name) end
        end)
        return L
    end
    local car, aero = cfg('car.ini'), cfg('aero.ini')
    f.mass = g(car, 'BASIC', 'TOTALMASS', 0)
    f.steer = g(car, 'CONTROLS', 'STEER_LOCK', 400)
    for w = 0, 15 do
        local sec = 'WING_' .. w
        local chord, span, gain = g(aero, sec, 'CHORD', 0), g(aero, sec, 'SPAN', 0), g(aero, sec, 'CL_GAIN', 0)
        if chord ~= 0 and span ~= 0 and gain ~= 0 then
            local L, cl = lut(g(aero, sec, 'LUT_AOA_CL', '')), 0
            if L then pcall(function() cl = tonumber(L:get(g(aero, sec, 'ANGLE', 0))) or 0 end) end
            if cl == cl then f.cla = f.cla + cl * gain * chord * span end                    -- skip NaN
        end
    end
    local ty = cfg('tyres.ini')
    for k = 0, 9 do
        local n = g(ty, k == 0 and 'FRONT' or ('FRONT_' .. k), 'NAME', ''):lower()
        if n:find('slick', 1, true) and not n:find('semi', 1, true) then f.slick = true end
    end
    local el = cfg('electronics.ini')
    f.aids = g(el, 'ABS', 'PRESENT', 0) > 0 or g(el, 'ABS_V2', 'PRESENT', '') ~= ''
        or g(el, 'TRACTION_CONTROL', 'PRESENT', 0) > 0 or g(el, 'TRACTION_CONTROL_2', 'PRESENT', '') ~= ''
    f.drive = g(cfg('drivetrain.ini'), 'TRACTION', 'TYPE', 'RWD'):upper()
    local eng = cfg('engine.ini')
    local boost = 0
    for t = 0, 3 do boost = boost + g(eng, 'TURBO_' .. t, 'MAX_BOOST', 0) end
    local P = lut(g(eng, 'HEADER', 'POWER_CURVE', 'power.lut'))
    if P then
        pcall(function()
            local best = 0
            for k = 0, 999 do
                local x, y = P:getPointInput(k), P:getPointOutput(k)
                if x == nil or y == nil or x ~= x or y ~= y then break end
                if x * y > best then best = x * y end
            end
            f.hp = best * math.pi / 30000 * (1 + boost) * 1.341                          -- Nm x rpm -> kW -> hp
        end)
    end
    return f
end

function M.V2.fromPhysics(f, roadcar)
    local V = M.V2
    if f.mass > 0 and f.mass < V.KART_KG then return 'kart' end
    if roadcar then return nil end
    local df = f.cla >= V.DF_CLA
    if not (f.slick or df) then return nil end
    if f.drive == 'FWD' and f.slick then return 'touring' end
    if df and not f.aids and f.mass > 0 and f.mass < V.FORMULA_KG and f.steer <= V.FORMULA_STEER then return 'formula' end
    if df and not f.aids and f.cla >= V.PROTO_CLA and f.mass > 0 and f.mass < V.PROTO_KG then return 'prototype' end
    return 'gt'
end

-- formula -> formula_jr: junior keywords, low power, or a pre-wing open-wheeler
function M.V2.split(t, f)
    local V = M.V2
    if V.has(t, V.JR, V.JR_P) then return 'formula_jr' end
    if f.hp > 0 and f.hp < V.JR_HP then return 'formula_jr' end
    if f.cla < V.JR_NOWING_CLA and f.hp > 0 and f.hp < V.JR_NOWING_HP then return 'formula_jr' end
    return 'formula'
end

-- tags -> ui class -> id -> physics -> default (vintage before 1975, else road), then the formula split
function M.V2.detect(i)
    local V = M.V2
    local id = carIdOf(i) or ''
    local tags = {}
    pcall(function()
        local t = ac.getCarTags(i)
        if t then for _, v in ipairs(t) do tags[#tags + 1] = tostring(v) end end
    end)
    local ui, roadcar = nil, false
    pcall(function()
        local s = io.load(ac.getFolder(ac.FolderID.ContentCars) .. '/' .. id .. '/ui/ui_car.json')
        ui = s and s:match('"class"%s*:%s*"([^"]*)"') or nil
    end)
    if ui then
        local u = ui:lower():gsub('^%s+', '')
        for _, p in ipairs(V.STREET_UI) do if u:sub(1, #p) == p then roadcar = true end end
    else
        pcall(function() roadcar = not ac.getCar(i).isRacingCar end)
    end
    local year, drive = 0, 'RWD'
    pcall(function() year = tonumber(ac.getCar(i).year) or 0 end)
    pcall(function() drive = tostring(ac.INIConfig.carData(i, 'drivetrain.ini'):get('TRACTION', 'TYPE', 'RWD')):upper() end)
    local f = nil
    local key, why = V.fromTokens(V.toks(tags), roadcar, year, drive), 'tags'
    if not key and ui then key, why = V.fromTokens(V.toks({ ui }), roadcar, year, drive), 'ui' end
    if not key then key, why = V.fromId(id, roadcar), 'id' end
    if not key then f = V.physics(i); key, why = V.fromPhysics(f, roadcar), 'physics' end
    if not key then key, why = (year > 0 and year < V.VINTAGE_YEAR) and 'vintage' or 'road', 'default' end
    if key == 'gt' and year > 0 and year < V.VINTAGE_YEAR then key = 'vintage' end
    if key == 'formula' then
        local name = ''
        pcall(function() name = tostring(ac.getCarName(i) or '') end)
        tags[#tags + 1] = id
        tags[#tags + 1] = name
        key = V.split(V.toks(tags), f or V.physics(i))
    end
    V.why[i] = why
    return key
end

-- class ignoring any user override (what the auto-detector thinks). Cached.
function M.autoKeyOf(i)
    local c = autoCache[i]
    if c ~= nil then return c end
    if M.DETECT_V2 then
        local ok, k = pcall(M.V2.detect, i)
        c = (ok and k) or M.DEFAULT
        autoCache[i] = c
        return c
    end
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
