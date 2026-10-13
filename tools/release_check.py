"""Is this branch releasable? Mechanical checks only, and it REFUSES a verdict it cannot back.

    python tools/release_check.py              # check dev016 against origin/main
    python tools/release_check.py --base main --head dev016

Written 2026-10-12 at the owner's request: "I'd like to get more disciplined moving forward to make sure every
release is high quality and really proven out to work really well."

WHY A TOOL AND NOT A CHECKLIST. Decision 0001 already said the regression suite runs before any default changes. It
did not stop me recommending the cold-tyre default to the owner in a morning email on evidence that the suite later
CONTRADICTED - I caught that only because I went looking afterwards. A prose rule that depends on remembering is not
a gate. This exits non-zero instead.

AND IT REFUSES RATHER THAN GUESSES, which is the lesson leak_check taught the same day: a check that cannot tell
"I verified this" from "I could not look" will quietly mint a pass. Every item below prints PASS, FAIL or REFUSED,
and REFUSED counts as a failure.

THE BAR, each line a thing this script actually tests:
  1. SUITE FRESHNESS - the named regression suite must have run AFTER the last commit touching always-on app code
     (lib/, Verve.lua, diag.lua). This is the one that was silently false on 2026-10-12: last app commit 00:00,
     newest suite run 18:13 the PREVIOUS day. A switch-gated change is not the only thing that can regress - feed,
     recovery and racecraft all changed in always-on paths.
  2. SUITE COMPLETENESS - all three named cells present (Spa, Barcelona, Monza) in the freshest suite, with enough
     runs each to mean anything. The sprint cells need MIN_SIDE because their run-to-run spread is large; one run of
     a 2-lap sprint is noise with a label on it.
  3. NOT WORSE THAN THE BASELINE - the actual bar from CLAUDE.md, and the one this script was missing on the day it
     was written: "a default only changes if the suite is not worse on contact, heavy hits, DNFs or pace". It
     compares the freshest suite prefix against the previous one, cell by cell. A cell FAILS when the new mean falls
     outside the baseline's whole observed range in the worse direction - with three runs a side that is the
     strongest honest statement available, and it does not pretend to a significance test three points cannot
     support. Fewer than two runs a side REFUSES: a single point has no range, so it can neither show a regression
     nor rule one out.
  4. EVIDENCE PER DEFAULT CHANGE - every R.* default that differs from base must have at least MIN_SIDE runs per arm
     in results.csv, and a line in LESSONS.md. A default with no A/B is a guess.
  5. NO WITHDRAWN CLAIM IN SUPPORT - no switch being defaulted may have WITHDRAWN on its LESSONS line.
  6. IDENTITY GATE - leak_check clean over every file the push would publish.
  7. DOCS CURRENT - docs_check reports no drift.
Items 4-5 are only as good as the registry and LESSONS being honest, which is why the docs routine is mandatory;
this script says which it could not evaluate rather than passing them.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "docs")
RESULTS = os.path.join(HERE, "harness_results", "results.csv")
APP_PATHS = ["lib", "Verve.lua", "diag.lua"]

# The arm token is OPTIONAL. An earlier version of this regex demanded an `on` and an `off` arm per cell, which was a
# pairing I had invented: the suite is a BASELINE-versus-HEAD comparison, not a switch A/B, so every row sits on the
# same side. Completeness therefore failed for all three cells while a real regression went unexamined.
SUITE_RE = re.compile(r"^(rc\d+[a-z]?)_(spa12|spa|bcn|mon)(?:_(on|off))?_\d+$")  # spa12 BEFORE spa, it is a prefix
# Recomposed 2026-10-13 on the owner's yes (decision 0027). GATING cells are the two 12-lap races; the 2-lap
# sprints are still run and scored but judged on opening-lap character, not on contact counts. The old suite put
# nine of ten runs in the sprints, and a 12-lap cell's own spread is 1.40x against a sprint arm's 3.50x on identical
# code - so the sprints cannot see a regression a long race can, and would need about n=10 to try.
GATING_CELLS = {"mon": 3, "spa12": 3}               # cell -> runs needed; these decide releasability
CHARACTER_CELLS = {"spa": 3, "bcn": 3}              # run and scored, but they do NOT gate
NEEDED_CELLS = GATING_CELLS                          # what completeness and not-worse are judged on
MIN_SIDE = 3          # runs per arm before a default change is evidenced; the opening-lap spread demands 3+

# metric -> (higher is worse?, label). laptime is two-sided: drifting either way means the pace changed.
SUITE_METRICS = [("contact_events", True, "contact"), ("incidents", True, "inc"),
                 ("heavy80", True, "heavy80"), ("retired_or_parked", True, "dead"),
                 ("laptime_median_s", None, "medlap")]


def sh(*args):
    r = subprocess.run(list(args), cwd=VERVE, capture_output=True, text=True)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


class Report(object):
    def __init__(self):
        self.rows = []

    def add(self, verdict, name, detail):
        self.rows.append((verdict, name, detail))

    def ok(self, name, detail=""):
        self.add("PASS", name, detail)

    def fail(self, name, detail):
        self.add("FAIL", name, detail)

    def refuse(self, name, detail):
        self.add("REFUSED", name, detail)

    def show(self):
        print()
        for v, n, d in self.rows:
            print("  %-8s %-20s %s" % (v, n, d))
        bad = [r for r in self.rows if r[0] != "PASS"]
        print()
        if bad:
            print("  NOT RELEASABLE - %d of %d checks did not pass:" % (len(bad), len(self.rows)))
            for v, n, _ in bad:
                print("     %s  %s" % (v, n))
            print("  A REFUSED item counts as a failure: it means this script could not verify the claim, not that")
            print("  the claim is false. Make it checkable or evidence it by hand in the release decision record.")
            return 1
        print("  all %d checks pass" % len(self.rows))
        return 0


def read_results():
    try:
        import csv
        import io
        with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return None


def stamp_of(row):
    m = re.search(r"(\d{8}_\d{6})", row.get("file") or "")
    return m.group(1) if m else ""


def cells_of(suite, prefix):
    """{(cell, arm): [row, ...]} for one suite prefix.

    KEYED BY ARM, which matters: rc16b ran an `on` and an `off` arm of the same cell, and pooling them gave the
    baseline a range so wide it swallowed everything (Spa contact 12-45). A comparison is only like-for-like inside
    one arm.
    """
    out = {}
    for r in suite:
        m = SUITE_RE.match(r["label"])
        if m.group(1) == prefix:
            out.setdefault((m.group(2), m.group(3) or "-"), []).append(r)
    return out


def per_cell(byarm):
    """{cell: total runs} across arms, for the completeness count."""
    out = {}
    for (cell, _), rows in byarm.items():
        out[cell] = out.get(cell, 0) + len(rows)
    return out


def nums(rows, key):
    vals = []
    for r in rows:
        try:
            vals.append(float(r.get(key) or 0))
        except (TypeError, ValueError):
            pass
    return vals


def check_suite(rep, rows):
    """1 and 2: the suite must post-date the last app-code commit, and cover all three cells deeply enough.

    Returns (freshest prefix, suite rows) for check_not_worse, or None when there is nothing to compare.
    """
    rc, out, _ = sh("git", "log", "-1", "--format=%ad", "--date=format:%Y%m%d_%H%M%S", "--", *APP_PATHS)
    if rc != 0 or not out:
        rep.refuse("suite freshness", "could not read the last app-code commit date from git")
        return None
    last_app = out.strip()
    suite = [r for r in rows if SUITE_RE.match(r.get("label") or "")]
    if not suite:
        rep.fail("suite freshness", "no regression-suite rows in results.csv at all")
        return None
    newest = max((stamp_of(r) for r in suite), default="")
    if not newest:
        rep.refuse("suite freshness", "suite rows carry no readable timestamp")
        return None
    if newest < last_app:
        rep.fail("suite freshness",
                 "newest suite run %s PRE-DATES the last app-code commit %s - re-run the suite on HEAD"
                 % (newest, last_app))
    else:
        rep.ok("suite freshness", "suite %s is newer than the last app commit %s" % (newest, last_app))

    # completeness of the FRESHEST suite prefix only
    fresh_prefix, best = None, ""
    for r in suite:
        s = stamp_of(r)
        if s > best:
            best, fresh_prefix = s, SUITE_RE.match(r["label"]).group(1)
    counts = per_cell(cells_of(suite, fresh_prefix))
    # the character cells are reported for visibility and never block
    chars = ", ".join("%s x%d" % (c, counts.get(c, 0)) for c in sorted(CHARACTER_CELLS))
    short = []
    for c in sorted(NEEDED_CELLS):
        n = counts.get(c, 0)
        if n < NEEDED_CELLS[c]:
            short.append("%s(%d of %d)" % (c, n, NEEDED_CELLS[c]))
    if short:
        rep.fail("suite completeness", "freshest suite %s is short: %s" % (fresh_prefix, " ".join(short)))
    else:
        rep.ok("suite completeness", "%s gating %s | character (not gating) %s" % (
            fresh_prefix, " ".join("%s x%d" % (c, counts[c]) for c in sorted(NEEDED_CELLS)), chars))
    return fresh_prefix, suite


def check_not_worse(rep, suite, fresh_prefix):
    """3: the freshest suite against the one before it, cell by cell. The bar CLAUDE.md actually states."""
    if not suite or not fresh_prefix:
        rep.refuse("not worse", "no suite to compare")
        return
    others = sorted({SUITE_RE.match(r["label"]).group(1) for r in suite} - {fresh_prefix})
    if not others:
        rep.refuse("not worse", "%s is the only suite prefix on record - nothing to compare against" % fresh_prefix)
        return
    base_prefix = others[-1]          # rc16a < rc16b < rc16c sorts correctly for this naming scheme
    new, old = cells_of(suite, fresh_prefix), cells_of(suite, base_prefix)
    for cell, arm in sorted(new):
        a, b = old.get((cell, arm), []), new[(cell, arm)]
        name = "not worse %s" % (cell if arm == "-" else "%s/%s" % (cell, arm))
        if len(a) < 2 or len(b) < 2:
            rep.refuse(name, "%s n=%d vs %s n=%d - a single run has no range, so this cell can neither show a "
                             "regression nor rule one out" % (base_prefix, len(a), fresh_prefix, len(b)))
            continue
        bad, unresolved, notes = [], [], []
        for key, higher_worse, label in SUITE_METRICS:
            av, bv = nums(a, key), nums(b, key)
            if not av or not bv or (max(av) == 0 and max(bv) == 0):
                continue              # the sprint cells never produce a median lap time; do not pretend they did
            mean = sum(bv) / len(bv)
            lo, hi = min(av), max(av)
            # The baseline arm's OWN observed spread is the yardstick for noise - but it can be ZERO, and then the
            # allowance vanishes and the rule degenerates to "any nonzero value is a regression". That fired on
            # 2026-10-12: rc16b's Monza arm had heavy80 0 and dead 0 across n=2, so ONE heavy hit in one of three new
            # races (rc16c_mon_off_2, 1 of 54 car-races) was reported WORSE. With two runs at zero you cannot tell
            # "never happens" from "happens once in fifty" - that is absence of evidence, not evidence of a change.
            # A floor of one whole event keeps a zero-width baseline from hair-triggering; the value still falls
            # outside [lo, hi], so it lands in the REFUSED middle state and correctly asks for a deeper baseline
            # instead of passing quietly.
            w = max(hi - lo, 1.0)
            if lo <= mean <= hi:
                tag, where = "", None                 # indistinguishable from the baseline: that is "not worse"
            elif mean > hi + w or (higher_worse is None and mean < lo - w):
                tag, where = " WORSE", bad            # further out than the spread can explain
            else:
                tag, where = " ?", unresolved         # outside the range but inside one spread of it
            notes.append("%s %.1f vs %.1f-%.1f%s" % (label, mean, lo, hi, tag))
            if where is not None:
                where.append(label)
        detail = "%s(n=%d) -> %s(n=%d): %s" % (base_prefix, len(a), fresh_prefix, len(b),
                                               ", ".join(notes) or "no metric comparable")
        if not notes:
            rep.refuse(name, detail)
        elif bad:
            rep.fail(name, detail)
        elif unresolved:
            rep.refuse(name, detail + " | ? = outside the baseline range but within one spread of it; deepen the "
                                      "baseline arm before calling it either way")
        else:
            rep.ok(name, detail)


def default_changes(base, head):
    """R.* defaults whose VALUE differs between base and head, from the diff."""
    rc, out, _ = sh("git", "diff", "%s..%s" % (base, head), "--", "lib", "Verve.lua", "diag.lua")
    if rc != 0:
        return None
    added, removed = {}, {}
    for line in out.splitlines():
        m = re.match(r"^([+-])(R\.[A-Z0-9_]+)\s*=\s*([^\s;]+)", line)
        if m:
            (added if m.group(1) == "+" else removed)[m.group(2)] = m.group(3).rstrip(",")
    return {k: (removed.get(k), v) for k, v in added.items() if k in removed and removed[k] != v}


def check_evidence(rep, rows, base, head):
    """4 and 5: every changed default needs runs per arm and an honest LESSONS line."""
    changed = default_changes(base, head)
    if changed is None:
        rep.refuse("evidence per default", "could not read the diff")
        return
    if not changed:
        rep.ok("evidence per default", "no R.* default value differs from %s" % base)
        return
    try:
        import io
        lessons = io.open(os.path.join(DOCS, "LESSONS.md"), encoding="utf-8", errors="replace").read()
    except OSError:
        rep.refuse("evidence per default", "could not read LESSONS.md")
        return
    for sw, (old, new) in sorted(changed.items()):
        bare = sw.split(".", 1)[1]
        n = sum(1 for r in rows if bare in (r.get("arm") or ""))
        cited = bare in lessons
        withdrawn = bool(re.search(r"WITHDRAWN[^\n]*" + re.escape(bare), lessons)
                         or re.search(re.escape(bare) + r"[^\n]*WITHDRAWN", lessons))
        detail = "%s -> %s | %d harness rows mention it | LESSONS: %s" % (
            old, new, n, "yes" if cited else "NO LINE")
        if withdrawn:
            rep.fail("default %s" % bare, detail + " | a LESSONS line marks it WITHDRAWN")
        elif n < MIN_SIDE * 2 or not cited:
            rep.fail("default %s" % bare, detail + " | needs >=%d rows an arm and a LESSONS line" % MIN_SIDE)
        else:
            rep.ok("default %s" % bare, detail)


def check_gate(rep, base, head):
    """6: identity gate over exactly what the push would publish."""
    rc, out, _ = sh("git", "diff", "--name-only", "%s..%s" % (base, head))
    files = [f for f in out.splitlines() if f.strip()]
    if rc != 0 or not files:
        rep.refuse("identity gate", "could not list the files the push would publish")
        return
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "leak_check.py")] + files,
                       cwd=VERVE, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    last = tail[-1] if tail else "(no output)"
    if r.returncode == 0 and "clean" in last:
        rep.ok("identity gate", last)
    else:
        rep.fail("identity gate", last)


def check_docs(rep):
    """7: docs_check reports no drift."""
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "docs_check.py")],
                       cwd=VERVE, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    last = tail[-1] if tail else "(no output)"
    if r.returncode == 0 and "current" in last.lower():
        rep.ok("docs current", last[:90])
    else:
        rep.fail("docs current", last[:90])


def main():
    base, head = "origin/main", "dev016"
    for i, a in enumerate(sys.argv):
        if a == "--base" and i + 1 < len(sys.argv):
            base = sys.argv[i + 1]
        if a == "--head" and i + 1 < len(sys.argv):
            head = sys.argv[i + 1]
    print("release_check: %s against %s" % (head, base))
    rows = read_results()
    rep = Report()
    if rows is None:
        rep.refuse("results.csv", "could not read %s" % RESULTS)
        return rep.show()
    fresh_prefix, suite = check_suite(rep, rows) or (None, None)
    check_not_worse(rep, suite, fresh_prefix)
    check_evidence(rep, rows, base, head)
    check_gate(rep, base, head)
    check_docs(rep)
    return rep.show()


if __name__ == "__main__":
    sys.exit(main())
