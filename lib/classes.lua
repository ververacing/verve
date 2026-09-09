-- Verve / classes.lua
-- Car-class detection + per-class physics multipliers. The class scales how the human layer
-- treats each car so classes FEEL different:
--   mistake = how often/whether it bobbles (0 = never, e.g. high-downforce open-wheelers)
--   warmup  = how much cold tyres hurt (F1 slicks >> vintage bias-ply)
--   wet     = how much a wet track hurts (aero slicks worst)
--   dirty   = how much grip it loses following through a corner (aero wake)
--
-- v0.1 classifier is heuristic (by car id keywords). Unknown -> "road" (a safe, mild default;
-- mistakes there are gentle and grip-slew-limited so misclassification can't spin a car).
-- A per-car manual override UI is planned for a later version.

local M = {}

M.MULT = {
    formula   = { mistake = 0.0, warmup = 1.6, wet = 1.5, dirty = 1.0 },
    prototype = { mistake = 0.3, warmup = 1.3, wet = 1.4, dirty = 0.9 },
    hypercar  = { mistake = 0.3, warmup = 1.2, wet = 1.3, dirty = 0.9 },
    gt        = { mistake = 1.0, warmup = 1.0, wet = 1.0, dirty = 0.4 },
    road      = { mistake = 0.9, warmup = 1.0, wet = 1.0, dirty = 0.2 },
    touring   = { mistake = 1.1, warmup = 0.8, wet = 0.9, dirty = 0.2 },
    vintage   = { mistake = 1.2, warmup = 0.4, wet = 0.9, dirty = 0.1 },
    drift     = { mistake = 0.0, warmup = 0.5, wet = 1.0, dirty = 0.0 },
}
M.DEFAULT = "road"

-- ordered keyword rules; first hit wins. Digit-guards avoid classic/muscle false friends
-- (gt40, gt350, gt500 must NOT read as modern GT race cars).
local function classify(id)
    id = (id or ""):lower()
    local function has(pat) return id:find(pat) ~= nil end

    if has("drift") then return "drift" end

    -- modern top-class prototypes / hypercars
    if has("499p") or has("valkyrie") or has("glickenhaus") or has("sc63")
       or has("p4%-5") or has("vision_gt") or has("lmdh") or has("_lmh") then return "hypercar" end
    if has("919") or has("_r18") or has("ts040") or has("787b") or has("_c9")
       or has("962") or has("_908") or has("_917") or has("lola_t70") or has("lmp")
       or has("_956") or has("group_?c") then return "prototype" end

    -- open-wheelers
    if has("formula") or id:match("^f1[_%-]") or has("_f1_") or has("tatuus")
       or has("dallara_f3") or has("lotus_25") or has("lotus_49") or has("lotus_72")
       or has("lotus_98t") or has("exos_125") or has("_rb%d%d") or has("sf70h")
       or has("sf15t") or has("_f2004") or has("_f2002") or has("ferrari_f138")
       or has("mp4%-4") or has("williams_fw") or has("mercedes_w0") or has("renault_r2")
       or has("ferrari_312t") or has("maserati_250f") or has("312_67") then return "formula" end

    -- modern GT race cars (guard against gt40/gt350/gt500)
    if id:find("gt3") and not id:find("gt3[0-9]") then return "gt" end
    if has("gte") then return "gt" end
    if id:find("gt4") and not id:find("gt4[0-9]") then return "gt" end
    if id:find("gt2") and not id:find("gt2[0-9]") then return "gt" end

    -- touring / tin-tops
    if has("dtm") or has("btcc") or has("touring") or has("clio_cup") or has("_tcr")
       or has("m235i_racing") or has("190_evo") or has("e30_dtm") or has("e30_gra")
       or has("_appk") or has("cortina") or has("hillman_imp") then return "touring" end

    -- vintage / classic
    if has("_356") or has("250f") or has("_312_67") or has("fiat_600") or has("tz2")
       or has("_tz_") or has("cobra") or has("gt40") or has("300sl") or has("_289")
       or has("historic") or has("vintage") or has("_50s") or has("_60s")
       or has("bizzarini") or has("_904") or has("healey") then return "vintage" end

    return M.DEFAULT
end

local cache = {}
function M.keyOf(carIndex)
    local c = cache[carIndex]
    if c ~= nil then return c end
    local key = M.DEFAULT
    pcall(function() key = classify(ac.getCarID(carIndex)) end)
    cache[carIndex] = key
    return key
end

function M.multOf(carIndex)
    return M.MULT[M.keyOf(carIndex)] or M.MULT[M.DEFAULT]
end

function M.reset() cache = {} end

return M
