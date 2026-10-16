"""Does a fault inside a per-frame car-control body get COUNTED, or silently swallowed?

    python tools/rcerr_test.py              # test the working tree
    python tools/rcerr_test.py --ref HEAD~1 # test an older revision (proves the test has teeth)
    python tools/rcerr_test.py --selftest

WHY THIS EXISTS. `R.evaluate` wrapped `evalBody` in a pcall and threw the result away. A fault anywhere inside
evalBody means that car skips its remaining control writes for the frame - `physics.setAIAggression` is called
near the END of evalBody - and `R.evaluate` still returns `caut + R.CAUT_BASE`, where caut holds whatever partial
value was assigned before the fault. So a race could be driving differently from what the switches say and every
number from it would look clean. Same defect in recovery's `carBody` and human's `modBody`.

HOW IT TESTS THE REAL THING RATHER THAN A REIMPLEMENTATION. There is no standalone lua on this machine, but
`lupa.luajit21` is already a project dependency (tools/career_detect_check.py runs lib/career.lua in LuaJIT with
a mocked `ac`). Loading the whole of lib/racecraft.lua would mean mocking ac, physics and every lib module it
requires; instead this EXTRACTS the actual source text of the one function under test and executes that in
LuaJIT with `evalBody` stubbed to raise. The code under test is the shipped code, byte for byte, with almost no
mocking surface - and if the extraction grabs the wrong text it REFUSES rather than testing something else.

TEETH. `--ref` runs the same assertions against any git revision, so "this test would have caught the bug" is
demonstrated rather than asserted: run it against the commit before the fix and every case must go RED.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)

# Each target names what to extract and what the extracted text must contain, so a wrong slice is refused rather
# than quietly tested. Two kinds:
#   "func"     - the whole function, from its declaration to the first column-0 `end`. Only viable where the
#                function is small and its upvalues few, which is true of R.evaluate (7 lines, 4 upvalues).
#   "fragment" - the guard itself: the `local ok, err = pcall(body)` line plus the `if not ok then ... end` that
#                follows it. R.update and H.getModifiers are large and need sim/ac/physics plus dozens of
#                upvalues, so the whole function cannot be executed in isolation - but the GUARD can, and it is
#                still the real shipped text rather than a reimplementation. Approved by verve-47.
TARGETS = {
    "racecraft": dict(kind="func", path="lib/racecraft.lua", anchor="function R.evaluate(i_, dt_)",
                      marker="evalBody", where="racecraft.evaluate", table="R", body="evalBody"),
    "recovery":  dict(kind="fragment", path="lib/recovery.lua", anchor="local ok, err = pcall(carBody)",
                      marker="R.errN", where="recovery.carBody", table="R", body="carBody"),
    "human":     dict(kind="fragment", path="lib/human.lua", anchor="local okM, errM = pcall(modBody)",
                      marker="H.errN", where="human.modBody", table="H", body="modBody"),
}


UNGUARDED = object()   # the anchor is absent: this revision has no guard at all, which is the RED state


def source_of(text, decl, marker):
    """The source of one function: from its declaration to the first column-0 `end`.

    Refuses unless the slice contains `marker`. A silently-wrong slice would test some other function and pass,
    which is worse than not testing at all. Returns UNGUARDED when the anchor is absent, so --ref against a
    revision predating the fix reports "no guard" rather than crashing.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == decl), None)
    if start is None:
        return UNGUARDED
    for j in range(start + 1, len(lines)):
        if lines[j].rstrip() == "end":
            body = "\n".join(lines[start:j + 1])
            if marker not in body:
                raise SystemExit("REFUSED: the slice for %r does not contain %r - wrong text extracted:\n%s"
                                 % (decl, marker, body))
            return body
    raise SystemExit("REFUSED: no column-0 `end` closes %r" % decl)


