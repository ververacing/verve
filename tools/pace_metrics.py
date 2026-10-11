"""Pace per arm on three metrics, from race_out. Built 2026-10-10 after a night of metric mistakes.

    python tools/pace_metrics.py coldbcn --arms g15,g25,g40
    python tools/pace_metrics.py as151 --arms ctrl,as151

WHY THREE METRICS. A single median over every car's laps is CONFOUNDED BY CARNAGE: a first-lap pile-up or a
teleport thins the field, the survivors get clean air, and the typical lap gets quicker without anyone driving
faster. Measured 2026-10-10: field median against lap-0/1 incidents r = -0.79, against repositions r = -0.37.
So we report:

  field    median of every clean lap from lap 2 on, all AI cars. The most laps, the most confounded.
  leader   the winning AI car's own median. Clean air by definition, but it is ONE car's ~6 laps and which car
           leads changes between races - on one grid its within-arm spread was 1.3-2.3 s, useless.
  top3     the first THREE AI finishers' laps pooled, ~18-21 laps. Still front-of-field, but robust to the
           leader's identity changing. Measured best of the three: lowest within-arm spread AND the lowest
           reposition sensitivity (r = -0.09). Prefer this one; it is still somewhat lap-0/1 sensitive (-0.66),
           so the incident counts are printed beside it and an arm outside the control's exposure range is
           suspect regardless of what the lap times say.

READ IT AS: an effect that shows on `field` and vanishes on `top3` is traffic, not pace. An effect on both is pace.
NEVER use results.csv laptime_median_s for this - it is quantised to about 4 s and cannot see a 1 s effect.

Slot 0 is excluded throughout: the harness autopilot ignores Verve's level and grip and starts on a different
fuel load. Cut laps are excluded. Lap 0 and lap 1 are excluded (standing start, first-lap traffic).
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from racelaps import labels, race_laps  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "harness_results")   # overridable with --res (PC #2's tree differs)


def exposure(prefix):
    """repositions and lap-0/1 incidents per label, from results.csv - the confound columns"""
    out = {}
    for f in glob.glob(os.path.join(RES, "results*.csv")):
        try:
            for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
                lab = r.get("label") or ""
                if lab.startswith(prefix):
                    try:
                        out[lab] = (int(r["drops"]), int(r["incidents_lap0_1"]))
                    except (ValueError, TypeError, KeyError):
                        pass
        except OSError:
            continue
    return out


def race(label):
    """-> (field median, leader median, top3 median, n laps pooled, source) or None. Laps via tools/racelaps.py:
    AC's race_out when it has laps, else Verve's feed (AC writes race_out with NO laps in 10-40 % of races a day;
    those races used to vanish from this table without a word)."""
    r = race_laps(label, RES)
    if not r:
        return None
    percar = collections.defaultdict(list)
    for car, ls in r["laps"].items():
        for idx, t, cuts in ls:
            # LAP RULE, fixed 2026-10-10 after PC #2 found two definitions in use: AC's lap index is 0-based,
            # so `< 2` drops index 0 (the standing start, which includes the launch) AND index 1 (the first flying
            # lap, still full of first-lap traffic). That is deliberate: first-lap incidents are a measured pace
            # confound, so excluding the first TWO laps is the safer rule. Earlier scripts tonight used `< 1`,
            # which keeps the first flying lap; figures from those differ slightly. THIS is the standard now.
            # (A feed-sourced race has no cut flag: cuts is None there and its cut laps stay in.)
            if car == 0 or idx < 2 or cuts:
                continue
            percar[car].append(t)
    if not percar:
        return None
    order = [c for c in r["order"] if c != 0 and len(percar.get(c, [])) >= 2]
    field = [x for v in percar.values() for x in v]
    lead = statistics.median(percar[order[0]]) if order else None
    pool = [x for c in order[:3] for x in percar[c]]
    return (statistics.median(field), lead,
            statistics.median(pool) if pool else None, len(pool), r["src"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", help="label prefix, e.g. coldbcn")
    ap.add_argument("--arms", help="comma-separated arm names in order, e.g. g15,g25,g40")
    ap.add_argument("--res", help="results directory holding race_out_*.json and results*.csv "
                                  "(default: the tools/harness_results next to this script)")
    a = ap.parse_args()

    global RES
    if a.res:
        RES = a.res
    exp = exposure(a.prefix)
    byarm = collections.defaultdict(list)
    for label in labels(a.prefix, RES):
        # <prefix>_<arm>_<n> is the normal shape. A label set with NO arm segment -
        # <prefix>_<n>, e.g. six identical races measuring their own spread - used to match
        # nothing at all and the tool printed an empty table (found 2026-10-10). Fall back to one
        # unnamed arm so single-arm sets score, which is exactly the case where SPREAD is the answer.
        m = re.search(r"^(%s_(\w+?)_(\d+))$" % re.escape(a.prefix), label)
        arm = m.group(2) if m else None
        if not m:
            m = re.search(r"^(%s_(\d+))$" % re.escape(a.prefix), label)
            arm = "(all)"
        if not m:
            continue
        r = race(label)
        if r:
            byarm[arm].append((m.group(1),) + r)
    if not byarm:
        print("no scored races matched %r" % a.prefix, file=sys.stderr)
        return 1

    arms = [s.strip() for s in a.arms.split(",")] if a.arms else sorted(byarm)
    print("PACE BY ARM  (prefix %s)   metrics: field | leader | TOP-3 pooled\n" % a.prefix)
    base = None
    for k in arms:
        v = byarm.get(k) or []
        if not v:
            continue
        cols = []
        for i, name in ((1, "field"), (2, "leader"), (3, "top3")):
            vals = [x[i] for x in v if x[i] is not None]
            cols.append((statistics.median(vals), max(vals) - min(vals)) if vals else (None, None))
        if base is None:
            base = [c[0] for c in cols]
        line = "  %-8s n=%d  " % (k, len(v))
        for (med, spread), b, nm in zip(cols, base, ("field", "leader", "top3")):
            line += "%s %s (sp %.2f)  " % (nm, ("%.3f" % med) if med else "-",
                                           spread if spread is not None else 0)
        print(line)
        d = ["%+.3f" % (c[0] - b) if c[0] and b else "-" for c, b in zip(cols, base)]
        print("           vs first arm:  field %s | leader %s | top3 %s" % tuple(d))
        for row in v:
            dr, l01 = exp.get(row[0], ("?", "?"))
            print("           %-28s teleports %s  lap-0/1 incidents %s  (laps: %s)" % (row[0], dr, l01, row[5]))
    print("\n  An effect on field that vanishes on top3 is TRAFFIC, not pace.")
    print("  Any arm whose teleports or lap-0/1 incidents fall outside the control's range is suspect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
