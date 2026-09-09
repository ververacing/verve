-- Verve / overrides.lua
-- Per-car user overrides, keyed by car id, persisted across sessions:
--   class : force a class (nil/'auto' = use the auto-classifier)
--   level : racecraft level 'chill' | 'clean' | 'intense' (default 'clean')
-- Stored as one serialized string in CSP app storage. Editable in the app UI.

local M = {}
local store = ac.storage({ data = "" })
local map = {}   -- carId -> { class = <key or nil>, level = <string or nil> }

do
    pcall(function()
        if store.data and #store.data > 0 then
            local t = stringify.tryParse(store.data, nil, nil)
            if type(t) == "table" then map = t end
        end
    end)
end

local function save()
    pcall(function() store.data = stringify(map, true) end)
end

function M.classOverride(carId)
    local e = carId and map[carId]
    return e and e.class or nil
end

function M.level(carId)
    local e = carId and map[carId]
    return (e and e.level) or "clean"
end

function M.setClass(carId, key)
    if not carId then return end
    local e = map[carId] or {}
    if key == nil or key == "auto" then e.class = nil else e.class = key end
    map[carId] = e
    save()
end

function M.setLevel(carId, lvl)
    if not carId then return end
    local e = map[carId] or {}
    e.level = lvl
    map[carId] = e
    save()
end

return M
