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
local D = {}
local function clamp(x, a, b) if x < a then return a elseif x > b then return b end return x end
-- pace spreads AI level DOWN from the difficulty. The FASTEST driver actually on the grid runs at the
-- slider level, and everyone else is spaced below by how far their pace rating trails his -- so the
-- field genuinely strings out instead of bunching. Widened (0.16 -> 0.32) because the old value barely
-- separated the field: a mid-pack driver ended up only a few hundredths of an AI level off the ace.
local SPREAD_PCT = 8.0     -- lap-time % between a 1.0-rated driver and a 0.0-rated one (a Rookie at 0.30 vs a 0.96 star ~ 5.3%; real F1 fields spread 2-3%, club grids 5-10%)

-- Detected class -> roster bucket. Classes not listed (road) offer only the archetypes.
local CLASS_BUCKET = {
    formula = 'f1', formula_jr = 'f1', kart = 'kart',
    prototype = 'proto', hypercar = 'proto', gt = 'gt',
    touring = 'touring', vintage = 'vintage', rally = 'rally', drift = 'drift', nascar = 'nascar',
}
D.DRIVERS = {
    -- F1-modern
    { key='max_verstappen', name='Pass Nearstappen', say='pass NEER-stuh-pen', bucket='f1', pace=0.87, aggr=0.76, risk=0.29, cons=0.93 },
    { key='lewis_hamilton', name='Bruisin Yamilton', say='BROO-zin yuh-MIL-tun', bucket='f1', pace=0.96, aggr=0.53, risk=0.23, cons=0.97 },
    { key='lando_norris', name='Wambo Boris', say='WOM-boh BOR-iss', bucket='f1', pace=0.71, aggr=0.53, risk=0.20, cons=0.86 },
    { key='charles_leclerc', name='Charlie LeKlay', say='CHAR-lee luh-KLAY', bucket='f1', pace=0.71, aggr=0.60, risk=0.46, cons=0.66 },
    { key='oscar_piastri', name='Lester Mystery', say='LES-ter MISS-tuh-ree', bucket='f1', pace=0.69, aggr=0.46, risk=0.16, cons=0.91 },
    { key='george_russell', name='Jim Bustle', say='jim BUSS-ul', bucket='f1', pace=0.66, aggr=0.61, risk=0.28, cons=0.82 },
    { key='fernando_alonso', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='f1', pace=0.73, aggr=0.60, risk=0.29, cons=0.87 },
    { key='kimi_antonelli', name='Timmy Slamonelli', say='TIM-ee slam-oh-NEL-ee', bucket='f1', pace=0.70, aggr=0.68, risk=0.56, cons=0.62 },
    { key='carlos_sainz_jr', name='Pavlov Rains', say='PAV-lov raynz', bucket='f1', pace=0.64, aggr=0.53, risk=0.24, cons=0.85 },
    { key='isack_hadjar', name='Knapsack Radbar', say='NAP-sak RAD-bar', bucket='f1', pace=0.63, aggr=0.68, risk=0.41, cons=0.71 },
    { key='alexander_albon', name='Callum Allbold', say='KAL-um AWL-bohld', bucket='f1', pace=0.63, aggr=0.46, risk=0.19, cons=0.84 },
    { key='pierre_gasly', name='Clear Blastly', say='kleer BLAST-lee', bucket='f1', pace=0.63, aggr=0.60, risk=0.29, cons=0.80 },
    { key='esteban_ocon', name='Stephen Rockon', say='STEE-vun ROCK-on', bucket='f1', pace=0.63, aggr=0.68, risk=0.32, cons=0.78 },
    { key='nico_hulkenberg', name='Nitro Krakenberg', say='NYE-troh KRAY-ken-berg', bucket='f1', pace=0.63, aggr=0.53, risk=0.30, cons=0.85 },
    { key='lance_stroll', name='Chance Patrol', say='chanss puh-TROHL', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='oliver_bearman', name='Grizzly Dareman', say='GRIZ-lee DAIR-man', bucket='f1', pace=0.62, aggr=0.68, risk=0.33, cons=0.77 },
    { key='sergio_perez', name='Gecko Presidente', say='GEK-oh prez-i-DEN-tay', bucket='f1', pace=0.64, aggr=0.60, risk=0.38, cons=0.73 },
    { key='valtteri_bottas', name='Valiant Bossman', say='VAL-yunt BOSS-man', bucket='f1', pace=0.67, aggr=0.53, risk=0.14, cons=0.88 },
    { key='liam_lawson', name='Beam Clawson', say='beem CLAW-sun', bucket='f1', pace=0.62, aggr=0.76, risk=0.36, cons=0.75 },
    { key='gabriel_bortoleto', name='Gavin Thunderleto', say='GAV-in thun-der-LET-oh', bucket='f1', pace=0.62, aggr=0.53, risk=0.43, cons=0.69 },
    { key='franco_colapinto', name='Bronco Cannonpinto', say='BRONG-koh kan-un-PIN-toh', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='arvid_lindblad', name='Avid Windblast', say='AV-id WIND-blast', bucket='f1', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    -- F1-classic
    { key='ayrton_senna', name='Aaron Sensei', say='AIR-un SEN-say', bucket='f1', pace=0.88, aggr=0.68, risk=0.56, cons=0.67 },
    { key='alain_prost', name='Aplomb Frost', say='uh-PLOM frost', bucket='f1', pace=0.86, aggr=0.53, risk=0.18, cons=0.97 },
    { key='michael_schumacher', name='Mike Zoomacher', say='myke ZOO-mah-ker', bucket='f1', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='niki_lauda', name='Nicholas Louder', say='NIK-uh-lus LOW-der', bucket='f1', pace=0.78, aggr=0.46, risk=0.21, cons=0.86 },
    { key='james_hunt', name='Blaze Stunt', say='blayz stunt', bucket='f1', pace=0.71, aggr=0.76, risk=0.85, cons=0.40 },
    { key='nigel_mansell', name='Regal Muscle', say='REE-gul MUSS-ul', bucket='f1', pace=0.73, aggr=0.84, risk=0.49, cons=0.67 },
    { key='nelson_piquet', name='Wesley Peakwell', say='WEZ-lee PEEK-wel', bucket='f1', pace=0.77, aggr=0.60, risk=0.38, cons=0.82 },
    { key='mika_hakkinen', name='Mecha Rockinen', say='MEK-uh ROCK-i-nen', bucket='f1', pace=0.77, aggr=0.53, risk=0.37, cons=0.80 },
    { key='kimi_raikkonen', name='Chilly Icekkonen', say='CHIL-ee ICE-koh-nen', bucket='f1', pace=0.68, aggr=0.60, risk=0.30, cons=0.83 },
    { key='sebastian_vettel', name='Bombastian Medal', say='bom-BAST-ee-un MED-ul', bucket='f1', pace=0.83, aggr=0.60, risk=0.34, cons=0.88 },
    { key='nico_rosberg', name='Neato Bossberg', say='NEE-toh BOSS-berg', bucket='f1', pace=0.70, aggr=0.46, risk=0.20, cons=0.92 },
    { key='jenson_button', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='f1', pace=0.66, aggr=0.46, risk=0.30, cons=0.83 },
    { key='damon_hill', name='Diamond Thrill', say='DYE-mund thril', bucket='f1', pace=0.74, aggr=0.60, risk=0.43, cons=0.72 },
    { key='gilles_villeneuve', name='Thrills Ironnerve', say='thrilz EYE-urn-nerv', bucket='f1', pace=0.65, aggr=0.76, risk=0.85, cons=0.40 },
    { key='juan_pablo_montoya', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='f1', pace=0.67, aggr=0.84, risk=0.60, cons=0.55 },
    { key='daniel_ricciardo', name='Badger Rippiardo', say='BAJ-er rip-ee-AR-doh', bucket='f1', pace=0.62, aggr=0.84, risk=0.27, cons=0.82 },
    { key='jean_alesi', name='Roland Amazi', say='ROH-lund uh-MAH-zee', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='gerhard_berger', name='Gunnar Surger', say='GUN-ar SUR-jer', bucket='f1', pace=0.65, aggr=0.61, risk=0.40, cons=0.71 },
    { key='david_coulthard', name='Dan Coolhard', say='dan KOOL-hard', bucket='f1', pace=0.65, aggr=0.46, risk=0.33, cons=0.82 },
    { key='mark_webber', name='Spark Webbest', say='spark web-BEST', bucket='f1', pace=0.64, aggr=0.68, risk=0.33, cons=0.78 },
    { key='felipe_massa', name='Feisty Maestro', say='FYE-stee MY-stroh', bucket='f1', pace=0.64, aggr=0.68, risk=0.32, cons=0.79 },
    { key='jacques_villeneuve', name='Jack Villenoove', say='jak VEE-luh-noov', bucket='f1', pace=0.68, aggr=0.84, risk=0.45, cons=0.75 },
    { key='robert_kubica', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='f1', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='ronnie_peterson', name='Rowdy Powerson', say='ROW-dee POW-er-sun', bucket='f1', pace=0.66, aggr=0.68, risk=0.50, cons=0.63 },
    { key='mario_andretti', name='Bravo Andread', say='BRAH-voh AN-dred', bucket='f1', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='jody_scheckter', name='Jolly Checkered', say='JOL-ee CHEK-erd', bucket='f1', pace=0.69, aggr=0.61, risk=0.46, cons=0.64 },
    -- Vintage
    { key='juan_manuel_fangio', name='Juan Marvel Tangio', say='wahn MAR-vul TAN-jee-oh', bucket='vintage', pace=0.98, aggr=0.53, risk=0.22, cons=0.96 },
    { key='stirling_moss', name='Stanley Boss', say='STAN-lee boss', bucket='vintage', pace=0.72, aggr=0.68, risk=0.44, cons=0.73 },
    { key='jim_clark', name='Slim Spark', say='slim spark', bucket='vintage', pace=0.85, aggr=0.53, risk=0.23, cons=0.92 },
    { key='jackie_stewart', name='Jaunty Sureheart', say='JAWN-tee SHOOR-hart', bucket='vintage', pace=0.80, aggr=0.46, risk=0.17, cons=0.95 },
    { key='graham_hill', name='Gordon Summit', say='GOR-dun SUM-it', bucket='vintage', pace=0.71, aggr=0.60, risk=0.36, cons=0.81 },
    { key='jack_brabham', name='Mack Bravado', say='mak bruh-VAH-doh', bucket='vintage', pace=0.75, aggr=0.68, risk=0.30, cons=0.89 },
    { key='alberto_ascari', name='Vincenzo Acestar', say='vin-CHEN-zoh ACE-star', bucket='vintage', pace=0.84, aggr=0.53, risk=0.28, cons=0.82 },
    { key='jochen_rindt', name='Rocken Sprint', say='ROCK-en sprint', bucket='vintage', pace=0.70, aggr=0.68, risk=0.50, cons=0.66 },
    { key='john_surtees', name='Don Surtwos', say='don SUR-tooz', bucket='vintage', pace=0.67, aggr=0.60, risk=0.32, cons=0.81 },
    { key='dan_gurney', name='Van Journey', say='van JUR-nee', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.77 },
    { key='phil_hill', name='Will Skill', say='wil skil', bucket='vintage', pace=0.69, aggr=0.46, risk=0.28, cons=0.80 },
    { key='mike_hawthorn', name='Ike Hawkstorm', say='ike HAWK-storm', bucket='vintage', pace=0.69, aggr=0.69, risk=0.41, cons=0.78 },
    { key='denny_hulme', name='Benny Helm', say='BEN-ee helm', bucket='vintage', pace=0.68, aggr=0.53, risk=0.27, cons=0.95 },
    { key='bruce_mclaren', name='Deuce McDaring', say='dooss mik-DAIR-ing', bucket='vintage', pace=0.64, aggr=0.53, risk=0.22, cons=0.86 },
    { key='pedro_rodriguez', name='Rocco Raindriguez', say='ROCK-oh rayn-DREE-gez', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.70 },
    { key='ken_miles', name='Glen Smiles', say='glen smylz', bucket='vintage', pace=0.62, aggr=0.76, risk=0.42, cons=0.72 },
    -- Prototype
    { key='tom_kristensen', name='Duke Crispensen', say='dook KRISP-en-sen', bucket='proto', pace=0.92, aggr=0.60, risk=0.36, cons=0.80 },
    { key='jacky_ickx', name='Rocky Slicks', say='ROCK-ee sliks', bucket='proto', pace=0.91, aggr=0.60, risk=0.42, cons=0.78 },
    { key='derek_bell', name='Fenwick Excel', say='FEN-wik ek-SEL', bucket='proto', pace=0.86, aggr=0.53, risk=0.36, cons=0.78 },
    { key='hans_joachim_stuck', name='Hansel Struck', say='HAN-sul struk', bucket='proto', pace=0.81, aggr=0.84, risk=0.48, cons=0.70 },
    { key='henri_pescarolo', name='Hardy Persevarolo', say='HAR-dee per-suh-vuh-ROH-loh', bucket='proto', pace=0.78, aggr=0.53, risk=0.42, cons=0.77 },
    { key='allan_mcnish', name='Dalton McFinish', say='DAWL-tun mik-FIN-ish', bucket='proto', pace=0.92, aggr=0.68, risk=0.42, cons=0.84 },
    { key='rinaldo_capello', name='Orlando Capablo', say='or-LAN-doh kuh-PAH-bloh', bucket='proto', pace=0.86, aggr=0.39, risk=0.30, cons=0.93 },
    { key='andre_lotterer', name='Duncan Lottawin', say='DUNG-kun LOT-uh-win', bucket='proto', pace=0.86, aggr=0.60, risk=0.42, cons=0.78 },
    { key='marcel_fassler', name='Wendel Fastler', say='WEN-dul FAST-ler', bucket='proto', pace=0.84, aggr=0.53, risk=0.30, cons=0.85 },
    { key='benoit_treluyer', name='Gaston Truegrit', say='gas-TOHN TROO-grit', bucket='proto', pace=0.83, aggr=0.53, risk=0.42, cons=0.80 },
    { key='sebastien_buemi', name='Bastion Boomi', say='BAS-chun BOO-mee', bucket='proto', pace=0.95, aggr=0.46, risk=0.30, cons=0.89 },
    { key='brendon_hartley', name='Weston Smartley', say='WES-tun SMART-lee', bucket='proto', pace=0.95, aggr=0.53, risk=0.36, cons=0.89 },
    { key='kazuki_nakajima', name='Kabuki Nakasteady', say='kuh-BOO-kee nah-kuh-STED-ee', bucket='proto', pace=0.88, aggr=0.53, risk=0.42, cons=0.80 },
    { key='kamui_kobayashi', name='Kapow Kobayaboss', say='kuh-POW koh-bye-uh-BOSS', bucket='proto', pace=0.87, aggr=0.84, risk=0.42, cons=0.78 },
    { key='mike_conway', name='Bolt Candoway', say='bohlt KAN-doo-way', bucket='proto', pace=0.87, aggr=0.53, risk=0.36, cons=0.83 },
    { key='timo_bernhard', name='Primo Blazenhard', say='PREE-moh BLAY-zen-hard', bucket='proto', pace=0.84, aggr=0.53, risk=0.36, cons=0.83 },
    { key='romain_dumas', name='Baptiste Climbas', say='bap-TEEST KLYME-buss', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='neel_jani', name='Zeno Genie', say='ZEE-noh JEE-nee', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.75 },
    { key='alessandro_pier_guidi', name='Salvatore Speedy', say='sal-vuh-TOR-ay SPEE-dee', bucket='proto', pace=0.88, aggr=0.84, risk=0.42, cons=0.84 },
    { key='james_calado', name='Dexter Calmando', say='DEK-ster kal-MAN-doh', bucket='proto', pace=0.88, aggr=0.60, risk=0.30, cons=0.94 },
    { key='antonio_giovinazzi', name='Giorgio Giovinjazzy', say='JOR-joh joh-vin-JAZ-ee', bucket='proto', pace=0.84, aggr=0.60, risk=0.42, cons=0.75 },
    { key='antonio_fuoco', name='Leonardo Fuego', say='lay-oh-NAR-doh FWAY-goh', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.72 },
    -- GT
    { key='kevin_estre', name='Tobin Extra', say='TOH-bin EK-struh', bucket='gt', pace=0.86, aggr=0.76, risk=0.48, cons=0.78 },
    { key='laurens_vanthoor', name='Bruno Vanthunder', say='BROO-noh van-THUN-der', bucket='gt', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='raffaele_marciello', name='Fabrizio Marvelo', say='fab-REET-see-oh mar-VEL-oh', bucket='gt', pace=0.79, aggr=0.60, risk=0.42, cons=0.72 },
    { key='maro_engel', name='Otto Angel', say='OT-oh AYN-jul', bucket='gt', pace=0.74, aggr=0.60, risk=0.36, cons=0.77 },
    { key='edoardo_mortara', name='Leandro Macautara', say='lee-AN-droh mah-kow-TAR-uh', bucket='gt', pace=0.74, aggr=0.53, risk=0.36, cons=0.72 },
    { key='nicki_thiim', name='Zippy Triumph', say='ZIP-ee TRY-umf', bucket='gt', pace=0.81, aggr=0.76, risk=0.48, cons=0.73 },
    { key='marco_sorensen', name='Kasper Soaringsen', say='KAS-per SOR-ing-sen', bucket='gt', pace=0.78, aggr=0.46, risk=0.30, cons=0.85 },
    { key='richard_lietz', name='Bennett Leadz', say='BEN-it leedz', bucket='gt', pace=0.74, aggr=0.46, risk=0.36, cons=0.77 },
    { key='jan_magnussen', name='Soren Magnifussen', say='SOR-en mag-ni-FUSS-en', bucket='gt', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    { key='oliver_gavin', name='Rowan Gavel', say='ROH-un GAV-ul', bucket='gt', pace=0.74, aggr=0.46, risk=0.30, cons=0.82 },
    { key='antonio_garcia', name='Antone Guardia', say='an-TOHN GWAR-dee-uh', bucket='gt', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='nicky_catsburg', name='Wade Nightsburg', say='wayd NITES-berg', bucket='gt', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='valentino_rossi', name='Doctor Bossi', say='DOK-ter BOSS-ee', bucket='gt', pace=0.68, aggr=0.60, risk=0.42, cons=0.72 },
    { key='sheldon_van_der_linde', name='Shelby van der Laser', say='SHEL-bee van der LAY-zer', bucket='gt', pace=0.78, aggr=0.60, risk=0.36, cons=0.80 },
    { key='kelvin_van_der_linde', name='Kelton van der Launch', say='KEL-tun van der LAWNCH', bucket='gt', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='jules_gounon', name='Remy Gonnawin', say='REM-ee GON-uh-win', bucket='gt', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='mirko_bortolotti', name='Enzo Winsalotti', say='EN-zoh win-zuh-LOT-ee', bucket='gt', pace=0.74, aggr=0.61, risk=0.42, cons=0.72 },
    { key='maxime_martin', name='Thibault Smartin', say='tee-BOH SMAR-tin', bucket='gt', pace=0.74, aggr=0.53, risk=0.42, cons=0.72 },
    { key='dries_vanthoor', name='Breeze Vandoor', say='breez van-DOOR', bucket='gt', pace=0.68, aggr=0.68, risk=0.42, cons=0.72 },
    -- Touring
    { key='bernd_schneider', name='Dietmar Shineider', say='DEET-mar SHYNE-der', bucket='touring', pace=0.92, aggr=0.61, risk=0.36, cons=0.87 },
    { key='klaus_ludwig', name='Rolf Loudking', say='rolf LOWD-king', bucket='touring', pace=0.84, aggr=0.53, risk=0.42, cons=0.81 },
    { key='mattias_ekstrom', name='Sven Eckstreme', say='sven ek-STREEM', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='rene_rast', name='Dominic Fast', say='DOM-i-nik fast', bucket='touring', pace=0.84, aggr=0.53, risk=0.30, cons=0.91 },
    { key='peter_brock', name='Dieter Brockstar', say='DEE-ter BROCK-star', bucket='touring', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='craig_lowndes', name='Blaine Loudness', say='blayn LOWD-ness', bucket='touring', pace=0.84, aggr=0.84, risk=0.48, cons=0.76 },
    { key='jamie_whincup', name='Tucker Winstreak', say='TUK-er WIN-streek', bucket='touring', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='shane_van_gisbergen', name='Bodie van Glidesbergen', say='BOH-dee van GLIDES-ber-gen', bucket='touring', pace=0.90, aggr=0.68, risk=0.42, cons=0.81 },
    { key='colin_turkington', name='Dermot Closington', say='DUR-mut KLOHZ-ing-tun', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.89 },
    { key='jason_plato', name='Mason Playmaker', say='MAY-sun PLAY-may-ker', bucket='touring', pace=0.81, aggr=0.84, risk=0.42, cons=0.78 },
    { key='matt_neal', name='Mack Steele', say='mak steel', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='ash_sutton', name='Dash Stunton', say='dash STUN-tun', bucket='touring', pace=0.93, aggr=0.76, risk=0.42, cons=0.84 },
    { key='andy_priaulx', name='Rory Prizeluxe', say='ROR-ee PRYZE-luks', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='yvan_muller', name='Etienne Smoothler', say='et-YEN SMOOTH-ler', bucket='touring', pace=0.92, aggr=0.61, risk=0.42, cons=0.87 },
    { key='gabriele_tarquini', name='Vittorio Tarquickni', say='vi-TOR-ee-oh tar-KWIK-nee', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='jose_maria_lopez', name='Emilio Lopedal', say='eh-MEEL-ee-oh loh-PED-ul', bucket='touring', pace=0.97, aggr=0.60, risk=0.42, cons=0.87 },
    { key='alain_menu', name='Gaspard Mainmenu', say='gas-PAR MAYN-men-yoo', bucket='touring', pace=0.81, aggr=0.46, risk=0.36, cons=0.78 },
    -- Rally
    { key='sebastien_loeb', name='Thierry Globe', say='tee-AIR-ee glohb', bucket='rally', pace=0.96, aggr=0.46, risk=0.17, cons=0.97 },
    { key='sebastien_ogier', name='Julien Ohyeah', say='ZHOO-lee-en oh-YAY', bucket='rally', pace=0.93, aggr=0.60, risk=0.24, cons=0.97 },
    { key='tommi_makinen', name='Mikko Makewinnen', say='MIK-oh MAKE-win-en', bucket='rally', pace=0.77, aggr=0.84, risk=0.61, cons=0.70 },
    { key='colin_mcrae', name='Angus McBrave', say='ANG-gus mik-BRAYV', bucket='rally', pace=0.69, aggr=0.76, risk=0.85, cons=0.40 },
    { key='richard_burns', name='Rupert Turns', say='ROO-pert turnz', bucket='rally', pace=0.69, aggr=0.46, risk=0.29, cons=0.84 },
    { key='carlos_sainz_sr', name='Carlito Reigns Sr.', say='kar-LEE-toh raynz SEE-nyur', bucket='rally', pace=0.72, aggr=0.61, risk=0.32, cons=0.84 },
    { key='juha_kankkunen', name='Eero Kankkoolen', say='AIR-oh kan-KOO-len', bucket='rally', pace=0.77, aggr=0.46, risk=0.16, cons=0.97 },
    { key='marcus_gronholm', name='Teemu Groundholm', say='TAY-moo GROWND-holm', bucket='rally', pace=0.73, aggr=0.68, risk=0.50, cons=0.74 },
    { key='petter_solberg', name='Better Showberg', say='BET-er SHOH-berg', bucket='rally', pace=0.67, aggr=0.76, risk=0.58, cons=0.59 },
    { key='walter_rohrl', name='Wolfgang Roarl', say='WOOLF-gang RORL', bucket='rally', pace=0.73, aggr=0.46, risk=0.34, cons=0.78 },
    { key='hannu_mikkola', name='Ilkka Mikkosteady', say='ILK-uh mik-oh-STED-ee', bucket='rally', pace=0.69, aggr=0.53, risk=0.43, cons=0.77 },
    { key='michele_mouton', name='Colette Mountain', say='koh-LET MOWN-tin', bucket='rally', pace=0.65, aggr=0.68, risk=0.55, cons=0.64 },
    { key='ari_vatanen', name='Osmo Flatoutanen', say='OZ-moh flat-OW-tuh-nen', bucket='rally', pace=0.68, aggr=0.76, risk=0.81, cons=0.44 },
    { key='henri_toivonen', name='Lasse Toivroomen', say='LASS-uh toy-VROO-men', bucket='rally', pace=0.68, aggr=0.60, risk=0.85, cons=0.40 },
    { key='kalle_rovanpera', name='Onni Rovanperfect', say='ON-ee roh-van-PUR-fekt', bucket='rally', pace=0.76, aggr=0.68, risk=0.47, cons=0.76 },
    { key='ott_tanak', name='Rein Attanak', say='rayn uh-TAN-ak', bucket='rally', pace=0.69, aggr=0.68, risk=0.51, cons=0.65 },
    { key='thierry_neuville', name='Damien Nailville', say='DAY-mee-un NAYL-vil', bucket='rally', pace=0.69, aggr=0.60, risk=0.61, cons=0.57 },
    { key='elfyn_evans', name='Gwilym Heavens', say='GWIL-im HEV-unz', bucket='rally', pace=0.66, aggr=0.46, risk=0.18, cons=0.89 },
    -- Drift
    { key='james_deane', name='Cormac Deanmachine', say='KOR-mak DEEN-muh-sheen', bucket='drift', pace=0.97, aggr=0.61, risk=0.36, cons=0.92 },
    { key='fredric_aasbo', name='Magnus Aceboss', say='MAG-nus ACE-boss', bucket='drift', pace=0.84, aggr=0.53, risk=0.36, cons=0.86 },
    { key='chris_forsberg', name='Trevor Forceberg', say='TREV-er FORCE-berg', bucket='drift', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='vaughn_gittin_jr', name='Garrison Gittinloose Jr.', say='GAIR-i-sun git-in-LOOSS JOO-nyur', bucket='drift', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='daigo_saito', name='Haru Slideto', say='HAH-roo SLIDE-toh', bucket='drift', pace=0.88, aggr=0.76, risk=0.42, cons=0.84 },
    { key='keiichi_tsuchiya', name='Ryo Tsuchiking', say='REE-oh SOO-chee-king', bucket='drift', pace=0.74, aggr=0.68, risk=0.48, cons=0.67 },
    { key='masato_kawabata', name='Shingo Kawablaster', say='SHIN-goh kah-wuh-BLAST-er', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='adam_lz', name='Axel Zeeway', say='AK-sul ZEE-way', bucket='drift', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='conor_shanahan', name='Declan Shenanigan', say='DEK-lun shuh-NAN-i-gun', bucket='drift', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='hiroya_minowa', name='Takeshi Minowow', say='tah-KESH-ee MIN-oh-wow', bucket='drift', pace=0.68, aggr=0.68, risk=0.48, cons=0.72 },
    -- F1-classic
    { key='rubens_barrichello', name='Tiago Barrichampion', say='tee-AH-goh bar-ee-CHAM-pee-un', bucket='f1', pace=0.65, aggr=0.53, risk=0.34, cons=0.76 },
    { key='ralf_schumacher', name='Dirk Shootmacher', say='durk SHOOT-mah-ker', bucket='f1', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='giancarlo_fisichella', name='Lorenzo Fisicheetah', say='loh-REN-zoh fee-see-CHEE-tuh', bucket='f1', pace=0.63, aggr=0.60, risk=0.35, cons=0.76 },
    { key='jarno_trulli', name='Fausto Trulligood', say='FOW-stoh TROO-lee-good', bucket='f1', pace=0.63, aggr=0.60, risk=0.33, cons=0.77 },
    { key='eddie_irvine', name='Barry Ironvine', say='BAIR-ee EYE-urn-vyne', bucket='f1', pace=0.64, aggr=0.68, risk=0.45, cons=0.67 },
    { key='heinz_harald_frentzen', name='Jurgen Frontrunner', say='YOOR-gen FRUNT-run-er', bucket='f1', pace=0.63, aggr=0.53, risk=0.38, cons=0.73 },
    { key='johnny_herbert', name='Leonard Herobert', say='LEN-erd HEER-oh-bert', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='nick_heidfeld', name='Lars Heightfield', say='larz HYTE-feeld', bucket='f1', pace=0.63, aggr=0.53, risk=0.20, cons=0.88 },
    { key='heikki_kovalainen', name='Antti Cavalrainen', say='AN-tee kav-ul-RY-nen', bucket='f1', pace=0.63, aggr=0.61, risk=0.43, cons=0.74 },
    { key='romain_grosjean', name='Olivier Grosgenius', say='oh-LIV-ee-ay grohss-JEEN-yus', bucket='f1', pace=0.62, aggr=0.60, risk=0.60, cons=0.54 },
    { key='pastor_maldonado', name='Rafael Bulldonado', say='rah-fah-EL bool-doh-NAH-doh', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='kevin_magnussen', name='Bjarne Magnumforce', say='BYAR-nuh MAG-num-forss', bucket='f1', pace=0.62, aggr=0.68, risk=0.35, cons=0.76 },
    { key='daniil_kvyat', name='Grigor Kwyatt', say='GREE-gor KWY-at', bucket='f1', pace=0.62, aggr=0.60, risk=0.42, cons=0.70 },
    { key='yuki_tsunoda', name='Riku Tsunami', say='REE-koo tsoo-NAH-mee', bucket='f1', pace=0.62, aggr=0.60, risk=0.45, cons=0.67 },
    { key='takuma_sato', name='Hideo Satonaut', say='hee-DAY-oh SAT-oh-nawt', bucket='f1', pace=0.62, aggr=0.68, risk=0.70, cons=0.46 },
    { key='mick_schumacher', name='Jonas Shoemaker', say='YOH-nus SHOO-may-ker', bucket='f1', pace=0.62, aggr=0.53, risk=0.48, cons=0.69 },
    { key='logan_sargeant', name='Cooper Sergewell', say='KOO-per SURJ-wel', bucket='f1', pace=0.62, aggr=0.60, risk=0.54, cons=0.59 },
    { key='jos_verstappen', name='Jan Papastappen', say='yahn PAH-puh-stap-en', bucket='f1', pace=0.62, aggr=0.60, risk=0.55, cons=0.59 },
    { key='riccardo_patrese', name='Massimo Patrecord', say='MASS-ee-moh PAT-ruh-kord', bucket='f1', pace=0.64, aggr=0.60, risk=0.42, cons=0.69 },
    { key='michele_alboreto', name='Silvio Alborocket', say='SIL-vee-oh AL-boh-rok-it', bucket='f1', pace=0.64, aggr=0.53, risk=0.42, cons=0.70 },
    { key='andrea_de_cesaris', name='Matteo de Caesar', say='mat-TAY-oh duh SEE-zer', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='derek_warwick', name='Clive Warwhack', say='klyve WOR-wak', bucket='f1', pace=0.62, aggr=0.68, risk=0.45, cons=0.68 },
    { key='martin_brundle', name='Giles Rumble', say='jylz RUM-bul', bucket='f1', pace=0.62, aggr=0.68, risk=0.43, cons=0.69 },
    { key='eddie_cheever', name='Dwight Achiever', say='dwyte uh-CHEE-ver', bucket='f1', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='thierry_boutsen', name='Bertrand Boostsen', say='bair-TRAHN BOOST-sen', bucket='f1', pace=0.63, aggr=0.46, risk=0.28, cons=0.77 },
    { key='keke_rosberg', name='Kimo Roarsberg', say='KEE-moh RORZ-berg', bucket='f1', pace=0.68, aggr=0.84, risk=0.51, cons=0.65 },
    { key='alan_jones', name='Dennis Thrones', say='DEN-iss throhnz', bucket='f1', pace=0.70, aggr=0.68, risk=0.36, cons=0.78 },
    { key='carlos_reutemann', name='Emiliano Roadmann', say='eh-mee-lee-AH-noh ROHD-man', bucket='f1', pace=0.67, aggr=0.60, risk=0.32, cons=0.78 },
    { key='clay_regazzoni', name='Aldo Regazzoom', say='AL-doh reg-uh-ZOOM', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='emerson_fittipaldi', name='Adriano Fittipedal', say='ah-dree-AH-noh FIT-ee-ped-ul', bucket='f1', pace=0.73, aggr=0.46, risk=0.26, cons=0.84 },
    { key='jacques_laffite', name='Michel Lafleet', say='mee-SHEL luh-FLEET', bucket='f1', pace=0.65, aggr=0.53, risk=0.42, cons=0.75 },
    { key='rene_arnoux', name='Alphonse Ironoux', say='al-FONSS EYE-run-oo', bucket='f1', pace=0.66, aggr=0.68, risk=0.44, cons=0.68 },
    { key='didier_pironi', name='Gerard Pyrocket', say='zheh-RAR PY-rock-it', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='john_watson', name='Clifford Wattage', say='KLIF-erd WOT-ij', bucket='f1', pace=0.64, aggr=0.60, risk=0.39, cons=0.73 },
    { key='patrick_tambay', name='Armand Tambourine', say='ar-MAHN tam-buh-REEN', bucket='f1', pace=0.64, aggr=0.53, risk=0.39, cons=0.72 },
    { key='elio_de_angelis', name='Fabio de Angelwing', say='FAH-bee-oh duh AYN-jul-wing', bucket='f1', pace=0.63, aggr=0.53, risk=0.42, cons=0.70 },
    { key='jean_pierre_jabouille', name='Gilbert Jabullet', say='zheel-BAIR zhah-BOOL-ay', bucket='f1', pace=0.65, aggr=0.60, risk=0.50, cons=0.63 },
    { key='francois_cevert', name='Pascal Cleverte', say='pas-KAL kluh-VAIRT', bucket='f1', pace=0.65, aggr=0.53, risk=0.46, cons=0.67 },
    { key='patrick_depailler', name='Yves Depedaler', say='eev duh-PED-ul-er', bucket='f1', pace=0.64, aggr=0.76, risk=0.63, cons=0.57 },
    -- Vintage
    { key='nino_farina', name='Guido Farinaflash', say='GWEE-doh fuh-REE-nuh-flash', bucket='vintage', pace=0.74, aggr=0.68, risk=0.63, cons=0.55 },
    { key='jose_froilan_gonzalez', name='Ramiro Gonzoblaze', say='rah-MEE-roh GON-zoh-blayz', bucket='vintage', pace=0.69, aggr=0.60, risk=0.38, cons=0.73 },
    { key='tony_brooks', name='Clement Brooksmile', say='KLEM-unt BROOK-smyle', bucket='vintage', pace=0.68, aggr=0.53, risk=0.33, cons=0.73 },
    { key='peter_collins', name='Desmond Coolins', say='DEZ-mund KOO-linz', bucket='vintage', pace=0.66, aggr=0.68, risk=0.42, cons=0.69 },
    { key='maurice_trintignant', name='Fabien Trintigallant', say='fah-bee-EN trin-ti-GAL-unt', bucket='vintage', pace=0.63, aggr=0.53, risk=0.34, cons=0.86 },
    { key='richie_ginther', name='Whitaker Ginzinger', say='WIT-uh-ker GIN-zing-er', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.82 },
    { key='wolfgang_von_trips', name='Konstantin von Zips', say='KON-stun-teen von zips', bucket='vintage', pace=0.65, aggr=0.68, risk=0.57, cons=0.57 },
    { key='jean_behra', name='Auguste Bravehra', say='oh-GOOST brah-VAIR-uh', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.65 },
    { key='jo_siffert', name='Emil Swiffert', say='AY-meel SWIF-ert', bucket='vintage', pace=0.63, aggr=0.76, risk=0.46, cons=0.72 },
    { key='chris_amon', name='Lyall Amonarch', say='LY-ul AM-on-ark', bucket='vintage', pace=0.63, aggr=0.60, risk=0.40, cons=0.72 },
    -- Formula-Indy
    { key='aj_foyt', name='T.J. Fortress', say='tee-jay FOR-tress', bucket='f1', pace=0.92, aggr=0.68, risk=0.42, cons=0.93 },
    { key='scott_dixon', name='Brett Slixon', say='bret SLIK-sun', bucket='f1', pace=0.92, aggr=0.60, risk=0.36, cons=0.95 },
    { key='will_power', name='Gareth Horsepower', say='GAIR-eth HORSS-pow-er', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='michael_andretti', name='Nathan Andcharge', say='NAY-thun AND-charj', bucket='f1', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='al_unser', name='Vern Winser', say='vurn WIN-ser', bucket='f1', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='sebastien_bourdais', name='Corentin Bourdash', say='kor-ahn-TAN BOOR-dash', bucket='f1', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='bobby_unser', name='Chip Onsurge', say='chip ON-serj', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='al_unser_jr', name='Vic Winsome Jr.', say='vik WIN-sum JOO-nyur', bucket='f1', pace=0.81, aggr=0.53, risk=0.42, cons=0.78 },
    { key='josef_newgarden', name='Wyatt Newgarland', say='WY-ut NEW-gar-lund', bucket='f1', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='paul_tracy', name='Grady Racy', say='GRAY-dee RAY-see', bucket='f1', pace=0.78, aggr=0.68, risk=0.48, cons=0.70 },
    { key='dario_franchitti', name='Ewan Franchisey', say='YOO-un FRAN-chy-zee', bucket='f1', pace=0.88, aggr=0.46, risk=0.36, cons=0.89 },
    { key='helio_castroneves', name='Nuno Castroclimbs', say='NOO-noh KAS-troh-klymz', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='rick_mears', name='Chuck Gears', say='chuk geerz', bucket='f1', pace=0.84, aggr=0.53, risk=0.36, cons=0.81 },
    { key='johnny_rutherford', name='Hollis Rocketford', say='HOL-iss ROK-it-ford', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='alex_palou', name='Marc Palooza', say='mark puh-LOO-zuh', bucket='f1', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='bobby_rahal', name='Gordy Royal', say='GOR-dee ROY-ul', bucket='f1', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='sam_hornish_jr', name='Gus Hornblast Jr.', say='guss HORN-blast JOO-nyur', bucket='f1', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='ryan_hunter_reay', name='Kirby Hunter-Blaze', say='KUR-bee HUN-ter-blayz', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='tony_kanaan', name='Rogerio Cannonaan', say='roh-ZHAIR-ee-oh KAN-un-ahn', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='alex_zanardi', name='Luca Zanhardy', say='LOO-kuh zan-HAR-dee', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='simon_pagenaud', name='Florent Pageturner', say='floh-RAHN PAYJ-turn-er', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='gil_de_ferran', name='Paulo de Ferrous', say='POW-loh duh FAIR-us', bucket='f1', pace=0.81, aggr=0.53, risk=0.36, cons=0.83 },
    { key='pato_oward', name='Patio O\'Warden', say='PAT-ee-oh oh-WAR-den', bucket='f1', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='colton_herta', name='Bryson Heartbeat', say='BRY-sun HART-beet', bucket='f1', pace=0.74, aggr=0.68, risk=0.54, cons=0.62 },
    { key='alexander_rossi', name='Harrison Glossi', say='HAIR-i-sun GLOSS-ee', bucket='f1', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='scott_mclaughlin', name='Blair McLaunchlin', say='blair muh-LAWNCH-lin', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='parnelli_jones', name='Barnaby Jonestone', say='BAR-nuh-bee JOHN-stohn', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    -- Rally
    { key='didier_auriol', name='Cyprien Aurigold', say='see-pree-EN OR-ee-gohld', bucket='rally', pace=0.69, aggr=0.53, risk=0.38, cons=0.71 },
    { key='markku_alen', name='Esko Allin', say='ES-koh AWL-in', bucket='rally', pace=0.67, aggr=0.76, risk=0.60, cons=0.59 },
    { key='jari_matti_latvala', name='Aarne Latvalanche', say='AR-nuh LAT-vuh-lanch', bucket='rally', pace=0.69, aggr=0.60, risk=0.65, cons=0.51 },
    { key='miki_biasion', name='Ennio Bravasion', say='EN-ee-oh bruh-VAY-zhun', bucket='rally', pace=0.74, aggr=0.46, risk=0.23, cons=0.92 },
    { key='bjorn_waldegard', name='Sigurd Wallguard', say='SIG-erd WAWL-gard', bucket='rally', pace=0.70, aggr=0.53, risk=0.34, cons=0.74 },
    { key='mikko_hirvonen', name='Arttu Hurryvonen', say='AR-too HUR-ee-voh-nen', bucket='rally', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='stig_blomqvist', name='Ingvar Blomtwist', say='ING-var BLOM-twist', bucket='rally', pace=0.68, aggr=0.60, risk=0.39, cons=0.75 },
    { key='timo_salonen', name='Urho Saloonen', say='OOR-hoh suh-LOO-nen', bucket='rally', pace=0.68, aggr=0.60, risk=0.45, cons=0.71 },
    { key='sandro_munari', name='Duilio Moonari', say='doo-EEL-ee-oh moo-NAR-ee', bucket='rally', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gilles_panizzi', name='Cedric Panpizzazz', say='SED-rik pan-pi-ZAZ', bucket='rally', pace=0.62, aggr=0.68, risk=0.42, cons=0.72 },
    { key='markko_martin', name='Tarmo Marveltin', say='TAR-moh MAR-vul-tin', bucket='rally', pace=0.62, aggr=0.53, risk=0.36, cons=0.72 },
    { key='kris_meeke', name='Fergal Mightke', say='FUR-gul MYTE-kee', bucket='rally', pace=0.67, aggr=0.60, risk=0.65, cons=0.50 },
    { key='dani_sordo', name='Iker Swordo', say='EE-ker SWOR-doh', bucket='rally', pace=0.64, aggr=0.60, risk=0.26, cons=0.83 },
    { key='andreas_mikkelsen', name='Hakon Mightelsen', say='HAH-kun MYTE-ul-sen', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='esapekka_lappi', name='Veikko Lapking', say='VAY-koh LAP-king', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.66 },
    { key='oliver_solberg', name='Torbjorn Stellarberg', say='TOR-byorn STEL-ar-berg', bucket='rally', pace=0.62, aggr=0.76, risk=0.48, cons=0.67 },
    { key='takamoto_katsuta', name='Sora Katsuper', say='SOR-uh kat-SOO-per', bucket='rally', pace=0.62, aggr=0.60, risk=0.48, cons=0.67 },
    -- Prototype
    { key='frank_biela', name='Lothar Beeline', say='LOH-tar BEE-lyne', bucket='proto', pace=0.94, aggr=0.53, risk=0.42, cons=0.88 },
    { key='emanuele_pirro', name='Cesare Pyrostar', say='cheh-ZAR-ay PY-roh-star', bucket='proto', pace=0.86, aggr=0.53, risk=0.42, cons=0.72 },
    { key='olivier_gendebien', name='Camille Gentlebien', say='kah-MEEL ZHAHN-tul-bee-en', bucket='proto', pace=0.84, aggr=0.46, risk=0.30, cons=0.77 },
    { key='yannick_dalmas', name='Gaetan Dalmaster', say='gy-TAHN DAL-mas-ter', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.77 },
    { key='al_holbert', name='Horace Holbright', say='HOR-iss HOHL-bryte', bucket='proto', pace=0.84, aggr=0.60, risk=0.36, cons=0.77 },
    { key='hurley_haywood', name='Judson Haywonder', say='JUD-sun HAY-wun-der', bucket='proto', pace=0.80, aggr=0.53, risk=0.42, cons=0.72 },
    { key='bob_wollek', name='Armel Wolfpack', say='ar-MEL WOOLF-pak', bucket='proto', pace=0.75, aggr=0.60, risk=0.42, cons=0.72 },
    { key='loic_duval', name='Anatole Duelval', say='an-uh-TOHL DOO-ul-val', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='anthony_davidson', name='Rufus Dashvidson', say='ROO-fus DASH-vid-sun', bucket='proto', pace=0.79, aggr=0.53, risk=0.36, cons=0.75 },
    { key='mike_rockenfeller', name='Falk Rockinfella', say='fahlk ROK-in-fel-uh', bucket='proto', pace=0.81, aggr=0.60, risk=0.30, cons=0.85 },
    { key='earl_bamber', name='Quinn Bambam', say='kwin BAM-bam', bucket='proto', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='nick_tandy', name='Percy Dandy', say='PUR-see DAN-dee', bucket='proto', pace=0.76, aggr=0.84, risk=0.42, cons=0.72 },
    { key='alexander_wurz', name='Konrad Whirls', say='KON-rad wurlz', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.72 },
    { key='stephane_sarrazin', name='Ulysse Sarrazoom', say='oo-LEESS sar-uh-ZOOM', bucket='proto', pace=0.77, aggr=0.60, risk=0.42, cons=0.72 },
    -- Touring
    { key='mark_skaife', name='Hugh Skyfe', say='hyoo skyfe', bucket='touring', pace=0.92, aggr=0.54, risk=0.36, cons=0.87 },
    { key='dick_johnson', name='Wally Johnstone', say='WOL-ee JON-stohn', bucket='touring', pace=0.92, aggr=0.68, risk=0.42, cons=0.87 },
    { key='allan_moffat', name='Keith Mofast', say='keeth MOH-fast', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='garth_tander', name='Lachlan Thunder', say='LOK-lun THUN-der', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='andy_rouse', name='Malcolm Rousing', say='MAL-kum ROW-zing', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='fabrizio_giovanardi', name='Nicola Giovanhardy', say='nee-KOH-luh joh-vun-HAR-dee', bucket='touring', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='gordon_shedden', name='Hamish Shredden', say='HAY-mish SHRED-un', bucket='touring', pace=0.81, aggr=0.68, risk=0.36, cons=0.83 },
    { key='rickard_rydell', name='Gustav Ridewell', say='GOO-stav RYDE-wel', bucket='touring', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='laurent_aiello', name='Sylvain Hiyello', say='seel-VAN hy-YEL-oh', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='john_cleland', name='Alasdair Clelandslide', say='AL-us-der KLEE-lund-slyde', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='james_thompson', name='Edmund Thumpson', say='ED-mund THUMP-sun', bucket='touring', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='gary_paffett', name='Julian Paffect', say='JOO-lee-un puh-FEKT', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='marco_wittmann', name='Lukas Wittyman', say='LOO-kus WIT-ee-man', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='timo_scheider', name='Ansgar Skyder', say='ANS-gar SKY-der', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='roberto_ravaglia', name='Gianni Ravaglide', say='JAH-nee RAV-uh-glyde', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    -- Drift
    { key='samuel_hubinette', name='Anders Hubcapette', say='AN-derz hub-kuh-PET', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='rhys_millen', name='Owen Milehigh', say='OH-un MILE-hy', bucket='drift', pace=0.78, aggr=0.68, risk=0.48, cons=0.75 },
    { key='tanner_foust', name='Colby Foustest', say='KOHL-bee FOW-stest', bucket='drift', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='daijiro_yoshihara', name='Kenji Yoshiflare', say='KEN-jee yoh-shee-FLAIR', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='michael_essa', name='Douglas Esscurve', say='DUG-lus ESS-kurv', bucket='drift', pace=0.78, aggr=0.53, risk=0.30, cons=0.85 },
    { key='chelsea_denofa', name='Delphine DeNofear', say='del-FEEN duh-NOH-feer', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='ryan_tuerck', name='Brody Torque', say='BROH-dee tork', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='aurimas_bakchis', name='Marius Backswish', say='MAR-ee-us BAK-swish', bucket='drift', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='matt_field', name='Rex Skidfield', say='reks SKID-feeld', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='mad_mike_whiddett', name='Wild Wayne Widetrack', say='wyld wayn WIDE-trak', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    -- NASCAR-modern
    { key='denny_hamlin', name='Rodney Hammerlin', say='ROD-nee HAM-er-lin', bucket='nascar', pace=0.78, aggr=0.53, risk=0.28, cons=0.81 },
    { key='kyle_busch', name='Bronson Bushfire', say='BRON-sun BUSH-fyre', bucket='nascar', pace=0.94, aggr=0.68, risk=0.39, cons=0.78 },
    { key='joey_logano', name='Vince Loganogo', say='vinss loh-guh-NOH-goh', bucket='nascar', pace=0.96, aggr=0.68, risk=0.32, cons=0.87 },
    { key='brad_keselowski', name='Zane Wrestleowski', say='zayn res-luh-OW-skee', bucket='nascar', pace=0.81, aggr=0.68, risk=0.31, cons=0.82 },
    { key='martin_truex_jr', name='Donovan Truest Jr.', say='DON-uh-vun TROO-est JOO-nyur', bucket='nascar', pace=0.79, aggr=0.53, risk=0.27, cons=0.80 },
    { key='kyle_larson', name='Kellan Larsonic', say='KEL-un lar-SON-ik', bucket='nascar', pace=0.91, aggr=0.60, risk=0.39, cons=0.78 },
    { key='chase_elliott', name='Kipp Elliblaze', say='kip EL-ee-blayz', bucket='nascar', pace=0.82, aggr=0.53, risk=0.21, cons=0.85 },
    { key='ryan_blaney', name='Griffin Blazeney', say='GRIF-in BLAYZ-nee', bucket='nascar', pace=0.80, aggr=0.53, risk=0.39, cons=0.75 },
    { key='william_byron', name='Fletcher Byronic', say='FLECH-er by-RON-ik', bucket='nascar', pace=0.73, aggr=0.46, risk=0.39, cons=0.72 },
    { key='christopher_bell', name='Sullivan Bellringer', say='SUL-i-vun BEL-ring-er', bucket='nascar', pace=0.75, aggr=0.46, risk=0.33, cons=0.72 },
    { key='tyler_reddick', name='Jonah Redzone', say='JOH-nuh RED-zohn', bucket='nascar', pace=0.73, aggr=0.68, risk=0.36, cons=0.75 },
    { key='ross_chastain', name='Deke Chasegain', say='deek CHAYSS-gayn', bucket='nascar', pace=0.67, aggr=0.68, risk=0.38, cons=0.73 },
    { key='chase_briscoe', name='Landon Briskly', say='LAN-dun BRISK-lee', bucket='nascar', pace=0.70, aggr=0.60, risk=0.37, cons=0.74 },
    { key='chris_buescher', name='Grant Boostcher', say='grant BOOST-cher', bucket='nascar', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='alex_bowman', name='Trey Arrowman', say='tray AIR-oh-man', bucket='nascar', pace=0.67, aggr=0.53, risk=0.43, cons=0.74 },
    { key='bubba_wallace', name='Truman Wallop', say='TROO-mun WOL-up', bucket='nascar', pace=0.66, aggr=0.60, risk=0.49, cons=0.64 },
    { key='shane_van_gisbergen_x', name='Bodie van Glidesbergen', say='BOH-dee van GLIDES-ber-gen', bucket='nascar', pace=0.74, aggr=0.60, risk=0.35, cons=0.76 },
    { key='ty_gibbs', name='Kai Gibbspeed', say='ky GIB-speed', bucket='nascar', pace=0.68, aggr=0.68, risk=0.44, cons=0.68 },
    { key='carson_hocevar', name='Beckett Hoceviper', say='BEK-it HOH-suh-vy-per', bucket='nascar', pace=0.66, aggr=0.68, risk=0.45, cons=0.67 },
    { key='austin_cindric', name='Preston Cinderick', say='PRES-tun SIN-der-ik', bucket='nascar', pace=0.66, aggr=0.53, risk=0.37, cons=0.74 },
    { key='ricky_stenhouse_jr', name='Beau Steelhouse Jr.', say='boh STEEL-howss JOO-nyur', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='austin_dillon', name='Jasper Drillon', say='JAS-per DRIL-un', bucket='nascar', pace=0.65, aggr=0.68, risk=0.37, cons=0.74 },
    { key='aj_allmendinger', name='C.J. Allmenwinner', say='see-jay AWL-men-win-er', bucket='nascar', pace=0.64, aggr=0.60, risk=0.33, cons=0.77 },
    { key='michael_mcdowell', name='Barrett McDoingwell', say='BAIR-it muk-DOO-ing-wel', bucket='nascar', pace=0.62, aggr=0.60, risk=0.39, cons=0.72 },
    { key='ryan_preece', name='Milo Preecision', say='MY-loh pruh-SIZH-un', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    -- NASCAR-classic
    { key='richard_petty', name='Everett Plentymore', say='EV-er-it PLEN-tee-mor', bucket='nascar', pace=0.96, aggr=0.68, risk=0.42, cons=0.93 },
    { key='david_pearson', name='Emmett Peerless', say='EM-it PEER-less', bucket='nascar', pace=0.82, aggr=0.53, risk=0.36, cons=0.81 },
    { key='jeff_gordon', name='Sawyer Gordian', say='SAW-yer GOR-dee-un', bucket='nascar', pace=0.82, aggr=0.53, risk=0.42, cons=0.84 },
    { key='bobby_allison', name='Hoyt Allwinson', say='hoyt AWL-win-sun', bucket='nascar', pace=0.70, aggr=0.68, risk=0.48, cons=0.75 },
    { key='darrell_waltrip', name='Jubal Waltriple', say='JOO-bul WAWL-trip-ul', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.81 },
    { key='jimmie_johnson', name='Clyde Sevenson', say='klyde SEV-un-sun', bucket='nascar', pace=0.94, aggr=0.61, risk=0.36, cons=0.97 },
    { key='cale_yarborough', name='Merle Yardcharger', say='murl YARD-char-jer', bucket='nascar', pace=0.80, aggr=0.68, risk=0.48, cons=0.81 },
    { key='dale_earnhardt', name='Boyd Ironheart', say='boyd EYE-urn-hart', bucket='nascar', pace=0.93, aggr=0.60, risk=0.42, cons=0.93 },
    { key='kevin_harvick', name='Wesson Havock', say='WES-un HAV-ok', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='rusty_wallace', name='Orson Wallride', say='OR-sun WAWL-ryde', bucket='nascar', pace=0.69, aggr=0.68, risk=0.42, cons=0.75 },
    { key='tony_stewart', name='Deacon Stouthart', say='DEE-kun STOWT-hart', bucket='nascar', pace=0.76, aggr=0.60, risk=0.42, cons=0.81 },
    { key='bill_elliott', name='Roy Rallyott', say='roy RAL-ee-ot', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='mark_martin', name='Chet Marathon', say='chet MAIR-uh-thon', bucket='nascar', pace=0.64, aggr=0.60, risk=0.36, cons=0.77 },
    { key='matt_kenseth', name='Lyle Kenzenith', say='lyle KEN-zen-ith', bucket='nascar', pace=0.68, aggr=0.53, risk=0.30, cons=0.80 },
    { key='kurt_busch', name='Randall Bushwhack', say='RAN-dul BUSH-wak', bucket='nascar', pace=0.67, aggr=0.60, risk=0.42, cons=0.75 },
    { key='dale_jarrett', name='Foster Starrett', say='FOSS-ter STAR-it', bucket='nascar', pace=0.67, aggr=0.53, risk=0.36, cons=0.80 },
    { key='carl_edwards', name='Dwayne Backflipwards', say='dwayn BAK-flip-werdz', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='dale_earnhardt_jr', name='Cody Earnedmore Jr.', say='KOH-dee URND-mor JOO-nyur', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='terry_labonte', name='Thaddeus Labonanza', say='THAD-ee-us lah-buh-NAN-zuh', bucket='nascar', pace=0.71, aggr=0.53, risk=0.42, cons=0.83 },
    { key='ricky_rudd', name='Holden Rugged', say='HOHL-dun RUG-id', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='alan_kulwicki', name='Marvin Coolwicki', say='MAR-vin kool-WIK-ee', bucket='nascar', pace=0.68, aggr=0.53, risk=0.36, cons=0.75 },
    { key='davey_allison', name='Shelton Allisoar', say='SHEL-tun AL-i-sor', bucket='nascar', pace=0.66, aggr=0.68, risk=0.42, cons=0.72 },
    { key='tim_richmond', name='Vance Rushmond', say='vanss RUSH-mund', bucket='nascar', pace=0.65, aggr=0.76, risk=0.48, cons=0.67 },
    { key='junior_johnson', name='Bo Johnshine', say='boh JON-shyne', bucket='nascar', pace=0.69, aggr=0.76, risk=0.54, cons=0.72 },
    { key='ned_jarrett', name='Whit Jarrhero', say='wit JAR-hee-roh', bucket='nascar', pace=0.75, aggr=0.60, risk=0.36, cons=0.83 },
    { key='fireball_roberts', name='Comet Rockettson', say='KOM-it ROK-it-sun', bucket='nascar', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='curtis_turner', name='Woodrow Turnpike', say='WOOD-roh TURN-pyke', bucket='nascar', pace=0.66, aggr=0.84, risk=0.60, cons=0.62 },
    { key='lee_petty', name='Ezra Plenty', say='EZ-ruh PLEN-tee', bucket='nascar', pace=0.76, aggr=0.53, risk=0.30, cons=0.86 },
    { key='herb_thomas', name='Amos Tomahawk', say='AY-mus TOM-uh-hawk', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.78 },
    { key='tim_flock', name='Ollie Flockstar', say='OL-ee FLOK-star', bucket='nascar', pace=0.79, aggr=0.60, risk=0.42, cons=0.78 },
    { key='buck_baker', name='Hoss Breaker', say='hoss BRAY-ker', bucket='nascar', pace=0.73, aggr=0.60, risk=0.42, cons=0.78 },
    { key='bobby_isaac', name='Lonnie Isaacspeed', say='LON-ee EYE-zak-speed', bucket='nascar', pace=0.71, aggr=0.60, risk=0.42, cons=0.75 },
    { key='buddy_baker', name='Lefty Bakespeed', say='LEF-tee BAYK-speed', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='benny_parsons', name='Elmer Pardner', say='EL-mer PARD-ner', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='harry_gant', name='Truett Gallant', say='TROO-it GAL-unt', bucket='nascar', pace=0.63, aggr=0.60, risk=0.36, cons=0.77 },
    { key='ernie_irvan', name='Sylvester Irvantage', say='sil-VES-ter ur-VAN-tij', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='geoff_bodine', name='Clayton Bodyline', say='KLAY-tun BOD-ee-lyne', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='sterling_marlin', name='Coleman Merlin', say='KOHL-mun MUR-lin', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='jeff_burton', name='Miles Blurton', say='mylz BLUR-tun', bucket='nascar', pace=0.63, aggr=0.53, risk=0.36, cons=0.77 },
    { key='bobby_labonte', name='Duane Labounty', say='dwayn luh-BOWN-tee', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='ryan_newman', name='Hobart Newrocket', say='HOH-bart NEW-rok-it', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='greg_biffle', name='Doyle Riffle', say='doyl RIF-ul', bucket='nascar', pace=0.63, aggr=0.68, risk=0.36, cons=0.77 },
    { key='kasey_kahne', name='Judd Kahnon', say='jud KAH-non', bucket='nascar', pace=0.63, aggr=0.53, risk=0.42, cons=0.72 },
    { key='ken_schrader', name='Otis Shredder', say='OH-tiss SHRED-er', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='dave_marcis', name='Orrin Wingtipp', say='OR-in WING-tip', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    -- Oval-Indy
    { key='rodger_ward', name='Milton Onward', say='MIL-tun ON-werd', bucket='f1', pace=0.81, aggr=0.46, risk=0.30, cons=0.78 },
    { key='gordon_johncock', name='Harlan Johnrocket', say='HAR-lun JON-rok-it', bucket='f1', pace=0.78, aggr=0.60, risk=0.42, cons=0.75 },
    { key='jimmy_bryan', name='Hank Brawny', say='hank BRAW-nee', bucket='f1', pace=0.84, aggr=0.60, risk=0.42, cons=0.81 },
    { key='dan_wheldon', name='Marcus Welldone', say='MAR-kus WEL-dun', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='tom_sneva', name='Gale Sneverquit', say='gayl SNEV-er-kwit', bucket='f1', pace=0.81, aggr=0.68, risk=0.48, cons=0.78 },
    { key='buddy_lazier', name='Sonny Blazier', say='SON-ee BLAY-zee-er', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.80 },
    { key='arie_luyendyk', name='Ruud Lionendyke', say='rood LY-un-en-dyke', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='wilbur_shaw', name='Orville Shawstopper', say='OR-vil SHAW-stop-er', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='mauri_rose', name='Homer Arose', say='HOH-mer uh-ROHZ', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='bill_vukovich', name='Walt Vroomovich', say='wawlt VROOM-oh-vich', bucket='f1', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    -- Oval-Dirt
    { key='steve_kinser', name='Royce Kingser', say='royss KING-ser', bucket='nascar', pace=0.92, aggr=0.68, risk=0.42, cons=0.97 },
    { key='sammy_swindell', name='Odell Swiftdell', say='oh-DEL SWIFT-del', bucket='nascar', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='donny_schatz', name='Garrett Smashatz', say='GAIR-it SMASH-atz', bucket='nascar', pace=0.92, aggr=0.60, risk=0.36, cons=0.97 },
    { key='mark_kinser', name='Boone Kinsman', say='boon KINZ-mun', bucket='nascar', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    -- Cross-category appearances
    { key='max_verstappen_kart', name='Pass Nearstappen', say='pass NEER-stuh-pen', bucket='kart', pace=1.00, aggr=0.76, risk=0.29, cons=0.93 },
    { key='ayrton_senna_kart', name='Aaron Sensei', say='AIR-un SEN-say', bucket='kart', pace=0.96, aggr=0.68, risk=0.56, cons=0.67 },
    { key='michael_schumacher_kart', name='Mike Zoomacher', say='myke ZOO-mah-ker', bucket='kart', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='lewis_hamilton_kart', name='Bruisin Yamilton', say='BROO-zin yuh-MIL-tun', bucket='kart', pace=0.97, aggr=0.53, risk=0.23, cons=0.97 },
    { key='lando_norris_kart', name='Wambo Boris', say='WOM-boh BOR-iss', bucket='kart', pace=0.98, aggr=0.53, risk=0.20, cons=0.86 },
    { key='fernando_alonso_proto', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='proto', pace=0.90, aggr=0.60, risk=0.29, cons=0.87 },
    { key='nico_hulkenberg_proto', name='Nitro Krakenberg', say='NYE-troh KRAY-ken-berg', bucket='proto', pace=0.88, aggr=0.53, risk=0.30, cons=0.85 },
    { key='mark_webber_proto', name='Spark Webbest', say='spark web-BEST', bucket='proto', pace=0.92, aggr=0.68, risk=0.33, cons=0.78 },
    { key='juan_pablo_montoya_proto', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='proto', pace=0.85, aggr=0.84, risk=0.60, cons=0.55 },
    { key='jenson_button_proto', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='proto', pace=0.80, aggr=0.46, risk=0.30, cons=0.83 },
    { key='robert_kubica_proto', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='proto', pace=0.85, aggr=0.61, risk=0.28, cons=0.77 },
    { key='mario_andretti_proto', name='Bravo Andread', say='BRAH-voh AN-dred', bucket='proto', pace=0.88, aggr=0.60, risk=0.42, cons=0.72 },
    { key='fernando_alonso_gt', name='Ferdinand Honkso', say='FUR-di-nand HONK-soh', bucket='gt', pace=0.86, aggr=0.60, risk=0.29, cons=0.87 },
    { key='juan_pablo_montoya_gt', name='Diablo Blastoya', say='dee-AH-bloh blas-TOY-uh', bucket='gt', pace=0.84, aggr=0.84, risk=0.60, cons=0.55 },
    { key='jenson_button_gt', name='Winston Clutchin', say='WIN-stun KLUTCH-in', bucket='gt', pace=0.82, aggr=0.46, risk=0.30, cons=0.83 },
    { key='kimi_raikkonen_rally', name='Chilly Icekkonen', say='CHIL-ee ICE-koh-nen', bucket='rally', pace=0.58, aggr=0.60, risk=0.30, cons=0.83 },
    { key='robert_kubica_rally', name='Robust Kublitzka', say='roh-BUST koo-BLITS-kuh', bucket='rally', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='hans_joachim_stuck_touring', name='Hansel Struck', say='HAN-sul struk', bucket='touring', pace=0.88, aggr=0.84, risk=0.48, cons=0.70 },
    { key='alex_zanardi_touring', name='Luca Zanhardy', say='LOO-kuh zan-HAR-dee', bucket='touring', pace=0.78, aggr=0.76, risk=0.48, cons=0.78 },
    { key='jacky_ickx_f1', name='Rocky Slicks', say='ROCK-ee sliks', bucket='f1', pace=0.82, aggr=0.60, risk=0.42, cons=0.78 },
    { key='hans_joachim_stuck_f1', name='Hansel Struck', say='HAN-sul struk', bucket='f1', pace=0.68, aggr=0.84, risk=0.48, cons=0.70 },

    -- Generic archetypes: always offered, used for randomize overflow. Labelled so nobody mistakes
    -- them for a real name.
    -- Three archetypes, always listed first: a beginner, a solid midfielder, a seasoned front-runner.
    { key='arch_rookie',     name='Rookie',     bucket='archetype', pace=0.30, aggr=0.50, risk=0.60, cons=0.50 },
    { key='arch_midfield',   name='Midfielder', bucket='archetype', pace=0.60, aggr=0.55, risk=0.35, cons=0.80 },
    { key='arch_veteran',    name='Veteran',    bucket='archetype', pace=0.85, aggr=0.55, risk=0.20, cons=0.95 },
}

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
    for _, d in ipairs(ARCHETYPES) do out[#out + 1] = d end     -- archetypes first, then the class roster
    if bucket then
        for _, d in ipairs(D.DRIVERS) do if d.bucket == bucket then out[#out + 1] = d end end
    end
    return out
end

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
            if d and d.pace and d.pace > m then m = d.pace end
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
function D.autoMatch()
    if matched then return end
    matched = true
    pcall(function()
        local sim = ac.getSim(); if not sim then return end
        local byName = {}
        for _, d in ipairs(D.DRIVERS) do byName[d.name:lower()] = d end
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
    return BY_KEY[k]
end
function D.anyAssigned() for _ in pairs(assigned) do return true end return false end
function D.clearAll()
    for i in pairs(assigned) do assigned[i] = nil; applyName(i) end
    assigned = {}; paceDirty = true
end
function D.reset() assigned = {}; baseLevel = {}; lastApplied = {}; fieldMaxPace = 1.0; paceDirty = true; lastSlot0AI = nil; named0 = false; origName = {}; matched = false end

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

-- how many real-name profiles vs archetypes are on the grid (telemetry)
function D.counts()
    local real, arch = 0, 0
    for _, k in pairs(assigned) do local d = BY_KEY[k]; if d then if d.bucket == 'archetype' then arch = arch + 1 else real = real + 1 end end end
    return real, arch
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
local named0 = false               -- slot 0's public name applied (needs the car to be AI-driven, which lags the autopilot switch by a frame)
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
            local Difficulty = require('lib.difficulty')
            local basePct = Difficulty.levelToPct(base)
            lvl = math.min(base, Difficulty.pctToLevel(basePct + (fieldMaxPace - st.pace) * SPREAD_PCT))
        end
        lvl = math.floor(lvl * 1000 + 0.5) / 1000
        if lastApplied[i] ~= lvl then physics.setAILevel(i, lvl); lastApplied[i] = lvl end   -- only on change (18 cars x 60 Hz otherwise)
    end)
end

return D
