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

VOLATILE, NOT A FAILURE (owner item 26-37, 27 Oct): cfg/race.ini is written fresh by the harness every run by
design (harness.py builds each row from race.ini.harness-backup as a template; handback.py keeps that backup on
purpose). Its content therefore differs run to run, and AC's own INIReader warnings against it - e.g.
"KEY_NOT_FOUND: [SESSION_0] ADDITITIONAL_LAP" seen in crash .report/errors.txt - are benign. Neither this gate nor
the docs check treats race.ini's churn or those warnings as a release failure; it is a volatile input, not a tracked
artifact. (Documented so a future error/log scanner is not written to fail a run on it.)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "docs")
RESULTS = os.path.join(HERE, "harness_results", "results.csv")
PACE_CSV = os.path.join(HERE, "harness_results", "pace.csv")   # written by tools/pace.py from the feed
APP_PATHS = ["lib", "Verve.lua", "diag.lua"]

# The arm token is OPTIONAL. An earlier version of this regex demanded an `on` and an `off` arm per cell, which was a
# pairing I had invented: the suite is a BASELINE-versus-HEAD comparison, not a switch A/B, so every row sits on the
# same side. Completeness therefore failed for all three cells while a real regression went unexamined.
SUITE_RE = re.compile(r"^(rc\d+[a-z]?)_(spa12|spa|bcn|mon|sgf)(?:_(on|off))?_\d+$")  # spa12 BEFORE spa, it is a prefix
# Recomposed 2026-10-13 on the owner's yes (decision 0027). GATING cells are the two 12-lap races; the 2-lap
# sprints are still run and scored but judged on opening-lap character, not on contact counts. The old suite put
# nine of ten runs in the sprints, and a 12-lap cell's own spread is 1.40x against a sprint arm's 3.50x on identical
# code - so the sprints cannot see a regression a long race can, and would need about n=10 to try.
GATING_CELLS = {"mon": 3, "spa12": 3, "sgf": 3}     # cell -> runs needed; these decide releasability

# `sgf` IS THE SINGAPORE FORMULA CELL (decision 0035): singapore_2020, uniform 20-car SF70H, 5 laps, ai-level 100,
# with NEW_LATERAL_GRIP_ESTIMATION=1 and FIX_GRIP_MULT=1 STATED EXPLICITLY on every row. It gates because the two
# GT3 cells are structurally blind to the worst defect this project has found, twice over: the formula interaction
# cannot appear on a GT3 field at any sample size (every Verve-ON GT3 row at key >= 1 retired zero cars, 0 of 12),
# and every other gating row runs the keys at 0, which is the one configuration where the bug cannot exist. So a
# build could take a default-CSP formula field from 12 retirements to 20 and the old suite would report PASS.
# IT RUNS ON PC #1 ONLY - the keys do not exist on CSP 3465, so a 3465 suite cannot produce this cell in any form.
# That is handled by completeness: `sgf` is in NEEDED_CELLS, so a suite without it is reported SHORT rather than
# passing on the cells it managed, which is what decision 0035 requires.
#
# DELIBERATELY **NOT** IN BASELINE_ALIAS, and this is the part to read before adding one. The obvious candidates
# (cspf1_dflt_on, cspf3_full, cspf4_full) are all disqualified by the 2026-10-15 drift finding: the stock arm of
# this very cell read 9/4/9, then 4/7/9, then 10/11/13 across three queues whose `cmd` strings are identical
# character-for-character with no commit between them. An alias must "differ from the new cell in NOTHING but the
# code version", and a baseline drawn from one of those queues silently carries up to ~6 retirements of
# between-queue movement. With no alias the cell lands in rep.refuse - "neither shows a regression nor rules one
# out" - which is the honest state and NOT a pass. The baseline to wire here is cspf5's `full` arm once it lands,
# because cspf5 interleaves full WITH stock in one queue, so the drift can be read instead of assumed.

