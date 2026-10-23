"""Separate REAL EXCURSIONS from wide lines and chicane cuts, per corner, from the race feed.

    python tools/excursions.py spa                      # every spa feed, one row per race
    python tools/excursions.py spa --label c2_spa12     # only races whose diag label contains this
    python tools/excursions.py spa --bands              # also print the speed map (which band is which corner)

WHY THIS EXISTS. A raw off_track count ranks troublespots WRONGLY. At Spa, wide-running outnumbers real excursions
about four to one, so the biggest count (Raidillon exit) is cars running marginally wide and carrying on, while the
genuine ones (Les Combes, the Bus Stop) are smaller. I withdrew a finding over that on 2026-10-12 and PC #2 withdrew
one the same morning. The discriminator is SPEED: a cut or a wide line holds the band speed, an excursion collapses
and stays collapsed.

THIS FILE IS THE DEFINITION, not a prose spec - both machines run it so the columns cannot drift apart.
  an EXCURSION = an off_track where the car is below the threshold AT the event (median of the state samples within
  +/-1.5 s) AND still below it 3-8 s LATER (median of the samples in that window, NOT a single point at t+8: states
  are 1 Hz, so one sample is noise and may be missing entirely).
  TWO thresholds, because an absolute one is track-position dependent - PC #2 raised this, and it is right: the Bus
  Stop's own speed is ~71 km/h, so a benign cut there is already under an absolute 90.
    ABS  below 90 km/h            - comparable across tracks, unreliable in slow corners
    REL  below 60 % of that band's own median speed - correct in slow corners, needs enough samples in the band
  If the two disagree about a band, believe REL and say which you quoted.

RATES are per 100 CAR-LAPS, with ALL-LAPS and LAP-2+ separate: lap 0-1 is 17 % of a 12-lap race but 3 % of a 60-lap
one, so the all-laps figure flatters whoever ran shorter races.

SPREAD: on two arm-identical clean Spa GT3 races this metric gave 3.89 and 1.11 lap-2+ excursions per 100 car-laps -
a 3.5x spread on nothing. Use three runs a side; one race cannot carry a reference. Check comparability first with
tools/arm_check.py.
"""
import collections
import glob
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NO_LABEL = "(no harness label)"
VERVE = os.path.dirname(HERE)
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
FEEDS = os.path.join(DOCS, "verve_feed")
# Housekeeping moves feeds older than harness.py's KEEP_DAYS (2.0) to the archive, so a tool that globs only the
# live directory can answer an ON/OFF question about last week with an empty set and no error. 2026-10-22: that is
# exactly what happened - 2690 archived feeds were invisible here while this file was treated as the definition of
# the metric. tools/paths.py was written for this exact defect and already resolves the archive wherever it is
# (D:, E:, or the local folder) and warns when it cannot find one; USE IT rather than hardcoding a path here,
# which is how the problem started. FEEDS_ARCH stays as a name for the selftest to rebind.
sys.path.insert(0, HERE)           # python -I drops the script directory from sys.path; batch.py and
import paths                       # harness.py insert it for the same reason. Without this the tool works
                                   # under a plain run and dies under an isolated one.
FEEDS_ARCH = paths.archive_feed_dir() or os.path.join(HERE, "harness_results", "archive", "verve_feed")


def _collect(dirs, track):
    """The feeds for a track across the given directories, each race exactly once, first directory winning.

    Takes `dirs` as an argument on purpose: the de-duplication assertion in selftest() was disarmed twice by
    edits to the directory-list code when it depended on that code to produce a duplicate. Handing this helper
    the same directory twice forces the condition, and no change to the caller can take it away.
    """
    seen, out = set(), []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for p in sorted(glob.glob(os.path.join(d, "*" + track + "*.jsonl"))):
            b = os.path.basename(p)
            if b in seen:          # a file mid-archive exists in both; counting it twice doubles its race
                continue
            seen.add(b)
            out.append(p)
    return sorted(out, key=os.path.basename)


def feed_paths(track):
    """Every feed for a track, live and archived, each race exactly once."""
    dirs = [d for d in paths.feed_dirs() if d != FEEDS_ARCH]
    dirs.append(FEEDS_ARCH)        # named explicitly so the selftest can point it elsewhere
    return _collect(dirs, track)

ABS_KMH = 90.0
REL_FRAC = 0.60
BAND = 0.02


