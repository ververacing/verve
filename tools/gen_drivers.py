# Reads the driver CSV and derives Verve's four 0..1 scalars (pace/aggr/risk/cons) with one
# consistent rubric, then writes lib/drivers.lua. Rubric is documented inline so it's editable.
import csv, re, sys

CSV = sys.argv[1]
OUT = sys.argv[2]

ROSTER_BUCKET = {
    'F1-modern':'f1', 'F1-classic':'f1', 'Formula-Indy':'f1', 'Vintage':'vintage',
    'Prototype':'proto', 'GT':'gt', 'Touring':'touring', 'Rally':'rally', 'Drift':'drift',
    'NASCAR-modern':'nascar', 'NASCAR-classic':'nascar', 'Oval-Indy':'f1', 'Oval-Dirt':'nascar',
}
# rosters where counts are comparable enough to compute rate-based pace/risk
RATE_ROSTERS = {'F1-modern','F1-classic','Vintage','Rally','NASCAR-modern','NASCAR-classic'}

def num(x):
    x=(x or '').strip()
    if x=='' : return None
    try: return float(x)
    except: return None

def clamp(v,a,b): return a if v<a else b if v>b else v

# --- style lexicons (substring match on lowered style text) ---
AGGR_UP = ['aggressive','attacker','hard-charging','hard charger','elbows','dive','diving','relentless',
    'combative','bold','forceful','fearless','flat-out','flat out','spectacular','wild','brave','committed',
    'attacking','ruthless','audacious','never gives up',"won't yield",'punchy','confrontational','hard defender',
    'hard racer','sideways','big angle','big commitment','extreme proximity','all-or-nothing','overtaker',
    'late-braking','from nowhere','heroic','flamboyant','showman','never quits']
AGGR_DOWN = ['smooth','calm','calculated','calculating','methodical','tidy','measured','cerebral','gentlemanly',
    'easygoing','clinical','precise','meticulous','unflappable','unflustered','ice-cool','quiet','silky','steady',
    'low-drama','analytical','disciplined','controlled']
RISK_UP = ['wild','crash-prone','flat-out','all-or-nothing','on the edge','overdrive','overdrives','emotional',
    'reckless','spectacular','heroic','fearless','big-moment','clumsy','error-prone','streaky','inconsistent',
    'wobbles','flamboyant','on the limit','overdrove']
RISK_DOWN = ['clinical','precise','tidy','methodical','calm','ice-cool','rarely errs','low-error','low-drama',
    'metronomic','consistent','calculated','calculating','meticulous','mechanically sympathetic','unflappable',
    'unflustered','disciplined','controlled','kind to cars','dependable','composed','cool under pressure']
CONS_UP = ['metronomic','consistent','clinical','methodical','meticulous','reliable','dependable','steady',
    'low-drama','low-error','ice-cool','unflappable','unflustered','calculated','disciplined','tidy',
    'kind to cars','composed','cool under pressure','relentless consistency']
CONS_DOWN = ['streaky','inconsistent','emotional','wild','crash-prone','flamboyant','all-or-nothing','on the edge',
    'wobbles','overdrive','overdrives','spectacular','heroic','error-prone']

def hits(text, words):
    t=text.lower()
    return sum(1 for w in words if w in t)

def slug(name):
    s=name.lower()
    s=s.replace('.','').replace("'",'').replace('-',' ')
    s=re.sub(r'[^a-z0-9]+','_',s).strip('_')
    return s

