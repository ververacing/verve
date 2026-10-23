"""Score an A/B cell the way the survival-gap rules require: lap-2+ primary, and BOTH normalisations bracketed.

Written for F2 (pre-registered spec, verve_desk/racecraft/f2_scoring_spec_PREREGISTERED.md) but the rules it
implements are standing ones, so it takes any track and any list of arm prefixes - PC #2 can score classcov2
with it.

WHY A TOOL RATHER THAN ARITHMETIC BY HAND. Two rules in that spec are easy to state and easy to forget:

  1. **lap-2+ excursions per 100 car-laps is the PRIMARY** for any leg whose arms have different survival. A car
     stranded on lap 0 contributes almost no car-laps and can still contribute an excursion, so an all-laps rate
     rewards the arm that loses cars. Lap-2+ drops exactly that case.
  2. **THE BRACKET.** Report excursions per RACE-START as well as per car-lap, because the two err in OPPOSITE
     directions: with fewer car-laps the per-lap rate is pushed UP for the arm that loses cars, while the
     per-race count is pushed DOWN for it. If both normalisations say the same thing the result survives the
     survival gap; if they disagree the honest answer is NOT SEPARABLE AT THIS n, and this tool refuses to pick
     one. That refusal is the whole point: a scorer that reports a single number cannot express it.

Race selection is `excursions.pick()` - imported, not reimplemented, so a cell cannot be scored here under one
set of exclusions and plotted there under another. Every excluded race is named.

    python tools/cell_score.py monza f2_tcr_k0_on f2_tcr_kd_on f2_gt3_k0_on f2_gt3_kd_on
    python tools/cell_score.py monza f2_gt3_k0_on f2_gt3_k0_off --compare
    python tools/cell_score.py --selftest
"""
import collections
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import excursions as X                                                                       # noqa: E402
import retire_why as RW                                                                      # noqa: E402

BAND_OF_INTEREST = 0.16          # 5 of 8 rs16 excursions and 30 of 56 TCR excursions sat in this spline band
STRAND_S = 60.0                  # an excursion whose car retires within this is the same event, counted twice
_ARITY_WARNED = False            # the version-mismatch warning fires once per run, not once per race


def strandings(path, events):
    """How many of these excursions are the first half of a retirement, and how many of those are lap-2+.

    An excursion is "below threshold at the off and still below it 3-8 s later", so a car that goes off and
    STOPS satisfies it by construction. Every one of F2's gt3_k0_off retirements had an off-track 15-25 s
    before it, so that arm's excursion count contains its own DNFs: an ON/OFF comparison in which only OFF
    strands counts the same failure twice, once as a retirement and once as an excursion. The spec says
    retirements are a separate outcome and never folded into the excursion rate; without this they are folded
    in by the metric's own definition. Raised by verve-47 against F2's GT3 leg.
    """
    # ARITY CHECKED, NEVER ASSUMED. `except ValueError: return 0, 0` was the first version of this and it is a
    # SILENT NULL: on a machine whose retire_why still returns two values, every arm reported zero strandings and
    # printed no stranding line, which is indistinguishable from "this arm has none". Found by BTeam on PC #2 the
    # same evening, in the fix for a silent null. A mismatch now warns once and the arm says NOT COMPUTED.
    try:
        res = RW.scan(path)
    except OSError:
        return 0, 0, False
    if not isinstance(res, tuple) or len(res) != 3:
        global _ARITY_WARNED
        if not _ARITY_WARNED:
            _ARITY_WARNED = True
            print("  !! retire_why.scan() returned %d value(s), expected 3 (finished, retirements, distance)."
                  " THE STRANDING ADJUSTMENT IS NOT RUNNING - install retire_why 1e9e111b or newer alongside"
                  " this file. Figures below are UNADJUSTED." % (len(res) if isinstance(res, tuple) else 1))
        return 0, 0, False
    _fin, rets, _mx = res
    if not rets:
        return 0, 0, True
    by_car = {}
    for d in rets:
        c, t = d.get("car"), d.get("t")
        if isinstance(c, int) and t is not None:
            by_car.setdefault(c, []).append(float(t))
    n = n2 = 0
    for car, t, l2 in events:
        for rt in by_car.get(car, []):
            if t is not None and 0 <= rt - float(t) <= STRAND_S:
                n += 1
                if l2:
                    n2 += 1
                break
    return n, n2, True


