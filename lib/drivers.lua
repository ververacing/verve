-- Verve / drivers.lua
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
local Difficulty = require('lib.difficulty')   -- the measured level <-> lap-time curve (no cycle: difficulty needs only career)
local D = {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
-- pace spreads AI level DOWN from the difficulty. The FASTEST driver actually on the grid runs at the
-- slider level, and everyone else is spaced below by how far their pace rating trails his -- so the
-- field genuinely strings out instead of bunching. Widened (0.16 -> 0.32) because the old value barely
-- separated the field: a mid-pack driver ended up only a few hundredths of an AI level off the ace.
local SPREAD_PCT = 8.0     -- lap-time % between a 1.0-rated driver and a 0.0-rated one (a Rookie at 0.30 vs a 0.96 star ~ 5.3%; real F1 fields spread 2-3%, club grids 5-10%)
-- D.PACE_ABS (setting paceAbs; owner's decision 2026-09-28): a driver profile SETS the car's pace outright -- the difficulty
-- slider no longer applies to profiled cars, and nothing depends on who else is on the grid (before, the fastest profile ran
-- at the slider and the rest were spread below it, so an all-Rookie grid ran at full slider pace). A driver at PACE_REF or
-- above runs at expert pace (difficulty 100); each 1.0 of rating below costs PACE_K lap-time %, on the car's class curve:
-- Rookie (0.30) +10 % = difficulty 80, Midfielder (0.60) +5 % = difficulty 90, Veteran (0.85) +0.8 % = ~98. The slider still
-- sets every car without a profile.
D.PACE_ABS = false
D.PACE_REF = 0.90
D.PACE_K   = 16.67

-- Detected class -> roster bucket. Classes not listed (road) offer only the archetypes.
local CLASS_BUCKET = {
    formula = 'f1', formula_jr = 'f1', kart = 'kart',
    prototype = 'proto', hypercar = 'proto', gt = 'gt',
    touring = 'touring', vintage = 'vintage', rally = 'rally', drift = 'drift', nascar = 'nascar',
}
D.DRIVERS = {
    -- F1-modern
    { key='f1_001', name='Pass Nearstappen', say='pass NEER-stuh-pen', bucket='f1', pace=1.00, aggr=0.90, risk=0.29, cons=0.95 },   -- owner 2026-09-29: the best on the grid at pace and aggression,
    { key='f1_002', name='Bruisin Yamilton', say='BROO-zin yuh-MIL-tun', bucket='f1', pace=0.96, aggr=0.53, risk=0.23, cons=0.97 },
    { key='f1_003', name='Wambo Boris', say='WOM-boh BOR-iss', bucket='f1', pace=0.71, aggr=0.53, risk=0.20, cons=0.86 },
    { key='f1_004', name='Charlie LeKlay', say='CHAR-lee luh-KLAY', bucket='f1', pace=0.71, aggr=0.60, risk=0.46, cons=0.66 },
    { key='f1_005', name='Lester Mystery', say='LES-ter MISS-tuh-ree', bucket='f1', pace=0.69, aggr=0.46, risk=0.16, cons=0.91 },
    { key='f1_006', name='Jim Bustle', say='jim BUSS-ul', bucket='f1', pace=0.66, aggr=0.61, risk=0.28, cons=0.82 },
    { key='f1_007', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='f1', pace=0.73, aggr=0.60, risk=0.29, cons=0.87 },
    { key='f1_008', name='Timmy Slamonelli', say='TIM-ee slam-oh-NEL-ee', bucket='f1', pace=0.70, aggr=0.68, risk=0.56, cons=0.62 },
    { key='f1_009', name='Pavlov Rains', say='PAV-lov raynz', bucket='f1', pace=0.64, aggr=0.53, risk=0.24, cons=0.85 },
    { key='f1_010', name='Knapsack Radbar', say='NAP-sak RAD-bar', bucket='f1', pace=0.63, aggr=0.68, risk=0.41, cons=0.71 },
    { key='f1_011', name='Callum Allbold', say='KAL-um AWL-bohld', bucket='f1', pace=0.63, aggr=0.46, risk=0.19, cons=0.84 },
    { key='f1_012', name='Clear Blastly', say='kleer BLAST-lee', bucket='f1', pace=0.63, aggr=0.60, risk=0.29, cons=0.80 },
    { key='f1_013', name='Stephen Rockon', say='STEE-vun ROCK-on', bucket='f1', pace=0.63, aggr=0.68, risk=0.32, cons=0.78 },
    { key='f1_014', name='Nitro Krakenberg', say='NYE-troh KRAY-ken-berg', bucket='f1', pace=0.63, aggr=0.53, risk=0.30, cons=0.85 },
    { key='f1_015', name='Chance Patrol', say='chanss puh-TROHL', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='f1_016', name='Grizzly Dareman', say='GRIZ-lee DAIR-man', bucket='f1', pace=0.62, aggr=0.68, risk=0.33, cons=0.77 },
    { key='f1_017', name='Gecko Presidente', say='GEK-oh prez-i-DEN-tay', bucket='f1', pace=0.64, aggr=0.60, risk=0.38, cons=0.73 },
    { key='f1_018', name='Valiant Bossman', say='VAL-yunt BOSS-man', bucket='f1', pace=0.67, aggr=0.53, risk=0.14, cons=0.88 },
    { key='f1_019', name='Beam Clawson', say='beem CLAW-sun', bucket='f1', pace=0.62, aggr=0.76, risk=0.36, cons=0.75 },
    { key='f1_020', name='Gavin Thunderleto', say='GAV-in thun-der-LET-oh', bucket='f1', pace=0.62, aggr=0.53, risk=0.43, cons=0.69 },
    { key='f1_021', name='Bronco Cannonpinto', say='BRONG-koh kan-un-PIN-toh', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='f1_022', name='Avid Windblast', say='AV-id WIND-blast', bucket='f1', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    -- F1-classic
    { key='f1_023', name='Aaron Sensei', say='AIR-un SEN-say', bucket='f1', pace=0.88, aggr=0.68, risk=0.56, cons=0.67 },
    { key='f1_024', name='Aplomb Frost', say='uh-PLOM frost', bucket='f1', pace=0.86, aggr=0.53, risk=0.18, cons=0.97 },
    { key='f1_025', name='Mike Zoomacher', say='myke ZOO-mah-ker', bucket='f1', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='f1_026', name='Nicholas Louder', say='NIK-uh-lus LOW-der', bucket='f1', pace=0.78, aggr=0.46, risk=0.21, cons=0.86 },
    { key='f1_027', name='Blaze Stunt', say='blayz stunt', bucket='f1', pace=0.71, aggr=0.76, risk=0.85, cons=0.40 },
    { key='f1_028', name='Regal Muscle', say='REE-gul MUSS-ul', bucket='f1', pace=0.73, aggr=0.84, risk=0.49, cons=0.67 },
    { key='f1_029', name='Wesley Peakwell', say='WEZ-lee PEEK-wel', bucket='f1', pace=0.77, aggr=0.60, risk=0.38, cons=0.82 },
    { key='f1_030', name='Mecha Rockinen', say='MEK-uh ROCK-i-nen', bucket='f1', pace=0.77, aggr=0.53, risk=0.37, cons=0.80 },
    { key='f1_031', name='Chilly Icekkonen', say='CHIL-ee ICE-koh-nen', bucket='f1', pace=0.68, aggr=0.60, risk=0.30, cons=0.83 },
    { key='f1_032', name='Bombastian Medal', say='bom-BAST-ee-un MED-ul', bucket='f1', pace=0.83, aggr=0.60, risk=0.34, cons=0.88 },
    { key='f1_033', name='Neato Bossberg', say='NEE-toh BOSS-berg', bucket='f1', pace=0.70, aggr=0.46, risk=0.20, cons=0.92 },
    { key='f1_034', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='f1', pace=0.66, aggr=0.46, risk=0.30, cons=0.83 },
    { key='f1_035', name='Diamond Thrill', say='DYE-mund thril', bucket='f1', pace=0.74, aggr=0.60, risk=0.43, cons=0.72 },
    { key='f1_036', name='Thrills Ironnerve', say='thrilz EYE-urn-nerv', bucket='f1', pace=0.65, aggr=0.76, risk=0.85, cons=0.40 },
    { key='f1_037', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='f1', pace=0.67, aggr=0.84, risk=0.60, cons=0.55 },
    { key='f1_038', name='Badger Rippiardo', say='BAJ-er rip-ee-AR-doh', bucket='f1', pace=0.62, aggr=0.84, risk=0.27, cons=0.82 },
    { key='f1_039', name='Roland Amazi', say='ROH-lund uh-MAH-zee', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='f1_040', name='Gunnar Surger', say='GUN-ar SUR-jer', bucket='f1', pace=0.65, aggr=0.61, risk=0.40, cons=0.71 },
    { key='f1_041', name='Dan Coolhard', say='dan KOOL-hard', bucket='f1', pace=0.65, aggr=0.46, risk=0.33, cons=0.82 },
    { key='f1_042', name='Spark Webbest', say='spark web-BEST', bucket='f1', pace=0.64, aggr=0.68, risk=0.33, cons=0.78 },
    { key='f1_043', name='Feisty Maestro', say='FYE-stee MY-stroh', bucket='f1', pace=0.64, aggr=0.68, risk=0.32, cons=0.79 },
    { key='f1_044', name='Jack Villenoove', say='jak VEE-luh-noov', bucket='f1', pace=0.68, aggr=0.84, risk=0.45, cons=0.75 },
    { key='f1_045', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='f1', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='f1_046', name='Rowdy Powerson', say='ROW-dee POW-er-sun', bucket='f1', pace=0.66, aggr=0.68, risk=0.50, cons=0.63 },
    { key='f1_047', name='Bravo Andread', say='BRAH-voh AN-dred', bucket='f1', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='f1_048', name='Jolly Checkered', say='JOL-ee CHEK-erd', bucket='f1', pace=0.69, aggr=0.61, risk=0.46, cons=0.64 },
    -- Vintage
    { key='vintage_001', name='Juan Marvel Tangio', say='wahn MAR-vul TAN-jee-oh', bucket='vintage', pace=0.98, aggr=0.53, risk=0.22, cons=0.96 },
    { key='vintage_002', name='Stanley Boss', say='STAN-lee boss', bucket='vintage', pace=0.72, aggr=0.68, risk=0.44, cons=0.73 },
    { key='vintage_003', name='Slim Spark', say='slim spark', bucket='vintage', pace=0.85, aggr=0.53, risk=0.23, cons=0.92 },
    { key='vintage_004', name='Jaunty Sureheart', say='JAWN-tee SHOOR-hart', bucket='vintage', pace=0.80, aggr=0.46, risk=0.17, cons=0.95 },
    { key='vintage_005', name='Gordon Summit', say='GOR-dun SUM-it', bucket='vintage', pace=0.71, aggr=0.60, risk=0.36, cons=0.81 },
    { key='vintage_006', name='Mack Bravado', say='mak bruh-VAH-doh', bucket='vintage', pace=0.75, aggr=0.68, risk=0.30, cons=0.89 },
    { key='vintage_007', name='Vincenzo Acestar', say='vin-CHEN-zoh ACE-star', bucket='vintage', pace=0.84, aggr=0.53, risk=0.28, cons=0.82 },
    { key='vintage_008', name='Rocken Sprint', say='ROCK-en sprint', bucket='vintage', pace=0.70, aggr=0.68, risk=0.50, cons=0.66 },
    { key='vintage_009', name='Don Surtwos', say='don SUR-tooz', bucket='vintage', pace=0.67, aggr=0.60, risk=0.32, cons=0.81 },
    { key='vintage_010', name='Van Journey', say='van JUR-nee', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.77 },
    { key='vintage_011', name='Will Skill', say='wil skil', bucket='vintage', pace=0.69, aggr=0.46, risk=0.28, cons=0.80 },
    { key='vintage_012', name='Ike Hawkstorm', say='ike HAWK-storm', bucket='vintage', pace=0.69, aggr=0.69, risk=0.41, cons=0.78 },
    { key='vintage_013', name='Benny Helm', say='BEN-ee helm', bucket='vintage', pace=0.68, aggr=0.53, risk=0.27, cons=0.95 },
    { key='vintage_014', name='Deuce McDaring', say='dooss mik-DAIR-ing', bucket='vintage', pace=0.64, aggr=0.53, risk=0.22, cons=0.86 },
    { key='vintage_015', name='Rocco Raindriguez', say='ROCK-oh rayn-DREE-gez', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.70 },
    { key='vintage_016', name='Glen Smiles', say='glen smylz', bucket='vintage', pace=0.62, aggr=0.76, risk=0.42, cons=0.72 },
    -- Prototype
    { key='proto_001', name='Duke Crispensen', say='dook KRISP-en-sen', bucket='proto', pace=0.92, aggr=0.60, risk=0.36, cons=0.80 },
    { key='proto_002', name='Rocky Slicks', say='ROCK-ee sliks', bucket='proto', pace=0.91, aggr=0.60, risk=0.42, cons=0.78 },
    { key='proto_003', name='Fenwick Excel', say='FEN-wik ek-SEL', bucket='proto', pace=0.86, aggr=0.53, risk=0.36, cons=0.78 },
    { key='proto_004', name='Hansel Struck', say='HAN-sul struk', bucket='proto', pace=0.81, aggr=0.84, risk=0.48, cons=0.70 },
    { key='proto_005', name='Hardy Persevarolo', say='HAR-dee per-suh-vuh-ROH-loh', bucket='proto', pace=0.78, aggr=0.53, risk=0.42, cons=0.77 },
    { key='proto_006', name='Dalton McFinish', say='DAWL-tun mik-FIN-ish', bucket='proto', pace=0.92, aggr=0.68, risk=0.42, cons=0.84 },
    { key='proto_007', name='Orlando Capablo', say='or-LAN-doh kuh-PAH-bloh', bucket='proto', pace=0.86, aggr=0.39, risk=0.30, cons=0.93 },
    { key='proto_008', name='Duncan Lottawin', say='DUNG-kun LOT-uh-win', bucket='proto', pace=0.86, aggr=0.60, risk=0.42, cons=0.78 },
    { key='proto_009', name='Wendel Fastler', say='WEN-dul FAST-ler', bucket='proto', pace=0.84, aggr=0.53, risk=0.30, cons=0.85 },
    { key='proto_010', name='Gaston Truegrit', say='gas-TOHN TROO-grit', bucket='proto', pace=0.83, aggr=0.53, risk=0.42, cons=0.80 },
    { key='proto_011', name='Bastion Boomi', say='BAS-chun BOO-mee', bucket='proto', pace=0.95, aggr=0.46, risk=0.30, cons=0.89 },
    { key='proto_012', name='Weston Smartley', say='WES-tun SMART-lee', bucket='proto', pace=0.95, aggr=0.53, risk=0.36, cons=0.89 },
    { key='proto_013', name='Kabuki Nakasteady', say='kuh-BOO-kee nah-kuh-STED-ee', bucket='proto', pace=0.88, aggr=0.53, risk=0.42, cons=0.80 },
    { key='proto_014', name='Kapow Kobayaboss', say='kuh-POW koh-bye-uh-BOSS', bucket='proto', pace=0.87, aggr=0.84, risk=0.42, cons=0.78 },
    { key='proto_015', name='Bolt Candoway', say='bohlt KAN-doo-way', bucket='proto', pace=0.87, aggr=0.53, risk=0.36, cons=0.83 },
    { key='proto_016', name='Primo Blazenhard', say='PREE-moh BLAY-zen-hard', bucket='proto', pace=0.84, aggr=0.53, risk=0.36, cons=0.83 },
    { key='proto_017', name='Baptiste Climbas', say='bap-TEEST KLYME-buss', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='proto_018', name='Zeno Genie', say='ZEE-noh JEE-nee', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.75 },
    { key='proto_019', name='Salvatore Speedy', say='sal-vuh-TOR-ay SPEE-dee', bucket='proto', pace=0.88, aggr=0.84, risk=0.42, cons=0.84 },
    { key='proto_020', name='Dexter Calmando', say='DEK-ster kal-MAN-doh', bucket='proto', pace=0.88, aggr=0.60, risk=0.30, cons=0.94 },
    { key='proto_021', name='Giorgio Giovinjazzy', say='JOR-joh joh-vin-JAZ-ee', bucket='proto', pace=0.84, aggr=0.60, risk=0.42, cons=0.75 },
    { key='proto_022', name='Leonardo Fuego', say='lay-oh-NAR-doh FWAY-goh', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.72 },
    -- GT
    { key='gt_001', name='Tobin Extra', say='TOH-bin EK-struh', bucket='gt', pace=0.86, aggr=0.76, risk=0.48, cons=0.78 },
    { key='gt_002', name='Bruno Vanthunder', say='BROO-noh van-THUN-der', bucket='gt', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='gt_003', name='Fabrizio Marvelo', say='fab-REET-see-oh mar-VEL-oh', bucket='gt', pace=0.79, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gt_004', name='Otto Angel', say='OT-oh AYN-jul', bucket='gt', pace=0.74, aggr=0.60, risk=0.36, cons=0.77 },
    { key='gt_005', name='Leandro Macautara', say='lee-AN-droh mah-kow-TAR-uh', bucket='gt', pace=0.74, aggr=0.53, risk=0.36, cons=0.72 },
    { key='gt_006', name='Zippy Triumph', say='ZIP-ee TRY-umf', bucket='gt', pace=0.81, aggr=0.76, risk=0.48, cons=0.73 },
    { key='gt_007', name='Kasper Soaringsen', say='KAS-per SOR-ing-sen', bucket='gt', pace=0.78, aggr=0.46, risk=0.30, cons=0.85 },
    { key='gt_008', name='Bennett Leadz', say='BEN-it leedz', bucket='gt', pace=0.74, aggr=0.46, risk=0.36, cons=0.77 },
    { key='gt_009', name='Soren Magnifussen', say='SOR-en mag-ni-FUSS-en', bucket='gt', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    { key='gt_010', name='Rowan Gavel', say='ROH-un GAV-ul', bucket='gt', pace=0.74, aggr=0.46, risk=0.30, cons=0.82 },
    { key='gt_011', name='Antone Guardia', say='an-TOHN GWAR-dee-uh', bucket='gt', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='gt_012', name='Wade Nightsburg', say='wayd NITES-berg', bucket='gt', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gt_013', name='Doctor Bossi', say='DOK-ter BOSS-ee', bucket='gt', pace=0.68, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gt_014', name='Shelby van der Laser', say='SHEL-bee van der LAY-zer', bucket='gt', pace=0.78, aggr=0.60, risk=0.36, cons=0.80 },
    { key='gt_015', name='Kelton van der Launch', say='KEL-tun van der LAWNCH', bucket='gt', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='gt_016', name='Remy Gonnawin', say='REM-ee GON-uh-win', bucket='gt', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='gt_017', name='Enzo Winsalotti', say='EN-zoh win-zuh-LOT-ee', bucket='gt', pace=0.74, aggr=0.61, risk=0.42, cons=0.72 },
    { key='gt_018', name='Thibault Smartin', say='tee-BOH SMAR-tin', bucket='gt', pace=0.74, aggr=0.53, risk=0.42, cons=0.72 },
    { key='gt_019', name='Breeze Vandoor', say='breez van-DOOR', bucket='gt', pace=0.68, aggr=0.68, risk=0.42, cons=0.72 },
    -- Touring
    { key='touring_001', name='Dietmar Shineider', say='DEET-mar SHYNE-der', bucket='touring', pace=0.92, aggr=0.61, risk=0.36, cons=0.87 },
    { key='touring_002', name='Rolf Loudking', say='rolf LOWD-king', bucket='touring', pace=0.84, aggr=0.53, risk=0.42, cons=0.81 },
    { key='touring_003', name='Sven Eckstreme', say='sven ek-STREEM', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='touring_004', name='Dominic Fast', say='DOM-i-nik fast', bucket='touring', pace=0.84, aggr=0.53, risk=0.30, cons=0.91 },
    { key='touring_005', name='Dieter Brockstar', say='DEE-ter BROCK-star', bucket='touring', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='touring_006', name='Blaine Loudness', say='blayn LOWD-ness', bucket='touring', pace=0.84, aggr=0.84, risk=0.48, cons=0.76 },
    { key='touring_007', name='Tucker Winstreak', say='TUK-er WIN-streek', bucket='touring', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='touring_008', name='Bodie van Glidesbergen', say='BOH-dee van GLIDES-ber-gen', bucket='touring', pace=0.90, aggr=0.68, risk=0.42, cons=0.81 },
    { key='touring_009', name='Dermot Closington', say='DUR-mut KLOHZ-ing-tun', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.89 },
    { key='touring_010', name='Mason Playmaker', say='MAY-sun PLAY-may-ker', bucket='touring', pace=0.81, aggr=0.84, risk=0.42, cons=0.78 },
    { key='touring_011', name='Mack Steele', say='mak steel', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='touring_012', name='Dash Stunton', say='dash STUN-tun', bucket='touring', pace=0.93, aggr=0.76, risk=0.42, cons=0.84 },
    { key='touring_013', name='Rory Prizeluxe', say='ROR-ee PRYZE-luks', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='touring_014', name='Etienne Smoothler', say='et-YEN SMOOTH-ler', bucket='touring', pace=0.92, aggr=0.61, risk=0.42, cons=0.87 },
    { key='touring_015', name='Vittorio Tarquickni', say='vi-TOR-ee-oh tar-KWIK-nee', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='touring_016', name='Emilio Lopedal', say='eh-MEEL-ee-oh loh-PED-ul', bucket='touring', pace=0.97, aggr=0.60, risk=0.42, cons=0.87 },
    { key='touring_017', name='Gaspard Mainmenu', say='gas-PAR MAYN-men-yoo', bucket='touring', pace=0.81, aggr=0.46, risk=0.36, cons=0.78 },
    -- Rally
    { key='rally_001', name='Thierry Globe', say='tee-AIR-ee glohb', bucket='rally', pace=0.96, aggr=0.46, risk=0.17, cons=0.97 },
    { key='rally_002', name='Julien Ohyeah', say='ZHOO-lee-en oh-YAY', bucket='rally', pace=0.93, aggr=0.60, risk=0.24, cons=0.97 },
    { key='rally_003', name='Mikko Makewinnen', say='MIK-oh MAKE-win-en', bucket='rally', pace=0.77, aggr=0.84, risk=0.61, cons=0.70 },
    { key='rally_004', name='Angus McBrave', say='ANG-gus mik-BRAYV', bucket='rally', pace=0.69, aggr=0.76, risk=0.85, cons=0.40 },
    { key='rally_005', name='Rupert Turns', say='ROO-pert turnz', bucket='rally', pace=0.69, aggr=0.46, risk=0.29, cons=0.84 },
    { key='rally_006', name='Carlito Reigns Sr.', say='kar-LEE-toh raynz SEE-nyur', bucket='rally', pace=0.72, aggr=0.61, risk=0.32, cons=0.84 },
    { key='rally_007', name='Eero Kankkoolen', say='AIR-oh kan-KOO-len', bucket='rally', pace=0.77, aggr=0.46, risk=0.16, cons=0.97 },
    { key='rally_008', name='Teemu Groundholm', say='TAY-moo GROWND-holm', bucket='rally', pace=0.73, aggr=0.68, risk=0.50, cons=0.74 },
    { key='rally_009', name='Better Showberg', say='BET-er SHOH-berg', bucket='rally', pace=0.67, aggr=0.76, risk=0.58, cons=0.59 },
    { key='rally_010', name='Wolfgang Roarl', say='WOOLF-gang RORL', bucket='rally', pace=0.73, aggr=0.46, risk=0.34, cons=0.78 },
    { key='rally_011', name='Ilkka Mikkosteady', say='ILK-uh mik-oh-STED-ee', bucket='rally', pace=0.69, aggr=0.53, risk=0.43, cons=0.77 },
    { key='rally_012', name='Colette Mountain', say='koh-LET MOWN-tin', bucket='rally', pace=0.65, aggr=0.68, risk=0.55, cons=0.64 },
    { key='rally_013', name='Osmo Flatoutanen', say='OZ-moh flat-OW-tuh-nen', bucket='rally', pace=0.68, aggr=0.76, risk=0.81, cons=0.44 },
    { key='rally_014', name='Lasse Toivroomen', say='LASS-uh toy-VROO-men', bucket='rally', pace=0.68, aggr=0.60, risk=0.85, cons=0.40 },
    { key='rally_015', name='Onni Rovanperfect', say='ON-ee roh-van-PUR-fekt', bucket='rally', pace=0.76, aggr=0.68, risk=0.47, cons=0.76 },
    { key='rally_016', name='Rein Attanak', say='rayn uh-TAN-ak', bucket='rally', pace=0.69, aggr=0.68, risk=0.51, cons=0.65 },
    { key='rally_017', name='Damien Nailville', say='DAY-mee-un NAYL-vil', bucket='rally', pace=0.69, aggr=0.60, risk=0.61, cons=0.57 },
    { key='rally_018', name='Gwilym Heavens', say='GWIL-im HEV-unz', bucket='rally', pace=0.66, aggr=0.46, risk=0.18, cons=0.89 },
    -- Drift
    { key='drift_001', name='Cormac Deanmachine', say='KOR-mak DEEN-muh-sheen', bucket='drift', pace=0.97, aggr=0.61, risk=0.36, cons=0.92 },
    { key='drift_002', name='Magnus Aceboss', say='MAG-nus ACE-boss', bucket='drift', pace=0.84, aggr=0.53, risk=0.36, cons=0.86 },
    { key='drift_003', name='Trevor Forceberg', say='TREV-er FORCE-berg', bucket='drift', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='drift_004', name='Garrison Gittinloose Jr.', say='GAIR-i-sun git-in-LOOSS JOO-nyur', bucket='drift', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='drift_005', name='Haru Slideto', say='HAH-roo SLIDE-toh', bucket='drift', pace=0.88, aggr=0.76, risk=0.42, cons=0.84 },
    { key='drift_006', name='Ryo Tsuchiking', say='REE-oh SOO-chee-king', bucket='drift', pace=0.74, aggr=0.68, risk=0.48, cons=0.67 },
    { key='drift_007', name='Shingo Kawablaster', say='SHIN-goh kah-wuh-BLAST-er', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='drift_008', name='Axel Zeeway', say='AK-sul ZEE-way', bucket='drift', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='drift_009', name='Declan Shenanigan', say='DEK-lun shuh-NAN-i-gun', bucket='drift', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='drift_010', name='Takeshi Minowow', say='tah-KESH-ee MIN-oh-wow', bucket='drift', pace=0.68, aggr=0.68, risk=0.48, cons=0.72 },
    -- F1-classic
    { key='f1_049', name='Tiago Barrichampion', say='tee-AH-goh bar-ee-CHAM-pee-un', bucket='f1', pace=0.65, aggr=0.53, risk=0.34, cons=0.76 },
    { key='f1_050', name='Dirk Shootmacher', say='durk SHOOT-mah-ker', bucket='f1', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='f1_051', name='Lorenzo Fisicheetah', say='loh-REN-zoh fee-see-CHEE-tuh', bucket='f1', pace=0.63, aggr=0.60, risk=0.35, cons=0.76 },
    { key='f1_052', name='Fausto Trulligood', say='FOW-stoh TROO-lee-good', bucket='f1', pace=0.63, aggr=0.60, risk=0.33, cons=0.77 },
    { key='f1_053', name='Barry Ironvine', say='BAIR-ee EYE-urn-vyne', bucket='f1', pace=0.64, aggr=0.68, risk=0.45, cons=0.67 },
    { key='f1_054', name='Jurgen Frontrunner', say='YOOR-gen FRUNT-run-er', bucket='f1', pace=0.63, aggr=0.53, risk=0.38, cons=0.73 },
    { key='f1_055', name='Leonard Herobert', say='LEN-erd HEER-oh-bert', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='f1_056', name='Lars Heightfield', say='larz HYTE-feeld', bucket='f1', pace=0.63, aggr=0.53, risk=0.20, cons=0.88 },
    { key='f1_057', name='Antti Cavalrainen', say='AN-tee kav-ul-RY-nen', bucket='f1', pace=0.63, aggr=0.61, risk=0.43, cons=0.74 },
    { key='f1_058', name='Olivier Grosgenius', say='oh-LIV-ee-ay grohss-JEEN-yus', bucket='f1', pace=0.62, aggr=0.60, risk=0.60, cons=0.54 },
    { key='f1_059', name='Rafael Bulldonado', say='rah-fah-EL bool-doh-NAH-doh', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='f1_060', name='Bjarne Magnumforce', say='BYAR-nuh MAG-num-forss', bucket='f1', pace=0.62, aggr=0.68, risk=0.35, cons=0.76 },
    { key='f1_061', name='Grigor Kwyatt', say='GREE-gor KWY-at', bucket='f1', pace=0.62, aggr=0.60, risk=0.42, cons=0.70 },
    { key='f1_062', name='Riku Tsunami', say='REE-koo tsoo-NAH-mee', bucket='f1', pace=0.62, aggr=0.60, risk=0.45, cons=0.67 },
    { key='f1_063', name='Hideo Satonaut', say='hee-DAY-oh SAT-oh-nawt', bucket='f1', pace=0.62, aggr=0.68, risk=0.70, cons=0.46 },
    { key='f1_064', name='Jonas Shoemaker', say='YOH-nus SHOO-may-ker', bucket='f1', pace=0.62, aggr=0.53, risk=0.48, cons=0.69 },
    { key='f1_065', name='Cooper Sergewell', say='KOO-per SURJ-wel', bucket='f1', pace=0.62, aggr=0.60, risk=0.54, cons=0.59 },
    { key='f1_066', name='Jan Papastappen', say='yahn PAH-puh-stap-en', bucket='f1', pace=0.62, aggr=0.60, risk=0.55, cons=0.59 },
    { key='f1_067', name='Massimo Patrecord', say='MASS-ee-moh PAT-ruh-kord', bucket='f1', pace=0.64, aggr=0.60, risk=0.42, cons=0.69 },
    { key='f1_068', name='Silvio Alborocket', say='SIL-vee-oh AL-boh-rok-it', bucket='f1', pace=0.64, aggr=0.53, risk=0.42, cons=0.70 },
    { key='f1_069', name='Matteo de Caesar', say='mat-TAY-oh duh SEE-zer', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='f1_070', name='Clive Warwhack', say='klyve WOR-wak', bucket='f1', pace=0.62, aggr=0.68, risk=0.45, cons=0.68 },
    { key='f1_071', name='Giles Rumble', say='jylz RUM-bul', bucket='f1', pace=0.62, aggr=0.68, risk=0.43, cons=0.69 },
    { key='f1_072', name='Dwight Achiever', say='dwyte uh-CHEE-ver', bucket='f1', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='f1_073', name='Bertrand Boostsen', say='bair-TRAHN BOOST-sen', bucket='f1', pace=0.63, aggr=0.46, risk=0.28, cons=0.77 },
    { key='f1_074', name='Kimo Roarsberg', say='KEE-moh RORZ-berg', bucket='f1', pace=0.68, aggr=0.84, risk=0.51, cons=0.65 },
    { key='f1_075', name='Dennis Thrones', say='DEN-iss throhnz', bucket='f1', pace=0.70, aggr=0.68, risk=0.36, cons=0.78 },
    { key='f1_076', name='Emiliano Roadmann', say='eh-mee-lee-AH-noh ROHD-man', bucket='f1', pace=0.67, aggr=0.60, risk=0.32, cons=0.78 },
    { key='f1_077', name='Aldo Regazzoom', say='AL-doh reg-uh-ZOOM', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='f1_078', name='Adriano Fittipedal', say='ah-dree-AH-noh FIT-ee-ped-ul', bucket='f1', pace=0.73, aggr=0.46, risk=0.26, cons=0.84 },
    { key='f1_079', name='Michel Lafleet', say='mee-SHEL luh-FLEET', bucket='f1', pace=0.65, aggr=0.53, risk=0.42, cons=0.75 },
    { key='f1_080', name='Alphonse Ironoux', say='al-FONSS EYE-run-oo', bucket='f1', pace=0.66, aggr=0.68, risk=0.44, cons=0.68 },
    { key='f1_081', name='Gerard Pyrocket', say='zheh-RAR PY-rock-it', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='f1_082', name='Clifford Wattage', say='KLIF-erd WOT-ij', bucket='f1', pace=0.64, aggr=0.60, risk=0.39, cons=0.73 },
    { key='f1_083', name='Armand Tambourine', say='ar-MAHN tam-buh-REEN', bucket='f1', pace=0.64, aggr=0.53, risk=0.39, cons=0.72 },
    { key='f1_084', name='Fabio de Angelwing', say='FAH-bee-oh duh AYN-jul-wing', bucket='f1', pace=0.63, aggr=0.53, risk=0.42, cons=0.70 },
    { key='f1_085', name='Gilbert Jabullet', say='zheel-BAIR zhah-BOOL-ay', bucket='f1', pace=0.65, aggr=0.60, risk=0.50, cons=0.63 },
    { key='f1_086', name='Pascal Cleverte', say='pas-KAL kluh-VAIRT', bucket='f1', pace=0.65, aggr=0.53, risk=0.46, cons=0.67 },
    { key='f1_087', name='Yves Depedaler', say='eev duh-PED-ul-er', bucket='f1', pace=0.64, aggr=0.76, risk=0.63, cons=0.57 },
    -- Vintage
    { key='vintage_017', name='Guido Farinaflash', say='GWEE-doh fuh-REE-nuh-flash', bucket='vintage', pace=0.74, aggr=0.68, risk=0.63, cons=0.55 },
    { key='vintage_018', name='Ramiro Gonzoblaze', say='rah-MEE-roh GON-zoh-blayz', bucket='vintage', pace=0.69, aggr=0.60, risk=0.38, cons=0.73 },
    { key='vintage_019', name='Clement Brooksmile', say='KLEM-unt BROOK-smyle', bucket='vintage', pace=0.68, aggr=0.53, risk=0.33, cons=0.73 },
    { key='vintage_020', name='Desmond Coolins', say='DEZ-mund KOO-linz', bucket='vintage', pace=0.66, aggr=0.68, risk=0.42, cons=0.69 },
    { key='vintage_021', name='Fabien Trintigallant', say='fah-bee-EN trin-ti-GAL-unt', bucket='vintage', pace=0.63, aggr=0.53, risk=0.34, cons=0.86 },
    { key='vintage_022', name='Whitaker Ginzinger', say='WIT-uh-ker GIN-zing-er', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.82 },
    { key='vintage_023', name='Konstantin von Zips', say='KON-stun-teen von zips', bucket='vintage', pace=0.65, aggr=0.68, risk=0.57, cons=0.57 },
    { key='vintage_024', name='Auguste Bravehra', say='oh-GOOST brah-VAIR-uh', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.65 },
    { key='vintage_025', name='Emil Swiffert', say='AY-meel SWIF-ert', bucket='vintage', pace=0.63, aggr=0.76, risk=0.46, cons=0.72 },
    { key='vintage_026', name='Lyall Amonarch', say='LY-ul AM-on-ark', bucket='vintage', pace=0.63, aggr=0.60, risk=0.40, cons=0.72 },
    -- Formula-Indy
    { key='f1_088', name='T.J. Fortress', say='tee-jay FOR-tress', bucket='f1', pace=0.92, aggr=0.68, risk=0.42, cons=0.93 },
    { key='f1_089', name='Brett Slixon', say='bret SLIK-sun', bucket='f1', pace=0.92, aggr=0.60, risk=0.36, cons=0.95 },
    { key='f1_090', name='Gareth Horsepower', say='GAIR-eth HORSS-pow-er', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='f1_091', name='Nathan Andcharge', say='NAY-thun AND-charj', bucket='f1', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='f1_092', name='Vern Winser', say='vurn WIN-ser', bucket='f1', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='f1_093', name='Corentin Bourdash', say='kor-ahn-TAN BOOR-dash', bucket='f1', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='f1_094', name='Chip Onsurge', say='chip ON-serj', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='f1_095', name='Vic Winsome Jr.', say='vik WIN-sum JOO-nyur', bucket='f1', pace=0.81, aggr=0.53, risk=0.42, cons=0.78 },
    { key='f1_096', name='Wyatt Newgarland', say='WY-ut NEW-gar-lund', bucket='f1', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='f1_097', name='Grady Racy', say='GRAY-dee RAY-see', bucket='f1', pace=0.78, aggr=0.68, risk=0.48, cons=0.70 },
    { key='f1_098', name='Ewan Franchisey', say='YOO-un FRAN-chy-zee', bucket='f1', pace=0.88, aggr=0.46, risk=0.36, cons=0.89 },
    { key='f1_099', name='Nuno Castroclimbs', say='NOO-noh KAS-troh-klymz', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='f1_100', name='Chuck Gears', say='chuk geerz', bucket='f1', pace=0.84, aggr=0.53, risk=0.36, cons=0.81 },
    { key='f1_101', name='Hollis Rocketford', say='HOL-iss ROK-it-ford', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='f1_102', name='Marc Palooza', say='mark puh-LOO-zuh', bucket='f1', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='f1_103', name='Gordy Royal', say='GOR-dee ROY-ul', bucket='f1', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='f1_104', name='Gus Hornblast Jr.', say='guss HORN-blast JOO-nyur', bucket='f1', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='f1_105', name='Kirby Hunter-Blaze', say='KUR-bee HUN-ter-blayz', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='f1_106', name='Rogerio Cannonaan', say='roh-ZHAIR-ee-oh KAN-un-ahn', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='f1_107', name='Luca Zanhardy', say='LOO-kuh zan-HAR-dee', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='f1_108', name='Florent Pageturner', say='floh-RAHN PAYJ-turn-er', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='f1_109', name='Paulo de Ferrous', say='POW-loh duh FAIR-us', bucket='f1', pace=0.81, aggr=0.53, risk=0.36, cons=0.83 },
    { key='f1_110', name='Patio O\'Warden', say='PAT-ee-oh oh-WAR-den', bucket='f1', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='f1_111', name='Bryson Heartbeat', say='BRY-sun HART-beet', bucket='f1', pace=0.74, aggr=0.68, risk=0.54, cons=0.62 },
    { key='f1_112', name='Harrison Glossi', say='HAIR-i-sun GLOSS-ee', bucket='f1', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='f1_113', name='Blair McLaunchlin', say='blair muh-LAWNCH-lin', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='f1_114', name='Barnaby Jonestone', say='BAR-nuh-bee JOHN-stohn', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    -- Rally
    { key='rally_019', name='Cyprien Aurigold', say='see-pree-EN OR-ee-gohld', bucket='rally', pace=0.69, aggr=0.53, risk=0.38, cons=0.71 },
    { key='rally_020', name='Esko Allin', say='ES-koh AWL-in', bucket='rally', pace=0.67, aggr=0.76, risk=0.60, cons=0.59 },
    { key='rally_021', name='Aarne Latvalanche', say='AR-nuh LAT-vuh-lanch', bucket='rally', pace=0.69, aggr=0.60, risk=0.65, cons=0.51 },
    { key='rally_022', name='Ennio Bravasion', say='EN-ee-oh bruh-VAY-zhun', bucket='rally', pace=0.74, aggr=0.46, risk=0.23, cons=0.92 },
    { key='rally_023', name='Sigurd Wallguard', say='SIG-erd WAWL-gard', bucket='rally', pace=0.70, aggr=0.53, risk=0.34, cons=0.74 },
    { key='rally_024', name='Arttu Hurryvonen', say='AR-too HUR-ee-voh-nen', bucket='rally', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='rally_025', name='Ingvar Blomtwist', say='ING-var BLOM-twist', bucket='rally', pace=0.68, aggr=0.60, risk=0.39, cons=0.75 },
    { key='rally_026', name='Urho Saloonen', say='OOR-hoh suh-LOO-nen', bucket='rally', pace=0.68, aggr=0.60, risk=0.45, cons=0.71 },
    { key='rally_027', name='Duilio Moonari', say='doo-EEL-ee-oh moo-NAR-ee', bucket='rally', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='rally_028', name='Cedric Panpizzazz', say='SED-rik pan-pi-ZAZ', bucket='rally', pace=0.62, aggr=0.68, risk=0.42, cons=0.72 },
    { key='rally_029', name='Tarmo Marveltin', say='TAR-moh MAR-vul-tin', bucket='rally', pace=0.62, aggr=0.53, risk=0.36, cons=0.72 },
    { key='rally_030', name='Fergal Mightke', say='FUR-gul MYTE-kee', bucket='rally', pace=0.67, aggr=0.60, risk=0.65, cons=0.50 },
    { key='rally_031', name='Iker Swordo', say='EE-ker SWOR-doh', bucket='rally', pace=0.64, aggr=0.60, risk=0.26, cons=0.83 },
    { key='rally_032', name='Hakon Mightelsen', say='HAH-kun MYTE-ul-sen', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='rally_033', name='Veikko Lapking', say='VAY-koh LAP-king', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.66 },
    { key='rally_034', name='Torbjorn Stellarberg', say='TOR-byorn STEL-ar-berg', bucket='rally', pace=0.62, aggr=0.76, risk=0.48, cons=0.67 },
    { key='rally_035', name='Sora Katsuper', say='SOR-uh kat-SOO-per', bucket='rally', pace=0.62, aggr=0.60, risk=0.48, cons=0.67 },
    -- Prototype
    { key='proto_023', name='Lothar Beeline', say='LOH-tar BEE-lyne', bucket='proto', pace=0.94, aggr=0.53, risk=0.42, cons=0.88 },
    { key='proto_024', name='Cesare Pyrostar', say='cheh-ZAR-ay PY-roh-star', bucket='proto', pace=0.86, aggr=0.53, risk=0.42, cons=0.72 },
    { key='proto_025', name='Camille Gentlebien', say='kah-MEEL ZHAHN-tul-bee-en', bucket='proto', pace=0.84, aggr=0.46, risk=0.30, cons=0.77 },
    { key='proto_026', name='Gaetan Dalmaster', say='gy-TAHN DAL-mas-ter', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.77 },
    { key='proto_027', name='Horace Holbright', say='HOR-iss HOHL-bryte', bucket='proto', pace=0.84, aggr=0.60, risk=0.36, cons=0.77 },
    { key='proto_028', name='Judson Haywonder', say='JUD-sun HAY-wun-der', bucket='proto', pace=0.80, aggr=0.53, risk=0.42, cons=0.72 },
    { key='proto_029', name='Armel Wolfpack', say='ar-MEL WOOLF-pak', bucket='proto', pace=0.75, aggr=0.60, risk=0.42, cons=0.72 },
    { key='proto_030', name='Anatole Duelval', say='an-uh-TOHL DOO-ul-val', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='proto_031', name='Rufus Dashvidson', say='ROO-fus DASH-vid-sun', bucket='proto', pace=0.79, aggr=0.53, risk=0.36, cons=0.75 },
    { key='proto_032', name='Falk Rockinfella', say='fahlk ROK-in-fel-uh', bucket='proto', pace=0.81, aggr=0.60, risk=0.30, cons=0.85 },
    { key='proto_033', name='Quinn Bambam', say='kwin BAM-bam', bucket='proto', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='proto_034', name='Percy Dandy', say='PUR-see DAN-dee', bucket='proto', pace=0.76, aggr=0.84, risk=0.42, cons=0.72 },
    { key='proto_035', name='Konrad Whirls', say='KON-rad wurlz', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.72 },
    { key='proto_036', name='Ulysse Sarrazoom', say='oo-LEESS sar-uh-ZOOM', bucket='proto', pace=0.77, aggr=0.60, risk=0.42, cons=0.72 },
    -- Touring
    { key='touring_018', name='Hugh Skyfe', say='hyoo skyfe', bucket='touring', pace=0.92, aggr=0.54, risk=0.36, cons=0.87 },
    { key='touring_019', name='Wally Johnstone', say='WOL-ee JON-stohn', bucket='touring', pace=0.92, aggr=0.68, risk=0.42, cons=0.87 },
    { key='touring_020', name='Keith Mofast', say='keeth MOH-fast', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='touring_021', name='Lachlan Thunder', say='LOK-lun THUN-der', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='touring_022', name='Malcolm Rousing', say='MAL-kum ROW-zing', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='touring_023', name='Nicola Giovanhardy', say='nee-KOH-luh joh-vun-HAR-dee', bucket='touring', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='touring_024', name='Hamish Shredden', say='HAY-mish SHRED-un', bucket='touring', pace=0.81, aggr=0.68, risk=0.36, cons=0.83 },
    { key='touring_025', name='Gustav Ridewell', say='GOO-stav RYDE-wel', bucket='touring', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='touring_026', name='Sylvain Hiyello', say='seel-VAN hy-YEL-oh', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='touring_027', name='Alasdair Clelandslide', say='AL-us-der KLEE-lund-slyde', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='touring_028', name='Edmund Thumpson', say='ED-mund THUMP-sun', bucket='touring', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='touring_029', name='Julian Paffect', say='JOO-lee-un puh-FEKT', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='touring_030', name='Lukas Wittyman', say='LOO-kus WIT-ee-man', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='touring_031', name='Ansgar Skyder', say='ANS-gar SKY-der', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='touring_032', name='Gianni Ravaglide', say='JAH-nee RAV-uh-glyde', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    -- Drift
    { key='drift_011', name='Anders Hubcapette', say='AN-derz hub-kuh-PET', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='drift_012', name='Owen Milehigh', say='OH-un MILE-hy', bucket='drift', pace=0.78, aggr=0.68, risk=0.48, cons=0.75 },
    { key='drift_013', name='Colby Foustest', say='KOHL-bee FOW-stest', bucket='drift', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='drift_014', name='Kenji Yoshiflare', say='KEN-jee yoh-shee-FLAIR', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='drift_015', name='Douglas Esscurve', say='DUG-lus ESS-kurv', bucket='drift', pace=0.78, aggr=0.53, risk=0.30, cons=0.85 },
    { key='drift_016', name='Delphine DeNofear', say='del-FEEN duh-NOH-feer', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='drift_017', name='Brody Torque', say='BROH-dee tork', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='drift_018', name='Marius Backswish', say='MAR-ee-us BAK-swish', bucket='drift', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='drift_019', name='Rex Skidfield', say='reks SKID-feeld', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='drift_020', name='Wild Wayne Widetrack', say='wyld wayn WIDE-trak', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    -- NASCAR-modern
    { key='nascar_001', name='Rodney Hammerlin', say='ROD-nee HAM-er-lin', bucket='nascar', pace=0.78, aggr=0.53, risk=0.28, cons=0.81 },
    { key='nascar_002', name='Bronson Bushfire', say='BRON-sun BUSH-fyre', bucket='nascar', pace=0.94, aggr=0.68, risk=0.39, cons=0.78 },
    { key='nascar_003', name='Vince Loganogo', say='vinss loh-guh-NOH-goh', bucket='nascar', pace=0.96, aggr=0.68, risk=0.32, cons=0.87 },
    { key='nascar_004', name='Zane Wrestleowski', say='zayn res-luh-OW-skee', bucket='nascar', pace=0.81, aggr=0.68, risk=0.31, cons=0.82 },
    { key='nascar_005', name='Donovan Truest Jr.', say='DON-uh-vun TROO-est JOO-nyur', bucket='nascar', pace=0.79, aggr=0.53, risk=0.27, cons=0.80 },
    { key='nascar_006', name='Kellan Larsonic', say='KEL-un lar-SON-ik', bucket='nascar', pace=0.91, aggr=0.60, risk=0.39, cons=0.78 },
    { key='nascar_007', name='Kipp Elliblaze', say='kip EL-ee-blayz', bucket='nascar', pace=0.82, aggr=0.53, risk=0.21, cons=0.85 },
    { key='nascar_008', name='Griffin Blazeney', say='GRIF-in BLAYZ-nee', bucket='nascar', pace=0.80, aggr=0.53, risk=0.39, cons=0.75 },
    { key='nascar_009', name='Fletcher Byronic', say='FLECH-er by-RON-ik', bucket='nascar', pace=0.73, aggr=0.46, risk=0.39, cons=0.72 },
    { key='nascar_010', name='Sullivan Bellringer', say='SUL-i-vun BEL-ring-er', bucket='nascar', pace=0.75, aggr=0.46, risk=0.33, cons=0.72 },
    { key='nascar_011', name='Jonah Redzone', say='JOH-nuh RED-zohn', bucket='nascar', pace=0.73, aggr=0.68, risk=0.36, cons=0.75 },
    { key='nascar_012', name='Deke Chasegain', say='deek CHAYSS-gayn', bucket='nascar', pace=0.67, aggr=0.68, risk=0.38, cons=0.73 },
    { key='nascar_013', name='Landon Briskly', say='LAN-dun BRISK-lee', bucket='nascar', pace=0.70, aggr=0.60, risk=0.37, cons=0.74 },
    { key='nascar_014', name='Grant Boostcher', say='grant BOOST-cher', bucket='nascar', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='nascar_015', name='Trey Arrowman', say='tray AIR-oh-man', bucket='nascar', pace=0.67, aggr=0.53, risk=0.43, cons=0.74 },
    { key='nascar_016', name='Truman Wallop', say='TROO-mun WOL-up', bucket='nascar', pace=0.66, aggr=0.60, risk=0.49, cons=0.64 },
    { key='nascar_017', name='Bodie van Glidesbergen', say='BOH-dee van GLIDES-ber-gen', bucket='nascar', pace=0.74, aggr=0.60, risk=0.35, cons=0.76 },
    { key='nascar_018', name='Kai Gibbspeed', say='ky GIB-speed', bucket='nascar', pace=0.68, aggr=0.68, risk=0.44, cons=0.68 },
    { key='nascar_019', name='Beckett Hoceviper', say='BEK-it HOH-suh-vy-per', bucket='nascar', pace=0.66, aggr=0.68, risk=0.45, cons=0.67 },
    { key='nascar_020', name='Preston Cinderick', say='PRES-tun SIN-der-ik', bucket='nascar', pace=0.66, aggr=0.53, risk=0.37, cons=0.74 },
    { key='nascar_021', name='Beau Steelhouse Jr.', say='boh STEEL-howss JOO-nyur', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='nascar_022', name='Jasper Drillon', say='JAS-per DRIL-un', bucket='nascar', pace=0.65, aggr=0.68, risk=0.37, cons=0.74 },
    { key='nascar_023', name='C.J. Allmenwinner', say='see-jay AWL-men-win-er', bucket='nascar', pace=0.64, aggr=0.60, risk=0.33, cons=0.77 },
    { key='nascar_024', name='Barrett McDoingwell', say='BAIR-it muk-DOO-ing-wel', bucket='nascar', pace=0.62, aggr=0.60, risk=0.39, cons=0.72 },
    { key='nascar_025', name='Milo Preecision', say='MY-loh pruh-SIZH-un', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    -- NASCAR-classic
    { key='nascar_026', name='Everett Plentymore', say='EV-er-it PLEN-tee-mor', bucket='nascar', pace=0.96, aggr=0.68, risk=0.42, cons=0.93 },
    { key='nascar_027', name='Emmett Peerless', say='EM-it PEER-less', bucket='nascar', pace=0.82, aggr=0.53, risk=0.36, cons=0.81 },
    { key='nascar_028', name='Sawyer Gordian', say='SAW-yer GOR-dee-un', bucket='nascar', pace=0.82, aggr=0.53, risk=0.42, cons=0.84 },
    { key='nascar_029', name='Hoyt Allwinson', say='hoyt AWL-win-sun', bucket='nascar', pace=0.70, aggr=0.68, risk=0.48, cons=0.75 },
    { key='nascar_030', name='Jubal Waltriple', say='JOO-bul WAWL-trip-ul', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.81 },
    { key='nascar_031', name='Clyde Sevenson', say='klyde SEV-un-sun', bucket='nascar', pace=0.94, aggr=0.61, risk=0.36, cons=0.97 },
    { key='nascar_032', name='Merle Yardcharger', say='murl YARD-char-jer', bucket='nascar', pace=0.80, aggr=0.68, risk=0.48, cons=0.81 },
    { key='nascar_033', name='Boyd Ironheart', say='boyd EYE-urn-hart', bucket='nascar', pace=0.93, aggr=0.60, risk=0.42, cons=0.93 },
    { key='nascar_034', name='Wesson Havock', say='WES-un HAV-ok', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='nascar_035', name='Orson Wallride', say='OR-sun WAWL-ryde', bucket='nascar', pace=0.69, aggr=0.68, risk=0.42, cons=0.75 },
    { key='nascar_036', name='Deacon Stouthart', say='DEE-kun STOWT-hart', bucket='nascar', pace=0.76, aggr=0.60, risk=0.42, cons=0.81 },
    { key='nascar_037', name='Roy Rallyott', say='roy RAL-ee-ot', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='nascar_038', name='Chet Marathon', say='chet MAIR-uh-thon', bucket='nascar', pace=0.64, aggr=0.60, risk=0.36, cons=0.77 },
    { key='nascar_039', name='Lyle Kenzenith', say='lyle KEN-zen-ith', bucket='nascar', pace=0.68, aggr=0.53, risk=0.30, cons=0.80 },
    { key='nascar_040', name='Randall Bushwhack', say='RAN-dul BUSH-wak', bucket='nascar', pace=0.67, aggr=0.60, risk=0.42, cons=0.75 },
    { key='nascar_041', name='Foster Starrett', say='FOSS-ter STAR-it', bucket='nascar', pace=0.67, aggr=0.53, risk=0.36, cons=0.80 },
    { key='nascar_042', name='Dwayne Backflipwards', say='dwayn BAK-flip-werdz', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='nascar_043', name='Cody Earnedmore Jr.', say='KOH-dee URND-mor JOO-nyur', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_044', name='Thaddeus Labonanza', say='THAD-ee-us lah-buh-NAN-zuh', bucket='nascar', pace=0.71, aggr=0.53, risk=0.42, cons=0.83 },
    { key='nascar_045', name='Holden Rugged', say='HOHL-dun RUG-id', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_046', name='Marvin Coolwicki', say='MAR-vin kool-WIK-ee', bucket='nascar', pace=0.68, aggr=0.53, risk=0.36, cons=0.75 },
    { key='nascar_047', name='Shelton Allisoar', say='SHEL-tun AL-i-sor', bucket='nascar', pace=0.66, aggr=0.68, risk=0.42, cons=0.72 },
    { key='nascar_048', name='Vance Rushmond', say='vanss RUSH-mund', bucket='nascar', pace=0.65, aggr=0.76, risk=0.48, cons=0.67 },
    { key='nascar_049', name='Bo Johnshine', say='boh JON-shyne', bucket='nascar', pace=0.69, aggr=0.76, risk=0.54, cons=0.72 },
    { key='nascar_050', name='Whit Jarrhero', say='wit JAR-hee-roh', bucket='nascar', pace=0.75, aggr=0.60, risk=0.36, cons=0.83 },
    { key='nascar_051', name='Comet Rockettson', say='KOM-it ROK-it-sun', bucket='nascar', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_052', name='Woodrow Turnpike', say='WOOD-roh TURN-pyke', bucket='nascar', pace=0.66, aggr=0.84, risk=0.60, cons=0.62 },
    { key='nascar_053', name='Ezra Plenty', say='EZ-ruh PLEN-tee', bucket='nascar', pace=0.76, aggr=0.53, risk=0.30, cons=0.86 },
    { key='nascar_054', name='Amos Tomahawk', say='AY-mus TOM-uh-hawk', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.78 },
    { key='nascar_055', name='Ollie Flockstar', say='OL-ee FLOK-star', bucket='nascar', pace=0.79, aggr=0.60, risk=0.42, cons=0.78 },
    { key='nascar_056', name='Hoss Breaker', say='hoss BRAY-ker', bucket='nascar', pace=0.73, aggr=0.60, risk=0.42, cons=0.78 },
    { key='nascar_057', name='Lonnie Isaacspeed', say='LON-ee EYE-zak-speed', bucket='nascar', pace=0.71, aggr=0.60, risk=0.42, cons=0.75 },
    { key='nascar_058', name='Lefty Bakespeed', say='LEF-tee BAYK-speed', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_059', name='Elmer Pardner', say='EL-mer PARD-ner', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='nascar_060', name='Truett Gallant', say='TROO-it GAL-unt', bucket='nascar', pace=0.63, aggr=0.60, risk=0.36, cons=0.77 },
    { key='nascar_061', name='Sylvester Irvantage', say='sil-VES-ter ur-VAN-tij', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='nascar_062', name='Clayton Bodyline', say='KLAY-tun BOD-ee-lyne', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='nascar_063', name='Coleman Merlin', say='KOHL-mun MUR-lin', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_064', name='Miles Blurton', say='mylz BLUR-tun', bucket='nascar', pace=0.63, aggr=0.53, risk=0.36, cons=0.77 },
    { key='nascar_065', name='Duane Labounty', say='dwayn luh-BOWN-tee', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='nascar_066', name='Hobart Newrocket', say='HOH-bart NEW-rok-it', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_067', name='Doyle Riffle', say='doyl RIF-ul', bucket='nascar', pace=0.63, aggr=0.68, risk=0.36, cons=0.77 },
    { key='nascar_068', name='Judd Kahnon', say='jud KAH-non', bucket='nascar', pace=0.63, aggr=0.53, risk=0.42, cons=0.72 },
    { key='nascar_069', name='Otis Shredder', say='OH-tiss SHRED-er', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='nascar_070', name='Orrin Wingtipp', say='OR-in WING-tip', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    -- Oval-Indy
    { key='f1_115', name='Milton Onward', say='MIL-tun ON-werd', bucket='f1', pace=0.81, aggr=0.46, risk=0.30, cons=0.78 },
    { key='f1_116', name='Harlan Johnrocket', say='HAR-lun JON-rok-it', bucket='f1', pace=0.78, aggr=0.60, risk=0.42, cons=0.75 },
    { key='f1_117', name='Hank Brawny', say='hank BRAW-nee', bucket='f1', pace=0.84, aggr=0.60, risk=0.42, cons=0.81 },
    { key='f1_118', name='Marcus Welldone', say='MAR-kus WEL-dun', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='f1_119', name='Gale Sneverquit', say='gayl SNEV-er-kwit', bucket='f1', pace=0.81, aggr=0.68, risk=0.48, cons=0.78 },
    { key='f1_120', name='Sonny Blazier', say='SON-ee BLAY-zee-er', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.80 },
    { key='f1_121', name='Ruud Lionendyke', say='rood LY-un-en-dyke', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='f1_122', name='Orville Shawstopper', say='OR-vil SHAW-stop-er', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='f1_123', name='Homer Arose', say='HOH-mer uh-ROHZ', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='f1_124', name='Walt Vroomovich', say='wawlt VROOM-oh-vich', bucket='f1', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    -- Oval-Dirt
    { key='nascar_071', name='Royce Kingser', say='royss KING-ser', bucket='nascar', pace=0.92, aggr=0.68, risk=0.42, cons=0.97 },
    { key='nascar_072', name='Odell Swiftdell', say='oh-DEL SWIFT-del', bucket='nascar', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='nascar_073', name='Garrett Smashatz', say='GAIR-it SMASH-atz', bucket='nascar', pace=0.92, aggr=0.60, risk=0.36, cons=0.97 },
    { key='nascar_074', name='Boone Kinsman', say='boon KINZ-mun', bucket='nascar', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    -- Cross-category appearances
    { key='kart_001', name='Pass Nearstappen', say='pass NEER-stuh-pen', bucket='kart', pace=1.00, aggr=0.76, risk=0.29, cons=0.93 },
    { key='kart_002', name='Aaron Sensei', say='AIR-un SEN-say', bucket='kart', pace=0.96, aggr=0.68, risk=0.56, cons=0.67 },
    { key='kart_003', name='Mike Zoomacher', say='myke ZOO-mah-ker', bucket='kart', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='kart_004', name='Bruisin Yamilton', say='BROO-zin yuh-MIL-tun', bucket='kart', pace=0.97, aggr=0.53, risk=0.23, cons=0.97 },
    { key='kart_005', name='Wambo Boris', say='WOM-boh BOR-iss', bucket='kart', pace=0.98, aggr=0.53, risk=0.20, cons=0.86 },
    { key='proto_037', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='proto', pace=0.90, aggr=0.60, risk=0.29, cons=0.87 },
    { key='proto_038', name='Nitro Krakenberg', say='NYE-troh KRAY-ken-berg', bucket='proto', pace=0.88, aggr=0.53, risk=0.30, cons=0.85 },
    { key='proto_039', name='Spark Webbest', say='spark web-BEST', bucket='proto', pace=0.92, aggr=0.68, risk=0.33, cons=0.78 },
    { key='proto_040', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='proto', pace=0.85, aggr=0.84, risk=0.60, cons=0.55 },
    { key='proto_041', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='proto', pace=0.80, aggr=0.46, risk=0.30, cons=0.83 },
    { key='proto_042', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='proto', pace=0.85, aggr=0.61, risk=0.28, cons=0.77 },
    { key='proto_043', name='Bravo Andread', say='BRAH-voh AN-dred', bucket='proto', pace=0.88, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gt_020', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='gt', pace=0.86, aggr=0.60, risk=0.29, cons=0.87 },
    { key='gt_021', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='gt', pace=0.84, aggr=0.84, risk=0.60, cons=0.55 },
    { key='gt_022', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='gt', pace=0.82, aggr=0.46, risk=0.30, cons=0.83 },
    { key='rally_036', name='Chilly Icekkonen', say='CHIL-ee ICE-koh-nen', bucket='rally', pace=0.58, aggr=0.60, risk=0.30, cons=0.83 },
    { key='rally_037', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='rally', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='touring_033', name='Hansel Struck', say='HAN-sul struk', bucket='touring', pace=0.88, aggr=0.84, risk=0.48, cons=0.70 },
    { key='touring_034', name='Luca Zanhardy', say='LOO-kuh zan-HAR-dee', bucket='touring', pace=0.78, aggr=0.76, risk=0.48, cons=0.78 },
    { key='f1_125', name='Rocky Slicks', say='ROCK-ee sliks', bucket='f1', pace=0.82, aggr=0.60, risk=0.42, cons=0.78 },
    { key='f1_126', name='Hansel Struck', say='HAN-sul struk', bucket='f1', pace=0.68, aggr=0.84, risk=0.48, cons=0.70 },

    -- Generic archetypes: always offered, used for randomize overflow. Labelled so nobody mistakes
    -- them for a real name.
    -- Three archetypes, always listed first: a beginner, a solid midfielder, a seasoned front-runner.
    { key='arch_rookie',     name='Rookie',     bucket='archetype', pace=0.30, aggr=0.50, risk=0.60, cons=0.50 },
    { key='arch_midfield',   name='Midfielder', bucket='archetype', pace=0.60, aggr=0.55, risk=0.35, cons=0.80 },
    { key='arch_veteran',    name='Veteran',    bucket='archetype', pace=0.85, aggr=0.55, risk=0.20, cons=0.95 },

    -- Chaos driver (owner 2026-09-28): not a person, not an archetype. Listed at the top of every class's picker with the
    -- archetypes; never picked by Randomize or name matching; never the pace anchor. wild=true lets racecraft's R.WILD layer
    -- relax his margins (R.WILD=false: the row's numbers only). Keep the field order key, name, say, bucket: the regexes in
    -- tools/harness.py and tools/apply_names.py depend on it.
    { key='wild_001', name='Wrecking Crew', say='RECK-ing crew', bucket='wild', pace=0.95, aggr=1.00, risk=1.00, cons=0.10, wild=true },
}

-- indexes
local BY_KEY, ARCHETYPES, WILD = {}, {}, {}
for _, d in ipairs(D.DRIVERS) do
    BY_KEY[d.key] = d
    if d.bucket == 'archetype' then ARCHETYPES[#ARCHETYPES + 1] = d elseif d.wild then WILD[#WILD + 1] = d end
end

-- D.RATING_V2 (setting ratingV2; owner 2026-09-29): every real driver is a pro. Each roster's pace is compressed into
-- V2_LO..V2_HI on a square-root curve that keeps the order (the weakest near V2_LO, a roster's solid middle at about a
-- Veteran, its best at V2_HI), the Veteran moves up to V2_VET, and pace maps to lap time against V2_REF (1.00: the best
-- name on the grid is the one at the ceiling) with V2_K % per 1.0 of rating (Rookie 0.30 stays +10 %). Off = 0.14.8.
D.RATING_V2 = false
D.V2_LO, D.V2_HI, D.V2_VET, D.V2_MID, D.V2_REF, D.V2_K = 0.86, 1.00, 0.93, 0.65, 1.00, 10 / 0.70
D.V2_VET_AGGR = 0.65
local V2 = {}
do
    local lo, hi = {}, {}
    for _, d in ipairs(D.DRIVERS) do
        if d.bucket ~= 'archetype' and not d.wild then
            lo[d.bucket] = math.min(lo[d.bucket] or 1, d.pace); hi[d.bucket] = math.max(hi[d.bucket] or 0, d.pace)
        end
    end
    for _, d in ipairs(D.DRIVERS) do
        local c = {}; for k, v in pairs(d) do c[k] = v end
        if d.key == 'arch_veteran' then c.pace = D.V2_VET; c.aggr = D.V2_VET_AGGR   -- (a Veteran races harder than a weak pro, e.g. Stroll 0.60)
        elseif d.key == 'arch_midfield' then c.pace = D.V2_MID
        elseif d.bucket ~= 'archetype' and not d.wild then
            local l, h = lo[d.bucket], hi[d.bucket]
            local n = (h and l and h > l) and clamp((d.pace - l) / (h - l), 0, 1) or 1
            c.pace = D.V2_LO + math.sqrt(n) * (D.V2_HI - D.V2_LO)
        end
        V2[d.key] = c
    end
end

function D.nameOf(key) local d = BY_KEY[key]; return d and d.name or key end

function D.rosterFor(classKey)
    local bucket = CLASS_BUCKET[classKey]
    local out = {}
    for _, d in ipairs(ARCHETYPES) do out[#out + 1] = d end     -- archetypes first, then the class roster
    for _, d in ipairs(WILD) do out[#out + 1] = d end           -- (the chaos driver sits with them, in every class)
    if bucket then
        for _, d in ipairs(D.DRIVERS) do if d.bucket == bucket then out[#out + 1] = d end end
    end
    return out
end

D.LEVEL_SLEW = 0.03   -- (0.15.1) AI level change per second at most for a moving car (0 = step at once, as before)
D.slewT = {}          -- per car: time of the last eased step
D.LOCKED = false      -- career events: profiles are off (the difficulty curve owns the field)

local assigned = {}
local baseLevel = {}
local lastApplied = {}   -- level last pushed per slot
-- the fastest pace rating among drivers currently on the grid -- the anchor everyone is spread below.
-- Recomputed lazily whenever the grid changes, so difficulty always tracks the best driver present.
local fieldMaxPace, paceDirty = 1.0, true
local lastSlot0AI = nil            -- slot 0 AI-controlled at the last anchor computation (nil = never computed)
local function recomputeFieldMaxPace()
    local m = 0
    -- slot 0 is skipped while a HUMAN drives it (a profile you assigned yourself shouldn't drag the AI field's pace
    -- anchor around) -- but when it's under AI control (the harness autopilot, Ctrl+C takeover) it IS part of the
    -- field: a star in slot 0 on a rookie grid was anchoring the field to the rookies, so everyone ran at 100 and the
    -- star had no pace advantage at all (Monza 2026-09-16: 18 cars at level 100, the star gained 2 places in 6 laps)
    local slot0AI = false
    pcall(function() local c = ac.getCar(0); slot0AI = c ~= nil and c.isAIControlled == true end)
    for i, k in pairs(assigned) do
        if i ~= 0 or slot0AI then
            local d = BY_KEY[k]
            if d and d.pace and d.pace > m and not d.wild then m = d.pace end   -- (the chaos driver is never the anchor)
        end
    end
    fieldMaxPace = (m > 0) and m or 1.0
    paceDirty = false
end

-- The name AC shows for a slot (leaderboard, results) follows the profile: pick a driver and the AI is
-- renamed to it; clear the profile and AC's original name comes back. Slot 0 (the player) is never renamed.
local origName = {}
local function applyName(i)
    pcall(function()
        -- slot 0 keeps the human's own name -- unless it is AI-driven (harness autopilot), when the profile's public
        -- name must show like any other car's (a slot-0 star showed the owner's AC name in the feed, 2026-09-16)
        if i == 0 then local c0 = ac.getCar(0); if not (c0 and c0.isAIControlled) then return end end
        if origName[i] == nil then origName[i] = ac.getDriverName(i) or '' end
        local key = assigned[i]
        local d = key and BY_KEY[key] or nil
        -- archetypes are types, not people: the car keeps AC's own driver name (a grid of 17 "Rookie"s otherwise)
        local name = (d and d.bucket ~= 'archetype') and d.name or origName[i]
        if name and #name > 0 then physics.setAIDriverName(i, name) end
    end)
end
function D.setProfile(i, key)
    if D.LOCKED then return end
    if key == nil or key == '' then assigned[i] = nil else assigned[i] = key end
    paceDirty = true
    applyName(i)
end
function D.profileOf(i) return assigned[i] end

-- Match AC's own driver names to the roster (Content Manager grids often carry real names): a slot whose
-- in-game name is a known driver gets that profile automatically. Unknown/random names stay unassigned.
local matched = false
-- D.AUTO_MATCH (owner 2026-09-29: off): a car whose AC driver name equals a roster name (Verve's own display names) got
-- that profile automatically. A profile now applies only when the player picks one (true = the old behaviour).
D.AUTO_MATCH = false
function D.autoMatch()
    if matched or not D.AUTO_MATCH then return end
    matched = true
    pcall(function()
        local sim = ac.getSim(); if not sim then return end
        local byName = {}
        for _, d in ipairs(D.DRIVERS) do if not d.wild then byName[d.name:lower()] = d end end   -- (never the chaos driver)
        for i = 1, sim.carsCount - 1 do
            local car = ac.getCar(i)
            if car and car.isAIControlled and not assigned[i] then
                local nm = (ac.getDriverName(i) or ''):lower():gsub('^%s+', ''):gsub('%s+$', '')
                local d = byName[nm]
                if d then assigned[i] = d.key; paceDirty = true end
            end
        end
    end)
end
function D.statsOf(i)
    local k = assigned[i]
    if not k then return nil end
    if D.RATING_V2 then return V2[k] or BY_KEY[k] end
    return BY_KEY[k]
end
D.WILD_ON = true   -- mirrored from Racecraft.WILD each frame (Verve.lua): one master switch for the chaos driver in every module
function D.isWild(i) local k = assigned[i]; local d = k and BY_KEY[k]; return d ~= nil and d.wild == true end   -- the chaos driver (wild row)
function D.anyAssigned() for _ in pairs(assigned) do return true end return false end
function D.clearAll()
    for i in pairs(assigned) do assigned[i] = nil; applyName(i) end
    assigned = {}; paceDirty = true
end
-- (declared before D.reset: when it sat further down, D.reset's `named0 = false` wrote a global and slot 0's public name
-- was never re-applied in a new session; found 2026-09-28)
local named0 = false               -- slot 0's public name applied (needs the car to be AI-driven, which lags the autopilot switch by a frame)
function D.reset(keepPicks)
    -- keepPicks: the same weekend moved to its next session (practice -> qualifying -> race). The picks and AC's
    -- original names stay; the levels are re-read (AC re-creates them per session) and the names re-applied.
    if not keepPicks then assigned = {}; origName = {}; matched = false end
    baseLevel = {}; lastApplied = {}; D.slewT = {}; fieldMaxPace = 1.0; paceDirty = true; lastSlot0AI = nil; named0 = false
    if keepPicks then for i in pairs(assigned) do applyName(i) end end
end

-- fixed grid ({all=key, slots={[i]=key}}) -- harness tests such as "a Rookie field with one star at the back"
function D.applyFixed(spec)
    if D.LOCKED or type(spec) ~= 'table' then return end
    local sim = ac.getSim(); if not sim then return end
    for i = 0, sim.carsCount - 1 do
        local key = (spec.slots and spec.slots[i]) or spec.all
        if key and key ~= '' and BY_KEY[key] then assigned[i] = key; applyName(i) end
    end
    paceDirty = true
end

-- one archetype for every AI car (the Drivers panel's quick fill: all Rookie / Midfielder / Veteran). Slot 0 is left to the
-- player, as with Randomize.
function D.fillGrid(key)
    if D.LOCKED or not BY_KEY[key] then return end
    pcall(function()
        local sim = ac.getSim(); if not sim then return end
        for i = 1, sim.carsCount - 1 do
            local car = ac.getCar(i)
            if car and car.isAIControlled then assigned[i] = key; applyName(i) end
        end
        paceDirty = true
    end)
end

-- how many real-name profiles vs archetypes (vs chaos drivers) are on the grid (telemetry)
function D.counts()
    local real, arch, wild = 0, 0, 0
    for _, k in pairs(assigned) do local d = BY_KEY[k]; if d then if d.bucket == 'archetype' then arch = arch + 1 elseif d.wild then wild = wild + 1 else real = real + 1 end end end
    return real, arch, wild
end

function D.randomizeGrid()
    if D.LOCKED then return end
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
                if pick then assigned[i] = pick.key; applyName(i) end
            end
        end
        paceDirty = true
    end)
end

-- `base` = the level the difficulty module wants for this car (configured / career curve); nil = AC's own.
-- A driver profile spreads the field BELOW that base by pace rating (the fastest profile runs at base).
function D.applyPace(i, base)
    pcall(function()
        if i == 0 and not named0 and assigned[0] then named0 = true; applyName(0) end
        local st = D.statsOf(i)
        local car = ac.getCar(i); if not car then return end
        if base == nil then
            if baseLevel[i] == nil then
                local lvl = car.aiLevel
                baseLevel[i] = (type(lvl) == 'number' and lvl > 0) and lvl or 1.0
            end
            base = baseLevel[i]
        end
        local lvl = base
        if st then
            -- the anchor depends on whether slot 0 is AI-driven (see recomputeFieldMaxPace); that flips when the
            -- harness autopilot arms during the countdown, so re-anchor when it changes
            local s0 = false
            pcall(function() local c0 = ac.getCar(0); s0 = c0 ~= nil and c0.isAIControlled == true end)
            if s0 ~= lastSlot0AI then lastSlot0AI = s0; paceDirty = true end
            if paceDirty then recomputeFieldMaxPace() end
            -- the fastest profile on the grid runs at `base`; the rest are spread BELOW it by pace rating,
            -- in lap-time terms (SPREAD_PCT per 1.0 of rating), converted to a level through the measured curve
            local basePct = Difficulty.levelToPct(base)
            if st.wild and not D.PACE_ABS then lvl = base    -- the chaos driver runs at the slider level (he is never the anchor)
            elseif D.PACE_ABS and not D.LOCKED then   -- (a career event keeps its difficulty curve: an auto-matched name must not override it)
                local ref, k = D.PACE_REF, D.PACE_K
                if D.RATING_V2 then ref, k = D.V2_REF, D.V2_K end
                lvl = Difficulty.levelForPct(i, math.max(0, (ref - st.pace) * k))   -- (D.PACE_ABS) the profile's own pace
            else
                lvl = math.min(base, Difficulty.pctToLevel(basePct + (fieldMaxPace - st.pace) * SPREAD_PCT))
            end
        end
        lvl = math.floor(lvl * 1000 + 0.5) / 1000
        -- (0.15.1) a MOVING car eases into a new level (D.LEVEL_SLEW per second, in 0.25 s steps): Clear drivers mid-race stepped
        -- a Veteran 0.93 -> 1.00 in one frame braking for the Parabolica - later brake point, off (mc15, 30 Sep). On the grid, in the
        -- pits or on the first write the level is set at once.
        local prev = lastApplied[i]
        if prev and D.LEVEL_SLEW > 0 and math.abs(lvl - prev) > 0.0015 and (car.speedKmh or 0) > 30 and not car.isInPitlane then
            local now = os.clock()
            local t0 = D.slewT[i]
            if not t0 then D.slewT[i] = now; return end
            if now - t0 < 0.25 then return end
            D.slewT[i] = now
            local step = D.LEVEL_SLEW * math.min(now - t0, 1.0)
            if math.abs(lvl - prev) > step then lvl = math.floor((prev + (lvl > prev and step or -step)) * 1000 + 0.5) / 1000 end
        else
            D.slewT[i] = nil
        end
        if lastApplied[i] ~= lvl then physics.setAILevel(i, lvl); lastApplied[i] = lvl end   -- only on change (18 cars x 60 Hz otherwise)
    end)
end

function D.appliedLevel(i) return lastApplied[i] end
-- (0.15.1) Verve switched off: the launcher's level back (lvl nil = leave it), and forget what Verve wrote, so that switching Verve
-- back on writes the profile level again (applyPace only writes on a change)
function D.handBack(i, lvl)
    if lvl then pcall(physics.setAILevel, i, lvl); lastApplied[i] = lvl end   -- (unknown launcher level: the car keeps what it has, and
end   -- switched back on mid-race a moving car eases from there to its profile: D.LEVEL_SLEW)   -- what Verve last wrote (the conflict watchdog reads it back)

-- A car's pace on the profile scale (Rookie 0.30 .. 0.90 = expert, the paceAbs reference): its profile's, else read back from the level
-- Verve applied, through its class curve (the inverse of paceAbs: level 100 -> 0.90, slider 90 -> 0.60, slider 80 -> 0.30; a career
-- band or a spread grid reads as what the car actually runs at). One scale for the manoeuvre tier (strategy S.TIER_MODE 1) and the
-- visible-mistake rate (human H.MISTAKE_V2). Cached 2 s per car.
D.paceCache = {}
function D.paceOf(i)
    local now = os.clock()
    local c = D.paceCache[i]
    if c and now - c.t < 2.0 then return c.p end
    local st = D.statsOf(i)
    local p = st and st.pace
    if type(p) ~= 'number' then
        local lvl = lastApplied[i]
        if type(lvl) ~= 'number' then pcall(function() lvl = ac.getCar(i).aiLevel end) end
        if type(lvl) ~= 'number' or lvl <= 0 then lvl = 1 end
        p = D.PACE_REF - Difficulty.pctOf(i, lvl) / D.PACE_K
    end
    p = clamp(p, 0, 1)
    if not c then c = {}; D.paceCache[i] = c end
    c.p, c.t = p, now
    return p
end

return D
