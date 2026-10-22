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
               carlaps=maxlap * cars, carlaps_l2=max(0, maxlap - 2) * cars, bands=bmed)

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
            if lap_at(t) >= 2:
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
        try:
            with io.open(os.path.join(HERE, "harness_results", "results.csv"), encoding="utf-8", errors="replace") as fh:
                import csv
                for r in csv.DictReader(fh):
                    f, lab = r.get("file") or "", r.get("label") or ""
                    b = os.path.basename(f)
                    if b.startswith("diag_race_") and lab:
                        _LABELS[b[len("diag_race_"):len("diag_race_") + 15]] = lab
        except OSError:
            pass
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
            return rest or b
    return stem


def selftest():
    """Asserts the two things that were broken, plus the hazard the fix introduces (double counting)."""
    global FEEDS_ARCH          # declared here because the de-duplication check below rebinds it; Python needs
    ok = True                  # the declaration before the first reference anywhere in the function
    if not os.path.isdir(FEEDS_ARCH):
        print("selftest: archive feed dir missing (%s) - cannot check the thing that was broken" % FEEDS_ARCH)
        ok = False
    else:
        n = len(glob.glob(os.path.join(FEEDS_ARCH, "*.jsonl")))
        if n == 0:
            print("SELFTEST FAIL: archive feed dir has no feeds; the glob is pointing at the wrong place")
            ok = False
        # the whole point: a track with archived races must be found even when the live dir has none of them
        found = feed_paths("spa")      # NOT named 'paths': that shadowed the paths MODULE and broke the
        if not any(os.path.dirname(p) == FEEDS_ARCH for p in found):   # checks further down this function
            print("SELFTEST FAIL: feed_paths() returned no ARCHIVED feed for spa (%d total)" % len(found))
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
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


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
    rows = []
    for p in feed_paths(track):
        lab = label_for(os.path.basename(p)[:15])
        if want and want not in lab:
            continue
        c = classify(p)
        if c and c["maxlap"]:
            rows.append((lab, c))
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
