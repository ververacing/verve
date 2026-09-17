-- Verve / troublespots.lua
-- Learns where cars REPEATEDLY crash/spin/beach on a track and adds a little caution there, so the
-- field stops piling into the same corner. Per track + per class, with a track-wide fallback until a
-- class has its own history. Persisted across sessions via ac.storage, so the second race on a track
-- already knows its hot spots. Heat decays if incidents stop, so a corner we've calmed relaxes again.
--
-- A trouble spot is RELATIVE: the handful of corners that are hot compared with the rest of the track.
-- An earlier build used an absolute threshold, and on a track with a long history (Zandvoort) every
-- kept bin ended up over it -- 40 "hot spots", a quarter of the lap, the whole field pegged at maximum
-- caution everywhere and the per-corner lever meaningless. Now the worst corner gets the full caution,
-- the others in proportion, and a merely-average bin gets none.

local T = {}
T.ENABLED = false
T.FRESH = false      -- harness: this session neither loads nor saves the persisted map (learns within the race only), so an
                     -- A/B measures the rule under test, not the heat a day of sprints left behind (Spa maxed out 2026-09-16)

-- bins are sized in METRES, not a fixed count, so resolution is ~constant on every track (a long
-- track gets more bins, a short one fewer -- a "corner" is the same size in metres everywhere).
local BIN_METERS    = 24.0       -- target bin length
local MIN_BINS      = 40         -- clamp the count for very short / very long tracks
local MAX_BINS      = 600
local LOOKAHEAD_M   = 45.0       -- apply the caution ~this many metres BEFORE the spot (brake earlier). Raised:
                                 -- the offs cluster at a few specific corners, so cars need to be slowing
                                 -- for the hot corner sooner, not just at it.
local INCIDENT_HEAT = 1.0
local UPSTREAM      = 3          -- also heat this many bins upstream (the cause precedes the mess)
local HOT_THRESHOLD = 2.5        -- bin heat before it can count as a trouble spot at all...
local HOT_REL       = 0.5        -- ...AND it must be at least this fraction of the track's hottest bin
local MAX_CAUT      = 0.35       -- caution added at the track's WORST corner (others in proportion). Was 0.70:
                                 -- the cars at the FRONT of a train crawled through the hot corner at 76 km/h
                                 -- while the ones behind arrived at 170 -- the caution itself made the pile-up.
                                 -- Drivers are a bit more careful at a corner that bites; they don't tiptoe.
local DECAY_PER_SEC = 0.0002     -- heat bleeds off slowly (~a few races) if incidents stop
local SAVE_EVERY    = 20.0       -- seconds between debounced saves
local FLOOR         = 0.05       -- drop a bin once its heat decays below this (keeps storage sparse)
local HEAT_MAX      = 9.0        -- cap heat so it can't grow unbounded over hundreds of races (small numbers)
local MAX_BINS_KEPT = 40         -- keep only the hottest N bins per class per track -- hard bound on size
-- Field-wide "crashiness" comes from what's happening THIS session, not from the stored map: a decaying
-- count of recent incidents. (Seeding it from history pegged it at 1.0 on Zandvoort from lap one, and
-- the logs showed that permanent max damping didn't reduce the offs at all -- it just made everyone
-- slow.) Drivers calm down after seeing crashes and relax again when the race settles: that's human.
local RECENT_TAU    = 240.0      -- seconds: how long a recent incident keeps the field's guard up
local CRASH_RECENT  = 6.0        -- this many recent incidents = fully crash-prone

local store = ac.storage({ troubleData = '' })
local data  = {}                 -- data[cls][bin] = heat for the CURRENT track ('_global' = all classes)
local peak  = {}                 -- peak[cls] = hottest bin heat in that class map (refreshed each second)
local trackKey = 'track'
local nbins, lookaheadFrac = 200, 0.008   -- recomputed per track from its length in T.reset()
local lastSave, lastDecay = 0, 0
local dirtyStore = false
local booted = false             -- have we loaded this track's data yet? (self-heal after a hot-reload)
local recent = 0                 -- decaying count of incidents this session
T.storeLen = 0                   -- diagnostics: size of the last persisted map
T.lastSaveOk = true              -- diagnostics: did the last save read back intact?

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

