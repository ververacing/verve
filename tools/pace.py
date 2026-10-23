"""Median per-car BEST LAP per arm, read from the feed's own lap events.

WHY NOT results.csv's `laptime_median_s`: `metric_sanity` puts that column's within-cell quantum at 4-8 s, and
every one of tonight's Monza GT3 cells reported exactly 112.0 - the column cannot resolve the difference 0042 is
expected to make (a few seconds at Monza). The feed carries each lap's own `time_s`, so the resolution problem
is avoidable rather than a limit.

WHAT IT EXCLUDES, and each one changes the answer:
  - `first: true` laps. The feed marks the standing-start lap, and feed.lua's own comment says consumers wanting
    lap TIMES must skip it. A standing start is several seconds slower than a flying lap.
  - SLOT 0. The autopilot player ignores Verve's level and grip and starts on a fixed fuel load, so its laps are
    not the AI's (memory: "slot 0 is not a star").
  - races that `excursions.pick()` would not pool - superseded attempts, live races, non-harness races - so the
    race set matches every other tool.

AND IT REPORTS CAR COUNT AND RACE COUNT BESIDE EVERY FIGURE, because a median over 17 cars in 3 races and a
median over 4 cars in 1 race are not the same claim, and tonight has been a lesson in printing the n.

    python tools/pace.py monza s42_gt3_80 s42_tcr_80 d100b_mon_on
    python tools/pace.py --selftest
"""
import collections
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import excursions as X                                                                       # noqa: E402


def best_laps(path):
    """{car: best flying lap in seconds} from the feed's lap events. Slot 0 and first laps excluded."""
    best = {}
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"type":"lap"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("type") != "lap" or d.get("first") is True:
                    continue
                car, t = d.get("car"), d.get("time_s")
                if car in (None, 0) or not isinstance(t, (int, float)) or t <= 0:
                    continue
                if car not in best or t < best[car]:
                    best[car] = float(t)
    except OSError:
        return {}
    return best


def arm(track, prefix):
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
        byst[stem] = (lab, p, c["maxlap"])
    if not cands:
        return None
    era = X.days_with_race_end(track, set(c["stem"][:8] for c in cands))
    for c in cands:
        c["era"] = era.get(c["stem"][:8], False)
    keep, dropped, _unknown = X.pick(cands)
    races = []
    for _, stem, _ in keep:
        lab, p, mx = byst[stem]
        bl = best_laps(p)
        if bl:
            races.append({"label": lab, "laps": mx, "cars": len(bl),
                          "median": statistics.median(bl.values()), "fastest": min(bl.values())})
    return {"prefix": prefix, "races": races, "dropped": dropped}


def show(a):
    if not a or not a["races"]:
        print("  %-20s no poolable races" % (a["prefix"] if a else "?"))
        return
    meds = [r["median"] for r in a["races"]]
    cars = sum(r["cars"] for r in a["races"])
    # ONE DECIMAL, NEVER THREE. feed.lua:279 says it in its own comment - "time_s is the 1 Hz tick difference
    # (x.1 s resolution)" - so the VALUES carry 0.1 s but the lap boundary is only located to the nearest 1 Hz
    # sample. Measured on 182 laps of one race: the fractional parts are ONLY 0.1 and 0.2, which is what a
    # 1 Hz detector looks like. So the accuracy is about a second whatever the digits suggest, and printing
    # three decimals here would be the `laptime_median_s` mistake (quoted to 0.1 s on a 4-8 s column) made again
    # in a new tool.
    print("  %-20s %d race(s), %d car-bests: MEDIAN BEST LAP %.1f s (fastest car %.1f)"
          % (a["prefix"], len(a["races"]), cars, statistics.median(meds), min(r["fastest"] for r in a["races"])))
    for r in a["races"]:
        print("      %-24s %2d laps  %2d cars  median %.1f  fastest %.1f"
              % (r["label"], r["laps"], r["cars"], r["median"], r["fastest"]))
    if len(meds) > 1:
        print("      per-race median spread %.1f s (%.1f to %.1f)" % (max(meds) - min(meds), min(meds),
                                                                      max(meds)))
    print("      !! RESOLUTION: lap boundaries are detected at 1 Hz, so these figures are accurate to about a"
          " SECOND. A difference under ~2 s is not evidence, however many digits are printed.")


def selftest():
    ok = True
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "20260101_000000_test.jsonl")
    with io.open(p, "w", encoding="utf-8") as f:
        # slot 0 is the player and must be ignored; the first lap is a standing start and must be ignored;
        # car 1's best is 90.5 and car 2's is 91.0, so the median of the two is 90.75
        f.write('{"type":"lap","car":0,"lap":2,"time_s":1.0,"first":false}\n')
        f.write('{"type":"lap","car":1,"lap":1,"time_s":5.0,"first":true}\n')
        f.write('{"type":"lap","car":1,"lap":2,"time_s":90.5,"first":false}\n')
        f.write('{"type":"lap","car":1,"lap":3,"time_s":99.0,"first":false}\n')
        f.write('{"type":"lap","car":2,"lap":2,"time_s":91.0,"first":false}\n')
    bl = best_laps(p)
    if 0 in bl:
        print("SELFTEST FAIL: slot 0 was counted - the autopilot ignores Verve's level and fuel")
        ok = False
    if bl.get(1) != 90.5:
        print("SELFTEST FAIL: car 1's best is %r, expected 90.5 (the 5.0 s first lap must be skipped and the"
              " slower 99.0 must not win)" % bl.get(1))
        ok = False
    if bl.get(2) != 91.0:
        print("SELFTEST FAIL: car 2's best is %r, expected 91.0" % bl.get(2))
        ok = False
    if bl and abs(statistics.median(bl.values()) - 90.75) > 1e-9:
        print("SELFTEST FAIL: median of the car bests is %r, expected 90.75" % statistics.median(bl.values()))
        ok = False
    os.remove(p)
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
    print("MEDIAN PER-CAR BEST LAP on %s, from the feed's lap events (slot 0 and standing-start laps"
          " excluded)\n" % track)
    for pre in prefixes:
        show(arm(track, pre))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