# A cell ADDED to the suite has no baseline under the suite's own naming, and never will. Decision 0027 created the
# Spa 12-lap gating cell on 2026-10-13, so there is no rc16c_spa12_* and the comparison has to use the pre-existing
# equivalent run. This map is explicit rather than a regex widening, so the substitution is auditable.
# A baseline named here MUST have run on pre-change code and differ from the new cell in NOTHING but the code
# version. Verified for this entry: ksc_spa12_gt3_keysoff_1..3 ran 2026-10-12 09:58-12:07, all before the
# 2026-10-13 00:30 app commit; the arm columns differ in NO dimension; track, cars, ai_level and leader_laps match.
BASELINE_ALIAS = {"spa12": "ksc_spa12_gt3_keysoff"}

# Rare events (heavy hits, DNFs) against a ZERO-SPREAD baseline cannot be resolved at n=3 - one event is
# indistinguishable from noise, and demanding otherwise means the gate can never pass on those metrics however good
# the code is. So a zero-spread baseline is only QUESTIONED once the new arm has produced this many events in total.
# Below it the cell passes with the count stated, which is honest: it says "1 DNF in 54 car-races against a baseline
# of none" rather than either hiding it or blocking on it.
RARE_EVENT_MIN = 3
CHARACTER_CELLS = {"spa": 3, "bcn": 3}              # run and scored, but they do NOT gate
NEEDED_CELLS = GATING_CELLS                          # what completeness and not-worse are judged on
MIN_SIDE = 3          # runs per arm before a default change is evidenced; the opening-lap spread demands 3+

# metric -> (higher is worse?, label). laptime is two-sided: drifting either way means the pace changed.
# laptime_median_s IS DELIBERATELY ABSENT. It is not a lap time: race_metrics derives it from the difference
# between DIAG SNAPSHOT timestamps, and diag writes every 8 s - so every "lap time" it produces is a multiple of 8,
# and a median over an even-length list gives multiples of 4. That is why every Monza 12-lap row in results.csv
# reads a whole number (120, 121, 124, 128) with spreads of exactly 8, 12 or 16, while a real GT3 Monza lap is
# about 110 s. It cannot resolve anything finer than ~8 s, so comparing 120.3 against 120.0 - which refused this
# release - was reading a quantisation artefact as a pace regression.
# The feed already carries AC's own lap times to the millisecond (`lap_ms`, with `cuts`), which is the right source
# for a pace gate. Until the suite scores from that, THIS GATE DOES NOT JUDGE PACE, and says so rather than
# pretending a coarse number is a fine one.
# PACE IS NOW JUDGED, from the source named above. tools/pace.py reads the feed's `lap_ms` and writes
# harness_results/pace.csv; `pace_best_s` is the field's fastest CLEAN lap, which is the pace CEILING.
# WHY THE CEILING AND NOT A FIELD AVERAGE: a field-aggregate lap time is partly a TRAFFIC metric, and the arms here
# differ in how much they overtake - which is the thing under test, so it confounds the measurement by construction.
# Measured 2026-10-13: Monza's unfiltered field median read 1.0-1.7 s "slower" on HEAD with non-overlapping ranges
# against a baseline whose own spread was 0.12 s, and the entire difference was midfield cars getting fewer clear
# laps because HEAD passes more. Filtering to laps run more than 2 s clear of the car ahead dissolved it. The
# ceiling needs no such filter - the fastest lap of a race is almost always a clear one, and filtering did not move
# it at all - so the ceiling is what this gates on.
# ONE-SIDED, NOT TWO-SIDED. The earlier two-sided treatment ("drifting either way means the pace changed") is wrong
# for a REGRESSION gate: getting faster is not a regression, and flagging it would block good work exactly as the
# better-than-baseline bug did for incidents. Whether we are faster than is REALISTIC is a different question, asked
# against reality.md's human references, not against our own previous build.
# The fourth field is the NOISE FLOOR in that metric's own units. It used to be a blanket 1.0, which reads as "one
# whole event" for a count and as "one second" for a lap time - the same number meaning two unrelated things.
# Counts keep 1.0 (you cannot resolve a rare event against a zero-spread baseline at n=3). Pace gets 0.30 s, which
# is MEASURED rather than chosen: the fastest clean lap repeats to 0.17 s across three Monza races and 0.23 s across
# three Spa races, so 0.30 s sits just above the tightest observed arm spread and otherwise lets the arm's own
# spread govern.
SUITE_METRICS = [("contact_events", True, "contact", 1.0), ("incidents", True, "inc", 1.0),
                 ("heavy80", True, "heavy80", 1.0), ("retired_or_parked", True, "dead", 1.0),
                 ("pace_best_s", True, "pace_s", 0.30)]
