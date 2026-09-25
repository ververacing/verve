"""Held behind a crawler: how long the field spends queued behind a car far below the pace of the road it is on.

    python tools/train.py diag_race_*baku*.jsonl            # one line per race, plus a total
    python tools/train.py --frac 0.45 --gap-m 30 ...        # the crawler and queue definitions

From the 8 s snapshots. A CRAWLER is a moving car (not retired, not in the pit lane, speed > 3 km/h) doing less than
FRAC of the pace of its bit of road - pace = the fastest speed any car has shown in that 1% of the lap so far in the
race, least of the three bins around it, so a braking zone reads as its apex - where that pace is at least PACE_MIN.
A car is HELD when the car ahead of it within GAP_M is a crawler, or is itself held (the queue), and it is moving.

Reports per race: crawler car-seconds, held car-seconds, the longest queue, and the worst crawler episode (car,
seconds, its speed, where). This is the metric for R.CRAWL_PASS: the fix should cut held-seconds without adding
contacts; the crawler-seconds themselves are the damaged car's problem, not this rule's.

Why not yield_train_snaps: that counts stale yield flags on dead cars (292 -> 12 at Baku once only moving cars count,
design panel 2026-09-24). This counts motion, from the same rows the harness scores.
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

STEP_S = 8.0     # snapshot interval in diag.lua


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r.get("grid"), list):
                rows.append(r)
    return rows


def analyse(rows, frac, gap_m, pace_min, track_len_m):
    pace = {}                       # bin -> fastest speed seen so far
    crawler_s = held_s = 0.0
    longest_queue = 0
    episodes = defaultdict(float)   # car -> crawler seconds
    worst = None                    # (seconds, car, speed, spline)
    ep_run = {}                     # car -> running episode seconds
    ep_meta = {}
    for r in rows:
        grid = [c for c in r["grid"] if not c.get("ret") and not c.get("pit")]
        # learn the road's pace from healthy movers first (this snapshot counts for the next one too)
        for c in grid:
            b = int((c.get("spline") or 0) / 10) % 100          # spline is x1000 in the diag
            if (c.get("dmg") or 0) < 55 and c.get("spd", 0) > pace.get(b, 0):
                pace[b] = c["spd"]
        crawl = set()
        for c in grid:
            if c.get("spd", 0) <= 3:
                continue
            b = int((c.get("spline") or 0) / 10) % 100
            pb = min(pace.get((b - 1) % 100, 1e9), pace.get(b, 1e9), pace.get((b + 1) % 100, 1e9))
            if pb < 1e9 and pb >= pace_min and c["spd"] < frac * pb:
                crawl.add(c["i"])
        crawler_s += STEP_S * len(crawl)
        for c in grid:
            if c["i"] in crawl:
                ep_run[c["i"]] = ep_run.get(c["i"], 0) + STEP_S
                ep_meta[c["i"]] = (c["spd"], c.get("spline"))
                episodes[c["i"]] += STEP_S
            elif c["i"] in ep_run:
                s = ep_run.pop(c["i"])
                if worst is None or s > worst[0]:
                    worst = (s, c["i"]) + ep_meta.get(c["i"], (None, None))
        # queue: walk the field by spline; a mover within gap_m behind a crawler or a held car is held
        movers = sorted([c for c in grid if c.get("spd", 0) > 3], key=lambda c: c.get("spline") or 0)
        held = set()
        n = len(movers)
        for k in range(n):
            me = movers[k]
            # the nearest car ahead by spline (wrapping)
            best = None
            for j in range(1, n):
                o = movers[(k + j) % n]
                d = ((o.get("spline") or 0) - (me.get("spline") or 0)) % 1000
                if d > 0:
                    best = (d, o)
                    break
            if best and best[0] * track_len_m / 1000.0 <= gap_m and (best[1]["i"] in crawl or best[1]["i"] in held):
                held.add(me["i"])
        # iterate once more so a queue longer than the walk order resolves
        for k in range(n):
            me = movers[k]
            if me["i"] in held:
                continue
            for j in range(1, n):
                o = movers[(k + j) % n]
                d = ((o.get("spline") or 0) - (me.get("spline") or 0)) % 1000
                if d > 0:
                    if d * track_len_m / 1000.0 <= gap_m and (o["i"] in crawl or o["i"] in held):
                        held.add(me["i"])
                    break
        held_s += STEP_S * len(held)
        longest_queue = max(longest_queue, len(held))
    for i, s in ep_run.items():
        if worst is None or s > worst[0]:
            worst = (s, i) + ep_meta.get(i, (None, None))
    return {"crawler_s": crawler_s, "held_s": held_s, "longest_queue": longest_queue, "worst": worst,
            "crawlers": len(episodes)}


TRACK_LEN = {"baku_2022": 6003, "monza": 5793, "spa": 7004, "ks_barcelona": 4655, "silverstone": 5891,
             "zandvoort": 4259, "imola": 4909, "daytona": 5730}


def track_of(path):
    base = os.path.basename(path)
    for k in TRACK_LEN:
        if k in base:
            return k
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--frac", type=float, default=0.45, help="crawler = below this fraction of local pace")
    ap.add_argument("--gap-m", type=float, default=30.0, help="held = this close behind a crawler / a held car")
    ap.add_argument("--pace-min", type=float, default=80.0, help="a bin must have seen this speed to judge anyone")
    ap.add_argument("--track-len", type=float, default=None, help="metres per lap (else from the file name)")
    a = ap.parse_args()
    paths = []
    for pat in a.files:
        hits = glob.glob(pat, recursive=True)
        if not hits and os.path.exists(pat):
            hits = [pat]
        if not hits:
            print(f"(no files match {pat})", file=sys.stderr)
        paths += hits
    tot_c = tot_h = 0.0
    print(f"{'race':58s} {'crawl_s':>8s} {'held_s':>7s} {'queue':>5s}  worst crawler (s, car, km/h, spline)")
    for p in sorted(paths):
        rows = load(p)
        if len(rows) < 5:
            continue
        tl = a.track_len or TRACK_LEN.get(track_of(p) or "", 5000)
        r = analyse(rows, a.frac, a.gap_m, a.pace_min, tl)
        tot_c += r["crawler_s"]; tot_h += r["held_s"]
        w = r["worst"]
        ws = f"{w[0]:.0f}s car {w[1]} at {w[2]} km/h, spline {w[3]}" if w else "-"
        print(f"{os.path.basename(p)[:58]:58s} {r['crawler_s']:8.0f} {r['held_s']:7.0f} {r['longest_queue']:5d}  {ws}")
    print(f"{'TOTAL':58s} {tot_c:8.0f} {tot_h:7.0f}")


if __name__ == "__main__":
    main()
