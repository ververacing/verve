-- Verve / racecraft.lua  (v0.5)
-- Our own racecraft from CSP AI primitives. Per AI car we read the gap to the nearest car
-- ahead/behind (+ their lateral position on track) and the shape of the track just ahead, then:
--   ATTACK  -- car in range & keeping up: tuck in (less caution), raise aggression, and pick a
--             passing line -- dive up the INSIDE of the corner ahead if it's open, else pass on
--             the side the defender isn't (slipstream out on straights).
--   DEFEND  -- faster car behind: ONE move to cover the vulnerable side (inside of the corner
--             ahead, or the side the attacker is on) and hold.
--   CRUISE  -- clear track: back to the racing line.
--
-- Track frame (ac.worldCoordinateToTrack): X = -1 left .. +1 right, Z = progress. Same sign as
-- setAISplineOffset, so lateral reads and offsets share one frame -- no handedness guessing.
-- Offset is slew-limited (anti-dart) and collision-awareness stays ON, so cars position not ram.
--
-- Per-CLASS tactics tune HOW each class races (an F1 slipstreams from far and passes precisely;
-- a touring car dive-bombs the inside). The global racecraft INTENSITY slider scales it all; the
-- Variability slider spreads per-driver aggression so the field isn't uniform. A short "pounce"
-- keeps a car eager to fill a gap right after it opens.

local Classes   = require('lib.classes')
local Drivers   = require('lib.drivers')
local Troublespots = require('lib.troublespots')
local Recovery  = require('lib.recovery')     -- for damage-since-repair (recovery never requires racecraft: no cycle)
local Strategy  = require('lib.strategy')     -- planned manoeuvres on top of attack mode (set-up, lunge, switchback, slingshot)

local R = {}
R.ENABLED     = true
R.INTENSITY   = 0.7        -- racecraft "how hard they race" slider
R.VARIABILITY = 0.5        -- variability slider: spreads per-driver aggression across the field
R.attacking = 0
R.defending = 0
R.isOval = false           -- set per session: true if the track turns mostly one way (an oval/speedway)

-- oval groove: on a speedway, stock cars commit to a high or low LANE and run it side-by-side
-- through the banking, instead of all returning to one racing line.
local GROOVE_RANGE  = 0.020  -- a car ahead within this spline gap -> we're in a pack, run a groove
local GROOVE_OFFSET = 0.62   -- how far toward the high/low line to commit (edge-safety still bounds it)
local GROOVE_HOLD   = 3.0    -- s to commit to a chosen lane (sustained, not a dart)

