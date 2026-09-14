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
    { key='max_verstappen', name='Max Verstappen', bucket='f1', pace=0.87, aggr=0.76, risk=0.29, cons=0.93 },
    { key='lewis_hamilton', name='Lewis Hamilton', bucket='f1', pace=0.96, aggr=0.53, risk=0.23, cons=0.97 },
    { key='lando_norris', name='Lando Norris', bucket='f1', pace=0.71, aggr=0.53, risk=0.20, cons=0.86 },
    { key='charles_leclerc', name='Charles Leclerc', bucket='f1', pace=0.71, aggr=0.60, risk=0.46, cons=0.66 },
    { key='oscar_piastri', name='Oscar Piastri', bucket='f1', pace=0.69, aggr=0.46, risk=0.16, cons=0.91 },
    { key='george_russell', name='George Russell', bucket='f1', pace=0.66, aggr=0.61, risk=0.28, cons=0.82 },
    { key='fernando_alonso', name='Fernando Alonso', bucket='f1', pace=0.73, aggr=0.60, risk=0.29, cons=0.87 },
    { key='kimi_antonelli', name='Kimi Antonelli', bucket='f1', pace=0.70, aggr=0.68, risk=0.56, cons=0.62 },
    { key='carlos_sainz_jr', name='Carlos Sainz Jr.', bucket='f1', pace=0.64, aggr=0.53, risk=0.24, cons=0.85 },
    { key='isack_hadjar', name='Isack Hadjar', bucket='f1', pace=0.63, aggr=0.68, risk=0.41, cons=0.71 },
    { key='alexander_albon', name='Alexander Albon', bucket='f1', pace=0.63, aggr=0.46, risk=0.19, cons=0.84 },
    { key='pierre_gasly', name='Pierre Gasly', bucket='f1', pace=0.63, aggr=0.60, risk=0.29, cons=0.80 },
    { key='esteban_ocon', name='Esteban Ocon', bucket='f1', pace=0.63, aggr=0.68, risk=0.32, cons=0.78 },
    { key='nico_hulkenberg', name='Nico Hulkenberg', bucket='f1', pace=0.63, aggr=0.53, risk=0.30, cons=0.85 },
    { key='lance_stroll', name='Lance Stroll', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='oliver_bearman', name='Oliver Bearman', bucket='f1', pace=0.62, aggr=0.68, risk=0.33, cons=0.77 },
    { key='sergio_perez', name='Sergio Perez', bucket='f1', pace=0.64, aggr=0.60, risk=0.38, cons=0.73 },
    { key='valtteri_bottas', name='Valtteri Bottas', bucket='f1', pace=0.67, aggr=0.53, risk=0.14, cons=0.88 },
    { key='liam_lawson', name='Liam Lawson', bucket='f1', pace=0.62, aggr=0.76, risk=0.36, cons=0.75 },
    { key='gabriel_bortoleto', name='Gabriel Bortoleto', bucket='f1', pace=0.62, aggr=0.53, risk=0.43, cons=0.69 },
    { key='franco_colapinto', name='Franco Colapinto', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='arvid_lindblad', name='Arvid Lindblad', bucket='f1', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    -- F1-classic
    { key='ayrton_senna', name='Ayrton Senna', bucket='f1', pace=0.88, aggr=0.68, risk=0.56, cons=0.67 },
    { key='alain_prost', name='Alain Prost', bucket='f1', pace=0.86, aggr=0.53, risk=0.18, cons=0.97 },
    { key='michael_schumacher', name='Michael Schumacher', bucket='f1', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='niki_lauda', name='Niki Lauda', bucket='f1', pace=0.78, aggr=0.46, risk=0.21, cons=0.86 },
    { key='james_hunt', name='James Hunt', bucket='f1', pace=0.71, aggr=0.76, risk=0.85, cons=0.40 },
    { key='nigel_mansell', name='Nigel Mansell', bucket='f1', pace=0.73, aggr=0.84, risk=0.49, cons=0.67 },
    { key='nelson_piquet', name='Nelson Piquet', bucket='f1', pace=0.77, aggr=0.60, risk=0.38, cons=0.82 },
    { key='mika_hakkinen', name='Mika Hakkinen', bucket='f1', pace=0.77, aggr=0.53, risk=0.37, cons=0.80 },
    { key='kimi_raikkonen', name='Kimi Raikkonen', bucket='f1', pace=0.68, aggr=0.60, risk=0.30, cons=0.83 },
    { key='sebastian_vettel', name='Sebastian Vettel', bucket='f1', pace=0.83, aggr=0.60, risk=0.34, cons=0.88 },
    { key='nico_rosberg', name='Nico Rosberg', bucket='f1', pace=0.70, aggr=0.46, risk=0.20, cons=0.92 },
    { key='jenson_button', name='Jenson Button', bucket='f1', pace=0.66, aggr=0.46, risk=0.30, cons=0.83 },
    { key='damon_hill', name='Damon Hill', bucket='f1', pace=0.74, aggr=0.60, risk=0.43, cons=0.72 },
    { key='gilles_villeneuve', name='Gilles Villeneuve', bucket='f1', pace=0.65, aggr=0.76, risk=0.85, cons=0.40 },
    { key='juan_pablo_montoya', name='Juan Pablo Montoya', bucket='f1', pace=0.67, aggr=0.84, risk=0.60, cons=0.55 },
    { key='daniel_ricciardo', name='Daniel Ricciardo', bucket='f1', pace=0.62, aggr=0.84, risk=0.27, cons=0.82 },
    { key='jean_alesi', name='Jean Alesi', bucket='f1', pace=0.62, aggr=0.68, risk=0.62, cons=0.53 },
    { key='gerhard_berger', name='Gerhard Berger', bucket='f1', pace=0.65, aggr=0.61, risk=0.40, cons=0.71 },
    { key='david_coulthard', name='David Coulthard', bucket='f1', pace=0.65, aggr=0.46, risk=0.33, cons=0.82 },
    { key='mark_webber', name='Mark Webber', bucket='f1', pace=0.64, aggr=0.68, risk=0.33, cons=0.78 },
    { key='felipe_massa', name='Felipe Massa', bucket='f1', pace=0.64, aggr=0.68, risk=0.32, cons=0.79 },
    { key='jacques_villeneuve', name='Jacques Villeneuve', bucket='f1', pace=0.68, aggr=0.84, risk=0.45, cons=0.75 },
    { key='robert_kubica', name='Robert Kubica', bucket='f1', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='ronnie_peterson', name='Ronnie Peterson', bucket='f1', pace=0.66, aggr=0.68, risk=0.50, cons=0.63 },
    { key='mario_andretti', name='Mario Andretti', bucket='f1', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='jody_scheckter', name='Jody Scheckter', bucket='f1', pace=0.69, aggr=0.61, risk=0.46, cons=0.64 },
    -- Vintage
    { key='juan_manuel_fangio', name='Juan Manuel Fangio', bucket='vintage', pace=0.98, aggr=0.53, risk=0.22, cons=0.96 },
    { key='stirling_moss', name='Stirling Moss', bucket='vintage', pace=0.72, aggr=0.68, risk=0.44, cons=0.73 },
    { key='jim_clark', name='Jim Clark', bucket='vintage', pace=0.85, aggr=0.53, risk=0.23, cons=0.92 },
    { key='jackie_stewart', name='Jackie Stewart', bucket='vintage', pace=0.80, aggr=0.46, risk=0.17, cons=0.95 },
    { key='graham_hill', name='Graham Hill', bucket='vintage', pace=0.71, aggr=0.60, risk=0.36, cons=0.81 },
    { key='jack_brabham', name='Jack Brabham', bucket='vintage', pace=0.75, aggr=0.68, risk=0.30, cons=0.89 },
    { key='alberto_ascari', name='Alberto Ascari', bucket='vintage', pace=0.84, aggr=0.53, risk=0.28, cons=0.82 },
    { key='jochen_rindt', name='Jochen Rindt', bucket='vintage', pace=0.70, aggr=0.68, risk=0.50, cons=0.66 },
    { key='john_surtees', name='John Surtees', bucket='vintage', pace=0.67, aggr=0.60, risk=0.32, cons=0.81 },
    { key='dan_gurney', name='Dan Gurney', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.77 },
    { key='phil_hill', name='Phil Hill', bucket='vintage', pace=0.69, aggr=0.46, risk=0.28, cons=0.80 },
    { key='mike_hawthorn', name='Mike Hawthorn', bucket='vintage', pace=0.69, aggr=0.69, risk=0.41, cons=0.78 },
    { key='denny_hulme', name='Denny Hulme', bucket='vintage', pace=0.68, aggr=0.53, risk=0.27, cons=0.95 },
    { key='bruce_mclaren', name='Bruce McLaren', bucket='vintage', pace=0.64, aggr=0.53, risk=0.22, cons=0.86 },
    { key='pedro_rodriguez', name='Pedro Rodriguez', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.70 },
    { key='ken_miles', name='Ken Miles', bucket='vintage', pace=0.62, aggr=0.76, risk=0.42, cons=0.72 },
    -- Prototype
    { key='tom_kristensen', name='Tom Kristensen', bucket='proto', pace=0.92, aggr=0.60, risk=0.36, cons=0.80 },
    { key='jacky_ickx', name='Jacky Ickx', bucket='proto', pace=0.91, aggr=0.60, risk=0.42, cons=0.78 },
    { key='derek_bell', name='Derek Bell', bucket='proto', pace=0.86, aggr=0.53, risk=0.36, cons=0.78 },
    { key='hans_joachim_stuck', name='Hans-Joachim Stuck', bucket='proto', pace=0.81, aggr=0.84, risk=0.48, cons=0.70 },
    { key='henri_pescarolo', name='Henri Pescarolo', bucket='proto', pace=0.78, aggr=0.53, risk=0.42, cons=0.77 },
    { key='allan_mcnish', name='Allan McNish', bucket='proto', pace=0.92, aggr=0.68, risk=0.42, cons=0.84 },
    { key='rinaldo_capello', name='Rinaldo Capello', bucket='proto', pace=0.86, aggr=0.39, risk=0.30, cons=0.93 },
    { key='andre_lotterer', name='Andre Lotterer', bucket='proto', pace=0.86, aggr=0.60, risk=0.42, cons=0.78 },
    { key='marcel_fassler', name='Marcel Fassler', bucket='proto', pace=0.84, aggr=0.53, risk=0.30, cons=0.85 },
    { key='benoit_treluyer', name='Benoit Treluyer', bucket='proto', pace=0.83, aggr=0.53, risk=0.42, cons=0.80 },
    { key='sebastien_buemi', name='Sebastien Buemi', bucket='proto', pace=0.95, aggr=0.46, risk=0.30, cons=0.89 },
    { key='brendon_hartley', name='Brendon Hartley', bucket='proto', pace=0.95, aggr=0.53, risk=0.36, cons=0.89 },
    { key='kazuki_nakajima', name='Kazuki Nakajima', bucket='proto', pace=0.88, aggr=0.53, risk=0.42, cons=0.80 },
    { key='kamui_kobayashi', name='Kamui Kobayashi', bucket='proto', pace=0.87, aggr=0.84, risk=0.42, cons=0.78 },
    { key='mike_conway', name='Mike Conway', bucket='proto', pace=0.87, aggr=0.53, risk=0.36, cons=0.83 },
    { key='timo_bernhard', name='Timo Bernhard', bucket='proto', pace=0.84, aggr=0.53, risk=0.36, cons=0.83 },
    { key='romain_dumas', name='Romain Dumas', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='neel_jani', name='Neel Jani', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.75 },
    { key='alessandro_pier_guidi', name='Alessandro Pier Guidi', bucket='proto', pace=0.88, aggr=0.84, risk=0.42, cons=0.84 },
    { key='james_calado', name='James Calado', bucket='proto', pace=0.88, aggr=0.60, risk=0.30, cons=0.94 },
    { key='antonio_giovinazzi', name='Antonio Giovinazzi', bucket='proto', pace=0.84, aggr=0.60, risk=0.42, cons=0.75 },
    { key='antonio_fuoco', name='Antonio Fuoco', bucket='proto', pace=0.80, aggr=0.60, risk=0.42, cons=0.72 },
    -- GT
    { key='kevin_estre', name='Kevin Estre', bucket='gt', pace=0.86, aggr=0.76, risk=0.48, cons=0.78 },
    { key='laurens_vanthoor', name='Laurens Vanthoor', bucket='gt', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='raffaele_marciello', name='Raffaele Marciello', bucket='gt', pace=0.79, aggr=0.60, risk=0.42, cons=0.72 },
    { key='maro_engel', name='Maro Engel', bucket='gt', pace=0.74, aggr=0.60, risk=0.36, cons=0.77 },
    { key='edoardo_mortara', name='Edoardo Mortara', bucket='gt', pace=0.74, aggr=0.53, risk=0.36, cons=0.72 },
    { key='nicki_thiim', name='Nicki Thiim', bucket='gt', pace=0.81, aggr=0.76, risk=0.48, cons=0.73 },
    { key='marco_sorensen', name='Marco Sorensen', bucket='gt', pace=0.78, aggr=0.46, risk=0.30, cons=0.85 },
    { key='richard_lietz', name='Richard Lietz', bucket='gt', pace=0.74, aggr=0.46, risk=0.36, cons=0.77 },
    { key='jan_magnussen', name='Jan Magnussen', bucket='gt', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    { key='oliver_gavin', name='Oliver Gavin', bucket='gt', pace=0.74, aggr=0.46, risk=0.30, cons=0.82 },
    { key='antonio_garcia', name='Antonio Garcia', bucket='gt', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='nicky_catsburg', name='Nicky Catsburg', bucket='gt', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='valentino_rossi', name='Valentino Rossi', bucket='gt', pace=0.68, aggr=0.60, risk=0.42, cons=0.72 },
    { key='sheldon_van_der_linde', name='Sheldon van der Linde', bucket='gt', pace=0.78, aggr=0.60, risk=0.36, cons=0.80 },
    { key='kelvin_van_der_linde', name='Kelvin van der Linde', bucket='gt', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='jules_gounon', name='Jules Gounon', bucket='gt', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='mirko_bortolotti', name='Mirko Bortolotti', bucket='gt', pace=0.74, aggr=0.61, risk=0.42, cons=0.72 },
    { key='maxime_martin', name='Maxime Martin', bucket='gt', pace=0.74, aggr=0.53, risk=0.42, cons=0.72 },
    { key='dries_vanthoor', name='Dries Vanthoor', bucket='gt', pace=0.68, aggr=0.68, risk=0.42, cons=0.72 },
    -- Touring
    { key='bernd_schneider', name='Bernd Schneider', bucket='touring', pace=0.92, aggr=0.61, risk=0.36, cons=0.87 },
    { key='klaus_ludwig', name='Klaus Ludwig', bucket='touring', pace=0.84, aggr=0.53, risk=0.42, cons=0.81 },
    { key='mattias_ekstrom', name='Mattias Ekstrom', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='rene_rast', name='Rene Rast', bucket='touring', pace=0.84, aggr=0.53, risk=0.30, cons=0.91 },
    { key='peter_brock', name='Peter Brock', bucket='touring', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='craig_lowndes', name='Craig Lowndes', bucket='touring', pace=0.84, aggr=0.84, risk=0.48, cons=0.76 },
    { key='jamie_whincup', name='Jamie Whincup', bucket='touring', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='shane_van_gisbergen', name='Shane van Gisbergen', bucket='touring', pace=0.90, aggr=0.68, risk=0.42, cons=0.81 },
    { key='colin_turkington', name='Colin Turkington', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.89 },
    { key='jason_plato', name='Jason Plato', bucket='touring', pace=0.81, aggr=0.84, risk=0.42, cons=0.78 },
    { key='matt_neal', name='Matt Neal', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='ash_sutton', name='Ash Sutton', bucket='touring', pace=0.93, aggr=0.76, risk=0.42, cons=0.84 },
    { key='andy_priaulx', name='Andy Priaulx', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='yvan_muller', name='Yvan Muller', bucket='touring', pace=0.92, aggr=0.61, risk=0.42, cons=0.87 },
    { key='gabriele_tarquini', name='Gabriele Tarquini', bucket='touring', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='jose_maria_lopez', name='Jose Maria Lopez', bucket='touring', pace=0.97, aggr=0.60, risk=0.42, cons=0.87 },
    { key='alain_menu', name='Alain Menu', bucket='touring', pace=0.81, aggr=0.46, risk=0.36, cons=0.78 },
    -- Rally
    { key='sebastien_loeb', name='Sebastien Loeb', bucket='rally', pace=0.96, aggr=0.46, risk=0.17, cons=0.97 },
    { key='sebastien_ogier', name='Sebastien Ogier', bucket='rally', pace=0.93, aggr=0.60, risk=0.24, cons=0.97 },
    { key='tommi_makinen', name='Tommi Makinen', bucket='rally', pace=0.77, aggr=0.84, risk=0.61, cons=0.70 },
    { key='colin_mcrae', name='Colin McRae', bucket='rally', pace=0.69, aggr=0.76, risk=0.85, cons=0.40 },
    { key='richard_burns', name='Richard Burns', bucket='rally', pace=0.69, aggr=0.46, risk=0.29, cons=0.84 },
    { key='carlos_sainz_sr', name='Carlos Sainz Sr.', bucket='rally', pace=0.72, aggr=0.61, risk=0.32, cons=0.84 },
    { key='juha_kankkunen', name='Juha Kankkunen', bucket='rally', pace=0.77, aggr=0.46, risk=0.16, cons=0.97 },
    { key='marcus_gronholm', name='Marcus Gronholm', bucket='rally', pace=0.73, aggr=0.68, risk=0.50, cons=0.74 },
    { key='petter_solberg', name='Petter Solberg', bucket='rally', pace=0.67, aggr=0.76, risk=0.58, cons=0.59 },
    { key='walter_rohrl', name='Walter Rohrl', bucket='rally', pace=0.73, aggr=0.46, risk=0.34, cons=0.78 },
    { key='hannu_mikkola', name='Hannu Mikkola', bucket='rally', pace=0.69, aggr=0.53, risk=0.43, cons=0.77 },
    { key='michele_mouton', name='Michele Mouton', bucket='rally', pace=0.65, aggr=0.68, risk=0.55, cons=0.64 },
    { key='ari_vatanen', name='Ari Vatanen', bucket='rally', pace=0.68, aggr=0.76, risk=0.81, cons=0.44 },
    { key='henri_toivonen', name='Henri Toivonen', bucket='rally', pace=0.68, aggr=0.60, risk=0.85, cons=0.40 },
    { key='kalle_rovanpera', name='Kalle Rovanpera', bucket='rally', pace=0.76, aggr=0.68, risk=0.47, cons=0.76 },
    { key='ott_tanak', name='Ott Tanak', bucket='rally', pace=0.69, aggr=0.68, risk=0.51, cons=0.65 },
    { key='thierry_neuville', name='Thierry Neuville', bucket='rally', pace=0.69, aggr=0.60, risk=0.61, cons=0.57 },
    { key='elfyn_evans', name='Elfyn Evans', bucket='rally', pace=0.66, aggr=0.46, risk=0.18, cons=0.89 },
    -- Drift
    { key='james_deane', name='James Deane', bucket='drift', pace=0.97, aggr=0.61, risk=0.36, cons=0.92 },
    { key='fredric_aasbo', name='Fredric Aasbo', bucket='drift', pace=0.84, aggr=0.53, risk=0.36, cons=0.86 },
    { key='chris_forsberg', name='Chris Forsberg', bucket='drift', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='vaughn_gittin_jr', name='Vaughn Gittin Jr.', bucket='drift', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='daigo_saito', name='Daigo Saito', bucket='drift', pace=0.88, aggr=0.76, risk=0.42, cons=0.84 },
    { key='keiichi_tsuchiya', name='Keiichi Tsuchiya', bucket='drift', pace=0.74, aggr=0.68, risk=0.48, cons=0.67 },
    { key='masato_kawabata', name='Masato Kawabata', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='adam_lz', name='Adam LZ', bucket='drift', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='conor_shanahan', name='Conor Shanahan', bucket='drift', pace=0.78, aggr=0.76, risk=0.48, cons=0.75 },
    { key='hiroya_minowa', name='Hiroya Minowa', bucket='drift', pace=0.68, aggr=0.68, risk=0.48, cons=0.72 },
    -- F1-classic
    { key='rubens_barrichello', name='Rubens Barrichello', bucket='f1', pace=0.65, aggr=0.53, risk=0.34, cons=0.76 },
    { key='ralf_schumacher', name='Ralf Schumacher', bucket='f1', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='giancarlo_fisichella', name='Giancarlo Fisichella', bucket='f1', pace=0.63, aggr=0.60, risk=0.35, cons=0.76 },
    { key='jarno_trulli', name='Jarno Trulli', bucket='f1', pace=0.63, aggr=0.60, risk=0.33, cons=0.77 },
    { key='eddie_irvine', name='Eddie Irvine', bucket='f1', pace=0.64, aggr=0.68, risk=0.45, cons=0.67 },
    { key='heinz_harald_frentzen', name='Heinz-Harald Frentzen', bucket='f1', pace=0.63, aggr=0.53, risk=0.38, cons=0.73 },
    { key='johnny_herbert', name='Johnny Herbert', bucket='f1', pace=0.63, aggr=0.60, risk=0.44, cons=0.68 },
    { key='nick_heidfeld', name='Nick Heidfeld', bucket='f1', pace=0.63, aggr=0.53, risk=0.20, cons=0.88 },
    { key='heikki_kovalainen', name='Heikki Kovalainen', bucket='f1', pace=0.63, aggr=0.61, risk=0.43, cons=0.74 },
    { key='romain_grosjean', name='Romain Grosjean', bucket='f1', pace=0.62, aggr=0.60, risk=0.60, cons=0.54 },
    { key='pastor_maldonado', name='Pastor Maldonado', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='kevin_magnussen', name='Kevin Magnussen', bucket='f1', pace=0.62, aggr=0.68, risk=0.35, cons=0.76 },
    { key='daniil_kvyat', name='Daniil Kvyat', bucket='f1', pace=0.62, aggr=0.60, risk=0.42, cons=0.70 },
    { key='yuki_tsunoda', name='Yuki Tsunoda', bucket='f1', pace=0.62, aggr=0.60, risk=0.45, cons=0.67 },
    { key='takuma_sato', name='Takuma Sato', bucket='f1', pace=0.62, aggr=0.68, risk=0.70, cons=0.46 },
    { key='mick_schumacher', name='Mick Schumacher', bucket='f1', pace=0.62, aggr=0.53, risk=0.48, cons=0.69 },
    { key='logan_sargeant', name='Logan Sargeant', bucket='f1', pace=0.62, aggr=0.60, risk=0.54, cons=0.59 },
    { key='jos_verstappen', name='Jos Verstappen', bucket='f1', pace=0.62, aggr=0.60, risk=0.55, cons=0.59 },
    { key='riccardo_patrese', name='Riccardo Patrese', bucket='f1', pace=0.64, aggr=0.60, risk=0.42, cons=0.69 },
    { key='michele_alboreto', name='Michele Alboreto', bucket='f1', pace=0.64, aggr=0.53, risk=0.42, cons=0.70 },
    { key='andrea_de_cesaris', name='Andrea de Cesaris', bucket='f1', pace=0.62, aggr=0.68, risk=0.85, cons=0.40 },
    { key='derek_warwick', name='Derek Warwick', bucket='f1', pace=0.62, aggr=0.68, risk=0.45, cons=0.68 },
    { key='martin_brundle', name='Martin Brundle', bucket='f1', pace=0.62, aggr=0.68, risk=0.43, cons=0.69 },
    { key='eddie_cheever', name='Eddie Cheever', bucket='f1', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='thierry_boutsen', name='Thierry Boutsen', bucket='f1', pace=0.63, aggr=0.46, risk=0.28, cons=0.77 },
    { key='keke_rosberg', name='Keke Rosberg', bucket='f1', pace=0.68, aggr=0.84, risk=0.51, cons=0.65 },
    { key='alan_jones', name='Alan Jones', bucket='f1', pace=0.70, aggr=0.68, risk=0.36, cons=0.78 },
    { key='carlos_reutemann', name='Carlos Reutemann', bucket='f1', pace=0.67, aggr=0.60, risk=0.32, cons=0.78 },
    { key='clay_regazzoni', name='Clay Regazzoni', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='emerson_fittipaldi', name='Emerson Fittipaldi', bucket='f1', pace=0.73, aggr=0.46, risk=0.26, cons=0.84 },
    { key='jacques_laffite', name='Jacques Laffite', bucket='f1', pace=0.65, aggr=0.53, risk=0.42, cons=0.75 },
    { key='rene_arnoux', name='Rene Arnoux', bucket='f1', pace=0.66, aggr=0.68, risk=0.44, cons=0.68 },
    { key='didier_pironi', name='Didier Pironi', bucket='f1', pace=0.65, aggr=0.68, risk=0.48, cons=0.65 },
    { key='john_watson', name='John Watson', bucket='f1', pace=0.64, aggr=0.60, risk=0.39, cons=0.73 },
    { key='patrick_tambay', name='Patrick Tambay', bucket='f1', pace=0.64, aggr=0.53, risk=0.39, cons=0.72 },
    { key='elio_de_angelis', name='Elio de Angelis', bucket='f1', pace=0.63, aggr=0.53, risk=0.42, cons=0.70 },
    { key='jean_pierre_jabouille', name='Jean-Pierre Jabouille', bucket='f1', pace=0.65, aggr=0.60, risk=0.50, cons=0.63 },
    { key='francois_cevert', name='Francois Cevert', bucket='f1', pace=0.65, aggr=0.53, risk=0.46, cons=0.67 },
    { key='patrick_depailler', name='Patrick Depailler', bucket='f1', pace=0.64, aggr=0.76, risk=0.63, cons=0.57 },
    -- Vintage
    { key='nino_farina', name='Nino Farina', bucket='vintage', pace=0.74, aggr=0.68, risk=0.63, cons=0.55 },
    { key='jose_froilan_gonzalez', name='Jose Froilan Gonzalez', bucket='vintage', pace=0.69, aggr=0.60, risk=0.38, cons=0.73 },
    { key='tony_brooks', name='Tony Brooks', bucket='vintage', pace=0.68, aggr=0.53, risk=0.33, cons=0.73 },
    { key='peter_collins', name='Peter Collins', bucket='vintage', pace=0.66, aggr=0.68, risk=0.42, cons=0.69 },
    { key='maurice_trintignant', name='Maurice Trintignant', bucket='vintage', pace=0.63, aggr=0.53, risk=0.34, cons=0.86 },
    { key='richie_ginther', name='Richie Ginther', bucket='vintage', pace=0.64, aggr=0.53, risk=0.33, cons=0.82 },
    { key='wolfgang_von_trips', name='Wolfgang von Trips', bucket='vintage', pace=0.65, aggr=0.68, risk=0.57, cons=0.57 },
    { key='jean_behra', name='Jean Behra', bucket='vintage', pace=0.63, aggr=0.68, risk=0.48, cons=0.65 },
    { key='jo_siffert', name='Jo Siffert', bucket='vintage', pace=0.63, aggr=0.76, risk=0.46, cons=0.72 },
    { key='chris_amon', name='Chris Amon', bucket='vintage', pace=0.63, aggr=0.60, risk=0.40, cons=0.72 },
    -- Formula-Indy
    { key='aj_foyt', name='A.J. Foyt', bucket='f1', pace=0.92, aggr=0.68, risk=0.42, cons=0.93 },
    { key='scott_dixon', name='Scott Dixon', bucket='f1', pace=0.92, aggr=0.60, risk=0.36, cons=0.95 },
    { key='will_power', name='Will Power', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='michael_andretti', name='Michael Andretti', bucket='f1', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='al_unser', name='Al Unser', bucket='f1', pace=0.84, aggr=0.46, risk=0.36, cons=0.81 },
    { key='sebastien_bourdais', name='Sebastien Bourdais', bucket='f1', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='bobby_unser', name='Bobby Unser', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='al_unser_jr', name='Al Unser Jr.', bucket='f1', pace=0.81, aggr=0.53, risk=0.42, cons=0.78 },
    { key='josef_newgarden', name='Josef Newgarden', bucket='f1', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='paul_tracy', name='Paul Tracy', bucket='f1', pace=0.78, aggr=0.68, risk=0.48, cons=0.70 },
    { key='dario_franchitti', name='Dario Franchitti', bucket='f1', pace=0.88, aggr=0.46, risk=0.36, cons=0.89 },
    { key='helio_castroneves', name='Helio Castroneves', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='rick_mears', name='Rick Mears', bucket='f1', pace=0.84, aggr=0.53, risk=0.36, cons=0.81 },
    { key='johnny_rutherford', name='Johnny Rutherford', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='alex_palou', name='Alex Palou', bucket='f1', pace=0.92, aggr=0.68, risk=0.36, cons=0.97 },
    { key='bobby_rahal', name='Bobby Rahal', bucket='f1', pace=0.84, aggr=0.53, risk=0.30, cons=0.86 },
    { key='sam_hornish_jr', name='Sam Hornish Jr.', bucket='f1', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='ryan_hunter_reay', name='Ryan Hunter-Reay', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='tony_kanaan', name='Tony Kanaan', bucket='f1', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='alex_zanardi', name='Alex Zanardi', bucket='f1', pace=0.81, aggr=0.76, risk=0.48, cons=0.78 },
    { key='simon_pagenaud', name='Simon Pagenaud', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='gil_de_ferran', name='Gil de Ferran', bucket='f1', pace=0.81, aggr=0.53, risk=0.36, cons=0.83 },
    { key='pato_oward', name='Pato O\'Ward', bucket='f1', pace=0.74, aggr=0.76, risk=0.42, cons=0.72 },
    { key='colton_herta', name='Colton Herta', bucket='f1', pace=0.74, aggr=0.68, risk=0.54, cons=0.62 },
    { key='alexander_rossi', name='Alexander Rossi', bucket='f1', pace=0.74, aggr=0.68, risk=0.42, cons=0.72 },
    { key='scott_mclaughlin', name='Scott McLaughlin', bucket='f1', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='parnelli_jones', name='Parnelli Jones', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    -- Rally
    { key='didier_auriol', name='Didier Auriol', bucket='rally', pace=0.69, aggr=0.53, risk=0.38, cons=0.71 },
    { key='markku_alen', name='Markku Alen', bucket='rally', pace=0.67, aggr=0.76, risk=0.60, cons=0.59 },
    { key='jari_matti_latvala', name='Jari-Matti Latvala', bucket='rally', pace=0.69, aggr=0.60, risk=0.65, cons=0.51 },
    { key='miki_biasion', name='Miki Biasion', bucket='rally', pace=0.74, aggr=0.46, risk=0.23, cons=0.92 },
    { key='bjorn_waldegard', name='Bjorn Waldegard', bucket='rally', pace=0.70, aggr=0.53, risk=0.34, cons=0.74 },
    { key='mikko_hirvonen', name='Mikko Hirvonen', bucket='rally', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='stig_blomqvist', name='Stig Blomqvist', bucket='rally', pace=0.68, aggr=0.60, risk=0.39, cons=0.75 },
    { key='timo_salonen', name='Timo Salonen', bucket='rally', pace=0.68, aggr=0.60, risk=0.45, cons=0.71 },
    { key='sandro_munari', name='Sandro Munari', bucket='rally', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='gilles_panizzi', name='Gilles Panizzi', bucket='rally', pace=0.62, aggr=0.68, risk=0.42, cons=0.72 },
    { key='markko_martin', name='Markko Martin', bucket='rally', pace=0.62, aggr=0.53, risk=0.36, cons=0.72 },
    { key='kris_meeke', name='Kris Meeke', bucket='rally', pace=0.67, aggr=0.60, risk=0.65, cons=0.50 },
    { key='dani_sordo', name='Dani Sordo', bucket='rally', pace=0.64, aggr=0.60, risk=0.26, cons=0.83 },
    { key='andreas_mikkelsen', name='Andreas Mikkelsen', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.67 },
    { key='esapekka_lappi', name='Esapekka Lappi', bucket='rally', pace=0.63, aggr=0.60, risk=0.46, cons=0.66 },
    { key='oliver_solberg', name='Oliver Solberg', bucket='rally', pace=0.62, aggr=0.76, risk=0.48, cons=0.67 },
    { key='takamoto_katsuta', name='Takamoto Katsuta', bucket='rally', pace=0.62, aggr=0.60, risk=0.48, cons=0.67 },
    -- Prototype
    { key='frank_biela', name='Frank Biela', bucket='proto', pace=0.94, aggr=0.53, risk=0.42, cons=0.88 },
    { key='emanuele_pirro', name='Emanuele Pirro', bucket='proto', pace=0.86, aggr=0.53, risk=0.42, cons=0.72 },
    { key='olivier_gendebien', name='Olivier Gendebien', bucket='proto', pace=0.84, aggr=0.46, risk=0.30, cons=0.77 },
    { key='yannick_dalmas', name='Yannick Dalmas', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.77 },
    { key='al_holbert', name='Al Holbert', bucket='proto', pace=0.84, aggr=0.60, risk=0.36, cons=0.77 },
    { key='hurley_haywood', name='Hurley Haywood', bucket='proto', pace=0.80, aggr=0.53, risk=0.42, cons=0.72 },
    { key='bob_wollek', name='Bob Wollek', bucket='proto', pace=0.75, aggr=0.60, risk=0.42, cons=0.72 },
    { key='loic_duval', name='Loic Duval', bucket='proto', pace=0.80, aggr=0.68, risk=0.42, cons=0.75 },
    { key='anthony_davidson', name='Anthony Davidson', bucket='proto', pace=0.79, aggr=0.53, risk=0.36, cons=0.75 },
    { key='mike_rockenfeller', name='Mike Rockenfeller', bucket='proto', pace=0.81, aggr=0.60, risk=0.30, cons=0.85 },
    { key='earl_bamber', name='Earl Bamber', bucket='proto', pace=0.83, aggr=0.68, risk=0.42, cons=0.75 },
    { key='nick_tandy', name='Nick Tandy', bucket='proto', pace=0.76, aggr=0.84, risk=0.42, cons=0.72 },
    { key='alexander_wurz', name='Alexander Wurz', bucket='proto', pace=0.82, aggr=0.53, risk=0.42, cons=0.72 },
    { key='stephane_sarrazin', name='Stephane Sarrazin', bucket='proto', pace=0.77, aggr=0.60, risk=0.42, cons=0.72 },
    -- Touring
    { key='mark_skaife', name='Mark Skaife', bucket='touring', pace=0.92, aggr=0.54, risk=0.36, cons=0.87 },
    { key='dick_johnson', name='Dick Johnson', bucket='touring', pace=0.92, aggr=0.68, risk=0.42, cons=0.87 },
    { key='allan_moffat', name='Allan Moffat', bucket='touring', pace=0.88, aggr=0.46, risk=0.30, cons=0.89 },
    { key='garth_tander', name='Garth Tander', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='andy_rouse', name='Andy Rouse', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    { key='fabrizio_giovanardi', name='Fabrizio Giovanardi', bucket='touring', pace=0.81, aggr=0.76, risk=0.42, cons=0.78 },
    { key='gordon_shedden', name='Gordon Shedden', bucket='touring', pace=0.81, aggr=0.68, risk=0.36, cons=0.83 },
    { key='rickard_rydell', name='Rickard Rydell', bucket='touring', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='laurent_aiello', name='Laurent Aiello', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='john_cleland', name='John Cleland', bucket='touring', pace=0.78, aggr=0.68, risk=0.42, cons=0.75 },
    { key='james_thompson', name='James Thompson', bucket='touring', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='gary_paffett', name='Gary Paffett', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='marco_wittmann', name='Marco Wittmann', bucket='touring', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    { key='timo_scheider', name='Timo Scheider', bucket='touring', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='roberto_ravaglia', name='Roberto Ravaglia', bucket='touring', pace=0.88, aggr=0.53, risk=0.36, cons=0.84 },
    -- Drift
    { key='samuel_hubinette', name='Samuel Hubinette', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    { key='rhys_millen', name='Rhys Millen', bucket='drift', pace=0.78, aggr=0.68, risk=0.48, cons=0.75 },
    { key='tanner_foust', name='Tanner Foust', bucket='drift', pace=0.81, aggr=0.53, risk=0.36, cons=0.78 },
    { key='daijiro_yoshihara', name='Daijiro Yoshihara', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='michael_essa', name='Michael Essa', bucket='drift', pace=0.78, aggr=0.53, risk=0.30, cons=0.85 },
    { key='chelsea_denofa', name='Chelsea DeNofa', bucket='drift', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='ryan_tuerck', name='Ryan Tuerck', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='aurimas_bakchis', name='Aurimas Bakchis', bucket='drift', pace=0.74, aggr=0.53, risk=0.30, cons=0.77 },
    { key='matt_field', name='Matt Field', bucket='drift', pace=0.74, aggr=0.60, risk=0.42, cons=0.72 },
    { key='mad_mike_whiddett', name='Mad Mike Whiddett', bucket='drift', pace=0.81, aggr=0.68, risk=0.42, cons=0.78 },
    -- NASCAR-modern
    { key='denny_hamlin', name='Denny Hamlin', bucket='nascar', pace=0.78, aggr=0.53, risk=0.28, cons=0.81 },
    { key='kyle_busch', name='Kyle Busch', bucket='nascar', pace=0.94, aggr=0.68, risk=0.39, cons=0.78 },
    { key='joey_logano', name='Joey Logano', bucket='nascar', pace=0.96, aggr=0.68, risk=0.32, cons=0.87 },
    { key='brad_keselowski', name='Brad Keselowski', bucket='nascar', pace=0.81, aggr=0.68, risk=0.31, cons=0.82 },
    { key='martin_truex_jr', name='Martin Truex Jr.', bucket='nascar', pace=0.79, aggr=0.53, risk=0.27, cons=0.80 },
    { key='kyle_larson', name='Kyle Larson', bucket='nascar', pace=0.91, aggr=0.60, risk=0.39, cons=0.78 },
    { key='chase_elliott', name='Chase Elliott', bucket='nascar', pace=0.82, aggr=0.53, risk=0.21, cons=0.85 },
    { key='ryan_blaney', name='Ryan Blaney', bucket='nascar', pace=0.80, aggr=0.53, risk=0.39, cons=0.75 },
    { key='william_byron', name='William Byron', bucket='nascar', pace=0.73, aggr=0.46, risk=0.39, cons=0.72 },
    { key='christopher_bell', name='Christopher Bell', bucket='nascar', pace=0.75, aggr=0.46, risk=0.33, cons=0.72 },
    { key='tyler_reddick', name='Tyler Reddick', bucket='nascar', pace=0.73, aggr=0.68, risk=0.36, cons=0.75 },
    { key='ross_chastain', name='Ross Chastain', bucket='nascar', pace=0.67, aggr=0.68, risk=0.38, cons=0.73 },
    { key='chase_briscoe', name='Chase Briscoe', bucket='nascar', pace=0.70, aggr=0.60, risk=0.37, cons=0.74 },
    { key='chris_buescher', name='Chris Buescher', bucket='nascar', pace=0.66, aggr=0.53, risk=0.31, cons=0.84 },
    { key='alex_bowman', name='Alex Bowman', bucket='nascar', pace=0.67, aggr=0.53, risk=0.43, cons=0.74 },
    { key='bubba_wallace', name='Bubba Wallace', bucket='nascar', pace=0.66, aggr=0.60, risk=0.49, cons=0.64 },
    { key='shane_van_gisbergen_x', name='Shane van Gisbergen', bucket='nascar', pace=0.74, aggr=0.60, risk=0.35, cons=0.76 },
    { key='ty_gibbs', name='Ty Gibbs', bucket='nascar', pace=0.68, aggr=0.68, risk=0.44, cons=0.68 },
    { key='carson_hocevar', name='Carson Hocevar', bucket='nascar', pace=0.66, aggr=0.68, risk=0.45, cons=0.67 },
    { key='austin_cindric', name='Austin Cindric', bucket='nascar', pace=0.66, aggr=0.53, risk=0.37, cons=0.74 },
    { key='ricky_stenhouse_jr', name='Ricky Stenhouse Jr.', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    { key='austin_dillon', name='Austin Dillon', bucket='nascar', pace=0.65, aggr=0.68, risk=0.37, cons=0.74 },
    { key='aj_allmendinger', name='A.J. Allmendinger', bucket='nascar', pace=0.64, aggr=0.60, risk=0.33, cons=0.77 },
    { key='michael_mcdowell', name='Michael McDowell', bucket='nascar', pace=0.62, aggr=0.60, risk=0.39, cons=0.72 },
    { key='ryan_preece', name='Ryan Preece', bucket='nascar', pace=0.64, aggr=0.60, risk=0.44, cons=0.68 },
    -- NASCAR-classic
    { key='richard_petty', name='Richard Petty', bucket='nascar', pace=0.96, aggr=0.68, risk=0.42, cons=0.93 },
    { key='david_pearson', name='David Pearson', bucket='nascar', pace=0.82, aggr=0.53, risk=0.36, cons=0.81 },
    { key='jeff_gordon', name='Jeff Gordon', bucket='nascar', pace=0.82, aggr=0.53, risk=0.42, cons=0.84 },
    { key='bobby_allison', name='Bobby Allison', bucket='nascar', pace=0.70, aggr=0.68, risk=0.48, cons=0.75 },
    { key='darrell_waltrip', name='Darrell Waltrip', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.81 },
    { key='jimmie_johnson', name='Jimmie Johnson', bucket='nascar', pace=0.94, aggr=0.61, risk=0.36, cons=0.97 },
    { key='cale_yarborough', name='Cale Yarborough', bucket='nascar', pace=0.80, aggr=0.68, risk=0.48, cons=0.81 },
    { key='dale_earnhardt', name='Dale Earnhardt', bucket='nascar', pace=0.93, aggr=0.60, risk=0.42, cons=0.93 },
    { key='kevin_harvick', name='Kevin Harvick', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='rusty_wallace', name='Rusty Wallace', bucket='nascar', pace=0.69, aggr=0.68, risk=0.42, cons=0.75 },
    { key='tony_stewart', name='Tony Stewart', bucket='nascar', pace=0.76, aggr=0.60, risk=0.42, cons=0.81 },
    { key='bill_elliott', name='Bill Elliott', bucket='nascar', pace=0.68, aggr=0.60, risk=0.42, cons=0.75 },
    { key='mark_martin', name='Mark Martin', bucket='nascar', pace=0.64, aggr=0.60, risk=0.36, cons=0.77 },
    { key='matt_kenseth', name='Matt Kenseth', bucket='nascar', pace=0.68, aggr=0.53, risk=0.30, cons=0.80 },
    { key='kurt_busch', name='Kurt Busch', bucket='nascar', pace=0.67, aggr=0.60, risk=0.42, cons=0.75 },
    { key='dale_jarrett', name='Dale Jarrett', bucket='nascar', pace=0.67, aggr=0.53, risk=0.36, cons=0.80 },
    { key='carl_edwards', name='Carl Edwards', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='dale_earnhardt_jr', name='Dale Earnhardt Jr.', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='terry_labonte', name='Terry Labonte', bucket='nascar', pace=0.71, aggr=0.53, risk=0.42, cons=0.83 },
    { key='ricky_rudd', name='Ricky Rudd', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='alan_kulwicki', name='Alan Kulwicki', bucket='nascar', pace=0.68, aggr=0.53, risk=0.36, cons=0.75 },
    { key='davey_allison', name='Davey Allison', bucket='nascar', pace=0.66, aggr=0.68, risk=0.42, cons=0.72 },
    { key='tim_richmond', name='Tim Richmond', bucket='nascar', pace=0.65, aggr=0.76, risk=0.48, cons=0.67 },
    { key='junior_johnson', name='Junior Johnson', bucket='nascar', pace=0.69, aggr=0.76, risk=0.54, cons=0.72 },
    { key='ned_jarrett', name='Ned Jarrett', bucket='nascar', pace=0.75, aggr=0.60, risk=0.36, cons=0.83 },
    { key='fireball_roberts', name='Fireball Roberts', bucket='nascar', pace=0.69, aggr=0.60, risk=0.42, cons=0.72 },
    { key='curtis_turner', name='Curtis Turner', bucket='nascar', pace=0.66, aggr=0.84, risk=0.60, cons=0.62 },
    { key='lee_petty', name='Lee Petty', bucket='nascar', pace=0.76, aggr=0.53, risk=0.30, cons=0.86 },
    { key='herb_thomas', name='Herb Thomas', bucket='nascar', pace=0.78, aggr=0.60, risk=0.42, cons=0.78 },
    { key='tim_flock', name='Tim Flock', bucket='nascar', pace=0.79, aggr=0.60, risk=0.42, cons=0.78 },
    { key='buck_baker', name='Buck Baker', bucket='nascar', pace=0.73, aggr=0.60, risk=0.42, cons=0.78 },
    { key='bobby_isaac', name='Bobby Isaac', bucket='nascar', pace=0.71, aggr=0.60, risk=0.42, cons=0.75 },
    { key='buddy_baker', name='Buddy Baker', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='benny_parsons', name='Benny Parsons', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='harry_gant', name='Harry Gant', bucket='nascar', pace=0.63, aggr=0.60, risk=0.36, cons=0.77 },
    { key='ernie_irvan', name='Ernie Irvan', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='geoff_bodine', name='Geoff Bodine', bucket='nascar', pace=0.64, aggr=0.68, risk=0.42, cons=0.72 },
    { key='sterling_marlin', name='Sterling Marlin', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='jeff_burton', name='Jeff Burton', bucket='nascar', pace=0.63, aggr=0.53, risk=0.36, cons=0.77 },
    { key='bobby_labonte', name='Bobby Labonte', bucket='nascar', pace=0.67, aggr=0.46, risk=0.42, cons=0.80 },
    { key='ryan_newman', name='Ryan Newman', bucket='nascar', pace=0.63, aggr=0.60, risk=0.42, cons=0.72 },
    { key='greg_biffle', name='Greg Biffle', bucket='nascar', pace=0.63, aggr=0.68, risk=0.36, cons=0.77 },
    { key='kasey_kahne', name='Kasey Kahne', bucket='nascar', pace=0.63, aggr=0.53, risk=0.42, cons=0.72 },
    { key='ken_schrader', name='Ken Schrader', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    { key='dave_marcis', name='Dave Marcis', bucket='nascar', pace=0.62, aggr=0.60, risk=0.42, cons=0.72 },
    -- Oval-Indy
    { key='rodger_ward', name='Rodger Ward', bucket='f1', pace=0.81, aggr=0.46, risk=0.30, cons=0.78 },
    { key='gordon_johncock', name='Gordon Johncock', bucket='f1', pace=0.78, aggr=0.60, risk=0.42, cons=0.75 },
    { key='jimmy_bryan', name='Jimmy Bryan', bucket='f1', pace=0.84, aggr=0.60, risk=0.42, cons=0.81 },
    { key='dan_wheldon', name='Dan Wheldon', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.75 },
    { key='tom_sneva', name='Tom Sneva', bucket='f1', pace=0.81, aggr=0.68, risk=0.48, cons=0.78 },
    { key='buddy_lazier', name='Buddy Lazier', bucket='f1', pace=0.78, aggr=0.53, risk=0.42, cons=0.80 },
    { key='arie_luyendyk', name='Arie Luyendyk', bucket='f1', pace=0.74, aggr=0.68, risk=0.48, cons=0.72 },
    { key='wilbur_shaw', name='Wilbur Shaw', bucket='f1', pace=0.81, aggr=0.60, risk=0.42, cons=0.78 },
    { key='mauri_rose', name='Mauri Rose', bucket='f1', pace=0.78, aggr=0.53, risk=0.36, cons=0.75 },
    { key='bill_vukovich', name='Bill Vukovich', bucket='f1', pace=0.79, aggr=0.68, risk=0.42, cons=0.72 },
    -- Oval-Dirt
    { key='steve_kinser', name='Steve Kinser', bucket='nascar', pace=0.92, aggr=0.68, risk=0.42, cons=0.97 },
    { key='sammy_swindell', name='Sammy Swindell', bucket='nascar', pace=0.84, aggr=0.68, risk=0.42, cons=0.81 },
    { key='donny_schatz', name='Donny Schatz', bucket='nascar', pace=0.92, aggr=0.60, risk=0.36, cons=0.97 },
    { key='mark_kinser', name='Mark Kinser', bucket='nascar', pace=0.81, aggr=0.60, risk=0.36, cons=0.83 },
    -- Cross-category appearances
    { key='max_verstappen_kart', name='Max Verstappen', bucket='kart', pace=1.00, aggr=0.76, risk=0.29, cons=0.93 },
    { key='ayrton_senna_kart', name='Ayrton Senna', bucket='kart', pace=0.96, aggr=0.68, risk=0.56, cons=0.67 },
    { key='michael_schumacher_kart', name='Michael Schumacher', bucket='kart', pace=0.96, aggr=0.76, risk=0.33, cons=0.97 },
    { key='lewis_hamilton_kart', name='Lewis Hamilton', bucket='kart', pace=0.97, aggr=0.53, risk=0.23, cons=0.97 },
    { key='lando_norris_kart', name='Lando Norris', bucket='kart', pace=0.98, aggr=0.53, risk=0.20, cons=0.86 },
    { key='fernando_alonso_proto', name='Fernando Alonso', bucket='proto', pace=0.90, aggr=0.60, risk=0.29, cons=0.87 },
    { key='nico_hulkenberg_proto', name='Nico Hulkenberg', bucket='proto', pace=0.88, aggr=0.53, risk=0.30, cons=0.85 },
    { key='mark_webber_proto', name='Mark Webber', bucket='proto', pace=0.92, aggr=0.68, risk=0.33, cons=0.78 },
    { key='juan_pablo_montoya_proto', name='Juan Pablo Montoya', bucket='proto', pace=0.85, aggr=0.84, risk=0.60, cons=0.55 },
    { key='jenson_button_proto', name='Jenson Button', bucket='proto', pace=0.80, aggr=0.46, risk=0.30, cons=0.83 },
    { key='robert_kubica_proto', name='Robert Kubica', bucket='proto', pace=0.85, aggr=0.61, risk=0.28, cons=0.77 },
    { key='mario_andretti_proto', name='Mario Andretti', bucket='proto', pace=0.88, aggr=0.60, risk=0.42, cons=0.72 },
    { key='fernando_alonso_gt', name='Fernando Alonso', bucket='gt', pace=0.86, aggr=0.60, risk=0.29, cons=0.87 },
    { key='juan_pablo_montoya_gt', name='Juan Pablo Montoya', bucket='gt', pace=0.84, aggr=0.84, risk=0.60, cons=0.55 },
    { key='jenson_button_gt', name='Jenson Button', bucket='gt', pace=0.82, aggr=0.46, risk=0.30, cons=0.83 },
    { key='kimi_raikkonen_rally', name='Kimi Raikkonen', bucket='rally', pace=0.58, aggr=0.60, risk=0.30, cons=0.83 },
    { key='robert_kubica_rally', name='Robert Kubica', bucket='rally', pace=0.62, aggr=0.61, risk=0.28, cons=0.77 },
    { key='hans_joachim_stuck_touring', name='Hans-Joachim Stuck', bucket='touring', pace=0.88, aggr=0.84, risk=0.48, cons=0.70 },
    { key='alex_zanardi_touring', name='Alex Zanardi', bucket='touring', pace=0.78, aggr=0.76, risk=0.48, cons=0.78 },
    { key='jacky_ickx_f1', name='Jacky Ickx', bucket='f1', pace=0.82, aggr=0.60, risk=0.42, cons=0.78 },
    { key='hans_joachim_stuck_f1', name='Hans-Joachim Stuck', bucket='f1', pace=0.68, aggr=0.84, risk=0.48, cons=0.70 },

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
local function recomputeFieldMaxPace()
    local m = 0
    for i, k in pairs(assigned) do
        if i ~= 0 then                       -- skip slot 0 (the player) -- a profile you assigned yourself
            local d = BY_KEY[k]              -- shouldn't drag the AI field's pace anchor around
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
    if i == 0 then return end
    pcall(function()
        if origName[i] == nil then origName[i] = ac.getDriverName(i) or '' end
        local key = assigned[i]
        local name = key and D.nameOf(key) or origName[i]
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
function D.reset() assigned = {}; baseLevel = {}; lastApplied = {}; fieldMaxPace = 1.0; paceDirty = true; origName = {}; matched = false end

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
function D.applyPace(i, base)
    pcall(function()
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
