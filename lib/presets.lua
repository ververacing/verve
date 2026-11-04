-- Verve / presets.lua
-- Named snapshots of the user-facing GLOBAL settings (the G table in Verve.lua), so a person can save a
-- tuning under a name and load it back later. Persisted as one serialized string via ac.storage, the same
-- pattern as lib/overrides.lua. GLOBALS ONLY -- never per-car overrides (those are keyed by car model /
-- grid slot and are meaningless under a different grid). A built-in "Default" is always present, maps to
-- DEFAULTS, and is never stored or deletable.
--
-- The working/stored split lives in Verve.lua (G = live, S = persisted, autosave gates S). Presets do not
-- re-implement it: SAVE snapshots the live G; LOAD returns a {k=v} table the caller applies through setG,
-- so a load is live immediately and persists iff autosave is on, exactly like moving a slider.

local P = {}

-- The exact keys a preset snapshots (15; owner via verve-47 2026-11-04). User-facing, UI-exposed,
-- behaviour-affecting globals written through Verve.lua's setG. EXCLUDES, by decision:
--   CORE (humanVar/classPhys/racecraft/recovery/crashRepair/troubleSpots) - forced on, a preset cannot
--     change them; harness switches (paceAbs/ratingV2/classV2) - not user-facing; showAdvanced - UI state;
--   shareData - a consent toggle is NEVER set by a preset; timedFuel/shortFuel - not UI-exposed;
--   enabled - the master switch is never touched by a preset, in either direction.
P.KEYS = {
    'intensity', 'rcIntensity', 'baseGrip', 'aboveExpert',
    'humanErrors', 'sliderCurve', 'careerCurve', 'raceStart',
    'rescueCrashed', 'repairOnTrack', 'strategy', 'smarterDives',
    'drsDiscipline', 'controlGrip', 'raceFeed',
}
P.SCHEMA = 1
P.DEFAULT = 'Default'   -- the built-in, non-deletable name

local store = ac.storage({ data = "" })
local saved = {}        -- name -> { schema = n, keys = { k = v, ... } }

do
    pcall(function()
        if store.data and #store.data > 0 then
            local t = stringify.tryParse(store.data, nil, nil)
            if type(t) == "table" then saved = t end
        end
    end)
end

local function persist() pcall(function() store.data = stringify(saved, true) end) end

-- snapshot exactly P.KEYS out of a source table (the live G), dropping anything not in KEYS
local function snap(src)
    local out = {}
    for _, k in ipairs(P.KEYS) do out[k] = src[k] end
    return out
end

-- Save the live globals under a name. Immediate and unconditional: a preset is a stored artifact,
-- independent of the autosave toggle (which governs the working settings, not the preset store).
-- The name is trimmed and capped at 32 chars; an empty (or all-space) name and the reserved "Default"
-- are rejected. Saving onto an existing name OVERWRITES it. Returns true on success.
local MAXNAME = 32
function P.save(name, g)
    if type(name) ~= "string" then return false end
    name = name:gsub("^%s+", ""):gsub("%s+$", "")
    if #name > MAXNAME then name = name:sub(1, MAXNAME) end
    if name == "" or name == P.DEFAULT then return false end
    saved[name] = { schema = P.SCHEMA, keys = snap(g) }   -- overwrites an existing name
    persist()
    return true
end

-- Resolve a preset's keys for applying, given the current DEFAULTS. Returns a { k = v } table where any
-- key missing from the stored preset is FILLED from defaults (an older preset gaining a new key) and any
-- stored key not in the current P.KEYS is DROPPED (never read). "Default" returns a fresh copy of
-- defaults. Unknown name -> nil. The caller applies each pair through setG.
function P.load(name, defaults)
    local out = {}
    if name == P.DEFAULT then
        for _, k in ipairs(P.KEYS) do out[k] = defaults[k] end
        return out
    end
    local e = saved[name]
    if not e then return nil end
    local keys = e.keys or {}
    for _, k in ipairs(P.KEYS) do
        local v = keys[k]
        if v == nil then v = defaults[k] end        -- fill missing from defaults
        out[k] = v
    end
    return out
end

function P.delete(name)
    if name == P.DEFAULT or saved[name] == nil then return false end
    saved[name] = nil
    persist()
    return true
end

function P.exists(name) return name == P.DEFAULT or saved[name] ~= nil end

-- Sorted preset names for the UI, built-in Default first.
function P.names()
    local t = {}
    for n in pairs(saved) do t[#t + 1] = n end
    table.sort(t)
    table.insert(t, 1, P.DEFAULT)
    return t
end

return P