def band_of(s):
    return round(s / BAND) * BAND


def read_feed(path):
    """(offs, speed samples per car, speed samples per band, max leader lap, cars, leader-lap timeline)."""
    st = collections.defaultdict(list)
    bysp = collections.defaultdict(list)
    offs, leader = [], []
    maxlap, ncars = 0, 0
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue          # a half-written tail line while the race is still running
                ty = d.get("type")
                if ty == "header":
                    cs = d.get("cars")
                    ncars = len(cs) if isinstance(cs, list) else 0
                elif ty == "state":
                    t, lap = d.get("t"), d.get("leader_lap")
                    if t is not None and isinstance(lap, (int, float)):
                        leader.append((t, lap))
                        if lap > maxlap:
                            maxlap = lap
                    for c in (d.get("cars") or []):
                        v, s = c.get("spd"), c.get("spline")
                        if isinstance(v, (int, float)):
                            st[c.get("i")].append((t, v))
                            if isinstance(s, (int, float)) and v > 5:
                                bysp[band_of(s)].append(v)
                elif ty == "off_track" and isinstance(d.get("spline"), (int, float)):
                    offs.append((d.get("car"), d.get("t"), d["spline"]))
    except OSError:
        return None
    return offs, st, bysp, maxlap, ncars, leader


def classify(path):
    r = read_feed(path)
    if not r:
        return None
    offs, st, bysp, maxlap, ncars, leader = r
    bmed = {b: statistics.median(v) for b, v in bysp.items() if len(v) >= 30}
    cars = max(ncars, 1)
    out = dict(maxlap=maxlap, ncars=ncars, n_off=len(offs), wide=0, unjoined=0,
               exc_abs=collections.Counter(), exc_rel=collections.Counter(), abs_l2=0, rel_l2=0,
               carlaps=maxlap * cars, carlaps_l2=max(0, maxlap - 2) * cars, bands=bmed,
               # (car, t, lap>=2) per ABS excursion, so a caller can ask which of them are STRANDINGS: a car
               # that goes off and stops is below threshold forever and is therefore an excursion BY
               # CONSTRUCTION, which means this metric is not independent of the retirement outcome.
               exc_events=[])

    def lap_at(t):
        best = 0
        for tt, lap in leader:
            if tt is not None and t is not None and tt <= t:
                best = lap
        return best

    for car, t, s in offs:
        sm = st.get(car) or []
        at = [v for (tt, v) in sm if tt is not None and t is not None and abs(tt - t) <= 1.5]
        later = [v for (tt, v) in sm if tt is not None and t is not None and 3 <= (tt - t) <= 8]
        if not at:
            out["unjoined"] += 1
            continue
        a = statistics.median(at)
        n = statistics.median(later) if later else a
        b = band_of(s)
        ref = bmed.get(b)
        is_abs = a < ABS_KMH and n < ABS_KMH
        is_rel = ref is not None and a < REL_FRAC * ref and n < REL_FRAC * ref
        if is_abs:
            out["exc_abs"][b] += 1
            l2 = lap_at(t) >= 2
            out["exc_events"].append((car, t, l2))
            if l2:
                out["abs_l2"] += 1
        if is_rel:
            out["exc_rel"][b] += 1
            if lap_at(t) >= 2:
                out["rel_l2"] += 1
        if not is_abs and not is_rel:
            out["wide"] += 1
    return out


_LABELS = None


def labels_by_stem():
    """{'20261012_071559': 'kxs_sgp_defaults_1'} from results.csv, which holds the diag filename AND the label.

    Do NOT recover the label by splitting the filename on '_' and dropping a fixed number of parts: the TRACK name
    can itself contain underscores, so singapore_2020 came back as '2020_kxs_sgp_defaults_1' and every join on it
    silently missed (2026-10-12). results.csv pairs file with label exactly, so look it up.
    """
    global _LABELS
    if _LABELS is None:
        _LABELS = {}
        import csv
        # EVERY results csv, rotated ones first so the live file wins any collision. Reading results.csv alone
        # was a defect (2026-10-22): the harness ROTATES this file - 319 `results_until_*.csv` on PC #1 - so a
        # stem absent from the live file was usually written before the last rotation, NOT aborted. The stem the
        # selftest probes, 20260917_000240, sits in results_until_20260917_1027.csv. BTeam saw the same thing on
        # PC #2 and read it as a PC #2 defect; it is the rotation, on both machines.
        rot = sorted(glob.glob(os.path.join(HERE, "harness_results", "results_until_*.csv")))
        arch = sorted(glob.glob(os.path.join(HERE, "harness_results", "archive", "results*.csv")))
        for path in arch + rot + [os.path.join(HERE, "harness_results", "results.csv")]:
            try:
                with io.open(path, encoding="utf-8", errors="replace") as fh:
                    for r in csv.DictReader(fh):
                        f, lab = r.get("file") or "", r.get("label") or ""
                        b = os.path.basename(f)
                        if b.startswith("diag_race_") and lab:
                            _LABELS[b[len("diag_race_"):len("diag_race_") + 15]] = lab
            except OSError:
                continue
    return _LABELS