def cars_in(path):
    """The grid size from the feed's own header, so the figure does not depend on results.csv."""
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return len(json.loads(fh.readline()).get("cars") or [])
    except (OSError, ValueError):
        return 0


def real_carlaps(path):
    """(car-laps actually driven, lap-2+ of them) from the race_end standings, or (None, None).

    `excursions.classify()` reports car-laps as `maxlap * cars` - the leader's distance times the grid size -
    which is NOMINAL: it counts a car that retired on lap 0 as having driven the full race. That matters here
    because the whole premise of the spec's bracket is that a per-car-lap rate is pushed UP for an arm that
    loses cars while a per-race count is pushed DOWN. With a nominal denominator the first half of that is
    simply false: the rate does not move at all.

    Caught because all six F2 arms reported exactly 540 car-laps while nine cars had retired in the OFF arms.
    The feed's race_end block carries each car's own lap count, so the real figure is already on disk.
    """
    laps = None
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"race_end"' in ln:
                    try:
                        res = json.loads(ln).get("results") or []
                    except ValueError:
                        return None, None
                    laps = [int(r.get("laps") or 0) for r in res if isinstance(r, dict)]
    except OSError:
        return None, None
    if not laps:
        return None, None
    return sum(laps), sum(max(0, l - 2) for l in laps)


def arm(track, prefix):
    """-> dict of pooled figures for one arm, plus the per-race rows and the exclusions, all named."""
    cands, byst = [], {}
    for p in X.feed_paths(track):
        stem = os.path.basename(p)[:15]
        lab = X.label_for(stem)
        if lab == X.NO_LABEL or not lab.startswith(prefix):
            continue
        c = X.classify(p)
        if not (c and c["maxlap"]):
            continue
        cands.append({"lab": lab, "stem": stem, "laps": c["maxlap"], "fin": X.feed_finished(p),
                      "live": X.feed_live(p)})
        byst[stem] = (lab, c, cars_in(p), p)
    # the ERA test is per DAY, not per label: a race still on track is the only attempt at its own label, so a
    # sibling test cannot see it (this arm pooled a 3-lap live race before the fix), and one query spans eras.
    era = X.days_with_race_end(track, set(c["stem"][:8] for c in cands))
    for c in cands:
        c["era"] = era.get(c["stem"][:8], False)
    keep, dropped, unknown = X.pick(cands)
    t = collections.Counter()
    races = []
    nominal_used = 0
    for _, stem, _ in keep:
        lab, c, cars, path = byst[stem]
        ea = sum(c["exc_abs"].values())
        band = sum(v for k, v in c["exc_abs"].items() if abs(k - BAND_OF_INTEREST) < 0.005)
        # ACTUAL car-laps where the feed records them, nominal only as a fallback - and the fallback is counted
        # and reported, never silent, because the two differ by exactly the survival gap under test.
        rcl, rcl2 = real_carlaps(path)
        if rcl is None:
            rcl, rcl2 = c["carlaps"], c["carlaps_l2"]
            nominal_used += 1
        sn, sn2, sok = strandings(path, c.get("exc_events") or [])
        if not sok:
            t["strand_blind"] += 1
        races.append({"label": lab, "laps": c["maxlap"], "cars": cars, "exc": ea, "exc_l2": c["abs_l2"],
                      "band": band, "carlaps": rcl, "carlaps_l2": rcl2, "off": c["n_off"],
                      "nominal": c["carlaps"], "strand": sn, "strand_l2": sn2})
        t["strand"] += sn; t["strand_l2"] += sn2
        t["exc"] += ea; t["exc_l2"] += c["abs_l2"]; t["band"] += band
        t["carlaps"] += rcl; t["carlaps_l2"] += rcl2; t["off"] += c["n_off"]
        t["nominal"] += c["carlaps"]; t["starts"] += cars
    return {"prefix": prefix, "n": len(races), "races": races, "dropped": dropped, "unknown": unknown,
            "exc": t["exc"], "exc_l2": t["exc_l2"], "band": t["band"], "off": t["off"],
            "carlaps": t["carlaps"], "carlaps_l2": t["carlaps_l2"], "starts": t["starts"],
            "nominal": t["nominal"], "nominal_used": nominal_used,
            "strand": t["strand"], "strand_l2": t["strand_l2"], "strand_blind": t["strand_blind"],
            "per_100cl_l2_nostrand": (100.0 * max(0, t["exc_l2"] - t["strand_l2"]) / max(t["carlaps_l2"], 1)),
            "per_100cl": 100.0 * t["exc"] / max(t["carlaps"], 1),
            "per_100cl_l2": 100.0 * t["exc_l2"] / max(t["carlaps_l2"], 1),
            "per_start": float(t["exc"]) / max(t["starts"], 1),
            "per_race": float(t["exc"]) / max(len(races), 1)}


