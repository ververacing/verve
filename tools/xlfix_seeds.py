"""Python twin of tools/xlfix_seeds.lua (same chain, same seeds; Lua's % on floats = a - floor(a/b)*b, as Python's). python -I tools/xlfix_seeds.py"""
import math
L, FIRST, LAST, MARGIN, GFM = 4909, 0.31526, 0.6772, 0.006, 10000
DROP_SAME_M, DROP_SKIP_M = 200, 150
def mod(a, b): return a - math.floor(a / b) * b
def gate_safe(p):
    if p < FIRST - MARGIN * 0.5 or (p - FIRST) * L > GFM: return p, False
    return FIRST - MARGIN, True
def land(stop, stagger_m, spots, fix):
    progress = mod(stop + stagger_m / L, 1); stop_p = stop; skip = False
    if spots:
        near = sum(1 for sp in spots if abs(mod(sp - progress + 0.5, 1) - 0.5) * L < DROP_SAME_M)
        if near >= 2: progress = mod(progress + DROP_SKIP_M / L, 1); skip = True
    wg = False
    if fix and not skip and progress < stop_p - 0.5: progress = stop_p; wg = True
    g = False
    if not skip: progress, g = gate_safe(progress)
    return progress, g, wg, skip
fails = 0
def check(name, ok, d):
    global fails
    print("%-62s %s  %s" % (name, "PASS" if ok else "FAIL", d)); fails += (not ok)
p, g, w, _ = land(0.998, 34, None, True); check("S1 stop 0.998 +34 m, FIX: lands before split 1 (gated)", p < FIRST and p > 0.2 and g and w, "land %.5f gated %s wrapGuard %s" % (p, g, w))
p, g, w, _ = land(0.998, 34, None, False); check("S1b same, rc2 (no fix): lands across the line at ~0.005 (the bug)", 0.00067 < p < 0.01 and not g, "land %.5f gated %s" % (p, g))
p2, g2, w2, sk = land(0.980, 0, [0.975, 0.978], True); check("S2 escape stop 0.980 (2 prior spots), FIX: unchanged (skipGate)", sk and not w2 and not g2 and 0.00067 < p2 < 0.02, "land %.5f skipGate %s wrapGuard %s" % (p2, sk, w2))
p2b = land(0.980, 0, [0.975, 0.978], False)[0]; check("S2b same, rc2: identical landing", abs(p2b - p2) < 1e-9, "land %.5f" % p2b)
p3, g3, w3, _ = land(0.500, 34, None, True); check("S3 mid-lap stop 0.500 +34 m: no wrap, guard off, gate-first as rc2", (not w3) and g3 and abs(p3 - land(0.5, 34, None, False)[0]) < 1e-9, "land %.5f gated %s" % (p3, g3))
p4, g4, w4, _ = land(0.300, 34, None, True); check("S4 sector-1 stop 0.300 +34 m: no wrap, guard off, not gated", (not w4) and (not g4) and abs(p4 - (0.3 + 34 / L)) < 1e-9, "land %.5f" % p4)
p5, g5, w5, _ = land(0.9995, 0, None, True); check("S5 stop 0.9995 +0 m (no stagger): no wrap, gate-first as rc2", (not w5) and g5, "land %.5f gated %s" % (p5, g5))
print("ALL PASS" if fails == 0 else "%d FAIL" % fails)