def label_for(stem):
    hit = labels_by_stem().get(stem)
    if hit:
        return hit
    # no results row (a race still running, or scored elsewhere): strip the track the diag header names, not a guess
    for pat in (os.path.join(VERVE, "diag_race_" + stem + "*"),
                # the archive keeps diag files in a 'diag' subdirectory; without it every archived race fell
                # through to the bare stem and joined nothing (found 2026-10-22)
                os.path.join(VERVE, "tools", "harness_results", "archive", "diag", "diag_race_" + stem + "*"),
                os.path.join(VERVE, "tools", "harness_results", "archive", "diag_race_" + stem + "*")):
        for d in glob.glob(pat):
            b = os.path.basename(d).replace("diag_race_", "").replace(".jsonl", "")
            try:
                with io.open(d, encoding="utf-8", errors="replace") as fh:
                    hdr = json.loads(fh.readline())
                track = hdr.get("track") or ""
            except (OSError, ValueError):
                track = ""
            rest = b[16:]                      # past '<date>_<time>_'
            if track and rest.startswith(track.replace("/", "_") + "_"):
                return rest[len(track.replace("/", "_")) + 1:]
            # `diag_race_<stamp>_<track>.jsonl` with nothing after the track is a race the harness did not label
            # - the owner's own race at 16:42 on 2026-10-22 produced one, and it used to be pooled under the
            # label "monza".
            if track and rest == track.replace("/", "_"):
                return NO_LABEL
            return rest or b
    # No diag on disk and no row in any results csv (the results branch above would have answered): the race
    # cannot be attributed to a queue row at all, so it is not poolable into a cell. Archived races whose diag
    # housekeeping removed are rescued by the rotated-csv read above, not by guessing here.
    return NO_LABEL