local AGGR_SPREAD = 0.15   -- per-driver aggression spread (scaled by the Variability slider)
local POUNCE_HOLD = 1.2    -- s a car stays eager to fill a gap after following someone
local POUNCE_CAUT = -0.5   -- extra closing while pouncing (fill the opened space, don't hang back)
-- Move commitment: once a car commits to attacking or defending it holds that INTENT for a
-- short beat instead of re-deciding every frame. A genuine read (re)commits; when the read
-- briefly drops (gap wobbles just past the line, speed dips in dirty air) the car coasts the
-- committed decision until a wider release threshold clears it. Kills frame-to-frame dithering
-- and makes passes / defences decisive instead of hesitant.
local COMMIT_HOLD    = 0.7   -- s to hold a committed attack/defend decision
local COMMIT_RELEASE = 1.5   -- gap must grow past threshold*this to drop the commitment early

-- Race awareness: competent drivers manage risk by CONTEXT, not just the car in front.
--   Opening-lap caution -- cold tyres + a packed grid: calmer, more spacing, less line-swapping
--     off the line, fading across the first lap. Kills first-corner pile-ups.
--   Stakes / bring-it-home -- with clear track both ways there's nothing to win by pushing, so a
--     lone car circulates a touch calmer instead of binning it for no reason.
--   Blue-flag yield -- a car on a higher lap coming through gets let past (move off-line, lift),
--     instead of being fought like a rival.
--   Leave room -- when genuinely alongside (overlapping) and NOT the car with the corner, don't
--     pinch into them; ease off and lift. Pure contact-reducer.
-- All are applied AFTER the racecraft-intensity scale, so the safety holds even at low intensity.
local OPENLAP_CAUT   = 0.45  -- extra caution at the very start of a race (0.38 -> 0.45, 2026-09-15: half the grid took contact on lap 1)
local OPENLAP_AGGR   = 0.45  -- aggression trimmed by up to this fraction at the start
local OPENLAP_OFFSET = 0.55  -- line-changes trimmed by up to this fraction at the start
local OPENLAP_FLOOR  = 0.30  -- the effect never drops below this during lap 0 (it used to be gone by half distance)
local OPENLAP_TAIL   = 0.40  -- ...and fades out over this fraction of lap 1 (a fifth of the contacts were on lap 1)
local OPENLAP_ATTACK = 0.60  -- attack-mode caution relief is scaled back by this much while the opening lap is in force
-- grid funnel: off the line, hold each car near its own starting lane and let it merge onto the
-- racing line GRADUALLY over the run to turn 1, instead of all 22 diving for the line at once.
local GRID_FADE_END  = 0.05  -- lane-hold fades to the racing line over this fraction of lap 1
local GRID_CAPTURE   = 0.02  -- capture a car's grid lane while it's still within this fraction (near the grid)
local GRID_HOLD      = 1.0   -- how strongly to hold the captured lane (1 = fully)
local ISOLATED_GAP   = 0.030 -- clear track BOTH ways -> nothing to race
local ISOLATED_AGGR  = 0.20  -- aggression trim when isolated
local ISOLATED_CAUT  = 0.10  -- small lift when isolated (no pointless risk)
-- pack leader / clear-ahead: a car with open road ahead can't be passed if it just DRIVES AWAY, so it
-- shouldn't sit in a slow defensive line every corner (that's what stalls the front of a bunch and
-- concertinas everyone behind). It keeps the racing line and gets a small pace stretch to string the
-- field out, instead of the whole crowd circulating nose-to-tail at one pace.
local PACK_LEAD_GAP  = 0.012 -- this much clear track ahead = "drive away" rather than defend a line
local PACK_STRETCH   = 0.14  -- small pace stretch (less caution) for a car leading a pack, to open it up
-- adaptive crash damping: the crashier a track has proven (from its learned trouble-spot history), the
-- calmer the WHOLE field runs -- more caution, less aggression, a bigger opening-lap ease, and the pace
-- stretch pulled back. Self-calibrating: a nasty track (Zandvoort) settles down, a clean one stays racy.
R.CRASH_CAUT = 0.20          -- extra field-wide caution at a fully crash-prone track (was 0.35 -- see CAUT_MAX); harness A/B field
R.CRASH_AGGR = 0.35          -- aggression trimmed by up to this fraction at a fully crash-prone track; harness A/B field
-- The back-off terms (hot corner, crash damping, cold tyres, anti-rear-end, pounce, leave-room...) are each
-- sensible alone but they STACK: a train reached caution 1.9 into a corner and its front cars crawled
-- through at 76 km/h while the tail arrived at 170. Different speeds in one corner is what actually
-- causes pile-ups, so the total racecraft caution is capped -- "careful", never "crawling".
local CAUT_MAX       = 0.80
-- anti rear-end: closing fast while sat DIRECTLY behind the car ahead (not moving alongside to pass)
-- -> ease the final approach so we don't pile into its gearbox in the braking zone. AC's own AI does
-- this badly; this is the biggest cause of the pack "wrecking crew". Even aggressive drivers keep a
-- margin, scaled by Risk. (When a car pulls off-line to pass, it's no longer "behind" -> no back-off.)
local REAREND_GAP    = 0.005 -- only this close behind counts as a rear-end risk
local REAREND_LAT    = 0.28  -- and only when roughly on the same line (directly behind), not alongside
local REAREND_CLOSE  = 8.0   -- km/h of closing speed before we start easing
local REAREND_RANGE  = 26.0  -- full ease by this much closing (close + range)
local REAREND_CAUT   = 1.2   -- how firmly to back off (kept high because a rear-end is a race-ruiner)
-- blockage: a car crawling far below pace just ahead and on my line (a crash / spun / limping car) is
-- an OBSTACLE, not a rival. Don't queue up behind it (anti-rear-end would just brake to a crawl) --
-- sweep around it on the OPEN side of the track. This is "if the line's blocked, take the open road".
local BLOCK_SPEED    = 24.0  -- a car ahead crawling below this (absolute) is a blockage (stalled/crashed)
-- OR a genuinely-slow car (a limper) that I'm arriving on much faster. Both gates matter: the absolute
-- cap keeps this from firing on a car simply BRAKING for a corner (that's ~100+ km/h, not a limper) --
-- without it, a fast car behind treated every braking car as an obstacle and swerved around it into the
-- corner, which was a contact machine at fast tracks.
local BLOCK_LIMP     = 55.0  -- only a car below THIS absolute speed can be a "limper" blockage
local BLOCK_DELTA    = 50.0  -- and I must be at least this much faster than it (clearly arriving on it)
local BLOCK_GAP      = 0.006 -- look this far ahead for the obstacle (start peeling off a bit earlier)
local BLOCK_MARGIN   = 6.0   -- I only need to be a little faster than it (so cars queued behind it still peel off)
local BLOCK_TIME     = 2.0   -- ...and at least this many SECONDS of travel at my speed: 27 m is 0.8 s at 120 km/h,
                             -- which is how a car T-boned a crawler at the last corner before it could move over
local BLOCK_OFFSET   = 0.48  -- swing this far to the open side -- just enough to sneak past, not a huge berth
local BLOCK_HOLD     = 1.5   -- commit to the avoidance side briefly (don't dart back into it)
local BLOCK_EDGE     = 0.60  -- only sweep around an obstacle THIS central; a car parked well off to the
                             -- side (in the grass/gravel) needs no berth -- just drive past it on the line
local YIELD_GAP      = 0.010 -- a lapping car this close behind -> start moving aside
-- OPENING-LAP CONVOY (harness A/B: R.CONVOY_ON): lap 0, first CONVOY_END of the lap, a car within CONVOY_GAP of the car
-- ahead on a similar line is capped at that car's speed + CONVOY_MARGIN. Stops the nose-to-tail hits into turn one
-- and the pile-ups they start (41% + 46% of opening-lap incidents in the 2026-09-15 feeds); racing resumes after.
R.CONVOY_ON = false          -- v1 speed cap: OFF (halved lap-1 contact at Barcelona, 16-of-18 pile-up at Spa); kept for experiments
-- (one table: LuaJIT allows a function 120 upvalues and R.evaluate's closure was over the limit -- Verve then fails to load)
local CV = { END = 0.45, GAP = 0.006, LAT = 0.35, MARGIN = 6.0,          -- v1: lap fraction covered, gap (m via scaleToTrack), same-line lat, km/h margin
             NEAR_M = 8.0, GAP_M = 25.0, THR_MIN = 0.35, CLOSING = 2.0,  -- v2 throttle convoy: gap at the floor, gap where it starts, floor, closing km/h
             ROW_M = 8.0, ROW_T = 0.12, THR = 0.35,                      -- v2 staggered release: one row of distance, extra hold per row, throttle while held
             ROWCAUT = 0.35, ROWCAUT_M = 90.0,                           -- brake-earlier-from-the-back: full extra caution this far behind the front car
             SPIN_FRAC = 0.55, SPIN_DOT = 0.55,                          -- opening-lap yellow: car ahead under this fraction of my speed, or nose off its travel by this much
             BG_M = 40.0, BG_HINT = 0.50, BG_BRAKE = 0.15, BG_CLOSE = 50.0,   -- brake-zone guard v2: gap where it starts, max hint CUT (lower = earlier), car-ahead brake pedal that counts, closing km/h for the full cut
             SIDE_M = 6.0, SIDE_LAT = 0.2, SIDE_LAT_MAX = 0.7, SIDE_THR = 0.55, SIDE_SPACE = 0.18,
             REACT_MIN = 0.15, REACT_THR = 0.05, PROX_NEAR = 15.0, PROX_FAR = 60.0, PRIO_OUT = 0.5,     -- reaction floor (s), caution-by-gap band (m), corner-priority outside line  -- side yield: their nose ahead of mine by less than this (m), lateral band that counts as alongside, throttle while tucking in
             RS_EDGE = 0.80, RS_MARGIN_M = 0.8, RS_CARW_M = 1.9, RS_BACK_M = 12.0, RS_FWD_M = 10.0, RS_REAREND = 0.35, RS_ADV = 0.5,
             ISO_REACH_M = 300.0, LONE_M = 50.0 }   -- alone-on-track: a car ahead within this is 'catchable' for a top-tier driver; nobody within this either way = lone   -- road space: usable edge (track units), margin + fallback car width (m), scan window behind me / past the car ahead (m), rear-end ease left while pulling out, run needed (x the aggression-scaled minimum)
local cv2 = { clock = nil, back = {}, thr = {}, bg = {}, base = {}, react = {} }      -- v2 state: lights-out clock, distance behind the front car, cars we throttled, guard applied, base brake hints
R.cv2 = cv2                                                               -- (read by diag's contact trace)
-- CONVOY v2 (harness A/B: R.CONVOY2_ON): throttle, never a speed cap. A follower closing on the car ahead on the
-- same line loses throttle in proportion to the gap; the field is released from the lights row by row.
R.CONVOY2_ON = true 
R.OL_ROWCAUT = true           -- opening lap: brake earlier the further back you started (harness A/B)
R.OL_SPINYELLOW = false       -- opening lap: a sideways / much slower car ahead is a yellow, not just a stopped one (harness A/B)
R.OL_SIDEYIELD = false        -- opening lap: alongside a car whose nose is ahead, corner coming -> tuck in behind it (harness A/B)
R.OL_SIDESPACE = false        -- laps 0-1: alongside a car -> move the lateral target away from it, leave a car's width (harness A/B)
R.GRID_FADE_X = 1.0           -- multiplier on the grid-lane hold's fade distance (225 m x this; harness A/B)
R.OL_AGGR_FORMULA = 0         -- laps 0-1: extra aggression trim (0..1) for formula / formula_jr (harness A/B)
R.OL_REACT_MAX = 0            -- lights: per-driver reaction time up to this many s (0 = off; harness A/B)
R.OL_CAUT_PROX = false        -- opening caution scaled by the gap ahead (leaders brake normally) (harness A/B)
R.OL_CORNER_PRIO = false      -- laps 0-1: alongside a car whose nose is ahead, corner coming -> take the outside line (harness A/B)
R.OL_BRAKEGUARD = true        -- opening lap: brake earlier when the car ahead on my line is already braking inside CV.BG_M (harness A/B)
R.BG_ALL = 0                  -- >0: every AI car's brake hint x this all race (direction test only; 0 = off)
-- ROAD SPACE (harness A/B: R.ROADSPACE): "use the whole road". The reactive pass aims a fixed small nudge off the racing
-- line (ATTACK_OFFSET x class), and the intensity, crowd and opening-lap multipliers plus the deadzone then shrink it to
-- nothing: a star behind a slow car ORBITS it instead of shooting the open side (kart grid 2026-09-16: 71% of attacking
-- samples under 0.10 off-line, the star's offset 0 while sat in attack for 40 s). With this on, an attacker with a real
-- run aims at a POINT ON THE ROAD: a car's width (+ margin) clear of the car ahead, on the inside of the next corner if
-- that fits, else the roomier side -- bounded by the edges and by every other car around the pair. Geometry, so it skips
-- the eagerness multipliers. DEFAULT since 2026-09-16: star from last Spa 10th -> won both, Monza 4th -> 2nd, star road use
-- 5 -> 24 %, field 6 -> 17 %, re-passes down, contacts equal; regression suite not worse on any gate; Monza manoeuvre
-- conversion 1/52 -> 8/60. Off on laps 0-1 for the pack (ungated it started pile-ups: 13/18 x2 vs 7-11); a top-tier
-- driver is exempt above RS_OL_METER.
R.ROADSPACE = true
-- ALONE ON TRACK (owner 2026-09-16: a lone star crawled through the Bus Stop with a car 140 m ahead). Two switches:
R.ISO_PACE = true             -- bring-it-home is pace-aware: a top-tier driver (tier 2) with a car within CV.ISO_REACH_M ahead does
                              -- not ease off -- that car is a target, not clear track. DEFAULT 2026-09-17 (owner): star from last
                              -- 10/8/6 vs lap-down/8/lap-down, passes 11.3 vs 6.3, field incidents 7 vs 15 (3 runs each, clean map)
R.LONE_FRAC = 0.4             -- with nobody within CV.LONE_M either way, the trouble-spot and crash-damping caution apply at this
                              -- fraction -- they exist to stop cars hitting each other. DEFAULT 2026-09-17 with ISO_PACE (0 = off)
-- (tried and dropped 2026-09-16: manoeuvres resolved on this geometry -- conversion unchanged at 13 %, fewer overtakes; a
-- lower caution cap for a committed star on laps 0-1 -- no gain. Both A/B'd, both removed.)
-- STAR ON THE OPENING LAP (harness A/B, 2026-09-16 night): room (the exemption) and a lower caution cap did not move a star
-- from last (16-17th at the end of lap 1 either way); the traces show him alongside and then losing the corner. What still
-- treats him like a rookie on lap 0: the convoy throttle limit and the opening-lap aggression trim.
R.OL_STAR_CONVOY = false      -- a top-tier driver is exempt from the convoy's gap-based throttle limit (the staggered release and the
                              -- reaction time stay: he launches with his row, then may close on the car ahead)
R.OL_STAR_AGGR = 0            -- >0: a top-tier driver keeps this fraction of the opening-lap aggression trim (0.5 = half of it)
R.SHIFT_UP = 0                -- >0: AI shift-up threshold handed to physics.setAIShiftingThresholds (units per CSP; probe first). Harness A/B
R.SHIFT_DOWN = 0.5            -- ...and the shift-down threshold that goes with it
R.RS_OL_METER = 95            -- laps 0-1: road space is allowed for a TOP-TIER driver (profile pace >= 0.75, the manoeuvre layer's tier 2)
                              -- when the difficulty meter is at or above this (0 = never). The pack stays gated; a star may go
                              -- round from the lights (owner 2026-09-16: 'Max behind a slow car with 75% of the track open')
local YIELD_GAP_FAR  = 0.027 -- ...but a car on a HIGHER LAP or a faster CLASS gets its blue flag from this far (real blue
                             -- flags come at 1-2 s; a prototype closing only on the straights never got inside 45 m of a GT3
                             -- before the next corner at Spa, so the GT3 never yielded: 88-104 s lap-arounds, 2026-09-15)
local YIELD_MAX_T    = 4.0   -- a boxed-in car lifts for at most this long per lapper; then it races on
local yieldT = {}
local YIELD_OFFSET   = 0.45  -- move this far off-line to let a faster car through. Was 0.58: at speed that put
                             -- yielding cars (damaged ones especially) into the gravel mid-corner -- a car
                             -- width is enough, and it's speed-damped below like every other line change
local DAMAGE_YIELD_HOLD = 4.0 -- a damaged car commits to its off-line side this long (vs SIDE_HOLD) -- no weaving
local DAMAGE_YIELD   = 55    -- body damage above which a car NURSES it: no diving for passes, moves over for a faster car.
                             -- Was 38: a 41 km/h first-lap tap turned a star driver into a backmarker for 15 laps (Imola 2026-09-14).
local DAMAGE_HEAVY   = 95    -- above this the car nurses it for the rest of the race
local DAMAGE_NURSE_LAPS = 2  -- lighter damage: nurse for this many laps after the last hit, then race again
local dmgSeen, dmgLap = {}, {}   -- per car: worst damage reading seen, and the lap it was seen on
                            -- so healthy cars can pass. Lowered so a moderately-hurt car yields cleanly
                            -- instead of limping down the middle and weaving as it tries to race.
local YIELD_AGGR     = 0.45  -- ease off only slightly while being lapped -- you're still racing
local YIELD_LIFT_GAP = 0.004 -- only actually lift once the lapper is THIS close (else keep racing pace)
local YIELD_CAUT     = 0.18  -- small lift as the faster car draws right up (was a big early slowdown)
-- DECISIVE LET-BY: yielding for this long with the lapper still right behind (equal pace) -> one proper lift on a
-- straight for LETBY_T seconds, then back to racing. Not in corners, once per lapper.
local LETBY_AFTER_T  = 6.0   -- s of yielding before the proper lift
local LETBY_T        = 3.0   -- s the proper lift lasts
local LETBY_CAUT     = 0.55  -- how much it lifts (on top of the small lift)
local letbyT, letbyDone, letbyFor = {}, {}, {}
local ALONGSIDE_GAP  = 0.0025-- on-track gap counting as "alongside" (overlap)
local ALONGSIDE_LAT  = 0.45  -- lateral separation under which two cars overlap
local LEAVEROOM_CAUT = 0.20  -- lift when overlapping and not the car with the corner

local ATTACK_GAP   = 0.008
local PASS_GAP     = 0.0035
local DEFEND_GAP   = 0.005
local FASTER_MARGIN= 3.0
local ATTACK_OFFSET= 0.35
-- opportunistic outside pass: with a real exit-speed run, use more of the track (wider off-line, and
-- allowed closer to the edge) to sweep around a slower car -- rather than a token move on the line.
local OUTSIDE_MIN_ADV = 8.0    -- km/h faster than the car ahead before we start using extra width
local OUTSIDE_RANGE   = 20.0   -- full extra width by this much faster (min_adv + range)
local OUTSIDE_EDGE    = 0.30   -- how much closer to the edge a full speed-run may run (raises EDGE_SOFT)
local DEFEND_OFFSET= 0.30
local EDGE_SOFT    = 0.5       -- start easing the offset once the car is this far toward an edge
local EDGE_HARD    = 0.9       -- fully suppressed by here (keeps cars off kerbs -> no trip/rollover)
local CAUTION_ATTACK = -0.6
local CAUTION_DEFEND = -0.25
-- aggression = the car's own slider value (car.aiAggression) plus a small delta when fighting,
-- so the Quick Race aggression slider stays meaningful instead of being overwritten.
local ATTACK_AGGR_ADD = 0.25
local DEFEND_AGGR_ADD = 0.12
local AGGR_CRUISE  = 0.55       -- fallback baseline only if the car's aggression can't be read
local OFFSET_SLEW  = 0.8        -- units/sec offset may move (lower = smoother, less skittish)
local DEADZONE     = 0.12       -- ignore tiny offsets (stay on the line)
local SIDE_HOLD    = 1.2        -- s to hold a chosen side before allowing a flip (anti-dart)
local OFFLINE_MAX  = 0.75      -- don't defend against a car this far off the racing line
local SPEED_MIN    = 30.0
local CROWD_GAP    = 0.006     -- cars within this spline gap count as "in the pack"
local SAMPLE_D     = 0.004     -- spline fraction between racing-line samples (~20m on a 5km track)
local CORNER_TURN  = 0.01      -- min (1 - dot) between tangents to count as "a corner ahead" (~8 deg)
local CLASS_YIELD_FRAC   = 0.08 -- a faster CLASS closing at least this fraction of my speed faster gets let through
local CLASS_YIELD_MIN    = 8.0  -- ...but never less than this many km/h (15 km/h flat was a huge margin for a kart at 70)
-- PACE-aware yield: the same thing by MEASURED pace, not class label. A mixed grid of "formula" mods spans
-- F3.5s to F1s -- all one class key, so the class rule never fired -- and the data shows it: the slowest
-- mod on today's grid (a Formula Renault 3.5 among F1s) averaged 1.9 laps before being collected. A car
-- whose best lap is this much slower than the one closing on it is being LAPPED in all but name: let it by.
local PACE_YIELD_RATIO   = 1.04
-- YELLOW FLAG: a stopped car on the road ahead gets everyone arriving a hard speed cap that tightens as they
-- approach -- double-waved yellows. Class-agnostic absolute caps: no racing car should pass a stationary
-- car faster than this. (The go-around handles the LATERAL part; this is the "slow down".) Before this, a
-- car sat sideways on the line after a spin was hit twice by cars arriving at full speed, and a just-
-- rescued car was T-boned at 150 km/h.
local YELLOW_NEAR    = 40    -- metres from the obstacle at which the cap is at its tightest...
local YELLOW_CAP     = 60    -- ...this (km/h). 80 let cars arrive at a blocked road at 80-95 and hit it; 45 had
                             -- the whole field crawling through a zone with one stopped car and stacking up
local YELLOW_FAR     = 250   -- the zone starts this far out...
local YELLOW_CAP_FAR = 200   -- ...at this cap (km/h), easing linearly to YELLOW_CAP
local FREEPASS_CAUT  = 0.15  -- caution taken OFF a car lapping a yielding backmarker
local YELLOW_LAT     = 1.3   -- a stopped car this far from the centre line still counts (edge/kerb); deep in the gravel doesn't

-- TRACK-LENGTH SCALING: every gap above is a spline FRACTION, and the tuning was done on ~4.5 km circuits.
-- A fraction is a different distance on every track (0.008 is 36 m at Zandvoort, 160 m at the
-- Nordschleife, 8 m on a kart track), so racecraft that felt right at one length was blind or twitchy at
-- another. The gaps are re-derived from METRES each session -- same names, identical values at 4.5 km.
local REF_LEN  = 4500
local trackLen = REF_LEN
local scaled   = false
local function scaleToTrack(len)
    trackLen = (type(len) == 'number' and len > 200) and len or REF_LEN
    local function m(x) return x / trackLen end
    GROOVE_RANGE  = m(90);   ISOLATED_GAP = m(135);  PACK_LEAD_GAP = m(54);   REAREND_GAP   = m(22.5)
    BLOCK_GAP     = m(27);   YIELD_GAP    = m(45);   YIELD_LIFT_GAP = m(18);  ALONGSIDE_GAP = m(11)
    YIELD_GAP_FAR = m(120)
    CV.GAP = m(25)
    ATTACK_GAP    = m(36);   PASS_GAP     = m(16);   DEFEND_GAP   = m(22.5);  CROWD_GAP     = m(27)
    SAMPLE_D      = m(18);   GRID_FADE_END = m(225); GRID_CAPTURE = m(90)
end

-- per-class racecraft tactics: gap = striking range, offset = how far off-line, corner = how hard
-- it commits to an inside dive (vs a straight slipstream pass), defend = defensive firmness.
-- follow = how close it tucks in behind (high-downforce cars keep MORE distance -> dirty air
-- costs them front grip, so tucking right up makes them twitchy/crash-prone).
local TACTICS = {
    formula   = { gap = 1.3,  offset = 0.7, corner = 0.5, defend = 1.0, follow = 0.25 }, -- slipstream from far, precise, keeps well back (dirty air + fragile)
    formula_jr= { gap = 1.25, offset = 0.9, corner = 0.9, defend = 1.0, follow = 0.85 }, -- low-downforce: slipstream packs, races close (no dirty air)
    prototype = { gap = 1.3,  offset = 0.8, corner = 0.6, defend = 1.0, follow = 0.35 },
    hypercar  = { gap = 1.2,  offset = 0.8, corner = 0.7, defend = 1.0, follow = 0.4 },
    gt        = { gap = 1.0,  offset = 1.0, corner = 1.1, defend = 1.1, follow = 0.9 },  -- out-brakes, close racing
    touring   = { gap = 0.85, offset = 1.1, corner = 1.2, defend = 1.15, follow = 1.05 }, -- dive-bomb, elbows out (moderated so it isn't chaotic)
    road      = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 0.9 },
    vintage   = { gap = 1.1,  offset = 0.9, corner = 0.8, defend = 0.9, follow = 0.8 },  -- momentum, wider lines
    drift     = { gap = 1.0,  offset = 1.0, corner = 1.0, defend = 1.0, follow = 1.0 },
    kart      = { gap = 1.0,  offset = 0.9, corner = 1.2, defend = 1.15, follow = 1.3 }, -- bumper-to-bumper, out-brakes, big slipstream
    rally     = { gap = 1.0,  offset = 1.0, corner = 1.05, defend = 1.0, follow = 0.9 }, -- AWD, races like a grippy road car on tarmac
    nascar    = { gap = 1.2,  offset = 1.2, corner = 0.8, defend = 1.1, follow = 1.4 }, -- pack/draft: run right up in the tow, use the whole width (high/low lines), block the draft
}
local curOffset = {}
local latNow = {}           -- every car's lateral track position this frame (one projection per car, not per pair; filled in beginFrame)
local gridLat = {}          -- each car's captured starting-lane lateral, for the grid funnel
local holdSign, holdUntil = {}, {}
local pounceT = {}
local commitState, commitUntil = {}, {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
local function sgn(x) if x > 0.1 then return 1 elseif x < -0.1 then return -1 else return 0 end end
local function hash01(n)
    local x = (n * 2654435761) % 2147483647
    x = (x * 1103515245 + 12345) % 2147483647
    return x / 2147483647
end
local function latOf(pos)
    local x = 0
    pcall(function() local tc = ac.worldCoordinateToTrack(pos); if tc then x = tc.x end end)
    return x
end

-- corner ahead: returns (isCorner, insideSign) using three racing-line samples + a lateral probe
-- Detect an oval/speedway: sample the racing line around the whole lap and measure how one-directional
-- the turning is. An oval turns the same way the entire lap (|sum of turns| ~ total turning); a road
-- course balances left and right (sum near zero). Computed once per session.
local function detectOval()
    local oval = false
    pcall(function()
        local N = 96
        local pts = {}
        for k = 0, N - 1 do
            local p = ac.trackProgressToWorldCoordinate(k / N, false)
            if not p then return end
            pts[k] = p
        end
        local signed, total = 0, 0
        for k = 0, N - 1 do
            local a, b, c = pts[k], pts[(k + 1) % N], pts[(k + 2) % N]
            local v1x, v1z = b.x - a.x, b.z - a.z
            local v2x, v2z = c.x - b.x, c.z - b.z
            local m1 = math.sqrt(v1x * v1x + v1z * v1z)
            local m2 = math.sqrt(v2x * v2x + v2z * v2z)
            if m1 > 1e-3 and m2 > 1e-3 then
                local turn = (v1x * v2z - v1z * v2x) / (m1 * m2)   -- signed turn between segments
                signed = signed + turn
                total = total + math.abs(turn)
            end
        end
        if total > 1e-3 then oval = (math.abs(signed) / total) > 0.6 end   -- mostly one-way = oval
    end)
    return oval
end

local function cornerAhead(prog)
    local isCorner, insideSign = false, 0
    pcall(function()
        local p0 = ac.trackProgressToWorldCoordinate(prog % 1, false)
        local p1 = ac.trackProgressToWorldCoordinate((prog + SAMPLE_D) % 1, false)
        local p2 = ac.trackProgressToWorldCoordinate((prog + 2 * SAMPLE_D) % 1, false)
        if not (p0 and p1 and p2) then return end
        local v1 = (p1 - p0):normalize()
        local v2 = (p2 - p1):normalize()
        if (1 - v1:dot(v2)) < CORNER_TURN then return end             -- basically straight
        isCorner = true
        local centripetal = (v2 - v1)                                 -- points toward the inside (v1,v2 unchanged by dot)
        if centripetal:length() < 1e-4 then return end
        local latHere  = latOf(p1)
        local latInside = latOf(p1 + centripetal:normalize() * 3.0)   -- 3 m toward the inside
        insideSign = (latInside >= latHere) and 1 or -1               -- track frame: +1 = right
    end)
    return isCorner, insideSign
end

function R.evaluate(i, dt)
    if not R.ENABLED then return 0 end
    local caut, state = 0, 0
    pcall(function()
        local me = ac.getCar(i)
        if not me or not me.isAIControlled then return end
        local spd = me.speedKmh or 0
        if spd < SPEED_MIN or me.isInPitlane then return end
        local mySpline = me.splinePosition
        if mySpline == nil then return end

        local classKey = Classes.keyOf(i)
        local t = TACTICS[classKey] or TACTICS.road
        local crash = Troublespots.crashiness()    -- 0..1: how crash-prone this track has proven

        local myLap = Recovery.lapsOf(i)           -- Verve's own count: AC's drops a lap after a teleport
        -- lap-0 progress with the grid's wrap undone: a grid before the line reads 0.98-0.99, which made every
        -- "start of the opening lap" rule below treat the run to turn one as the END of the lap (2026-09-16)
        local olS = mySpline
        if myLap == 0 and mySpline > 0.5 then olS = mySpline - 1 end

        -- nearest ahead / behind (gap, speed, index)
        local gapA, aheadSpd, aheadIdx = 1e9, 0, -1
        local gapB, behindSpd, behindIdx = 1e9, 0, -1
        local nearGap, nearIdx, nearAhead = 1e9, -1, true   -- closest car by on-track gap (either side)
        local lapperIdx, lapperGap = -1, 1e9                -- nearest car on a higher lap coming through
        local crowd = 0
        local myPace = me.bestLapTimeMs                     -- (0 until the car has set a lap)
        if type(myPace) ~= 'number' or myPace <= 0 then myPace = nil end
        local yellowD, yellowSpd = 1e9, 0                   -- nearest STOPPED car on the road ahead (yellow flag)
        local lappedAhead = false                           -- the car ahead is a lap down and letting me through
        local yellowRange = YELLOW_FAR / trackLen
        local sideBy = false                                -- lap 0: a car alongside with its nose just ahead of mine
        local sideSign = 0                                  -- laps 0-1: a car alongside -> which way is AWAY from it (+/-1)
        local sim = ac.getSim()
        for j = 0, sim.carsCount - 1 do
            if j ~= i then
                local oc = ac.getCar(j)
                if oc and oc.splinePosition then
                    local ocSpd = oc.speedKmh or 0
                    local d = oc.splinePosition - mySpline; if d < 0 then d = d + 1 end
                    local b = mySpline - oc.splinePosition; if b < 0 then b = b + 1 end
                    local ocLat = latNow[j] or 0
                    if (R.OL_SIDEYIELD or R.OL_SIDESPACE) and myLap <= 1 and ocSpd > 30 then
                        local sd = d < 0.5 and d or d - 1                   -- signed spline gap: + their nose ahead of mine
                        if math.abs(sd) * trackLen < CV.SIDE_M then
                            local dl = math.abs(ocLat - (latNow[i] or 0))
                            if dl > CV.SIDE_LAT and dl < CV.SIDE_LAT_MAX then
                                if sd > 0 then sideBy = true end
                                sideSign = ((latNow[i] or 0) >= ocLat) and 1 or -1
                            end
                        end
                    end
                    -- a stopped (or crawling) car ON the road ahead is a yellow flag, not a rival
                    local hazard = ocSpd < BLOCK_SPEED
                    if not hazard and R.OL_SPINYELLOW and myLap == 0 and d > 0 and d < yellowRange and math.abs(ocLat) < YELLOW_LAT then
                        -- lap 0: a car ahead going sideways, or far slower than me, is about to be hit by the next arrivals
                        if ocSpd < spd * CV.SPIN_FRAC and spd > 60 then hazard = true
                        else
                            local v, lk = oc.velocity, oc.look
                            if v and lk and ocSpd > 30 then
                                local vl = math.sqrt(v.x * v.x + v.z * v.z)
                                if vl > 1 and (v.x * lk.x + v.z * lk.z) / vl < CV.SPIN_DOT then hazard = true end
                            end
                        end
                    end
                    if d > 0 and d < yellowRange and hazard and math.abs(ocLat) < YELLOW_LAT and d < yellowD then
                        yellowD = d; yellowSpd = ocSpd
                    end
                    -- stopped or off-track cars aren't rivals to attack/defend against (the blockage scan and
                    -- the yellow handle them). A repaired car once "attacked" a wreck parked 40 m out in the
                    -- gravel and drove itself off the road doing it.
                    if ocSpd >= BLOCK_SPEED and math.abs(ocLat) <= OFFLINE_MAX then
                        if d > 0 and d < gapA then
                            gapA = d; aheadSpd = ocSpd; aheadIdx = j
                            local L2 = R.last[j]
                            lappedAhead = Recovery.lapsOf(j) < myLap and L2 ~= nil and L2.yield == true
                        end
                        if b > 0 and b < gapB then gapB = b; behindSpd = ocSpd; behindIdx = j end
                        if d < CROWD_GAP or b < CROWD_GAP then crowd = crowd + 1 end
                        local nd = d < b and d or b                       -- true nearest on track
                        if nd < nearGap then nearGap = nd; nearIdx = j; nearAhead = (d <= b) end
                        -- a car on a higher lap (blue flag) -- or, in a MIXED field, a faster CLASS closing on me:
                        -- multi-class racing lets the prototypes through rather than fighting them corner by corner.
                        -- (Same class = a rival, however fast: that's racing.)
                        if b < YIELD_GAP_FAR and b < lapperGap then
                            local faster = ocSpd > spd + math.max(CLASS_YIELD_MIN, spd * CLASS_YIELD_FRAC)
                            local slowerPace = false
                            if faster and myPace then
                                local op = oc.bestLapTimeMs
                                slowerPace = type(op) == 'number' and op > 0 and myPace > op * PACE_YIELD_RATIO
                            end
                            local otherClass = Classes.keyOf(j) ~= classKey
                            if Recovery.lapsOf(j) > myLap or (faster and otherClass) then
                                lapperIdx = j; lapperGap = b                                   -- blue flag from YIELD_GAP_FAR
                            elseif b < YIELD_GAP and faster and slowerPace then
                                lapperIdx = j; lapperGap = b                                   -- same class, clearly quicker: short range
                            end
                        end
                    end
                end
            end
        end
        -- YELLOW FLAG speed cap (cleared -- 1e9 -- every frame it doesn't apply), combined with recovery's
        -- own cap for a car that's just been set back on the track (the two are the only writers of it)
        local cap = 1e9
        if yellowD < 1e9 then
            local dm = yellowD * trackLen
            cap = YELLOW_CAP + (YELLOW_CAP_FAR - YELLOW_CAP) * clamp((dm - YELLOW_NEAR) / (YELLOW_FAR - YELLOW_NEAR), 0, 1)
            -- a CRAWLING obstacle (a car just set back on the road, getting going) is passed at moderate speed,
            -- not matched: two repositioned cars capping each other crawled at 50 km/h for 30 s (Silverstone)
            if yellowSpd > 15 then cap = math.max(cap, yellowSpd + 40) end
        end
        if R.CONVOY_ON and myLap == 0 and olS < CV.END and aheadIdx >= 0 and gapA < CV.GAP and crowd >= 1 then
            local aCar = ac.getCar(aheadIdx)
            if aCar and math.abs(latOf(aCar.position) - latOf(me.position)) < CV.LAT then
                cap = math.min(cap, math.max(aheadSpd + CV.MARGIN, 40))
            end
        end
        pcall(function() cap = math.min(cap, Recovery.rampCap(i)) end)
        pcall(function() physics.setAITopSpeed(i, cap) end)
        -- CONVOY v2: throttle only (see the constants). Left alone for a car recovery is driving (its own throttle ramp).
        local thr = 1.0
        if R.CONVOY2_ON and myLap == 0 and crowd >= 1 and not (Recovery.stateOf(i) or {}).rec then
            if cv2.clock and cv2.back[i] then
                local tl0 = os.clock() - cv2.clock
                if tl0 < (cv2.react[i] or 0) then thr = math.min(thr, CV.REACT_THR)   -- reaction time: not on the gas yet
                elseif tl0 < (cv2.react[i] or 0) + CV.ROW_T * (cv2.back[i] / CV.ROW_M) then thr = math.min(thr, CV.THR) end   -- staggered release
            end
            if olS < CV.END and aheadIdx >= 0 and gapA * trackLen < CV.GAP_M and spd > aheadSpd + CV.CLOSING
               and not (R.OL_STAR_CONVOY and Strategy.tierOf(i) >= 2) then
                local aCar = ac.getCar(aheadIdx)
                if aCar and math.abs(latOf(aCar.position) - latOf(me.position)) < CV.LAT then
                    local gm = gapA * trackLen
                    thr = math.min(thr, clamp(CV.THR_MIN + (1 - CV.THR_MIN) * (gm - CV.NEAR_M) / (CV.GAP_M - CV.NEAR_M), CV.THR_MIN, 1))
                end
            end
            -- SIDE YIELD: two-abreast into a corner on lap 0 is how same-row pairs touch (Barcelona F1 2026-09-16:
            -- six of nine lap-0 contacts). The car behind by a nose eases and tucks in.
            if R.OL_SIDEYIELD and sideBy and cornerAhead(mySpline) then thr = math.min(thr, CV.SIDE_THR) end
        end
        if thr < 1.0 then cv2.thr[i] = true; pcall(physics.setAIThrottleLimit, i, thr)
        elseif cv2.thr[i] then cv2.thr[i] = nil; pcall(physics.setAIThrottleLimit, i, 1.0) end
        -- BRAKE-ZONE GUARD (lap 0): the car ahead on my line is on the brakes and I'm inside CV.BG_M -> raise my brake
        -- hint (earlier brake point) in proportion to the gap. R.BG_ALL: whole-race multiplier, direction test only.
        if (R.OL_BRAKEGUARD or R.BG_ALL > 0) and physics.setAIBrakeHint then
            if cv2.base[i] == nil then
                cv2.base[i] = 1.0
                pcall(function() cv2.base[i] = ac.INIConfig.carData(i, 'ai.ini'):get('PEDALS', 'BRAKE_HINT', 1.0) end)
            end
            local mul = R.BG_ALL > 0 and R.BG_ALL or 1.0
            if R.OL_BRAKEGUARD and myLap <= 1 and aheadIdx >= 0 and not (Recovery.stateOf(i) or {}).rec then
                local gm = gapA * trackLen
                if gm < CV.BG_M then
                    local aCar = ac.getCar(aheadIdx)
                    if aCar and (aCar.brake or 0) > CV.BG_BRAKE and math.abs(latOf(aCar.position) - latOf(me.position)) < CV.LAT then
                        -- LOWER hint = earlier braking (x1.5 field-wide: 18/18 lap-1 contact, 101 repairs, 2026-09-16).
                        -- The cut scales with how fast I'm closing on a braking car and how close it already is.
                        local closing = clamp((spd - aheadSpd) / CV.BG_CLOSE, 0, 1)
                        mul = mul * (1 - CV.BG_HINT * closing * clamp(1 - gm / CV.BG_M, 0, 1))
                    end
                end
            end
            if mul ~= 1.0 then cv2.bg[i] = true; pcall(physics.setAIBrakeHint, i, cv2.base[i] * mul)
            elseif cv2.bg[i] then cv2.bg[i] = nil; pcall(physics.setAIBrakeHint, i, cv2.base[i]) end
        end

        local attackGap = ATTACK_GAP * t.gap
        local defendGap = DEFEND_GAP
        -- baseline aggression: a driver profile sets it directly; otherwise the car's own (slider)
        -- value plus a per-driver spread (scaled by Variability) so the field isn't uniform.
        local prof = Drivers.statsOf(i)
        local baseA
        if prof then
            baseA = clamp(prof.aggr, 0.15, 1.0)
        else
            baseA = me.aiAggression
            if not baseA or baseA < 0 then baseA = AGGR_CRUISE end
            baseA = clamp(baseA, 0.2, 1.0)
            baseA = clamp(baseA + (hash01(i * 11 + 5) * 2 - 1) * AGGR_SPREAD * R.VARIABILITY, 0.15, 1.0)
        end
        local myLat = latOf(me.position)          -- current lateral on track (-1 left .. +1 right)
        local target, aggr, wide = 0, baseA, 0    -- wide = 0..1 extra track width earned by an exit-speed run
        -- body damage SINCE the car's last repair (km/h). Not raw `me.damage`: that's a never-decreasing
        -- record of the worst hit, so a repaired car would read as wrecked for the rest of the race.
        local myDmg = 0
        pcall(function() myDmg = Recovery.damageOf(i) end)

        -- BLOCKAGE detect: scan a short window ahead for the SLOWEST car -- a stalled/crashed/crawling car
        -- is an obstacle, not a rival. Crucially we key off the genuinely-slow car (usually the crash),
        -- not just whoever's nearest (which, once a queue forms, is another queued car), and we only need
        -- to be a little faster than it -- so cars ALREADY crawling in the queue behind it still peel off
        -- and filter past, instead of everyone sitting nose-to-tail. Route to the OPEN side (away from
        -- where the obstacle sits), so a car stopped on the right sends the field around it on the left.
        local blockSide = 0
        do
            local slowIdx, slowSpd = -1, 1e9
            local blockLook = math.max(BLOCK_GAP, (spd / 3.6) * BLOCK_TIME / trackLen)   -- speed-scaled lookahead
            for j = 0, sim.carsCount - 1 do
                if j ~= i then
                    local oc = ac.getCar(j)
                    if oc and oc.splinePosition then
                        local d = oc.splinePosition - mySpline; if d < 0 then d = d + 1 end
                        if d > 0 and d < blockLook and (oc.speedKmh or 1e9) < slowSpd then
                            slowSpd = oc.speedKmh or 1e9; slowIdx = j
                        end
                    end
                end
            end
            if slowIdx >= 0 and spd > slowSpd + BLOCK_MARGIN
               and (slowSpd < BLOCK_SPEED or (slowSpd < BLOCK_LIMP and (spd - slowSpd) > BLOCK_DELTA)) then
                local aLat = latOf(ac.getCar(slowIdx).position)
                -- ONLY sweep around an obstacle that's actually on the racing surface / in the path. A car
                -- already parked well off to the side needs no berth -- just pass it on the line, don't
                -- swerve all the way to the far side of the road for it.
                if math.abs(aLat) < BLOCK_EDGE then
                    if math.abs(aLat) > 0.1 then blockSide = -sgn(aLat)             -- obstacle off to a side -> go the other way (the open track)
                    elseif sgn(myLat) ~= 0 then blockSide = -sgn(myLat)             -- obstacle mid-track -> head toward the roomier half
                    else blockSide = (hash01(i * 5 + 2) < 0.5) and -1 or 1 end      -- dead-centre -> pick a side and commit
                end
            end
        end
        local yielding = false   -- set when we're being lapped (blue flag) -- suppresses obstacle-swerving
        local rsPass = false     -- set when the road-space rule picked a side this frame (R.ROADSPACE)

        -- raw instantaneous reads: is there a fight on right now?
        local rawAttack = (gapA < attackGap and spd >= aheadSpd - FASTER_MARGIN)
        local behindLat = behindIdx >= 0 and latOf(ac.getCar(behindIdx).position) or 0
        local rawDefend = (gapB < defendGap and behindSpd > spd - FASTER_MARGIN
                           and math.abs(behindLat) < OFFLINE_MAX)   -- ignore a car miles off-line

        -- resolve the COMMITTED state (see COMMIT_* notes): a genuine read (re)commits and refreshes
        -- the hold; otherwise coast the last decision until a wider release threshold clears it.
        local nowd = os.clock()
        if rawAttack then
            commitState[i], commitUntil[i], state = 1, nowd + COMMIT_HOLD, 1
        elseif rawDefend then
            commitState[i], commitUntil[i], state = 2, nowd + COMMIT_HOLD, 2
        elseif commitState[i] and (commitUntil[i] or 0) > nowd then
            if commitState[i] == 1 and gapA < attackGap * COMMIT_RELEASE then state = 1
            elseif commitState[i] == 2 and gapB < defendGap * COMMIT_RELEASE then state = 2
            else state = 0; commitState[i] = nil end
        else
            state = 0; commitState[i] = nil
        end

        if state == 1 then
            aggr = math.min(1, baseA + ATTACK_AGGR_ADD)
            caut = CAUTION_ATTACK * clamp(1 - gapA / attackGap, 0, 1) * (t.follow or 1.0)   -- aero cars keep more distance
            -- Start MOVING for the pass earlier when there's a genuine speed run on the car ahead -- not
            -- only when almost touching. Fixes a fast car sitting in the slipstream too long before it
            -- commits to the open space beside a slower car (most visible off the start, but present
            -- everywhere). Still needs a real closing-speed advantage, so it isn't a constant weave.
            local runAdv = spd - aheadSpd
            local passActive = (gapA < PASS_GAP) or (gapA < attackGap and runAdv > OUTSIDE_MIN_ADV * 0.6)
            local myTc = ac.worldCoordinateToTrack(me.position)
            local progZ = myTc and myTc.z or mySpline
            local dLat = aheadIdx >= 0 and latOf(ac.getCar(aheadIdx).position) or 0
            local off = ATTACK_OFFSET * t.offset
            local isCorner, inside = false, 0
            if passActive then
                isCorner, inside = cornerAhead(progZ)
                -- a genuine exit-speed run earns extra width -- and how readily a car takes it scales
                -- with AGGRESSION (the driver profile's aggr, or the Quick Race slider, via baseA): an
                -- aggressive driver pounces on a smaller advantage AND commits harder to it; a cautious
                -- one needs a bigger gap and uses less width. Verstappen takes every opening; Prost picks his.
                local minAdv = OUTSIDE_MIN_ADV * (1.4 - baseA)
                wide = clamp(clamp((spd - aheadSpd - minAdv) / OUTSIDE_RANGE, 0, 1) * (0.5 + baseA), 0, 1.5)
                if isCorner and inside ~= 0 then
                    if dLat * inside < 0.3 then          -- inside is OPEN -> dive in, committing harder with a real run
                        target = inside * off * (0.5 + 0.5 * t.corner) * (1 + 0.7 * wide)
                    else                                 -- inside covered -> go AROUND THE OUTSIDE, wider with a run
                        target = -inside * off * (0.6 + 1.4 * wide)
                    end
                elseif math.abs(dLat) > 0.15 then        -- straight/exit: pass where the defender isn't, wider with a run
                    target = -sgn(dLat) * off * (1 + 1.5 * wide)
                elseif inside ~= 0 then                  -- straight: pre-position for the next corner's inside
                    target = inside * off * 0.5
                end
            end
            -- STRATEGY: a planned manoeuvre (set-up, late-brake lunge, switchback, slingshot) overrides the
            -- reactive pass above. Skill- and difficulty-gated inside; nil = no opinion.
            local ov = Strategy.evaluate(i, { dt = dt, gapA = gapA, spd = spd, aheadSpd = aheadSpd, aheadIdx = aheadIdx,
                prog = progZ, dLat = dLat, myLat = myLat, wide = wide, baseA = baseA, prof = prof, classKey = classKey,
                off = off, passGap = PASS_GAP, attackGap = attackGap, isOval = R.isOval, lap = myLap, crowd = crowd })
            if ov then
                if ov.target ~= nil then target = ov.target end
                caut = caut + (ov.caut or 0)
                aggr = math.min(1, aggr + (ov.aggr or 0))
                if ov.hold and sgn(target) ~= 0 then holdSign[i] = sgn(target); holdUntil[i] = os.clock() + ov.hold end
            end
            -- ROAD SPACE (see R.ROADSPACE): no planned manoeuvre running, a genuine run on the car ahead -> where is the
            -- open road? Measure the free lateral room on each side of the car ahead, then aim just clear of it.
            -- Not while the opening-lap easing is in force (lap 0, and lap 1 until OPENLAP_TAIL): in the pack it started
            -- pile-ups (Spa sprint 2026-09-16: 13/18 in contact x2 vs 7-11 baseline, both chains begun by a car aiming
            -- for a gap on lap 1). Once the field has strung out it is neutral-to-better on contact.
            if R.ROADSPACE and ov == nil and passActive and aheadIdx >= 0
               and (myLap >= 2 or (myLap == 1 and mySpline >= OPENLAP_TAIL)
                    or (R.RS_OL_METER > 0 and Strategy.tierOf(i) >= 2 and Strategy.meterOK(R.RS_OL_METER)))
               and runAdv > OUTSIDE_MIN_ADV * (1.4 - baseA) * CV.RS_ADV then
                local half = 6.0                                          -- half track width here (m): track units per metre
                pcall(function() local sd = ac.getTrackAISplineSides(mySpline); if sd then half = math.max(3.0, (sd.x + sd.y) * 0.5) end end)
                local carW = CV.RS_CARW_M
                pcall(function() local ab = me.aabbSize; if ab and ab.x > 0.8 and ab.x < 4.0 then carW = ab.x end end)
                local need = (carW + CV.RS_MARGIN_M) / half               -- centre-to-centre lateral gap that clears a car
                local room = { [-1] = dLat + CV.RS_EDGE, [1] = CV.RS_EDGE - dLat }   -- how far from the car ahead I may sit, per side
                local back, fwd = CV.RS_BACK_M / trackLen, gapA + CV.RS_FWD_M / trackLen
                for j = 0, sim.carsCount - 1 do
                    if j ~= i and j ~= aheadIdx then
                        local oc = ac.getCar(j)
                        if oc and oc.splinePosition and (oc.speedKmh or 0) > BLOCK_SPEED then
                            local sd = oc.splinePosition - mySpline; if sd < -0.5 then sd = sd + 1 elseif sd > 0.5 then sd = sd - 1 end
                            if sd > -back and sd < fwd then                       -- from just behind me to just past the car ahead
                                local dl = (latNow[j] or 0) - dLat
                                local s = (dl >= 0) and 1 or -1
                                local r = math.abs(dl) - need                     -- I must clear that car too
                                if r < room[s] then room[s] = r end
                            end
                        end
                    end
                end
                local side = 0
                if isCorner and inside ~= 0 and room[inside] >= need then side = inside              -- the inside fits: take it
                elseif room[1] >= need or room[-1] >= need then side = (room[1] >= room[-1]) and 1 or -1   -- else the roomier side
                end
                if side ~= 0 then
                    target = clamp(dLat + side * need, -CV.RS_EDGE, CV.RS_EDGE)
                    rsPass = true
                end
            end
        elseif state == 2 then
            aggr = math.min(1, baseA + DEFEND_AGGR_ADD)
            caut = CAUTION_DEFEND
            if gapA >= PACK_LEAD_GAP then
                -- clear road ahead: don't defend a slow line -- just drive away on the racing line.
                target = 0
            else
                local myTc = ac.worldCoordinateToTrack(me.position)
                local progZ = myTc and myTc.z or mySpline
                local isCorner, inside = cornerAhead(progZ)
                if isCorner and inside ~= 0 then
                    target = inside * (DEFEND_OFFSET * t.defend)   -- hold the inside line (stable, corner-based)
                end
                -- on straights, keep the racing line -- don't weave to mirror the attacker
            end
        end

        if state ~= 1 then Strategy.clear(i) end
        local eff = R.INTENSITY

        -- pounce: after following a car, stay eager to fill the space for a moment (fixes the
        -- "slow to pounce when the gap opens" lag). Refreshes while attacking, decays after.
        pounceT[i] = math.max((pounceT[i] or 0) - dt, 0)
        if state == 1 then pounceT[i] = POUNCE_HOLD
        elseif state == 0 and pounceT[i] > 0 and (t.follow or 1) >= 0.7 then
            -- only pounce on a straight/fast bit, never while braking into a corner (that just
            -- bunches the pack up in the braking zone). Close-quarters classes only.
            local st = me.steer
            if type(st) ~= "number" or math.abs(st) < 0.2 then
                caut = caut + POUNCE_CAUT * (pounceT[i] / POUNCE_HOLD)
            end
        end

        -- pack damping: in a crowd (race start, traffic) damp the LINE-CHANGING only, so the field
        -- doesn't all dart around at once. NOT applied to caution/closing -- cars must stay willing
        -- to tuck up and pass in traffic, or the pack over-gaps and concertinas to a crawl.
        local crowdDamp = clamp(1 - math.max(0, crowd - 1) * 0.25, 0.35, 1)   -- eased: was over-damping pull-outs in packs
        -- a car with a genuine speed run (wide > 0) resists the crowd damping, so a fast car CAN still
        -- pull out into open space in a pack instead of being pinned on the line behind a slower car.
        local passResist = clamp(wide, 0, 1)
        crowdDamp = crowdDamp + (1 - crowdDamp) * passResist
        caut = caut * eff

        -- RACE AWARENESS (added after the intensity scale, so safety terms hold at any intensity):
        -- opening-lap caution -- calmer + more spacing off the line, fading across the first lap.
        local openingLap = 0
        if crowd >= 1 then
            if myLap == 0 then openingLap = clamp(1 - math.max(0, olS) * (1 - OPENLAP_FLOOR), OPENLAP_FLOOR, 1)   -- 1.0 at the lights (and on the grid before the line) -> 0.3 at the line
            elseif myLap == 1 then openingLap = OPENLAP_FLOOR * clamp(1 - mySpline / OPENLAP_TAIL, 0, 1) end   -- tail into lap 1
        end
        if openingLap > 0 then
            -- caution by the gap ahead: extra caution only matters with a car a few lengths ahead; the leaders keep
            -- braking normally, so they don't trigger the concertina behind them
            local prox = 1
            if R.OL_CAUT_PROX then prox = clamp((CV.PROX_FAR - gapA * trackLen) / (CV.PROX_FAR - CV.PROX_NEAR), 0, 1) end
            caut = caut + OPENLAP_CAUT * openingLap * (1 + crash) * prox   -- crashy tracks get extra start caution (kills the opening-lap pile-ups)
            if R.OL_ROWCAUT and myLap == 0 and cv2.back[i] then    -- row ten brakes on the lights of the car ahead: earlier the further back
                -- (scaling this by aggression was tried 2026-09-16: the star went off the road at 127 km/h; it protects him)
                caut = caut + CV.ROWCAUT * clamp(cv2.back[i] / CV.ROWCAUT_M, 0, 1) * openingLap * prox
            end
            local olAggr = OPENLAP_AGGR
            if R.OL_STAR_AGGR > 0 and Strategy.tierOf(i) >= 2 then olAggr = OPENLAP_AGGR * R.OL_STAR_AGGR end
            aggr = aggr * (1 - olAggr * openingLap)
            if R.OL_AGGR_FORMULA > 0 and (classKey == 'formula' or classKey == 'formula_jr') then
                aggr = aggr * (1 - R.OL_AGGR_FORMULA * openingLap)   -- open-wheelers: no bodywork to lean on
            end
            if state == 1 and caut < 0 then caut = caut * (1 - OPENLAP_ATTACK * openingLap) end   -- still attacking, just not diving in
        end
        -- bring-it-home -- clear track both ways: nothing to race, so ease off a touch.
        local catchable = R.ISO_PACE and aheadIdx >= 0 and gapA * trackLen < CV.ISO_REACH_M and Strategy.tierOf(i) >= 2
        if gapA > ISOLATED_GAP and gapB > ISOLATED_GAP and not catchable then
            aggr = aggr * (1 - ISOLATED_AGGR)
            caut = caut + ISOLATED_CAUT
        -- pack leader -- clear road ahead but a pack right behind: a small pace stretch so the leader
        -- noses away and strings the field out, instead of the front artificially anchoring the bunch.
        elseif gapA > PACK_LEAD_GAP and crowd >= 2 then
            caut = caut - PACK_STRETCH * (1 - crash)   -- don't stretch away (more catching) on a crashy track
        end
        -- trouble-spot learning: a bit more caution approaching a corner this class keeps crashing at.
        local tsCaut = Troublespots.cautionAt(mySpline, classKey)
        local lone = (R.LONE_FRAC > 0 and nearGap * trackLen > CV.LONE_M) and R.LONE_FRAC or 1.0   -- nobody near: a fraction
        caut = caut + tsCaut * lone
        -- adaptive crash damping: on a track that keeps wrecking cars, calm the whole field (more caution,
        -- less aggression) so the crash RATE falls, not just the after-the-fact repairs.
        if crash > 0 then
            caut = caut + R.CRASH_CAUT * crash * lone
            aggr = aggr * (1 - R.CRASH_AGGR * crash)
        end
        -- anti rear-end: closing fast, right behind, and still ON the same line (not pulling out to
        -- pass) -> ease the approach. Risk lowers how much a driver backs off, but never to nothing.
        if gapA < REAREND_GAP and aheadIdx >= 0 and blockSide == 0 then    -- (going around a blockage? don't also brake to a crawl behind it)
            local closing = spd - aheadSpd
            if closing > REAREND_CLOSE and math.abs(myLat - latOf(ac.getCar(aheadIdx).position)) < REAREND_LAT then
                local urgency = clamp((closing - REAREND_CLOSE) / REAREND_RANGE, 0, 1) * clamp(1 - gapA / REAREND_GAP, 0, 1)
                local riskF = prof and clamp(1.0 - 0.6 * prof.risk, 0.4, 1.0) or 0.8
                if rsPass then urgency = urgency * CV.RS_REAREND end   -- pulling out to pass: don't kill the run first
                caut = caut + REAREND_CAUT * urgency * riskF
            end
        end

        -- high-speed damping: smaller line changes at speed (a big lateral move at 300 km/h is
        -- what unsettles fast cars). Full effect up to ~180 km/h, tapering to half by ~360.
        local speedDamp = clamp(1 - math.max(0, spd - 180) / 400, 0.5, 1)
        local phaseOff  = 1 - OPENLAP_OFFSET * openingLap        -- less line-swapping at the start
        if rsPass then target = clamp(target * speedDamp, -1, 1)   -- a point on the road, not an eagerness: only the speed damping applies
        else target = clamp(target * eff * speedDamp * crowdDamp * phaseOff, -1, 1) end

        -- leave room -- genuinely alongside (overlapping) and NOT the car with the corner: don't
        -- pinch into them and lift a touch. Can only reduce contact; never forces a move.
        if nearIdx >= 0 and nearGap < ALONGSIDE_GAP and nearAhead then
            local nearLat = latOf(ac.getCar(nearIdx).position)
            if math.abs(nearLat - myLat) < ALONGSIDE_LAT then
                local towardSign = (nearLat >= myLat) and 1 or -1
                if target * towardSign > 0 then target = target * 0.2 end   -- stop leaning into them
                caut = caut + LEAVEROOM_CAUT
            end
        end

        -- blue-flag yield -- a car on a higher lap is coming through: concede the line and lift,
        -- rather than racing the leader. Overrides attack/defend; edge-safety below keeps it honest.
        if lapperIdx < 0 then yieldT[i] = 0; letbyDone[i] = nil; letbyFor[i] = nil; letbyT[i] = nil end
        if lapperIdx >= 0 and letbyFor[i] ~= lapperIdx then letbyFor[i] = lapperIdx; letbyDone[i] = nil; letbyT[i] = nil; yieldT[i] = 0 end
        if lapperIdx >= 0 then
            yielding = true
            local lapLat = latOf(ac.getCar(lapperIdx).position)
            local side = (lapLat >= myLat) and -1 or 1                              -- off-line, the side the lapper isn't
            -- IS THAT SIDE CLEAR? A car being lapped is often mid-fight with cars on its own lap; moving aside into
            -- one of them made the start-of-race pile-ups (Zandvoort star test, 2026-09-14). If a same-lap car is
            -- alongside or right behind on that side, hold the line and just lift -- the lapper goes round.
            local sideClear = true
            for j = 0, sim.carsCount - 1 do
                if j ~= i and j ~= lapperIdx then
                    local oc = ac.getCar(j)
                    if oc and oc.splinePosition and (oc.speedKmh or 0) > BLOCK_SPEED then
                        local dd = oc.splinePosition - mySpline; if dd < -0.5 then dd = dd + 1 elseif dd > 0.5 then dd = dd - 1 end
                        local ol = latNow[j] or 0
                        if math.abs(dd) < ALONGSIDE_GAP * 1.6 and ((side > 0 and ol > myLat) or (side < 0 and ol < myLat)) then sideClear = false; break end
                    end
                end
            end
            -- ONLY THE CAR DIRECTLY AHEAD OF THE LAPPER YIELDS. Every car within 45 m used to yield at once, so a
            -- train of backmarkers all lifted together and nobody got past anybody (the "conga line"). If there's
            -- another car between me and the lapper, it's that car's job; I keep racing.
            local nearestToLapper = true
            for j = 0, sim.carsCount - 1 do
                if j ~= i and j ~= lapperIdx then
                    local oc = ac.getCar(j)
                    if oc and oc.splinePosition and (oc.speedKmh or 0) > BLOCK_SPEED then
                        local db = mySpline - oc.splinePosition; if db < 0 then db = db + 1 end   -- oc behind me by db
                        if db > 0 and db < lapperGap then nearestToLapper = false; break end
                    end
                end
            end
            if not nearestToLapper then
                yielding = false
            elseif sideClear then
                target = side * YIELD_OFFSET * speedDamp
                holdSign[i] = side; holdUntil[i] = os.clock() + SIDE_HOLD   -- commit to the move-aside
                yieldT[i] = (yieldT[i] or 0) + dt
            else
                -- boxed in: hold the line, lift a touch, and only for a few seconds -- if the lapper hasn't gone by
                -- in that time it will have to make the move itself (it has attack + free-pass on its side)
                yieldT[i] = (yieldT[i] or 0) + dt
                -- the boxed-in cutoff is for a SAME-class lapper (equal pace: nothing more the yielder can do). A faster
                -- CLASS coming through keeps its blue flag: the rivals boxing this car in are about to be lapped too.
                -- (Spa 2026-09-15: prototypes sat 48-72 s behind GT3s that had yielded for 4 s and raced on.)
                if yieldT[i] > YIELD_MAX_T and Classes.keyOf(lapperIdx) == classKey then yielding = false end
            end
            if yielding then aggr = math.min(aggr, YIELD_AGGR) end
            -- A lapped car should EASE aside and keep rolling, NOT crawl. Cap the total caution so the
            -- other back-off terms (crash-damping, anti-rear-end, trouble-spots) can't stack into a near
            -- stop -- that's what makes traffic pile up and rear-end a car being lapped. Lift a touch more
            -- only as the faster car draws right alongside, to wave it by.
            local lift = (lapperGap < YIELD_LIFT_GAP) and YIELD_CAUT * clamp(1 - lapperGap / YIELD_LIFT_GAP, 0, 1) or 0
            -- the proper lift: yielded long enough, lapper still on the tail, on a straight, not done yet for this lapper
            if yielding and not letbyDone[i] and (yieldT[i] or 0) > LETBY_AFTER_T and lapperGap < YIELD_GAP then
                if letbyT[i] == nil then
                    local isCornerY = cornerAhead(mySpline)
                    if not isCornerY then letbyT[i] = os.clock() end
                end
            end
            if letbyT[i] then
                if os.clock() - letbyT[i] < LETBY_T then lift = lift + LETBY_CAUT
                else letbyDone[i] = true; letbyT[i] = nil end
            end
            if yielding then
                caut = math.min(caut, YIELD_CAUT + tsCaut) + lift   -- (never capped BELOW the corner's own trouble-spot caution)
                state  = 0
            end
        end

        -- DAMAGED CAR: a significantly damaged car stops RACING (no attack/defend, eased aggression,
        -- stays on the line) and, when a healthy car is right behind, pulls OFF the line to let it
        -- through -- a self-imposed blue flag. It does NOT live off-line permanently and its caution is
        -- NOT capped: an earlier build did both, and over ten Zandvoort races 73% of the cars that
        -- crossed the damage threshold went off AGAIN within 24-40 s -- driving every corner 0.58 off
        -- the racing line with less caution than a healthy car. (It also took out the leader and the
        -- player together: P1 picked up 48 km/h of damage, was sent off-line into the banked corner
        -- with the player 30 m behind, and both were collected.) A real driver nurses a damaged car
        -- ON the line and moves over when someone's on their tail.
        -- how fresh is the damage? (a real driver nurses a fresh hit, then gets on with it unless the car is wrecked)
        if myDmg > (dmgSeen[i] or 0) + 3 then dmgSeen[i] = myDmg; dmgLap[i] = myLap end
        local nursing = myDmg > DAMAGE_YIELD and (myDmg > DAMAGE_HEAVY or (myLap - (dmgLap[i] or myLap)) < DAMAGE_NURSE_LAPS)
        if not yielding and nursing then
            state = 0
            target = 0                                                 -- no diving for passes with a bent car
            aggr = math.min(aggr, YIELD_AGGR)
            if behindIdx >= 0 and gapB < YIELD_GAP and behindSpd > spd + FASTER_MARGIN then
                yielding = true
                -- keep whatever side we've already committed to (don't re-pick and weave); only choose
                -- one the first time, or if the current side is against an edge.
                local side = holdSign[i] or ((hash01(i * 5 + 7) < 0.5) and -1 or 1)
                if (side > 0 and myLat > EDGE_SOFT) or (side < 0 and myLat < -EDGE_SOFT) then side = -side end
                target = side * YIELD_OFFSET * speedDamp
                holdSign[i] = side; holdUntil[i] = os.clock() + DAMAGE_YIELD_HOLD   -- long hold: pick a side and STAY
            end
        end

        -- track-edge safety: never push a car further toward an edge it's already near (keeps cars off
        -- kerbs). A car with a real speed run is allowed a bit closer to the edge to finish an outside
        -- pass, but EDGE_HARD still keeps it on the road.
        local edgeSoft = EDGE_SOFT + wide * OUTSIDE_EDGE
        if (target > 0 and myLat > edgeSoft) or (target < 0 and myLat < -edgeSoft) then
            target = target * clamp((EDGE_HARD - math.abs(myLat)) / (EDGE_HARD - edgeSoft), 0, 1)
        end

        -- deadzone + side-hold: ignore tiny offsets (stay on the line), and hold the chosen side
        -- briefly so the car doesn't dart back and forth when the other car moves around.
        if math.abs(target) < DEADZONE then
            target = 0
        else
            local nowc = os.clock()
            local want = target > 0 and 1 or -1
            if holdSign[i] == nil or (want ~= holdSign[i] and nowc > (holdUntil[i] or 0)) then
                holdSign[i] = want; holdUntil[i] = nowc + SIDE_HOLD
            end
            target = math.abs(target) * (holdSign[i] or want)
        end

        -- OVAL GROOVE (stock cars on a speedway): in a pack, commit to a high or low LANE and run it
        -- side-by-side through the banking, holding it (not darting back to one line). Take the lane
        -- the car ahead isn't in, else a stable personal groove. Edge-safety below still keeps it off
        -- the wall. This is what turns oval running into real pack racing.
        if R.isOval and classKey == 'nascar' and gapA < GROOVE_RANGE then
            local dLatA = aheadIdx >= 0 and latOf(ac.getCar(aheadIdx).position) or 0
            local side = (math.abs(dLatA) > 0.12) and -sgn(dLatA) or ((hash01(i * 7 + 3) < 0.5) and -1 or 1)
            target = side * GROOVE_OFFSET
            holdSign[i] = side; holdUntil[i] = os.clock() + GROOVE_HOLD    -- commit to the lane
        end

        -- GRID FUNNEL (race start only): hold the car near its own grid lane and merge it onto the
        -- racing line gradually over the run to turn 1, so the field funnels down instead of all
        -- converging at once. Overrides the racecraft offset here (after the deadzone) so the fade
        -- stays smooth. Gated to a packed field (crowd) so it never fires on a lone practice lap.
        if myLap == 0 and crowd >= 1 and olS < GRID_FADE_END * R.GRID_FADE_X then
            if gridLat[i] == nil and olS < GRID_CAPTURE then gridLat[i] = myLat end
            if gridLat[i] then
                target = clamp(gridLat[i] * GRID_HOLD * clamp(1 - math.max(0, olS) / (GRID_FADE_END * R.GRID_FADE_X), 0, 1), -1, 1)
            end
        end
        -- LEAVE A CAR'S WIDTH (laps 0-1): alongside another car, move the target away from it. Both cars of a pair
        -- move apart; nobody lifts (a lifting car became the next car's hazard, Barcelona 2026-09-16).
        if R.OL_SIDESPACE and myLap <= 1 and sideSign ~= 0 then
            target = clamp(target + sideSign * CV.SIDE_SPACE, -0.85, 0.85)
        end
        -- CORNER-ENTRY PRIORITY (laps 0-1): alongside a car whose nose is ahead of mine with a corner coming, the corner
        -- is theirs: take the outside line (a lateral move, not a lift)
        if R.OL_CORNER_PRIO and myLap <= 1 and sideBy then
            local isC, inside = cornerAhead(mySpline)
            if isC and inside ~= 0 then target = clamp(-inside * CV.PRIO_OUT, -0.85, 0.85) end
        end

        -- BLOCKAGE sweep (final word): a stopped/crawling car is on my line just ahead -> commit to the
        -- open side and go around, overriding the normal line, groove and funnel. Kept off the wall by
        -- flipping to the roomier side if the chosen one is already near an edge.
        if blockSide ~= 0 and not yielding then                          -- (a car being lapped holds its move-aside line)
            if (blockSide > 0 and myLat > EDGE_SOFT) or (blockSide < 0 and myLat < -EDGE_SOFT) then
                blockSide = -blockSide                                   -- that side's against the edge -> take the other
            end
            target = blockSide * BLOCK_OFFSET
            holdSign[i] = blockSide; holdUntil[i] = os.clock() + BLOCK_HOLD
        end

        -- FREE PASS: the car ahead is a lap down and already yielding -- go by, don't tiptoe. Lapping cars ran
        -- 6-13 km/h under their own pace behind yielding backmarkers (Zandvoort 72-lap GP, 2026-09-14).
        if lappedAhead then caut = caut - FREEPASS_CAUT; if state == 0 then state = 1 end end
        -- cap the stacked back-off (see CAUT_MAX); the attack/defend NEGATIVE caution is left alone
        if caut > CAUT_MAX then caut = CAUT_MAX end

        -- slew the offset (anti-dart)
        local cur = curOffset[i] or 0
        local step = OFFSET_SLEW * (dt > 0 and dt < 0.5 and dt or 0.016)
        if target > cur + step then cur = cur + step
        elseif target < cur - step then cur = cur - step
        else cur = target end
        curOffset[i] = cur

        physics.setAISplineOffset(i, clamp(cur, -1, 1), false)
        physics.setAIAggression(i, clamp(aggr, 0, 1))
        -- what we actually applied this frame, for the diagnostics log (reused table: no per-frame garbage)
        local L = R.last[i] or {}
        L.off, L.aggr, L.caut, L.state, L.yield, L.block, L.dmg = cur, aggr, caut, state, yielding, blockSide, myDmg
        L.rs = rsPass
        L.mv = Strategy.last[i] or 0
        R.last[i] = L
    end)
    if state == 1 then R.attacking = R.attacking + 1
    elseif state == 2 then R.defending = R.defending + 1 end
    return caut
end

R.last = {}                 -- per-car applied values (offset/aggr/caution/state) -- diagnostics only
function R.beginFrame()
    R.attacking = 0; R.defending = 0
    pcall(Strategy.tick)
    -- lights out: the first frame an AI car on lap 0 is moving. Record how far behind the front car everyone started
    -- (spline with the wrap undone: a grid that straddles the line has its back rows at 0.99), for the staggered release.
    if (R.CONVOY2_ON or R.OL_ROWCAUT) and not cv2.clock then
        pcall(function()
            local s = ac.getSim()
            local moving, front, sp = false, -1e9, {}
            for j = 0, s.carsCount - 1 do
                local c = ac.getCar(j)
                if c and c.splinePosition then
                    local x = c.splinePosition; if x > 0.5 then x = x - 1 end
                    sp[j] = x; if x > front then front = x end
                    if c.isAIControlled and (c.lapCount or 0) == 0 and (c.speedKmh or 0) > 20 then moving = true end
                end
            end
            if moving then
                cv2.clock = os.clock()
                for j, x in pairs(sp) do
                    cv2.back[j] = math.max(0, (front - x) * trackLen)
                    -- reaction time at the lights: a human grid never launches as one
                    cv2.react[j] = (R.OL_REACT_MAX > 0) and (CV.REACT_MIN + math.max(0, R.OL_REACT_MAX - CV.REACT_MIN) * math.random()) or 0
                end
            end
        end)
    end
    pcall(function()
        local s = ac.getSim()
        for j = 0, s.carsCount - 1 do
            local c = ac.getCar(j)
            latNow[j] = c and latOf(c.position) or 0
        end
    end)
    if not scaled then      -- (re)derive the metre-based gaps for this track (also self-heals after a hot-reload)
        scaled = true
        pcall(function() local s = ac.getSim(); scaleToTrack(s and s.trackLengthM) end)
    end
end
function R.reset()
    dmgSeen, dmgLap = {}, {}
    curOffset = {}; holdSign = {}; holdUntil = {}; pounceT = {}; commitState = {}; commitUntil = {}; gridLat = {}
    letbyT, letbyDone, letbyFor = {}, {}, {}
    cv2 = { clock = nil, back = {}, thr = {}, bg = {}, base = {}, react = {} }; R.cv2 = cv2
    R.last = {}
    pcall(Strategy.reset)
    scaled = false
    R.isOval = detectOval()     -- classify the track once per session (oval vs road course)
end

return R