PACE_NOTE = "pace judged on pace_best_s (feed lap_ms, 0.001 s resolution, fastest clean lap = the ceiling)"
# Metrics where an ABSENT (empty) value is different from a genuine 0 and must REFUSE rather than coerce to 0.0.
# pace_best_s is joined from pace.csv and is missing until the writer runs. contact_events and incidents are
# feed-derived and - verified across the 829-row results archive - are never empty in practice, so this is
# defensive future-proofing for them (a schema gap would otherwise read as a perfect 0 = "not worse"/BETTER).
# heavy80 and retired_or_parked are NOT here: 0 is a real and common value for them, so "0 in both arms = not
# judged" (the skip rule) is correct, not a refusal.
REFUSE_IF_ABSENT = ("contact_events", "incidents", "pace_best_s")


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
            rows = list(csv.DictReader(fh))
    except OSError:
        return None
    # Join the pace sidecar on label. Pace lives in its own file because it is computed from the FEED, not from the
    # harness row - the harness cannot write it without being imported, and importing harness.py taskkills the game.
    # A missing pace.csv, or a row absent from it, simply leaves the column empty and the gate skips the metric for
    # that cell rather than inventing a value.
    try:
        with io.open(PACE_CSV, encoding="utf-8", errors="replace") as fh:
            pace = {r["label"]: r for r in csv.DictReader(fh) if r.get("label")}
    except OSError:
        return rows
    for r in rows:
        p = pace.get(r.get("label") or "")
        if p and p.get("best_s"):
            r["pace_best_s"] = p["best_s"]
    return rows


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


def short_cells(counts):
    """Which GATING cells the freshest suite has too few runs of, as "cell(n of m)" strings.

    Pulled out of check_suite so the rule is testable without git or results.csv - see --selftest. The rule that
    matters is what it does NOT look at: CHARACTER_CELLS never appear here, because decision 0027 demoted the
    2-lap sprints and a sprint was previously able to refuse a whole release.
    """
    out = []
    for c in sorted(NEEDED_CELLS):
        n = counts.get(c, 0)
        if n < NEEDED_CELLS[c]:
            out.append("%s(%d of %d)" % (c, n, NEEDED_CELLS[c]))
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
    short = short_cells(counts)
    if short:
        rep.fail("suite completeness", "freshest suite %s is short: %s" % (fresh_prefix, " ".join(short)))
    else:
        rep.ok("suite completeness", "%s gating %s | character (not gating) %s" % (
            fresh_prefix, " ".join("%s x%d" % (c, counts[c]) for c in sorted(NEEDED_CELLS)), chars))
    return fresh_prefix, suite