local function refreshPeaks()
    peak = {}
    for cls, bins in pairs(data) do
        local p = 0
        for _, h in pairs(bins) do if h > p then p = h end end
        peak[cls] = p
    end
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
    if T.FRESH then return end
    if not force and not dirtyStore then return end
    pcall(function()
        for _, bins in pairs(data) do pruneClass(bins) end    -- hard-bound each class before writing
        local all = loadAll()
        -- NEVER overwrite a track's learned data with an empty set. A CSP hot-reload (or the app
        -- re-initialising) resets `data` to {}; without this guard the next save/reset would wipe the
        -- stored history for the track. If we have nothing in memory, leave whatever's on disk alone.
        if next(data) == nil and all[trackKey] ~= nil then return end
        all[trackKey] = data
        local s = stringify(all)
        store.troubleData = s
        T.storeLen = #s
        -- self-check: read it straight back. If the store silently rejected it (size, format), say so in
        -- the CSP log rather than quietly losing a track's history.
        local back = store.troubleData
        T.lastSaveOk = (type(back) == 'string' and #back == #s)
        if not T.lastSaveOk then ac.log(string.format('Verve: trouble-spot save did not stick (%d chars)', #s)) end
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
    recent = 0
    if not T.FRESH then pcall(function()
        local td = loadAll()[trackKey]
        if type(td) == 'table' then data = td end
    end) end
    refreshPeaks()
    -- Seed the field's guard from the track's history, DECAYING: a known-nasty track starts the race
    -- cautious (that's what kept the opening-lap pile-ups down -- removing it cost 9 lap-0 incidents in
    -- one race) and relaxes over the first minutes if the race is actually clean.
    recent = CRASH_RECENT * 0.6 * clamp((peak['_global'] or 0) / HEAT_MAX, 0, 1)
    pcall(function()
        local n = 0
        if data['_global'] then for _ in pairs(data['_global']) do n = n + 1 end end
        ac.log(string.format('Verve: trouble-spots for %s: %d bins, peak heat %.1f', trackKey, n, peak['_global'] or 0))
    end)
    lastSave = os.clock(); lastDecay = os.clock()
    booted = true
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
    recent = recent + 1
    dirtyStore = true
end

-- heat of a bin IF it's a trouble spot for this class (relative to the class map's peak), else 0.
-- Falls back to the track-wide map when the class has no history of its own there.
local function hotHeat(cls, bin)
    local h = (data[cls] and data[cls][bin]) or 0
    local p = peak[cls] or 0
    if h < HOT_THRESHOLD or h < p * HOT_REL then
        h = (data['_global'] and data['_global'][bin]) or 0
        p = peak['_global'] or 0
    end
    if h < HOT_THRESHOLD or h < p * HOT_REL then return 0, p end
    return h, p
end

-- Caution to apply for a car approaching `spline` in class `cls` (0 if it isn't a trouble spot).
-- The track's worst corner gets MAX_CAUT; lesser hot spots get a proportional share.
function T.cautionAt(spline, cls)
    if not T.ENABLED or type(spline) ~= 'number' then return 0 end
    local bin = math.floor(((spline + lookaheadFrac) % 1) * nbins) % nbins
    local h, p = hotHeat(cls or 'road', bin)
    if h <= 0 then return 0 end
    local span = math.max(p, HOT_THRESHOLD + 1.0) - HOT_THRESHOLD
    return clamp((h - HOT_THRESHOLD) / span, 0, 1) * MAX_CAUT
end

function T.update(dt)
    -- Self-heal: if the module re-initialised (a CSP hot-reload, or the app reloading) without a fresh
    -- session start, `data` is empty and this track's learned hot-spots aren't loaded -- so the adaptive
    -- damping silently stops. Load them on the first update if a reset hasn't run this load.
    if not booted then booted = true; pcall(T.reset) end
    if not T.ENABLED then return end
    local now = os.clock()
    if now - lastDecay > 1.0 then
        local el = now - lastDecay
        local f = 1 - DECAY_PER_SEC * el; lastDecay = now
        for _, bins in pairs(data) do
            for b, h in pairs(bins) do
                local nh = h * f
                if nh < FLOOR then bins[b] = nil else bins[b] = nh end
                dirtyStore = true   -- decay changes the map too -> must be saved, or a calmed corner reloads hot
            end
        end
        recent = math.max(0, recent * (1 - el / RECENT_TAU))
        refreshPeaks()
    end
    if now - lastSave > SAVE_EVERY then lastSave = now; T.save(false) end
end

-- diagnostic: how many genuine trouble spots the track currently has (track-wide map)
function T.hotCount()
    local n, g = 0, data['_global']
    local p = peak['_global'] or 0
    if g then for _, h in pairs(g) do if h >= HOT_THRESHOLD and h >= p * HOT_REL then n = n + 1 end end end
    return n
end

-- diagnostic: the hottest bin's heat on this track
function T.peakHeat() return peak['_global'] or 0 end

-- How crash-prone the race is proving RIGHT NOW, 0..1, from recent incidents this session (decaying).
-- The director uses this to calm the whole field down while cars keep going off -- and to let them
-- race again once things settle.
function T.crashiness()
    if not T.ENABLED then return 0 end
    return clamp(recent / CRASH_RECENT, 0, 1)
end

return T