def selftest():
    """Asserts the two things that were broken, plus the hazard the fix introduces (double counting)."""
    global FEEDS_ARCH          # declared here because the de-duplication check below rebinds it; Python needs
    ok = True                  # the declaration before the first reference anywhere in the function
    # THREE STATES, and only one of them is a failure. A machine with NO archive is not a machine with a broken
    # archive lookup - paths.py's own docstring calls a missing archive "a normal answer: the drive may simply
    # not be attached". The first version of this check failed on PC #2 for having all its feeds live, which is
    # a selftest crying wolf, and the stop-and-ask habit it would train away is the one worth keeping.
    if not os.path.isdir(FEEDS_ARCH):
        print("selftest: NOTE - no feed archive on this machine (%s). Nothing to check there, and nothing is"
              % FEEDS_ARCH)
        print("          wrong: feeds are read from the live directory alone, which is correct when every feed")
        print("          is live. This is a PASS - the archive assertions are SKIPPED, not satisfied.")
    else:
        n = len(glob.glob(os.path.join(FEEDS_ARCH, "*.jsonl")))
        if n == 0:
            print("selftest: NOTE - the archive directory exists but holds no feeds; archive assertions skipped")
        else:
            # the whole point: a track with archived races must be found even when the live dir has none of them
            found = feed_paths("spa")      # NOT named 'paths': that shadowed the paths MODULE and broke the
            if not any(os.path.dirname(p) == FEEDS_ARCH for p in found):   # checks further down this function
                print("SELFTEST FAIL: feed_paths() returned no ARCHIVED feed for spa (%d total)" % len(found))
                ok = False
        if FEEDS_ARCH not in paths.feed_dirs(warn=False):
            print("SELFTEST FAIL: the archive exists but paths.feed_dirs() does not return it")
            ok = False
    # NO RACE COUNTED TWICE, and the duplicate condition is FORCED by handing _collect the same directory twice.
    # Two earlier versions of this check were disarmed without anyone noticing: one hoped a monza feed would
    # happen to sit in both directories, the other rebound FEEDS_ARCH and was then neutralised by a refactor that
    # filtered the live directory out of the list. Both passed on the mutant with the de-duplication deleted.
    probe_dirs = [d for d in paths.feed_dirs() if glob.glob(os.path.join(d, "*monza*.jsonl"))]
    if not probe_dirs:
        print("SELFTEST FAIL: no directory holds a monza feed, so de-duplication cannot be exercised at all")
        ok = False
    else:
        d = probe_dirs[0]
        names = [os.path.basename(p) for p in _collect([d, d], "monza")]
        if len(names) != len(set(names)):
            print("SELFTEST FAIL: _collect() returned the same race twice (%d paths, %d distinct)"
                  % (len(names), len(set(names))))
            ok = False
    # THE ASSERTION THAT BITES: label_for must resolve a stem that ONLY the archive can answer. This stem is one
    # of the 2175 archived diags absent from results.csv, so the results.csv branch cannot reach it and the
    # archive glob is the only path left. Asserting that archive/diag merely EXISTS passes through any mutation
    # of the code that reads it, which is the difference between a selftest and a comment.
    ad = os.path.join(VERVE, "tools", "harness_results", "archive", "diag")
    if os.path.isdir(ad) and not glob.glob(os.path.join(ad, "diag_race_*")):
        print("SELFTEST FAIL: archive/diag exists but holds no diag_race_* files")
        ok = False
    probe = "20260917_000240"
    if glob.glob(os.path.join(ad, "diag_race_" + probe + "*")):
        got = label_for(probe)
        if got != "n17_reg_spa_3":
            print("SELFTEST FAIL: label_for(%s) = %r, expected 'n17_reg_spa_3' - the archived diag was not read"
                  % (probe, got))
            ok = False
    # THE FRAGMENT RULE, and the case the PREVIOUS version of this gate got wrong. Both are FORCED: the
    # candidates are synthetic, so no assertion here can be satisfied by what happens to be on disk, and none of
    # them can be satisfied by consulting results.csv - pick() cannot see it.
    def _c(lab, stem, laps, fin, era=True, live=False):
        return {"lab": lab, "stem": stem, "laps": laps, "fin": fin, "era": era, "live": live}

    cands = [_c("row_a", "s1", 10, True),                     # the completed attempt
             _c("row_a", "s2", 5, True),                      # killed at 16:43 for the owner's race: HAS race_end
             _c("row_a", "s3", 1, False),                     # killed by the 17:38 reboot: no race_end
             _c("row_b", "s4", 8, True),                      # complete, in no results csv: BTeam's PC #2 rows
             _c("row_c", "s5", 2, False, era=False),          # pre-29-Sep: no race on that DAY could write
             _c("row_c", "s6", 2, False, era=False),          # race_end, so absence says nothing - both KEPT
             _c("row_d", "s7", 3, False, live=True)]          # ON TRACK RIGHT NOW - its own label, so a sibling
    keep, dropped, unknown = pick(cands)                      # test could never catch it; mtime does
    got = sorted(s for _, s, _ in keep)
    if got != ["s1", "s4", "s5", "s6"]:
        print("SELFTEST FAIL: pick() kept %s, expected ['s1', 's4', 's5', 's6']: row_a's 5-lap and 1-lap"
              " attempts must go; row_b must be KEPT though no results csv names it; row_c's two races must be"
              " KEPT because no race that DAY could write race_end; and row_d must go because it is still on"
              " track - it is the sole attempt at its label, which is exactly what the old per-label test"
              " could not see (it pooled a 3-lap live race into an F2 arm)" % got)
        ok = False
    if not any("still running" in r for r in dropped):
        print("SELFTEST FAIL: pick() did not exclude the live race as still running (%r)" % list(dropped))
        ok = False
    if sorted(u.split(" ")[0] for u in unknown) != ["row_c", "row_c"]:
        print("SELFTEST FAIL: pick() kept the cohort races without flagging them uncertain (%r)" % unknown)
        ok = False
    if not any("superseded" in r for r in dropped):
        print("SELFTEST FAIL: pick() removed the short attempt without naming it superseded (%r), so the"
              " denominator would shrink in silence" % list(dropped))
        ok = False
    if not any("no tidy end" in r for r in dropped):
        print("SELFTEST FAIL: pick() did not name the unfinished attempt (%r)" % list(dropped))
        ok = False
    # THE ROTATION ASSERTION, WITH ITS PROBE DERIVED FROM THE DATA. The first version hardcoded
    # 20260917_000240 - PC #1's 17 Sep data - so on PC #2, whose oldest race is 9 Oct, the stem could not exist
    # and its absence was read as "the rotated files are not being read": a FALSE FAIL on the very machine this
    # fix was written for, and the fourth selftest in one evening to assume this machine's data (BTeam found
    # it). So pick any stem that a ROTATED file names and the live file does not, and assert labels_by_stem()
    # resolves it. No rotation on this machine means nothing to check, which is a PASS WITH A NOTE.
    # The csv read below is deliberately a second implementation: labels_by_stem() is the function under test,
    # so an assertion built from its own output would guard nothing.
    import csv as _csv

    def _stems(paths):
        out = set()
        for p in paths:
            try:
                with io.open(p, encoding="utf-8", errors="replace") as fh:
                    for r in _csv.DictReader(fh):
                        b = os.path.basename((r.get("file") or "").replace("\\", "/"))
                        if b.startswith("diag_race_") and (r.get("label") or ""):
                            out.add(b[10:25])
            except OSError:
                pass
        return out

    _rot = sorted(glob.glob(os.path.join(HERE, "harness_results", "results_until_*.csv")))
    if not _rot:
        print("selftest: NOTE - no rotated results csv on this machine, so the rotation assertion is SKIPPED,")
        print("          not satisfied. Nothing is wrong: results.csv has not rotated here yet.")
    else:
        _only_rotated = sorted(_stems(_rot) - _stems([os.path.join(HERE, "harness_results", "results.csv")]))
        if not _only_rotated:
            print("selftest: NOTE - every rotated stem is also in the live results.csv, so the rotation"
                  " assertion cannot bite here; SKIPPED, not satisfied")
        else:
            _p = _only_rotated[0]
            if _p not in labels_by_stem():
                print("SELFTEST FAIL: %s is named by a rotated results csv and NOT by the live one, and"
                      " labels_by_stem() cannot find it - the results_until_*.csv files are not being read."
                      " %d stems are in that state on this machine." % (_p, len(_only_rotated)))
                ok = False
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


