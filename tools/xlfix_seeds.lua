-- xlfix seeds (26 Nov): paste into LuaJIT (luajit tools/xlfix_seeds.lua). Self-contained mirror of rc2 putBackOnLine's landing chain:
-- same-spot escape -> (xlfix) wrap guard -> gateSafe gate-first. Imola: splits 0.00067 / 0.31526 / 0.6772, 4909 m, GATE_FIRST_M 10000,
-- GATE_MARGIN 0.006. The gate's straight-spot walk and stagger are reduced to "just before split 1" (the seeds only ask: before split 1,
-- or not). Verifies logic, not the build.
local L, FIRST, LAST, MARGIN, GFM = 4909, 0.31526, 0.6772, 0.006, 10000
local DROP_SAME_M, DROP_SKIP_M = 200, 150
local function gateSafe(p)   -- rc2 lines 345-350: gate-first to split 1 when the landing is past it and within GATE_FIRST_M
    if p < FIRST - MARGIN * 0.5 or (p - FIRST) * L > GFM then return p, false end
    return FIRST - MARGIN, true
end
local function land(stop, stagger_m, spots, fix)
    local progress = (stop + stagger_m / L) % 1   -- the rescue's stagger is added by the caller, before putBackOnLine
    local stopProgress = stop
    local skipGate = false
    if spots then   -- same-spot escape (rc2 680-692)
        local near = 0
        for _, sp in ipairs(spots) do if math.abs((sp - progress + 0.5) % 1 - 0.5) * L < DROP_SAME_M then near = near + 1 end end
        if near >= 2 then progress = (progress + DROP_SKIP_M / L) % 1; skipGate = true end
    end
    local wrapGated = false
    if fix and not skipGate and stopProgress and progress < stopProgress - 0.5 then progress = stopProgress; wrapGated = true end   -- (xlfix)
    local gated = false
    if not skipGate then progress, gated = gateSafe(progress) end
    return progress, gated, wrapGated, skipGate
end
local fails = 0
local function check(name, ok, detail) print(string.format('%-62s %s  %s', name, ok and 'PASS' or 'FAIL', detail)); if not ok then fails = fails + 1 end end
-- SEED 1 (verve-47): stop 0.998, stagger +34 m -> must land before split 1, not at 0.005
local p, g, w = land(0.998, 34, nil, true)
check('S1 stop 0.998 +34 m, FIX: lands before split 1 (gated)', p < FIRST and p > 0.2 and g and w, string.format('land %.5f gated %s wrapGuard %s', p, tostring(g), tostring(w)))
p, g, w = land(0.998, 34, nil, false)
check('S1b same, rc2 (no fix): lands across the line at ~0.005 (the bug)', p > 0.00067 and p < 0.01 and not g, string.format('land %.5f gated %s', p, tostring(g)))
-- SEED 2 (verve-47): the same-spot escape near the line: stop 0.980, two earlier drops at 0.975 / 0.978 -> +150 m, skipGate
local p2, g2, w2, sk = land(0.980, 0, { 0.975, 0.978 }, true)
check('S2 escape stop 0.980 (2 prior spots), FIX: unchanged (skipGate)', sk and not w2 and not g2 and p2 > 0.00067 and p2 < 0.02, string.format('land %.5f skipGate %s wrapGuard %s (still across the line: the escape pays the lap by design)', p2, tostring(sk), tostring(w2)))
local p2b = land(0.980, 0, { 0.975, 0.978 }, false)
check('S2b same, rc2: identical landing', math.abs(p2b - p2) < 1e-9, string.format('land %.5f', p2b))
-- controls: the guard never fires without a wrap
local p3, g3, w3 = land(0.500, 34, nil, true)
check('S3 mid-lap stop 0.500 +34 m: no wrap, guard off, gate-first as rc2', not w3 and g3 and math.abs(p3 - land(0.500, 34, nil, false)) < 1e-9, string.format('land %.5f gated %s', p3, tostring(g3)))
local p4, g4, w4 = land(0.300, 34, nil, true)
check('S4 sector-1 stop 0.300 +34 m: no wrap, guard off, not gated', not w4 and not g4 and math.abs(p4 - (0.300 + 34 / L)) < 1e-9, string.format('land %.5f', p4))
local p5, g5, w5 = land(0.9995, 0, nil, true)
check('S5 stop 0.9995 +0 m (no stagger): no wrap, gate-first as rc2', not w5 and g5, string.format('land %.5f gated %s', p5, tostring(g5)))
print(fails == 0 and 'ALL PASS' or (fails .. ' FAIL'))