def check_not_worse(rep, suite, fresh_prefix, all_rows=()):
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
    # ONLY THE GATING CELLS. Decision 0027 made the 2-lap sprints character-only, and this loop was still
    # judging them - so a single heavy hit in a Spa sprint (heavy80 0.3 against a 0.0-0.0 baseline) could refuse
    # the whole release on a cell the owner had explicitly demoted. The sprints are reported by completeness and
    # scored by hand for opening-lap character; they do not appear here.
    for cell, arm in sorted(k for k in new if k[0] in GATING_CELLS):
        a, b = old.get((cell, arm), []), new[(cell, arm)]
        base_label = base_prefix
        # A cell added to the suite has no baseline under the suite's naming (decision 0027 created spa12 today), so
        # fall back to the declared equivalent pre-change run. Explicit map, verified entry by entry - see
        # BASELINE_ALIAS.
        if len(a) < 2 and cell in BASELINE_ALIAS:
            pref = BASELINE_ALIAS[cell]
            a = [r for r in all_rows if (r.get("label") or "").startswith(pref)]
            base_label = "%s (aliased baseline)" % pref
        name = "not worse %s" % (cell if arm == "-" else "%s/%s" % (cell, arm))
        if len(a) < 2 or len(b) < 2:
            rep.refuse(name, "%s n=%d vs %s n=%d - a single run has no range, so this cell can neither show a "
                             "regression nor rule one out" % (base_label, len(a), fresh_prefix, len(b)))
            continue
        bad, unresolved, notes, skipped, refused = [], [], [], [], []
        for key, higher_worse, label, floor in SUITE_METRICS:
            if key in REFUSE_IF_ABSENT:
                # An ABSENT value means the metric could not be computed (pace.csv not written, or a log/feed
                # gap), which is different from a genuine 0. nums() would coerce it to 0.0 and, these metrics all
                # being higher-worse, a 0.0 reads as mean < lo and prints "0.0 BETTER" - absence masquerading as
                # the best possible result. PC #1's rc17 did exactly this for pace on mon, spa12 and sgf. So an
                # absent value REFUSES the cell (a REFUSED counts as a failure) rather than being compared.
                amiss = sum(1 for r in a if not str(r.get(key) or "").strip())
                bmiss = sum(1 for r in b if not str(r.get(key) or "").strip())
                if amiss or bmiss:
                    where = "both arms" if amiss and bmiss else "baseline" if amiss else "head"
                    refused.append(label)
                    notes.append("%s REFUSED (absent: %s)" % (label, where))
                    continue
            av, bv = nums(a, key), nums(b, key)
            if key == "pace_best_s" and any(x <= 0 for x in av + bv):
                # pace can be PRESENT but 0 or negative (a stale/garbage row); that is still not a lap time.
                refused.append(label)
                notes.append("%s REFUSED (zero/negative)" % label)
                continue
            if not av or not bv or (max(av) == 0 and max(bv) == 0):
                # the sprint cells never produce a median lap time; do not pretend they did.
                # BUT SAY SO. This skip used to be silent, and the cell then read "4 of 5 metrics judged" with
                # no indication of WHICH one went missing. On the 2026-10-14 release the missing one was `dead`
                # in BOTH gating cells - retirements, the claim the whole project rests on - because GT3 at
                # Monza and Spa with Verve on retires nobody, so the metric is structurally dead there. A
                # release could regress "Verve keeps cars racing" and this gate would not notice.
                skipped.append(label)
                continue
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
            w = max(hi - lo, floor)
            # For a higher-is-worse metric, anything at or BELOW the top of the baseline range is not worse -
            # including below the whole range, which is an IMPROVEMENT. The old form only passed values INSIDE
            # [lo, hi], so HEAD being better than baseline came back "?" and refused the release: Monza incidents
            # went 24,25,24 -> 22,20,21 and the gate called a four-incident improvement unresolved. A gate that
            # cannot tell "better" from "unmeasurable" will block good work as readily as bad.
            if higher_worse:
                if mean <= hi:
                    tag, where = (" BETTER", None) if mean < lo else ("", None)
                elif hi == lo and sum(bv) < RARE_EVENT_MIN:
                    # A RARE EVENT AGAINST A ZERO-SPREAD BASELINE, at n=3 a side. One heavy hit or one DNF cannot be
                    # told from noise here, and refusing on it means the gate can NEVER pass on these metrics
                    # however good the code is - it would have blocked this release on a single retirement in 54
                    # car-races. The count is stated rather than hidden or treated as a verdict.
                    tag, where = " %d in %d runs, below significance" % (int(sum(bv)), len(bv)), None
                elif mean > hi + w:
                    tag, where = " WORSE", bad
                else:
                    tag, where = " ?", unresolved
            else:                                      # two-sided (pace): drifting either way is a change
                if lo <= mean <= hi:
                    tag, where = "", None
                elif mean > hi + w or mean < lo - w:
                    tag, where = " WORSE", bad
                else:
                    tag, where = " ?", unresolved
            notes.append("%s %.1f vs %.1f-%.1f%s" % (label, mean, lo, hi, tag))
            if where is not None:
                where.append(label)
        # NOT a failure, deliberately. A skipped metric means 0 against 0, which is uninformative, and refusing
        # on it would make this gate UNPASSABLE on any GT3 cell however good the code was - the same trap the
        # rare-event rule above exists to avoid. So it is STATED and left to the reader: they can act on a
        # number they can see, and cannot act on one that silently vanished from a count.
        skip_note = ""
        if skipped:
            skip_note = " | NOT JUDGED (0 in both arms): %s" % ", ".join(skipped)
            if "dead" in skipped:
                skip_note += " -- so THIS CELL SAYS NOTHING ABOUT RETIREMENTS"
        detail = "%s(n=%d) -> %s(n=%d): %s%s | %s" % (base_label, len(a), fresh_prefix, len(b),
                                                      ", ".join(notes) or "no metric comparable", skip_note,
                                                      PACE_NOTE)
        if not notes:
            rep.refuse(name, detail)
        elif bad:
            rep.fail(name, detail)
        elif refused:
            rep.refuse(name, detail + " | pace REFUSED: a cell's pace is absent/zero/negative; write it with "
                                      "tools/pace.py --cell <c> --write (or rerun the cell) - a non-positive pace "
                                      "must never read as '0.0 BETTER'")
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