LIVE_S = 90.0        # a feed written this recently belongs to a race that is ON TRACK


def feed_finished(path, tail=65536):
    """True when the feed carries a `race_end` line. NOT a completion marker on its own - see pick().

    Verve writes race_end from `ac.onRelease`, so a race killed by hand carries one too; and no feed before
    29 Sep 2026 carries one at all, because the event did not exist. What it does tell you is that the app shut
    down tidily. It is the LAST line a feed ever gets (F.finish does `flush(); closeFh()`), so only the tail is
    read: a full scan here cost every feed in a day being read end to end.
    """
    try:
        size = os.path.getsize(path)
        with io.open(path, "rb") as fh:
            if size > tail:
                fh.seek(size - tail)
            return b'"race_end"' in fh.read()
    except OSError:
        return False


def feed_live(path):
    """True when this feed is being written RIGHT NOW - the only CERTAIN still-running signal there is.

    The first version of the completion gate inferred "still running" from a missing race_end, and a running
    race is the sole attempt at its own label, so a per-label sibling test could never see a finished one: the
    race on track at 20:29 on 2026-10-22 was pooled into its arm as a 3-lap result (414 car-laps instead of
    540). mtime answers it outright.
    """
    try:
        import time
        return (time.time() - os.path.getmtime(path)) < LIVE_S
    except OSError:
        return False


def days_with_race_end(track, days):
    """{day: True/False} - did ANY race on that day write race_end? The ERA test, at the right scope.

    Measured provenance: 712 feeds from 14-28 Sep carry no race_end, the first is 20260929, and from 30 Sep on
    nearly every race has one. So absence is evidence of a kill only on a day that demonstrably could write one.
    The day, not the label (a single-attempt label proves nothing) and not the query (one query spans both eras).
    Deliberately NOT a date constant: PC #2 runs an older Verve that may never write race_end, and a 29-Sep
    cutoff would read every race there as killed.
    """
    out = {}
    for d in days:
        out[d] = False
    for p in feed_paths(track):
        d = os.path.basename(p)[:8]
        if d in out and not out[d] and feed_finished(p):
            out[d] = True
    return out


