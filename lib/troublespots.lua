-- Verve / troublespots.lua
-- Learns where cars REPEATEDLY crash/spin/beach on a track and adds a little caution there, so the
-- field stops piling into the same corner. Per track + per class, with a track-wide fallback until a
-- class has its own history. Persisted across sessions via ac.storage, so the second race on a track
-- already knows its hot spots. Heat decays if incidents stop, so a corner we've calmed relaxes again.

local T = {}
T.ENABLED = false

-- bins are sized in METRES, not a fixed count, so resolution is ~constant on every track (a long
-- track gets more bins, a short one fewer -- a "corner" is the same size in metres everywhere).
local BIN_METERS    = 24.0       -- target bin length
local MIN_BINS      = 40         -- clamp the count for very short / very long tracks
local MAX_BINS      = 600
local LOOKAHEAD_M   = 30.0       -- apply the caution ~this many metres BEFORE the spot (brake earlier)
local INCIDENT_HEAT = 1.0
local UPSTREAM      = 3          -- also heat this many bins upstream (the cause precedes the mess)
local HOT_THRESHOLD = 2.5        -- bin heat before we treat it as a trouble spot
local HOT_RANGE     = 4.0        -- heat above threshold that maps to full caution
local MAX_CAUT      = 0.45       -- most caution a trouble spot adds
local DECAY_PER_SEC = 0.0002     -- heat bleeds off slowly (~a few races) if incidents stop
local SAVE_EVERY    = 20.0       -- seconds between debounced saves
local FLOOR         = 0.05       -- drop a bin once its heat decays below this (keeps storage sparse)
local HEAT_MAX      = 9.0        -- cap heat so it can't grow unbounded over hundreds of races (small numbers)
local MAX_BINS_KEPT = 40         -- keep only the hottest N bins per class per track -- hard bound on size

local store = ac.storage({ troubleData = '' })
local data  = {}                 -- data[cls][bin] = heat for the CURRENT track ('_global' = all classes)
local trackKey = 'track'
local nbins, lookaheadFrac = 200, 0.008   -- recomputed per track from its length in T.reset()
local lastSave, lastDecay = 0, 0
local dirtyStore = false

local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end

-- keep only the hottest MAX_BINS_KEPT bins in a class table (bounds stored size on crash-heavy tracks)
local function pruneClass(bins)
    local n = 0; for _ in pairs(bins) do n = n + 1 end
    if n <= MAX_BINS_KEPT then return end
    local arr = {}
    for b, h in pairs(bins) do arr[#arr + 1] = { b, h } end
    table.sort(arr, function(a, c) return a[2] > c[2] end)
    for k = MAX_BINS_KEPT + 1, #arr do bins[arr[k][1]] = nil end
end

local function curTrackKey()
    local k = nil
    pcall(function() if ac.getTrackFullID then k = ac.getTrackFullID('/') end end)
    if not k or k == '' then pcall(function() if ac.getTrackID then k = ac.getTrackID() end end) end
    return tostring(k or 'track')
end

local function loadAll()
    local all = {}
    pcall(function()
        local s = store.troubleData
        if type(s) == 'string' and #s > 0 then all = stringify.tryParse(s, nil, {}) or {} end
    end)
    return type(all) == 'table' and all or {}
end

function T.save(force)
    if not force and not dirtyStore then return end
    pcall(function()
        for _, bins in pairs(data) do pruneClass(bins) end    -- hard-bound each class before writing
        local all = loadAll()
        all[trackKey] = data
        store.troubleData = stringify(all)
    end)
    dirtyStore = false
end

-- Session start: save the outgoing track's map, then load the incoming track's.
function T.reset()
    pcall(T.save, true)
    trackKey = curTrackKey()
    -- size the bins to this track's length so a "corner" spans a similar distance on every track
    local len = 0
    pcall(function() local s = ac.getSim(); if s and s.trackLengthM then len = s.trackLengthM end end)
    if len < 200 then len = 4000 end                          -- fallback if length is unavailable
    nbins = clamp(math.floor(len / BIN_METERS + 0.5), MIN_BINS, MAX_BINS)
    lookaheadFrac = clamp(LOOKAHEAD_M / len, 0.001, 0.05)
    data = {}
    pcall(function()
        local td = loadAll()[trackKey]
        if type(td) == 'table' then data = td end
    end)
    lastSave = os.clock(); lastDecay = os.clock()
end

-- Report an incident (a car crashed/spun/beached) at a track position, for a class.
function T.incident(spline, cls)
    if not T.ENABLED or type(spline) ~= 'number' then return end
    cls = cls or 'road'
    local bin = math.floor((spline % 1) * nbins) % nbins
    for d = 0, UPSTREAM do
        local b = (bin - d) % nbins
        local w = 1.0 - d * 0.25
        if w > 0 then
            data[cls] = data[cls] or {}
            data[cls][b] = math.min(HEAT_MAX, (data[cls][b] or 0) + w * INCIDENT_HEAT)
            data['_global'] = data['_global'] or {}
            data['_global'][b] = math.min(HEAT_MAX, (data['_global'][b] or 0) + w * INCIDENT_HEAT)
        end
    end
    dirtyStore = true
end

-- Caution to apply for a car approaching `spline` in class `cls` (0 if it isn't a trouble spot).
function T.cautionAt(spline, cls)
    if not T.ENABLED or type(spline) ~= 'number' then return 0 end
    local bin = math.floor(((spline + lookaheadFrac) % 1) * nbins) % nbins
    local h = (data[cls] and data[cls][bin]) or 0
    if h < HOT_THRESHOLD then h = (data['_global'] and data['_global'][bin]) or 0 end   -- fallback
    if h < HOT_THRESHOLD then return 0 end
    return clamp((h - HOT_THRESHOLD) / HOT_RANGE, 0, 1) * MAX_CAUT
end

function T.update(dt)
    if not T.ENABLED then return end
    local now = os.clock()
    if now - lastDecay > 1.0 then
        local f = 1 - DECAY_PER_SEC * (now - lastDecay); lastDecay = now
        for _, bins in pairs(data) do
            for b, h in pairs(bins) do
                local nh = h * f
                if nh < FLOOR then bins[b] = nil else bins[b] = nh end
            end
        end
    end
    if now - lastSave > SAVE_EVERY then lastSave = now; T.save(false) end
end

-- diagnostic: how many hot spots the track currently has (global aggregate)
function T.hotCount()
    local n, g = 0, data['_global']
    if g then for _, h in pairs(g) do if h >= HOT_THRESHOLD then n = n + 1 end end end
    return n
end

return T