rows=[]
with open(CSV, newline='', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if not (r.get('driver') or '').strip(): continue
        rows.append(r)

# group by roster for within-roster pace normalisation
from collections import defaultdict
byrost=defaultdict(list)
for r in rows: byrost[r['roster']].append(r)

def merit(r):
    starts=num(r['starts']); wins=num(r['wins']); poles=num(r['poles'])
    podiums=num(r['podiums']); champs=num(r['championships']) or 0; avg=num(r['avg_finish_est'])
    m=0.0
    if starts and starts>0:
        if wins is not None: m += 3.0*(wins/starts)
        if poles is not None: m += 1.5*(poles/starts)
        if podiums is not None: m += 1.0*(podiums/starts)
    m += 0.4*champs
    if avg is not None: m -= 0.02*avg
    return m

# precompute min/max merit per rate-roster and per proto
rost_minmax={}
for rost,rs in byrost.items():
    ms=[merit(r) for r in rs]
    rost_minmax[rost]=(min(ms),max(ms))

def pace_of(r):
    rost=r['roster']; style=r['style'] or ''; champs=num(r['championships']) or 0
    if rost in RATE_ROSTERS or rost=='Prototype':
        lo,hi=rost_minmax[rost]; m=merit(r)
        nrm=0.5 if hi<=lo else (m-lo)/(hi-lo)
        if rost=='Prototype':
            p=0.75+0.20*nrm      # endurance aces: compressed high band
        else:
            p=0.62+0.34*nrm
    else:  # GT / Touring / Drift : champs + style tier
        p=0.74+min(champs,5)*0.035
        if hits(style,['benchmark','dominant','huge one-lap','blistering','sublime','raw pace','raw qualifying','record']): p+=0.05
        if hits(style,['still learning','young gun','teenage','rookie','moderate pace','unproven']): p-=0.06
    # small universal style nudge for clearly quick/slow descriptors
    if hits(style,['blinding','supernatural','prodigious','effortlessly','masterful']): p+=0.03
    return clamp(p,0.60,0.98)

def aggr_of(r):
    style=r['style'] or ''
    a=0.60 + 0.08*hits(style,AGGR_UP) - 0.07*hits(style,AGGR_DOWN)
    return clamp(a,0.35,0.97)

def risk_of(r):
    rost=r['roster']; style=r['style'] or ''
    starts=num(r['starts']); crash=num(r['dnf_crash_error_est'])
    if rost in RATE_ROSTERS and starts and starts>0 and crash is not None:
        base=0.18 + 2.6*(crash/starts)
    else:
        base=0.42
    base += 0.06*hits(style,RISK_UP) - 0.06*hits(style,RISK_DOWN)
    return clamp(base,0.12,0.85)

def cons_of(r):
    rost=r['roster']; style=r['style'] or ''
    starts=num(r['starts']); crash=num(r['dnf_crash_error_est']); champs=num(r['championships']) or 0
    if rost in RATE_ROSTERS and starts and starts>0 and crash is not None:
        base=0.90 - 2.2*(crash/starts)
    else:
        base=0.72
    base += 0.03*champs
    base += 0.05*hits(style,CONS_UP) - 0.05*hits(style,CONS_DOWN)
    return clamp(base,0.40,0.97)

seen=set()
entries=[]
for r in rows:
    name=r['driver'].strip()
    key=slug(name)
    while key in seen: key+='_x'
    seen.add(key)
    bucket=ROSTER_BUCKET[r['roster']]
    entries.append((key,name,bucket,round(pace_of(r),2),round(aggr_of(r),2),round(risk_of(r),2),round(cons_of(r),2),r['roster']))

# ---- cross-category appearances ----
# A driver who genuinely competed in another discipline appears in that dropdown too, keeping their
# PERSONALITY (aggr/risk/cons) but with a discipline-specific PACE (their real standing there).
# Only well-documented crossovers; pace reflects results in THAT discipline. (base_key, bucket, pace)
CROSS = [
    # Karting -- just a handful of iconic kart champions; the kart grid stays mostly archetypes
    ('max_verstappen','kart',1.00), ('ayrton_senna','kart',0.96), ('michael_schumacher','kart',0.96),
    ('lewis_hamilton','kart',0.97), ('lando_norris','kart',0.98),
    # Prototype / Le Mans / WEC (real sportscar results)
    ('fernando_alonso','proto',0.90), ('nico_hulkenberg','proto',0.88), ('mark_webber','proto',0.92),
    ('juan_pablo_montoya','proto',0.85), ('jenson_button','proto',0.80), ('robert_kubica','proto',0.85),
    ('mario_andretti','proto',0.88),
    # GT
    ('fernando_alonso','gt',0.86), ('juan_pablo_montoya','gt',0.84), ('jenson_button','gt',0.82),
    # Rally (competed, midfield privateer level)
    ('kimi_raikkonen','rally',0.58), ('robert_kubica','rally',0.62),
    # Touring / DTM
    ('hans_joachim_stuck','touring',0.88), ('alex_zanardi','touring',0.78),
    # F1 (endurance names who had real F1 careers)
    ('jacky_ickx','f1',0.82), ('hans_joachim_stuck','f1',0.68),
]
scalars={k:(a,rk,c,nm) for k,nm,b,p,a,rk,c,ro in entries}
for bk,bkt,pace in CROSS:
    s=scalars.get(bk)
    if not s: print("  ! cross base not found:", bk); continue
    a,rk,c,nm=s
    entries.append((bk+'_'+bkt, nm, bkt, round(pace,2), a, rk, c, 'Cross-category appearances'))

# ---- emit drivers.lua ----
HEADER = '''-- Verve / drivers.lua
-- OPTIONAL per-grid-slot driver profiles. Session-only: keyed by car INDEX and wiped every race,
-- so five identical cars can be five different drivers. Assigning a profile OVERRIDES the field's
-- uniform treatment for that one car -- its own pace (per-car AI level), aggression, risk
-- (mistakes) and consistency -- while the CAR CLASS still governs racecraft STYLE (an "Auto
-- (formula)" car still slipstreams and defends like an F1). Blank slot = the normal slider system.
--
-- The four scalars (0..1, 0.5 = field average) are DERIVED from public racing record by one
-- consistent rubric (see tools/gen_drivers.py): pace from win/pole/podium rate + titles + avg
-- finish (normalised within each roster); aggression + risk + consistency from crash/error-DNF
-- rate and racing style. Same idea the official F1 games use (real drivers, numeric ratings).
-- Not affiliated with any driver, team or series -- for entertainment. Numbers are easy to edit.

local Classes = require('lib.classes')
local D = {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
-- pace spreads AI level DOWN from the difficulty. The FASTEST driver actually on the grid runs at the
-- slider level, and everyone else is spaced below by how far their pace rating trails his -- so the
-- field genuinely strings out instead of bunching. Widened (0.16 -> 0.32) because the old value barely
-- separated the field: a mid-pack driver ended up only a few hundredths of an AI level off the ace.
local PACE_SPREAD = 0.32

-- Detected class -> roster bucket. Classes not listed (road) offer only the archetypes.
local CLASS_BUCKET = {
    formula = 'f1', formula_jr = 'f1', kart = 'kart',
    prototype = 'proto', hypercar = 'proto', gt = 'gt',
    touring = 'touring', vintage = 'vintage', rally = 'rally', drift = 'drift', nascar = 'nascar',
}
'''

ARCHETYPES = '''    -- Generic archetypes: always offered, used for randomize overflow. Labelled so nobody mistakes
    -- them for a real name.
    { key='arch_ace',        name='Archetype - Ace',        bucket='archetype', pace=0.90, aggr=0.70, risk=0.25, cons=0.90 },
    { key='arch_charger',    name='Archetype - Charger',    bucket='archetype', pace=0.80, aggr=0.95, risk=0.55, cons=0.75 },
    { key='arch_veteran',    name='Archetype - Veteran',    bucket='archetype', pace=0.75, aggr=0.55, risk=0.20, cons=0.95 },
    { key='arch_midfield',   name='Archetype - Midfielder', bucket='archetype', pace=0.50, aggr=0.50, risk=0.35, cons=0.80 },
    { key='arch_wildcard',   name='Archetype - Wildcard',   bucket='archetype', pace=0.65, aggr=0.75, risk=0.80, cons=0.45 },
    { key='arch_rookie',     name='Archetype - Rookie',     bucket='archetype', pace=0.35, aggr=0.50, risk=0.60, cons=0.50 },
    { key='arch_backmarker', name='Archetype - Backmarker', bucket='archetype', pace=0.20, aggr=0.40, risk=0.45, cons=0.70 },
'''

FOOTER = '''}

-- indexes
local BY_KEY, ARCHETYPES = {}, {}
for _, d in ipairs(D.DRIVERS) do
    BY_KEY[d.key] = d
    if d.bucket == 'archetype' then ARCHETYPES[#ARCHETYPES + 1] = d end
end

function D.nameOf(key) local d = BY_KEY[key]; return d and d.name or key end

function D.rosterFor(classKey)
    local bucket = CLASS_BUCKET[classKey]
    local out = {}
    if bucket then
        for _, d in ipairs(D.DRIVERS) do if d.bucket == bucket then out[#out + 1] = d end end
    end
    for _, d in ipairs(ARCHETYPES) do out[#out + 1] = d end
    return out
end

local assigned = {}
local baseLevel = {}
-- the fastest pace rating among drivers currently on the grid -- the anchor everyone is spread below.
-- Recomputed lazily whenever the grid changes, so difficulty always tracks the best driver present.
local fieldMaxPace, paceDirty = 1.0, true
local function recomputeFieldMaxPace()
    local m = 0
    for _, k in pairs(assigned) do
        local d = BY_KEY[k]
        if d and d.pace and d.pace > m then m = d.pace end
    end
    fieldMaxPace = (m > 0) and m or 1.0
    paceDirty = false
end

function D.setProfile(i, key)
    if key == nil or key == '' then assigned[i] = nil else assigned[i] = key end
    paceDirty = true
end
function D.profileOf(i) return assigned[i] end
function D.statsOf(i)
    local k = assigned[i]
    if not k then return nil end
    return BY_KEY[k]
end
function D.anyAssigned() for _ in pairs(assigned) do return true end return false end
function D.clearAll() assigned = {}; paceDirty = true end
function D.reset() assigned = {}; baseLevel = {}; fieldMaxPace = 1.0; paceDirty = true end

function D.randomizeGrid()
    pcall(function()
        math.randomseed(os.time() + math.floor((os.clock() * 1000) % 100000))
        local sim = ac.getSim(); if not sim then return end
        local usedByBucket = {}
        for i = 1, sim.carsCount - 1 do
            local car = ac.getCar(i)
            if car and car.isAIControlled then
                local bucket = CLASS_BUCKET[Classes.keyOf(i)]
                local pick = nil
                if bucket then
                    usedByBucket[bucket] = usedByBucket[bucket] or {}
                    local pool = {}
                    for _, d in ipairs(D.DRIVERS) do
                        if d.bucket == bucket and not usedByBucket[bucket][d.key] then pool[#pool + 1] = d end
                    end
                    if #pool > 0 then
                        pick = pool[math.random(#pool)]
                        usedByBucket[bucket][pick.key] = true
                    end
                end
                if not pick and #ARCHETYPES > 0 then pick = ARCHETYPES[math.random(#ARCHETYPES)] end
                if pick then assigned[i] = pick.key end
            end
        end
        paceDirty = true
    end)
end

function D.applyPace(i)
    pcall(function()
        local st = D.statsOf(i)
        local car = ac.getCar(i); if not car then return end
        if st then
            if baseLevel[i] == nil then
                local lvl = car.aiLevel
                baseLevel[i] = (type(lvl) == 'number' and lvl > 0) and lvl or 1.0
            end
            if paceDirty then recomputeFieldMaxPace() end
            -- anchor to the fastest driver on the grid: he runs at the slider (baseLevel), everyone else
            -- is spaced below by how far their pace trails his. Never above the slider.
            physics.setAILevel(i, clamp(baseLevel[i] - (fieldMaxPace - st.pace) * PACE_SPREAD, 0.70, baseLevel[i]))
        elseif baseLevel[i] ~= nil then
            physics.setAILevel(i, baseLevel[i])
            baseLevel[i] = nil
        end
    end)
end

return D
'''

lines=[HEADER, 'D.DRIVERS = {\n']
cur=None
for key,name,bucket,p,a,rk,c,rost in entries:
    if rost!=cur:
        lines.append(f'    -- {rost}\n'); cur=rost
    nm=name.replace("'","\\'")
    lines.append(f"    {{ key='{key}', name='{nm}', bucket='{bucket}', pace={p:.2f}, aggr={a:.2f}, risk={rk:.2f}, cons={c:.2f} }},\n")
lines.append('\n')
lines.append(ARCHETYPES)
lines.append(FOOTER)

with open(OUT,'w',encoding='utf-8') as f:
    f.write(''.join(lines))

# sanity print for marquee names
want={'ayrton_senna','alain_prost','lewis_hamilton','max_verstappen','lance_stroll','fernando_alonso',
      'colin_mcrae','sebastien_loeb','juan_manuel_fangio','jim_clark','ken_miles','tom_kristensen',
      'james_deane','keiichi_tsuchiya','valentino_rossi','franco_colapinto','gilles_villeneuve'}
print(f"{'driver':22} {'bkt':7} pace aggr risk cons")
for key,name,bucket,p,a,rk,c,rost in entries:
    if key in want:
        print(f"{name:22} {bucket:7} {p:.2f} {a:.2f} {rk:.2f} {c:.2f}")
print(f"\nTOTAL drivers: {len(entries)}")
from collections import Counter
print("per bucket:", dict(Counter(e[2] for e in entries)))
