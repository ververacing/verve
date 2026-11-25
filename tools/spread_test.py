"""Spread-before-drop + rescue true-stop selftest (0.16.9 draft, 25 Nov 2026).

    python -I tools/spread_test.py               # the working tree
    python -I tools/spread_test.py --ref 79e3e7a # an older revision: must FAIL (no spread, rescue bypass)

No Lua interpreter on the desk: this reads lib/recovery.lua, checks the pieces are wired (signature, rescue call, reqProgress, the
spread block's guards, the drop record) and runs a Python MIRROR of the spread loop and the order rule as written. verve-47 runs the
real Lua separately. Imola 4864.1 m; DROP_NEAR 18 m, STAGGER_BASE 18 m, STAGGER_RANGE 45 m, GATE_BACK_MAX 0.03 (as scaleToTrack).
SEEDS
  T1 rescue bypass: stop 0.500, rescue stagger 50 m ahead, a car ahead in the race 40 m past the stop -> lands 10 m past the stop
     (30 m behind that car), not 50 m.
  T2 3-car forced stack: drops of cars 10, 8, 12 at 0.2963 / 0.2969 / 0.2971 within 0.4 s -> every pair >= 18 m apart.
  T3 lap-0 line guard: stop 0.0015 with another drop 2 m away -> never below 0 (no backward wrap across the line).
  T4 Reset my car (car 0), another drop 10 m away -> unchanged (car 0 spreads only under 4.5 m); at 3 m -> one step only.
  T5 a single isolated drop -> unchanged."""
import re, sys, subprocess, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ref = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else None
src = subprocess.run(["git", "-C", HERE, "show", "%s:lib/recovery.lua" % ref], capture_output=True, text=True, encoding="utf-8").stdout if ref else open(os.path.join(HERE, "lib", "recovery.lua"), encoding="utf-8").read()
L = 4864.1; NEAR, SB, SR, GBM = 18 / L, 18 / L, 45 / L, 0.03
def hash01(n):
    x = (n * 2654435761) % 2147483647; x = (x * 1103515245 + 12345) % 2147483647; return x / 2147483647
fnames = set(re.findall(r"^function R\.(\w+)\(", src, re.M)); assigned = set(re.findall(r"\bR\.(\w+)\s*=[^=]", src))
clash = sorted(fnames & assigned)
wired = {
    "no R.* name is both a function and an assigned value (25 Nov: R.recentDrops clash, %s)" % (clash or "none"): not clash,
    "signature has stopProgress": "local function putBackOnLine(sim, i, progress, center, force, skipGate, stopProgress)" in src,
    "reqProgress = stopProgress or progress": "local reqProgress = stopProgress or progress" in src,
    "rescue passes its true stop": "rescueWaitT[i] > RESCUE_FORCE_T, nil, progress)" in src,
    "spread block present (R.SPREAD_DROPS)": "if R.SPREAD_DROPS and trackLen" in src,
    "line guard (np < 0)": "if np < 0 then why = 'line'; break end" in src,
    "gate cap (GATE_BACK_MAX)": "if gated and p0 - np > GATE_BACK_MAX then" in src,
    "car 0: 4.5 m, one step": "(i == 0) and 4.5 or DROP_NEAR * trackLen, (i == 0) and 1 or 3" in src,
    "drops recorded": "R.spreadRecent[#R.spreadRecent + 1] = { i = i, t = os.clock(), prog = progress }" in src,
    "spread after the order rule, before the force check": src.find("if R.SPREAD_DROPS and trackLen") > src.find("if orderMoved then R.orderMovedN") > 0 and src.find("if R.SPREAD_DROPS and trackLen") < src.find("if not force and not dropSafe(sim, i, progress)"),
}
SPREAD = wired["spread block present (R.SPREAD_DROPS)"]; TRUESTOP = wired["reqProgress = stopProgress or progress"] and wired["rescue passes its true stop"]
def spread(i, prog, recent, gated=False):
    if not SPREAD: return prog
    p0, steps = prog, 0; nearM, maxS = (4.5, 1) if i == 0 else (NEAR * L, 3)
    while steps < maxS:
        if not any(d[0] != i and abs((d[1] - prog + 0.5) % 1 - 0.5) * L < nearM for d in recent): break
        np = prog - (SB + hash01(i * 17) * SR)
        if np < 0: break
        if gated and p0 - np > GBM: break
        prog = np; steps += 1
    return prog
def order(prog, req, ahead_m):   # 79e3e7a's order rule: fwd from reqProgress, unwrapped; car ahead ahead_m past reqProgress
    fwd = (prog - req) * L
    if fwd <= 0: return prog
    if 0 < ahead_m <= 300 and ahead_m < fwd: return (req + max(0, ahead_m - 30) / L) % 1
    return prog
res = []
# T1
stop = 0.500; stag = stop + 50 / L; req = stop if TRUESTOP else stag
land = order(stag, req, (stop + 40 / L - req) * L)
res.append(("T1 rescue lands 30 m behind the car ahead (10 m past the stop)", abs((land - stop) * L - 10) < 0.01, "%.1f m past the stop" % ((land - stop) * L)))
# T2
recent = []; out = {}
for car, p in ((10, 0.2963), (8, 0.2969), (12, 0.2971)):
    q = spread(car, p, recent); out[car] = q; recent.append((car, q))
gaps = [abs(out[a] - out[b]) * L for a, b in ((10, 8), (10, 12), (8, 12))]
res.append(("T2 3-car stack ends >= 18 m apart", min(gaps) >= 18, "pair gaps %s m" % [round(g, 1) for g in gaps]))
# T3
q = spread(5, 0.0015, [(6, 0.0015 + 2 / L)])
res.append(("T3 never back across the line", q >= 0 and q == 0.0015, "landing %.4f" % q))
# T4
a = spread(0, 0.400, [(3, 0.400 + 10 / L)]); b = spread(0, 0.400, [(3, 0.400 + 3 / L)])
one = SB + hash01(0) * SR
res.append(("T4 Reset my car: unchanged at 10 m; one step at 3 m", a == 0.400 and abs((0.400 - b) - one) < 1e-12, "10 m -> %.4f, 3 m -> %.4f (one step = %.1f m)" % (a, b, one * L)))
# T5
res.append(("T5 isolated drop unchanged", spread(7, 0.600, []) == 0.600 and spread(7, 0.600, [(2, 0.600 + 200 / L)]) == 0.600, "ok"))
print("ref %s" % (ref or "working tree"))
for k, v in wired.items(): print("  wired %s: %s" % ("yes" if v else "NO ", k))
ok = all(wired.values())
for n, g, d in res: ok &= g; print("  %s: %s (%s)" % ("PASS" if g else "FAIL", n, d))
print("SPREAD SELFTEST %s" % ("OK" if ok else "FAILED")); sys.exit(0 if ok else 1)