def bracket(a, b):
    """THE BRACKET. -> (verdict, detail). The two normalisations must agree or the cell is NOT SEPARABLE.

    Direction is taken on the LAP-2+ per-car-lap figure (the primary) and on excursions per RACE-START (which
    moves the opposite way when an arm loses cars). Equality on either one is not agreement: it is an absence of
    signal, and a cell where one normalisation sees nothing cannot be said to have been separated by the other.
    """
    d_lap = a["per_100cl_l2"] - b["per_100cl_l2"]
    d_start = a["per_start"] - b["per_start"]
    same = (d_lap > 0 and d_start > 0) or (d_lap < 0 and d_start < 0)
    worse = a["prefix"] if d_lap > 0 else b["prefix"]
    if not same:
        return ("NOT SEPARABLE at this n",
                "the two normalisations disagree (lap-2+ per 100 car-laps %+.2f, per race-start %+.2f), which is"
                " exactly the case the bracket exists to catch - neither is picked" % (d_lap, d_start))
    return ("%s is worse" % worse,
            "both normalisations agree (lap-2+ per 100 car-laps %+.2f, per race-start %+.2f)" % (d_lap, d_start))


def show(a):
    lost = a.get("nominal", 0) - a["carlaps"]
    tag = ""
    if lost > 0:
        # NOT "lost to retirements": these arms often have none. A car a lap down drives fewer laps than the
        # leader, and the nominal figure counts every car as having gone the full distance. (verve-47 caught the
        # old label, which would have had a reader infer DNFs that did not happen.)
        tag = "  (%d short of the nominal %d: lapped cars, plus any retirements)" % (lost, a["nominal"])
    if a.get("nominal_used"):
        tag += "  [%d race(s) had no race_end: nominal denominator used for those]" % a["nominal_used"]
    print("  %-18s n=%d  %5d car-laps ACTUAL (%5d lap2+), %3d starts%s"
          % (a["prefix"], a["n"], a["carlaps"], a["carlaps_l2"], a["starts"], tag))
    if a["n"] == 0:
        print("      NO RACES - nothing to report for this arm")
        return
    print("      excursions %3d  (lap2+ %3d, band %.2f: %d)   raw off-tracks %d"
          % (a["exc"], a["exc_l2"], BAND_OF_INTEREST, a["band"], a["off"]))
    print("      per 100 car-laps %6.2f   LAP2+ %6.2f (PRIMARY)   per race-start %5.3f   per race %5.2f"
          % (a["per_100cl"], a["per_100cl_l2"], a["per_start"], a["per_race"]))
    if a.get("strand_blind"):
        print("      STRANDINGS NOT COMPUTED for %d of %d race(s) - retire_why is the wrong version here, so"
              " these figures are UNADJUSTED and are NOT comparable with adjusted ones."
              % (a["strand_blind"], a["n"]))
    if a.get("strand"):
        print("      OF WHICH STRANDINGS: %d excursions (%d lap2+) are a car that RETIRED within %.0f s - the"
              " same failure as a retirement, counted twice." % (a["strand"], a["strand_l2"], STRAND_S))
        print("      LAP2+ EXCLUDING STRANDINGS %6.2f per 100 car-laps - compare arms on BOTH, because a"
              " stranding is a real off-track too." % a["per_100cl_l2_nostrand"])
    for r in a["races"]:
        print("        %-24s %2d laps  %3d cars  exc %2d (l2 %2d)  offs %3d"
              % (r["label"], r["laps"], r["cars"], r["exc"], r["exc_l2"], r["off"]))
    for reason, items in a["dropped"].items():
        print("      EXCLUDED (%d) - %s: %s" % (len(items), reason, ", ".join(sorted(items))))
    if a["unknown"]:
        print("      KEPT but no race_end anywhere at these labels: %s" % ", ".join(sorted(a["unknown"])))