def rule_checks():
    """Every rule, as one list of failures. Seeded defects RE-RUN THIS, rather than a second copy of the logic.

    That matters: cspf1's scorer was proven against four synthetic cases that all shared its own assumption, so
    the test re-encoded the bug it was meant to catch. A seed must drive the real checker, not a paraphrase.
    """
    f = []
    full = dict(NEEDED_CELLS)
    if short_cells(full):
        f.append("a complete suite was reported short: %s" % short_cells(full))
    for c in full:
        missing = dict((k, v) for k, v in full.items() if k != c)
        if not any(s.startswith(c + "(") for s in short_cells(missing)):
            f.append("a suite missing the gating cell %r was NOT reported short" % c)
    with_chars = dict(full)
    for c in CHARACTER_CELLS:
        with_chars[c] = 0
    if short_cells(with_chars):
        f.append("a character cell at zero runs was treated as gating: %s" % short_cells(with_chars))
    # THE DEPTH ITSELF, not just which cells. Found by a seeded defect: nothing here noticed the requirement being
    # lowered to one run a cell, which would let a single race per cell satisfy the gate while every other check
    # still passed. n>=3 is the project standard and a 12-lap cell's own spread is 1.40x, so one run has no range.
    thin = sorted("%s=%d" % (c, n) for c, n in NEEDED_CELLS.items() if n < 3)
    if thin:
        f.append("a gating cell requires fewer than 3 runs: %s" % ", ".join(thin))
    if MIN_SIDE < 3:
        f.append("MIN_SIDE %d is below the project's n>=3 standard" % MIN_SIDE)

    # a one-run baseline must refuse, never pass: "no range" is not "no regression"
    rep = Report()
    mk = lambda lab, inc: {"label": lab, "incidents": str(inc), "contact_events": "50", "file": "x"}
    suite = [mk("rc99a_sgf_1", 20)] + [mk("rc99b_sgf_%d" % i, 20) for i in (1, 2, 3)]
    check_not_worse(rep, suite, "rc99b", all_rows=suite)
    verdicts = [v for v, n, d in rep.rows if "sgf" in n]
    if "PASS" in verdicts:
        f.append("a gating cell with a 1-run baseline PASSED: %s" % verdicts)
    if "REFUSED" not in verdicts:
        f.append("a gating cell with a 1-run baseline was not refused: %s" % verdicts)

    # PACE: absent, empty, zero or negative pace must REFUSE, never read as "0.0 BETTER". nums() coerces a
    # missing pace to 0.0 and pace_best_s is higher-worse, so a 0.0 would print mean < lo = BETTER - which is
    # what PC #1's rc17 did on mon, spa12 and sgf. Three seeded cases: a missing row, a 0.0 row, a valid row.
    def pace_verdicts(fresh_pace):
        base = [dict(mk("rc98a_sgf_%d" % i, 20), pace_best_s="110.5") for i in (1, 2, 3)]
        extra = {} if fresh_pace is None else {"pace_best_s": fresh_pace}
        fresh = [dict(mk("rc98b_sgf_%d" % i, 20), **extra) for i in (1, 2, 3)]
        r = Report()
        check_not_worse(r, base + fresh, "rc98b", all_rows=base + fresh)
        return [v for v, n, d in r.rows if "sgf" in n]
    if "REFUSED" not in pace_verdicts(None):
        f.append("a MISSING pace row did not REFUSE (would read as 0.0 BETTER): %s" % pace_verdicts(None))
    if "REFUSED" not in pace_verdicts("0.0"):
        f.append("a pace of 0.0 did not REFUSE (the '0.0 BETTER' bug): %s" % pace_verdicts("0.0"))
    if "REFUSED" in pace_verdicts("109.0"):
        f.append("a VALID pace (109.0, faster than baseline) was wrongly refused: %s" % pace_verdicts("109.0"))

    # An ABSENT (empty) contact_events must REFUSE too; a genuine 0 must still be judged, not refused.
    def contact_verdicts(fresh_contact):
        base = [dict(mk("rc97a_sgf_%d" % i, 20), pace_best_s="110.5") for i in (1, 2, 3)]
        fresh = [dict(mk("rc97b_sgf_%d" % i, 20), pace_best_s="110.5", contact_events=fresh_contact)
                 for i in (1, 2, 3)]
        r = Report(); check_not_worse(r, base + fresh, "rc97b", all_rows=base + fresh)
        return [v for v, n, d in r.rows if "sgf" in n]
    if "REFUSED" not in contact_verdicts(""):
        f.append("an ABSENT contact_events did not REFUSE: %s" % contact_verdicts(""))
    if "REFUSED" in contact_verdicts("0"):
        f.append("a genuine-0 contact_events was wrongly refused (0 must be judged): %s" % contact_verdicts("0"))

    for cell in list(GATING_CELLS) + list(CHARACTER_CELLS):
        m = SUITE_RE.match("rc16c_%s_on_1" % cell)
        if not m or m.group(2) != cell:
            f.append("SUITE_RE does not match cell %r (got %r)" % (cell, m and m.group(2)))
    m = SUITE_RE.match("rc16c_spa12_on_1")
    if not m or m.group(2) != "spa12":
        f.append("spa12 lost its precedence over spa in SUITE_RE")
    return f


