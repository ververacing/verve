-- Verve / overrides.lua
-- Per-car user overrides, keyed by car id: class (nil/'auto' = auto-classify) and racecraft
-- level ('chill'|'clean'|'intense', default 'clean'). Persisted as one serialized string.
--
-- Two layers so the app can offer "session-only vs save":
--   live   = the working set the game reads right now (edits apply immediately, live in-race)
--   stored = what's persisted to disk (survives restarts)
-- With autosave ON, every edit commits live -> stored at once (simple, permanent).
-- With autosave OFF, edits stay in `live` (live for this race) until save() commits them;
-- revert() throws away un-saved edits.

local M = {}
M.autosave = true

local store = ac.storage({ data = "" })
local stored, live = {}, {}

local function deepcopy(m)
    local t = {}
    for id, e in pairs(m) do t[id] = { class = e.class, level = e.level } end
    return t
end

do
    pcall(function()
        if store.data and #store.data > 0 then
            local t = stringify.tryParse(store.data, nil, nil)
            if type(t) == "table" then stored = t end
        end
    end)
    live = deepcopy(stored)
end

local function persist() pcall(function() store.data = stringify(stored, true) end) end
local function commitIfAuto() if M.autosave then stored = deepcopy(live); persist() end end

-- read (from live -> what the game uses this instant)
function M.classOverride(carId) local e = carId and live[carId]; return e and e.class or nil end
function M.level(carId)        local e = carId and live[carId]; return (e and e.level) or "clean" end

-- edit (into live; commit now only if autosave)
function M.setClass(carId, key)
    if not carId then return end
    local e = live[carId] or {}
    if key == nil or key == "auto" then e.class = nil else e.class = key end
    live[carId] = e
    commitIfAuto()
end
function M.setLevel(carId, lvl)
    if not carId then return end
    local e = live[carId] or {}
    e.level = lvl
    live[carId] = e
    commitIfAuto()
end

-- resets
function M.resetCar(carId) if carId then live[carId] = nil; commitIfAuto() end end
function M.resetAll()      live = {}; commitIfAuto() end

-- session-only commit controls
function M.save()   stored = deepcopy(live); persist() end
function M.revert() live = deepcopy(stored) end
function M.dirty()  return stringify(live, true) ~= stringify(stored, true) end

-- when autosave is switched back on, flush any pending session edits
function M.setAutosave(on)
    M.autosave = on
    if on and M.dirty() then M.save() end
end

-- list of configured car ids (for the review UI), sorted
function M.ids()
    local t = {}
    for id in pairs(live) do t[#t + 1] = id end
    table.sort(t)
    return t
end

return M
