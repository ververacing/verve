"""Repeat-off loops: cars Verve repositioned 3+ times after going off at the same spot (+-0.01 spline). Read-only.

    python tools/offloop_scan.py [since YYYYMMDD] [--all]

Reads the race feeds (verve_feed in Documents, then D:/verve_archive/verve_feed). An off counts when a reposition of the same
car follows within 40 s. Prints one line per looping car (stamp, track, car, model, offs, spline, seconds from first to
last, how its race ended) and a per-track tally. --all lists every race scanned, looping or not.
"""
import glob, json, os, sys
from collections import Counter, defaultdict

DIRS = [os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed"), "D:/verve_archive/verve_feed"]


def loops_in(path):
    evs = []
    for ln in open(path, encoding="utf-8"):
        try: evs.append(json.loads(ln))
        except ValueError: pass
    if not any(e.get("type") == "race_start" for e in evs): return None, []
    hdr = next((e for e in evs if e.get("type") == "header"), {})
    models = {c.get("i"): c.get("model") for c in hdr.get("cars", [])}
    offs, reps, ret = defaultdict(list), defaultdict(list), {}
    for e in evs:
        t = e.get("type")
        if t == "off_track": offs[e["car"]].append((e["t"], e["spline"]))
        elif t == "reposition": reps[e["car"]].append(e["t"])
        elif t == "retire": ret[e["car"]] = e.get("reason")
    out = []
    for c, lst in offs.items():
        fixed = [(t, s) for t, s in lst if any(t <= r <= t + 40 for r in reps[c])]
        best = []
        for _, s0 in fixed:
            same = [(t, s) for t, s in fixed if abs(s - s0) < 0.01]
            if len(same) > len(best): best = same
        if len(best) >= 3:
            out.append((c, models.get(c, "?"), len(best), best[0][1], best[-1][0] - best[0][0], ret.get(c, "running")))
    return hdr.get("track", "?"), out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    since = args[0] if args else "00000000"
    seen, files = set(), []
    for d in DIRS:
        for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
            b = os.path.basename(f)
            if b[:8] >= since and b not in seen: seen.add(b); files.append(f)
    races, tally = 0, defaultdict(lambda: [0, 0, 0])
    for f in sorted(files, key=os.path.basename):
        track, loops = loops_in(f)
        if track is None: continue
        races += 1; tally[track][0] += 1
        if "--all" in sys.argv and not loops: print(f"{os.path.basename(f)[:15]} {track[:36]:36} -")
        for c, model, n, spl, dur, end in loops:
            tally[track][1] += 1; tally[track][2] += end != "running"
            print(f"{os.path.basename(f)[:15]} {track[:36]:36} car {c:2} {model[:28]:28} offs {n:2} at {spl:.3f} over {dur:5.0f} s  {end}")
    print(f"\n{sum(v[1] for v in tally.values())} looping cars in {races} races")
    for k, v in sorted(tally.items(), key=lambda x: -x[1][1]):
        if v[1]: print(f"  {k[:40]:40} races {v[0]:3}  looping cars {v[1]:3}  of them retired {v[2]}")


if __name__ == "__main__":
    main()