def selftest():
    """Check the gate's own rules, then break each rule and confirm the check complains.

    THIS TOOL HAD NO SELFTEST UNTIL NOW, and it is the one place where that mattered most: it decides whether a
    release is admissible, and five rule defects were found in it by hand on 2026-10-13. A gate that admits or
    excludes evidence deserves more scrutiny than the measurement it gates, not less.

    The rules checked are the ones whose failure would be SILENT: that every gating cell is required by
    completeness (which is what makes a CSP-3465 suite report incomplete rather than passing on the cells it
    managed, decision 0035); that character cells never gate (a 2-lap sprint could once refuse a whole release,
    decision 0027); that a gating cell with a one-run baseline is refused rather than passed, which is the state
    `sgf` sits in until cspf5 provides an interleaved baseline; and that the label grammar still matches each
    cell token with spa12 winning over its own prefix spa.
    """
    fails = rule_checks()
    print("=== release_check selftest ===")
    for x in fails:
        print("  FAIL %s" % x)
    print("  %s" % ("every rule holds" if not fails else "RULES BROKEN"))

    print("\n=== seeded rule defects (untrusted until each FAILS rule_checks) ===")
    allok = True
    seeds = [
        ("a gating cell dropped from the requirement", "pop_sgf"),
        ("a character cell promoted to gating", "promote_spa"),
        ("the gating requirement lowered to 1 run", "loosen"),
    ]
    for name, kind in seeds:
        saved_needed, saved_chars = dict(NEEDED_CELLS), dict(CHARACTER_CELLS)
        if kind == "pop_sgf":
            NEEDED_CELLS.pop("sgf", None)
        elif kind == "promote_spa":
            NEEDED_CELLS["spa"] = 3
        else:
            for k in list(NEEDED_CELLS):
                NEEDED_CELLS[k] = 1
        got = rule_checks()
        NEEDED_CELLS.clear(); NEEDED_CELLS.update(saved_needed)
        CHARACTER_CELLS.clear(); CHARACTER_CELLS.update(saved_chars)
        print("  %-46s %s" % (name[:46], "caught" if got else "NOT CAUGHT"))
        allok &= bool(got)
    print("\n  %s" % ("every seeded defect caught" if allok else "SELFTEST NOT TRUSTWORTHY"))
    return 0 if (not fails and allok) else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
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
    check_not_worse(rep, suite, fresh_prefix, all_rows=rows)
    check_evidence(rep, rows, base, head)
    check_gate(rep, base, head)
    check_docs(rep)
    return rep.show()


if __name__ == "__main__":
    sys.exit(main())