def pick(cands):
    """[{lab, stem, laps, fin, live, era}] -> (keep, dropped, unknown): what a cell may pool, and why not.

    THE RULE THAT MATTERS, and it needs no lap target: **within one label, only the longest attempt is
    poolable.** A queue row attempted three times (killed for the owner's race, killed by a reboot, then
    completed) leaves three feeds carrying the same label, which is how `f2_gt3_k0_off_2` came to appear three
    times in one table at 10, 5 and 1 laps on 2026-10-22.

    No target is used because none exists: the feed header's `laps` is 0 in every harness race measured
    (`sim.raceSessionLaps` is not populated), so "the leader reached the row's target" is not computable from a
    feed. And results.csv is NOT consulted - this function has no access to it - because the harness rotates
    that file, so "no row" means "before the last rotation" far more often than it means "aborted". Both
    mistakes were made here first.

    `dropped` is a reason -> races map rather than a count: an exclusion that is not named is a denominator
    that shrank in silence, which is the defect this tool was built to stop making.
    """
    keep, dropped, unknown = [], collections.OrderedDict(), []

    def drop(reason, text):
        dropped.setdefault(reason, []).append(text)

    # AN ABSENT SIGNAL IS ONLY A NEGATIVE ONCE IT HAS BEEN SHOWN TO FIRE. `race_end` did not exist before
    # 29 Sep 2026 (measured: 712 feeds from 14-28 Sep carry none; the first is 20260929), so reading its absence
    # as "killed" excluded every race before that date - the n17_reg cell lost all three of its complete 2-lap
    # sprints that way. So: per LABEL, a missing race_end excludes a race only when a SIBLING attempt at the same
    # label has one. Per label and not per query because one query spans both eras, and no date constant because
    # PC #2 runs an older Verve that may never write race_end - a cutoff would re-break that machine.
    rest = []
    for c in cands:
        where = "%s (%s, %d laps)" % (c["lab"], c["stem"], c["laps"])
        if c.get("live"):
            # CERTAIN, not inferred: the feed is being written as we read it.
            drop("still running - the feed was written in the last %.0f s" % LIVE_S, where)
        elif c["fin"] or not c.get("era"):
            rest.append((c["lab"], c["stem"], c["laps"]))
            if not c["fin"]:
                unknown.append(where)
        else:
            drop("no tidy end - killed mid-race (other races the same day wrote one, so the absence is"
                 " informative here)", where)
    best = {}
    for lab, _, m in rest:
        best[lab] = max(best.get(lab, 0), m)
    for lab, stem, m in rest:
        if m < best[lab]:
            drop("superseded by a longer attempt at the same label",
                 "%s (%s, %d of %d laps)" % (lab, stem, m, best[lab]))
        else:
            keep.append((lab, stem, m))
    return keep, dropped, unknown


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[0])
        return 2
    track = args[0]
    want = None
    for i, a in enumerate(sys.argv):
        if a == "--label" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1]
    cands, byst, unlabelled = [], {}, []
    for p in feed_paths(track):
        stem = os.path.basename(p)[:15]
        lab = label_for(stem)
        if lab == NO_LABEL:
            unlabelled.append(stem)             # not a harness race (or a diag housekeeping has removed)
            continue
        if want and want not in lab:
            continue
        c = classify(p)
        if not (c and c["maxlap"]):
            continue
        cands.append({"lab": lab, "stem": stem, "laps": c["maxlap"], "fin": feed_finished(p),
                      "live": feed_live(p), "path": p})
        byst[stem] = (lab, c)
    era = days_with_race_end(track, set(c["stem"][:8] for c in cands))
    for c in cands:
        c["era"] = era.get(c["stem"][:8], False)
    keep, dropped, unknown = pick(cands)
    rows = [byst[stem] for _, stem, _ in keep]
    for reason, items in dropped.items():
        print("  (%d race(s) EXCLUDED - %s: %s)" % (len(items), reason, ", ".join(sorted(items))))
    if unknown:
        print("  (%d race(s) KEPT with no race_end, and nothing at their label writes one: they predate the"
              " feature (before 29 Sep 2026) or every attempt was killed - the tool cannot tell which: %s)"
              % (len(unknown), ", ".join(sorted(unknown))))
    if unlabelled and not want:
        print("  (%d feed(s) with no harness label skipped - not harness races)" % len(unlabelled))
    if keep:
        hi = max(m for _, _, m in keep)
        short = ["%s (%d of %d laps)" % (lab, m, hi) for lab, _, m in keep if m < 0.6 * hi]
        if short:
            # a sole attempt at a row cannot be caught by the superseded rule - there is nothing to compare it
            # with - so say it looks short rather than pooling it silently. A cell of one distance makes this
            # exact; a mixed-distance --label group will flag its short rows harmlessly.
            print("  (WARNING - %d kept race(s) ran far shorter than the longest in this group, so they may be"
                  " unreplaced fragments: %s)" % (len(short), ", ".join(sorted(short))))
        nolab = [l + " (" + s + ")" for l, s, _ in keep if s not in labels_by_stem()]
        if nolab:
            print("  (note: %d kept race(s) have no row in ANY results csv - labelled from the diag filename."
                  " This is provenance, not a defect: the harness rotates results.csv.)" % len(nolab))
    if not rows:
        print("excursions: no %s feeds matched%s" % (track, " --label " + want if want else ""))
        return 1
    if "--bands" in sys.argv:
        bm = max((c["bands"] for _, c in rows), key=len)
        print("speed map, median km/h per %.2f band (a local minimum is a braking zone):" % BAND)
        for b in sorted(bm):
            print("   %.2f  %6.1f" % (b, bm[b]))
        print()
    print("EXCURSION = below threshold at the off AND still below it 3-8 s later (medians, never a single point).")
    print("ABS = under %.0f km/h. REL = under %.0f%% of that band's median. Rates per 100 car-laps.\n"
          % (ABS_KMH, 100 * REL_FRAC))
    print("%-26s %5s %5s %6s %7s %7s %10s %9s" % ("label", "laps", "offs", "wide", "excAbs", "excRel", "abs/100cl", "L2/100cl"))
    tot = collections.Counter()
    per_race = []
    for lab, c in rows:
        ea, er = sum(c["exc_abs"].values()), sum(c["exc_rel"].values())
        rate = 100.0 * ea / max(c["carlaps"], 1)
        per_race.append(rate)
        print("  %-24s %5d %5d %6d %7d %7d %10.2f %9.2f"
              % (lab[:24], c["maxlap"], c["n_off"], c["wide"], ea, er, rate,
                 100.0 * c["abs_l2"] / max(c["carlaps_l2"], 1)))
        tot["off"] += c["n_off"]; tot["wide"] += c["wide"]; tot["ea"] += ea; tot["er"] += er
        tot["cl"] += c["carlaps"]; tot["cl2"] += c["carlaps_l2"]; tot["l2"] += c["abs_l2"]
        tot["unjoined"] += c["unjoined"]
        for b, n in c["exc_abs"].items():
            tot["band_%.2f" % b] += n
    print()
    print("  POOLED %d races: %d offs = %d wide + %d excursions(ABS), %d excursions(REL)"
          % (len(rows), tot["off"], tot["wide"], tot["ea"], tot["er"]))
    print("  rate %.2f per 100 car-laps, LAP2+ %.2f"
          % (100.0 * tot["ea"] / max(tot["cl"], 1), 100.0 * tot["l2"] / max(tot["cl2"], 1)))
    if tot["ea"]:
        print("  wide:excursion %.1f:1 - this is why a raw off_track count ranks corners wrongly"
              % (tot["wide"] / float(tot["ea"])))
    bands = sorted(((k, v) for k, v in tot.items() if k.startswith("band_")), key=lambda x: -x[1])
    if bands:
        print("  excursions by band: " + ", ".join("%s=%d" % (k.replace("band_", ""), v) for k, v in bands[:8]))
    if len(rows) > 1:
        print("  per-race spread %.2f to %.2f per 100 car-laps - run tools/arm_check.py before pooling these"
              % (min(per_race), max(per_race)))
    if tot["unjoined"]:
        print("  (%d off_track events had no state sample within 1.5 s and were skipped, not counted either way)"
              % tot["unjoined"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
