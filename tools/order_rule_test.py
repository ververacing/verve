"""Order-rule selftest (25 Nov 2026): a GATED set-back must stay a set-back.

    python -I tools/order_rule_test.py               # test the working tree
    python -I tools/order_rule_test.py --ref 091ffa6 # test an older revision (proves the test has teeth: must FAIL)

No Lua interpreter is available on the desk, so this mirrors the rule from the SOURCE: it reads putBackOnLine's order-rule
block from lib/recovery.lua, checks the guard (`not gated`), extracts the fwd expression, translates it to Python and runs
the seeds through it, the way the rule would use them.
SEEDS (Imola, 4864 m; ghost run ghi_imo_1 car 6):
  S1 gated set-back 0.851 -> 0.300 (0.55 lap back), a car ahead in the race 171 m beyond the stop: the rule must NOT move it.
  S2 ungated forward landing 0.851 -> 0.880 (141 m ahead), car ahead 100 m beyond the stop: the rule MUST move it (still works).
  S3 ungated set-back 0.851 -> 0.300 (e.g. a retry back to an old spot), car ahead 171 m: must NOT move it (signed wrap)."""
import re, sys, subprocess, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ref = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else None
src = subprocess.run(["git", "-C", HERE, "show", "%s:lib/recovery.lua" % ref], capture_output=True, text=True, encoding="utf-8").stdout if ref else open(os.path.join(HERE, "lib", "recovery.lua"), encoding="utf-8").read()
m = re.search(r"if \(R\.ORDER_RULE_M or 0\) > 0 and trackLen and trackLen > 0(.*?) then\s*pcall\(function\(\)(.*?)if rear then", src, re.S)
assert m, "order-rule block not found"
guard, body = m.group(1), m.group(2)
fx = re.search(r"local fwd = (.+)", body).group(1).strip()
cond = re.search(r"if (fwd <= 0[^\n]*?) then return end", body).group(1)
py = lambda e: e.replace("%", "%").replace("trackLen", "L")
L = 4864.1
def rule(stop, land, gated, ahead_m, order_m=300):
    if "not gated" in guard and gated: return land
    progress, reqProgress = land, stop
    fwd = eval(py(fx), {"progress": progress, "reqProgress": reqProgress, "L": L})
    if eval(py(cond).replace(" or ", " or ").replace("fwd", repr(fwd)), {"L": L}): return land
    if 0 < ahead_m <= order_m and ahead_m < fwd: return (reqProgress + max(0, ahead_m - 30) / L) % 1
    return land
cases = [("S1 gated 0.55-lap set-back stays", 0.851, 0.300, True, 171, lambda r: abs(r - 0.300) < 1e-9),
         ("S2 ungated forward landing is moved behind the car ahead", 0.851, 0.880, False, 100, lambda r: abs(r - (0.851 + 70 / L)) < 1e-9),
         ("S3 ungated 0.55-lap set-back stays", 0.851, 0.300, False, 171, lambda r: abs(r - 0.300) < 1e-9)]
ok = True
print("ref %s | guard%s | fwd = %s | skip if %s" % (ref or "working tree", guard or " (none)", fx, cond))
for name, stop, land, g, ahead, chk in cases:
    r = rule(stop, land, g, ahead); good = chk(r); ok &= good
    print("  %s: %s -> landing %.4f" % ("PASS" if good else "FAIL", name, r))
print("ORDER RULE SELFTEST %s" % ("OK" if ok else "FAILED")); sys.exit(0 if ok else 1)
