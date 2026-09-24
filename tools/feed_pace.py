"""Pace from the race feed, when AC's race_out is missing.

AC only writes race_out when the session ends cleanly. A race where cars are stranded never ends, so five Baku races
on 2026-09-23 produced no lap times at all and looked unmeasurable. They were not: lib/feed.lua emits a `lap` event
per car per lap with the lap time in it, so best lap, median race lap and field spread survive whatever AC does.

Lap 1 is excluded everywhere (standing start), as are laps under 10 s (timing glitches) and pit laps where the feed
marks them.

    python tools/feed_pace.py --glob baku_2022          # every feed for a track
    python tools/feed_pace.py <feed.jsonl> [...]
"""
import argparse
import glob
import json
import os
import statistics

FEED_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
ARCHIVE = "D:/verve_archive/verve_feed"


def laps(path):
    """{car: [lap times in seconds]} from the feed's lap events."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if (d.get("e") or d.get("type")) != "lap":
                continue
            car = d.get("car", d.get("i"))
            t = d.get("time_s", d.get("time"))
            n = d.get("lap", d.get("n", 0))
            if car is None or not t:
                continue
            t = float(t)
            if t > 1000:            # milliseconds
                t /= 1000.0
            if t < 10 or n <= 1:    # lap 1 is the standing start
                continue
            out.setdefault(car, []).append(t)
    return out


def view(path):
    per_car = laps(path)
    allv = [t for v in per_car.values() for t in v]
    if len(allv) < 5:
        return None
    best_per_car = sorted(min(v) for v in per_car.values() if v)
    return {
        "file": os.path.basename(path),
        "cars": len(per_car),
        "laps": len(allv),
        "best": min(allv),
        "median": statistics.median(allv),
        # spread of the field's BEST laps, median car vs fastest car - the same definition the harness now records
        "spread_median_pct": (best_per_car[len(best_per_car) // 2] / best_per_car[0] - 1) * 100 if len(best_per_car) >= 8 else None,
        "spread_full_pct": (best_per_car[-1] / best_per_car[0] - 1) * 100 if len(best_per_car) >= 8 else None,
    }


def fmt(s):
    return f"{int(s // 60)}:{s % 60:06.3f}" if s >= 60 else f"{s:.3f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("feeds", nargs="*")
    ap.add_argument("--glob", help="match feeds whose name contains this (e.g. a track id)")
    a = ap.parse_args()
    paths = list(a.feeds)
    if a.glob:
        for d in (FEED_DIR, ARCHIVE):
            paths += sorted(glob.glob(os.path.join(d, f"*{a.glob}*.jsonl")))
    if not paths:
        print(f"no feeds found (looked in {FEED_DIR})")
        return
    print(f"{'feed':<34} {'cars':>4} {'laps':>5} {'best':>10} {'median':>10} {'spread med':>11} {'spread full':>12}")
    for p in paths:
        v = view(p)
        if not v:
            print(f"{os.path.basename(p):<34}   (too few laps)")
            continue
        sm = f"{v['spread_median_pct']:.1f}%" if v["spread_median_pct"] is not None else "-"
        sf = f"{v['spread_full_pct']:.1f}%" if v["spread_full_pct"] is not None else "-"
        print(f"{v['file']:<34} {v['cars']:>4} {v['laps']:>5} {fmt(v['best']):>10} {fmt(v['median']):>10} {sm:>11} {sf:>12}")


if __name__ == "__main__":
    main()