def fragment_of(text, anchor, marker):
    """The guard itself: the anchor line plus the `if not ok then ... end` that follows it.

    The close is the first line that is exactly `end` at the SAME indentation as the line after the anchor (the
    `if`). That is the shape all three guards have; anything else is refused rather than guessed at, and the
    slice must still contain `marker`.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == anchor), None)
    if start is None:
        return UNGUARDED
    if start + 1 >= len(lines):
        raise SystemExit("REFUSED: %r is the last line - nothing follows it to be the guard" % anchor)
    nxt = lines[start + 1]
    indent = len(nxt) - len(nxt.lstrip())
    if not nxt.strip().startswith("if not ok"):
        raise SystemExit("REFUSED: the line after %r is %r, not an `if not ok ...` guard" % (anchor, nxt.strip()))
    for j in range(start + 2, len(lines)):
        l = lines[j]
        if l.strip() == "end" and (len(l) - len(l.lstrip())) == indent:
            frag = "\n".join(x[indent:] if len(x) > indent else x.lstrip() for x in lines[start:j + 1])
            if marker not in frag:
                raise SystemExit("REFUSED: the fragment for %r lacks %r:\n%s" % (anchor, marker, frag))
            return frag
    raise SystemExit("REFUSED: no `end` at the guard's own indentation closes %r" % anchor)


def file_at(ref, rel):
    """The file as of a git revision, or the working tree when ref is None. Never touches the checkout."""
    if ref is None:
        with open(os.path.join(VERVE, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    out = subprocess.run(["git", "-C", VERVE, "show", "%s:%s" % (ref, rel)],
                         capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        raise SystemExit("REFUSED: git show %s:%s failed - %s" % (ref, rel, out.stderr.strip()[:200]))
    return out.stdout


def run_case(src, faulting, t):
    """Execute the extracted real source with the body stubbed. -> dict of what happened.

    `t` is the target: it decides which module table to stand up (R or H), what the per-car body is called, and
    whether the result is reached by CALLING a function (kind "func") or by the fragment running inline.
    """
    import lupa.luajit21 as lj
    rt = lj.LuaRuntime(unpack_returned_tuples=True)
    tbl, body = t["table"], t["body"]
    # the module table plus the upvalues the extracted text shares with its enclosing scope
    rt.execute("""
        %s = { ENABLED = true, CAUT_BASE = 0, attacking = 0, defending = 0, INTENSITY = 0.5,
               errN = 0, errFirst = nil }
        SEEN = {}
        %s.onError = function(where, e) SEEN[#SEEN + 1] = tostring(where) .. '|' .. tostring(e) end
        i, i_, dt, caut, state = 7, 7, 0.016, 0, 0
    """ % (tbl, tbl))
    rt.execute("%s = function() %s end"
               % (body, "error('seeded fault')" if faulting else "caut = 0.25; state = 1"))
    rt.execute(src)
    ret = rt.eval("%s.evaluate(7, 0.016)" % tbl) if t["kind"] == "func" else 0.0
    seen = rt.eval("SEEN")
    return {
        "ret": ret,
        "errN": rt.eval("%s.errN" % tbl),
        "errFirst": rt.eval("%s.errFirst" % tbl),
        "hook": [seen[k] for k in range(1, len(seen) + 1)] if seen is not None else [],
        "attacking": rt.eval("%s.attacking" % tbl),
    }


def check(ref=None, name="racecraft"):
    t = TARGETS[name]
    text = file_at(ref, t["path"])
    src = (source_of if t["kind"] == "func" else fragment_of)(text, t["anchor"], t["marker"])
    label = ref or "working tree"
    print("=== %s :: %s (%s) ===" % (name, t["anchor"], label))
    if src is UNGUARDED:
        print("  NO GUARD AT ALL in this revision: the pcall result is discarded, so a fault in %s is invisible."
              % t["body"])
        print("  FAILED - the fault is not visible")
        return False
    where = t["where"]
    ok = True

    # the `where` handed to the shared logger must be a FIXED literal. noteErr keys on `where .. ': ' .. err`, so
    # a per-car `where` would turn one bug on an 18-car grid into 18 "distinct" messages and burn 18 of its cap
    # of 25, crowding out every other module's first error. Checked on the TEXT, because a runtime check with one
    # car cannot tell a literal from a concatenation.
    import re as _re
    call = _re.search(r"onError\(\s*([^,]+),", src)
    literal = bool(call) and call.group(1).strip() in ("'%s'" % where, '"%s"' % where)
    print("  the `where` is a FIXED literal, not per-car?       %s (%s)"
          % ("yes" if literal else "NO - it would burn the shared log cap",
             call.group(1).strip() if call else "no onError call found"))
    ok &= literal

    f = run_case(src, faulting=True, t=t)
    print("  a seeded fault is COUNTED?                       %s (errN=%s, want 1)"
          % ("yes" if f["errN"] == 1 else "NO - SWALLOWED", f["errN"]))
    ok &= f["errN"] == 1
    print("  the first message is kept?                       %s (%s)"
          % ("yes" if f["errFirst"] else "NO", str(f["errFirst"])[:60]))
    ok &= bool(f["errFirst"])
    hook_ok = len(f["hook"]) == 1 and f["hook"][0].split("|")[0] == where
    print("  the shared logger is called, with a FIXED where? %s (%s)"
          % ("yes" if hook_ok else "NO", f["hook"][0].split("|")[0] if f["hook"] else "not called"))
    ok &= hook_ok
    if t["kind"] == "func":
        print("  it still RETURNS a number, no rethrow?           %s (%s)"
              % ("yes" if isinstance(f["ret"], (int, float)) else "NO - the fault escaped", f["ret"]))
        ok &= isinstance(f["ret"], (int, float))

    # the happy path must be untouched: no count, no log, and for the whole-function case the state side-effect
    # still applied. A fragment has no return value, so only the counters are asserted there.
    h = run_case(src, faulting=False, t=t)
    want_attack = 1 if t["kind"] == "func" else 0
    clean = h["errN"] == 0 and not h["hook"] and h["attacking"] == want_attack
    print("  a clean frame counts NOTHING and still works?    %s (errN=%s hook=%d attacking=%s)"
          % ("yes" if clean else "NO - BROKEN", h["errN"], len(h["hook"]), h["attacking"]))
    ok &= clean

    print("  %s" % ("every case holds" if ok else "FAILED - the fault is not visible"))
    return ok


def selftest():
    """The extractor is the risky part: a wrong slice would test the wrong function and pass."""
    ok = True
    good = "function R.evaluate(i_, dt_)\n    pcall(evalBody)\nend\nend   -- do-block\n"
    got = source_of(good, "function R.evaluate(i_, dt_)", "evalBody")
    print("  extracts the function and stops at the first end? %s (%d lines)"
          % ("yes" if got.count("\n") == 2 else "NO", got.count("\n")))
    ok &= got.count("\n") == 2
    # A MISSING ANCHOR IS NOT A REFUSAL, IT IS THE RED STATE: it means this revision has no guard, which is
    # exactly what --ref against a pre-fix commit must report. Distinct from a wrong slice, which IS refused.
    print("  a missing anchor reports UNGUARDED, not an error?  %s"
          % ("yes" if source_of("function R.other()\nend\n", "function R.evaluate(i_, dt_)", "evalBody")
             is UNGUARDED else "NO - BROKEN, --ref would crash instead of going red"))
    ok &= source_of("function R.other()\nend\n", "function R.evaluate(i_, dt_)", "evalBody") is UNGUARDED

    # the fragment extractor, which is what reaches recovery and human
    frag_src = ("        local ok, err = pcall(carBody)\n"
                "        if not ok then\n"
                "            R.errN = R.errN + 1\n"
                "        end\n"
                "    end\n"
                "    R.count = active\n")
    fr = fragment_of(frag_src, "local ok, err = pcall(carBody)", "R.errN")
    print("  fragment stops at the guard's own `end`?           %s (%d lines)"
          % ("yes" if fr is not UNGUARDED and fr.count("\n") == 3 else "NO",
             -1 if fr is UNGUARDED else fr.count("\n")))
    ok &= fr is not UNGUARDED and fr.count("\n") == 3
    print("  fragment with a missing anchor is UNGUARDED?       %s"
          % ("yes" if fragment_of("        pcall(carBody)\n", "local ok, err = pcall(carBody)", "R.errN")
             is UNGUARDED else "NO - BROKEN"))
    ok &= fragment_of("        pcall(carBody)\n", "local ok, err = pcall(carBody)", "R.errN") is UNGUARDED
    for bad, why in ((frag_src.replace("if not ok then", "if something then"), "fragment: not an if-not-ok"),
                     (frag_src.replace("R.errN = R.errN + 1", "nothing()"), "fragment: marker missing")):
        try:
            fragment_of(bad, "local ok, err = pcall(carBody)", "R.errN")
            print("  refuses on %-22s %s" % (why + "?", "NO - BROKEN"))
            ok = False
        except SystemExit:
            print("  refuses on %-22s %s" % (why + "?", "yes"))

    for bad, why in ((good.replace("pcall(evalBody)", "pcall(other)"), "marker missing"),
                     ("function R.evaluate(i_, dt_)\n    pcall(evalBody)\n", "unterminated")):
        try:
            source_of(bad, "function R.evaluate(i_, dt_)", "evalBody")
            print("  refuses on %-22s %s" % (why + "?", "NO - BROKEN, it would test the wrong text"))
            ok = False
        except SystemExit:
            print("  refuses on %-22s %s" % (why + "?", "yes"))
    print("\n  %s" % ("extractor sound" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", help="git revision to test instead of the working tree (e.g. HEAD~1)")
    ap.add_argument("--name", default="all", choices=sorted(TARGETS) + ["all"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    names = sorted(TARGETS) if a.name == "all" else [a.name]
    return 0 if all([check(a.ref, n) for n in names]) else 1


if __name__ == "__main__":
    sys.exit(main())