def selftest():
    ok = True
    # THE BRACKET MUST REFUSE TO PICK when the two normalisations disagree. Built from numbers, not from feeds,
    # so the assertion cannot be satisfied by whatever is on disk - and the disagreement is FORCED: arm A has a
    # higher lap-2+ rate while arm B has more excursions per race-start, which is precisely what a survival gap
    # manufactures.
    # Every synthetic arm also carries an ALL-LAPS rate pointing the OPPOSITE way to its lap-2+ rate - the
    # signature of a survival gap - because WHICH normalisation is the primary is itself load-bearing. Without
    # that, a mutant scoring on all-laps passed this selftest untouched (checked 2026-10-22: it did).
    A = {"prefix": "armA", "per_100cl_l2": 2.0, "per_100cl": 0.5, "per_start": 0.10}
    B = {"prefix": "armB", "per_100cl_l2": 1.0, "per_100cl": 3.0, "per_start": 0.20}
    v, _ = bracket(A, B)
    if "NOT SEPARABLE" not in v:
        print("SELFTEST FAIL: bracket() returned %r for arms that disagree across normalisations" % v)
        ok = False
    # and it must NOT refuse when they agree - on the LAP-2+ figure, which is the primary
    B2 = {"prefix": "armB", "per_100cl_l2": 1.0, "per_100cl": 3.0, "per_start": 0.05}
    v2, _ = bracket(A, B2)
    if v2 != "armA is worse":
        print("SELFTEST FAIL: bracket() returned %r when both normalisations agree, on lap-2+, that armA is"
              " worse - scoring on ALL laps would read these arms the other way round, which is the whole"
              " reason lap-2+ is the primary" % v2)
        ok = False
    # a tie on either normalisation is an absence of signal, never agreement
    v3, _ = bracket(A, {"prefix": "armB", "per_100cl_l2": 1.0, "per_100cl": 3.0, "per_start": 0.10})
    if "NOT SEPARABLE" not in v3:
        print("SELFTEST FAIL: bracket() treated a tie on per-race-start as agreement (%r)" % v3)
        ok = False
    # the arm figures must use the SHARED selection logic, not a local copy
    if not hasattr(X, "pick"):
        print("SELFTEST FAIL: excursions.pick() is missing - this tool must not select races on its own")
        ok = False
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__.strip().splitlines()[0])
        return 2
    track, prefixes = args[0], args[1:]
    arms = [arm(track, p) for p in prefixes]
    print("CELL SCORE on %s. PRIMARY = lap-2+ excursions per 100 car-laps. Every rate is bracketed by the"
          " per-race-start count.\n" % track)
    for a in arms:
        show(a)
        print()
    if "--compare" in sys.argv and len(arms) == 2:
        if min(a["n"] for a in arms) == 0:
            print("NO VERDICT: an arm has no races.")
            return 1
        v, why = bracket(arms[0], arms[1])
        print("VERDICT: %s - %s" % (v, why))
        lo = min(a["n"] for a in arms)
        if lo < 3:
            print("  (and the arms are not full: n=%d. Under rule 1 this figure does not go into a report.)" % lo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
