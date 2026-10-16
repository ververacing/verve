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

# (module path, the function to extract, the marker its body MUST contain, the `where` string expected)
TARGETS = {
    "racecraft": ("lib/racecraft.lua", "function R.evaluate(i_, dt_)", "evalBody", "racecraft.evaluate"),
}


def source_of(text, decl, marker):
    """The source of one function: from its declaration to the first column-0 `end`.

    Refuses unless the slice contains `marker`. A silently-wrong slice would test some other function and pass,
    which is worse than not testing at all.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == decl)
    except StopIteration:
        raise SystemExit("REFUSED: could not find %r - the function was renamed or the anchor is stale" % decl)
    for j in range(start + 1, len(lines)):
        if lines[j].rstrip() == "end":
            body = "\n".join(lines[start:j + 1])
            if marker not in body:
                raise SystemExit("REFUSED: the slice for %r does not contain %r - wrong text extracted:\n%s"
                                 % (decl, marker, body))
            return body
    raise SystemExit("REFUSED: no column-0 `end` closes %r" % decl)


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


def run_case(body_src, faulting):
    """Execute the extracted function with evalBody stubbed. -> dict of what happened."""
    import lupa.luajit21 as lj
    rt = lj.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()
    # the upvalues R.evaluate shares with evalBody inside its do-block, plus the module table
    rt.execute("""
        R = { ENABLED = true, CAUT_BASE = 0, attacking = 0, defending = 0, errN = 0, errFirst = nil }
        SEEN = {}
        R.onError = function(where, e) SEEN[#SEEN + 1] = tostring(where) .. '|' .. tostring(e) end
        i, dt, caut, state = nil, nil, 0, 0
    """)
    rt.execute("evalBody = function() %s end"
               % ("error('seeded fault')" if faulting else "caut = 0.25; state = 1"))
    rt.execute(body_src)
    ret = rt.eval("R.evaluate(7, 0.016)")
    seen = rt.eval("SEEN")
    return {
        "ret": ret,
        "errN": rt.eval("R.errN"),
        "errFirst": rt.eval("R.errFirst"),
        "hook": [seen[k] for k in range(1, len(seen) + 1)] if seen is not None else [],
        "attacking": rt.eval("R.attacking"),
    }


def check(ref=None, name="racecraft"):
    rel, decl, marker, where = TARGETS[name]
    src = source_of(file_at(ref, rel), decl, marker)
    label = ref or "working tree"
    print("=== %s :: %s (%s) ===" % (name, decl, label))
    ok = True

    f = run_case(src, faulting=True)
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
    print("  it still RETURNS a number, no rethrow?           %s (%s)"
          % ("yes" if isinstance(f["ret"], (int, float)) else "NO - the fault escaped", f["ret"]))
    ok &= isinstance(f["ret"], (int, float))

    # the happy path must be untouched: no count, no log, and the state side-effects still applied
    h = run_case(src, faulting=False)
    print("  a clean frame counts NOTHING and still works?    %s (errN=%s hook=%d attacking=%s)"
          % ("yes" if (h["errN"] == 0 and not h["hook"] and h["attacking"] == 1) else "NO - BROKEN",
             h["errN"], len(h["hook"]), h["attacking"]))
    ok &= h["errN"] == 0 and not h["hook"] and h["attacking"] == 1

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
    for bad, why in ((good.replace("pcall(evalBody)", "pcall(other)"), "marker missing"),
                     ("function R.other()\nend\n", "declaration missing"),
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
    ap.add_argument("--name", default="racecraft", choices=sorted(TARGETS))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return 0 if check(a.ref, a.name) else 1


if __name__ == "__main__":
    sys.exit(main())
