"""ERS within-race split (R.ERS_SPLIT=1): odd AI cars run R.ERS_MODE, even AI cars keep AC's own program. One race, so
start, traffic, grip and weather are shared - the race-to-race noise (top-3 sd ~0.4 s) cancels. Per model and race:

  lap    median of each car's median clean lap (lap index 2+, no cuts; slot 0, the autopilot, excluded)
  kc     mean state of charge (diag 'kc', %) over snapshots from lap 2 on, out of the pits, not recovering
  flat   share of those snapshots under 5 % - a battery spent to nothing
  pos    mean finishing position (AC's classification, race_out raceResult)

    python tools/ers_split.py ers_ab_smart          # every race whose label starts with the prefix
    python tools/ers_split.py ers_ab --res DIR      # another results tree (PC #2)

The verdict line per model is the MEDIAN of the per-race (mode - control) lap differences: negative = the ERS mode
is FASTER. A race run without ERS_SPLIT is skipped (every car got the mode; score it with pace_metrics.py instead).

Laps come from tools/racelaps.py: AC's race_out, else Verve's feed (AC often writes race_out with no laps). A feed-sourced
race cannot drop cut laps and its "pos" is the live order when the feed stopped; the last column names the source.
"""
import argparse
import collections
import csv
import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from racelaps import labels, race_laps  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
RES = os.path.join(HERE, "harness_results")
OUTLIER = 0.04   # a car this much slower than the race's median car is damage, not deployment (left out, listed)


def arms_by_label():
    out = {}
    for f in glob.glob(os.path.join(RES, "results*.csv")):
        try:
            for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
                try:
                    out[r.get("label") or ""] = json.loads(r.get("arm") or "{}")
                except ValueError:
                    pass
        except OSError:
            continue
    return out


def diag_for(label):
    for d in (VERVE, RES, os.path.join(RES, "archive")):
        hits = sorted(glob.glob(os.path.join(d, "diag_race_*_%s.jsonl" % label)))
        if hits:
            return hits[-1]
    return None


def battery(path):
    """-> {car: [kc, ...]} from lap 2 on, out of the pits, not recovering"""
    kc = collections.defaultdict(list)
    if not path:
        return kc
    for line in open(path, encoding="utf-8", errors="replace"):
        if '"grid"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        for c in o.get("grid") or []:
            if c.get("kc") is None or c.get("lap", 0) < 2 or c.get("pit") or c.get("rec") or c.get("ret"):
                continue
            kc[c["i"]].append(c["kc"])
    return kc


def race(label):
    """-> (models, {car: [clean lap s]}, {car: finishing pos}, source) via racelaps (race_out, else the feed)"""
    r = race_laps(label, RES)
    if not r:
        return None
    laps = {}
    for car, ls in r["laps"].items():
        keep = [t for idx, t, cuts in ls if car != 0 and idx >= 2 and not cuts]
        if keep:
            laps[car] = keep
    # a damaged or stricken car is not a deployment result: with 2-3 cars an arm one of them decides the arm (a control
    # SF70H at 105.7 s on 2026-10-10). Cars more than OUTLIER slower than the race's median car are left out, and counted.
    meds = [statistics.median(v) for v in laps.values() if len(v) >= 2]
    out = []
    if meds:
        ref = statistics.median(meds)
        out = [c for c, v in laps.items() if len(v) >= 2 and statistics.median(v) > ref * (1 + OUTLIER)]
        for c in out:
            del laps[c]
    pos = {c: k + 1 for k, c in enumerate(r["order"])}
    return r["models"], laps, pos, r["src"], out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--res")
    a = ap.parse_args()
    global RES
    if a.res:
        RES = a.res
    arms = arms_by_label()
    diffs = collections.defaultdict(list)
    print("ERS SPLIT  prefix %s   odd AI cars = R.ERS_MODE, even AI cars = AC's own program (control)\n" % a.prefix)
    print("%-26s %-24s %16s %16s %7s  %9s  %11s  %9s" % ("race", "model", "mode lap (cars)", "ctrl lap (cars)", "diff",
                                                         "kc m/c", "flat% m/c", "pos m/c"))
    for label in labels(a.prefix, RES):
        rc = (arms.get(label) or {}).get("racecraft") or {}
        if not (float(rc.get("ERS_SPLIT") or 0) > 0):
            print("%-26s skipped: not a split race (ERS_MODE=%s for every car)" % (label, rc.get("ERS_MODE", "off")))
            continue
        r = race(label)
        if not r:
            print("%-26s no laps in race_out or feed" % label)
            continue
        models, laps, pos, src, dropped = r
        if dropped:
            print("%-26s left out (over %.0f %% slower than the race's median car): %s" % (label, OUTLIER * 100, ", ".join(
                "car %d %s %s" % (c, models[c] if c < len(models) else "?", "mode" if c % 2 else "ctrl") for c in sorted(dropped))))
        kc = battery(diag_for(label))
        groups = collections.defaultdict(lambda: {"mode": [], "ctrl": []})
        for car, ls in laps.items():
            if car < len(models) and len(ls) >= 2:
                groups[models[car]]["mode" if car % 2 == 1 else "ctrl"].append(car)
        for model in sorted(groups):
            g, cols = groups[model], {}
            for arm in ("mode", "ctrl"):
                cars = g[arm]
                med = [statistics.median(laps[c]) for c in cars]
                ks = [x for c in cars for x in kc.get(c, [])]
                cols[arm] = (statistics.median(med) if med else None, len(cars),
                             statistics.mean(ks) if ks else None, 100.0 * sum(1 for x in ks if x < 5) / len(ks) if ks else None,
                             statistics.mean([pos[c] for c in cars if c in pos]) if any(c in pos for c in cars) else None)
            mo, ct = cols["mode"], cols["ctrl"]
            d = (mo[0] - ct[0]) if mo[0] and ct[0] else None
            if d is not None:
                diffs[model].append(d)
            f1 = lambda v, fmt: (fmt % v) if v is not None else "-"
            print("%-26s %-24s %11s (%d) %11s (%d) %7s  %4s/%-4s  %5s/%-5s  %4s/%-4s  %s" % (
                label[:26], model[:24], f1(mo[0], "%.3f"), mo[1], f1(ct[0], "%.3f"), ct[1], f1(d, "%+.3f"),
                f1(mo[2], "%.0f"), f1(ct[2], "%.0f"), f1(mo[3], "%.0f"), f1(ct[3], "%.0f"), f1(mo[4], "%.1f"), f1(ct[4], "%.1f"), src))
    if diffs:
        print("\nVERDICT per model: median of per-race (mode - control) lap differences; negative = the mode is FASTER")
        for model, ds in sorted(diffs.items()):
            print("  %-26s %+.3f s/lap  (n=%d races: %s)" % (model, statistics.median(ds), len(ds), " ".join("%+.2f" % x for x in ds)))
    else:
        print("\nno split races scored for %r" % a.prefix)


if __name__ == "__main__":
    main()
