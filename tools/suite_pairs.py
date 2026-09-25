"""Score an interleaved on/off regression suite as PAIRS: each `<track>_on_i` diag against its `<track>_off_i` twin.

    python tools/suite_pairs.py d25_suite            # label prefix; finds diag_race_*<prefix>_<track>_on|off_<i>.jsonl

Per pair: heavy hits (contact events >= 80 km/h), dead cars, contact events, median lap (s), each as on, off and on-off.
Per track: the mean paired difference and the OFF arm's spread (max - min over its runs). The gate (night plan
2026-09-25): a track reads "worse" only if the mean paired difference in heavy80 or dead exceeds the off arm's spread;
median lap must stay within 0.5 s; raw contacts are reported, never gated. One-of-one tracks (Monza) are informational.
"""
import glob
import os
import re
import statistics
import subprocess
import sys


def metrics(diag):
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "race_metrics.py"), diag],
                         capture_output=True, text=True).stdout
    g = lambda k, cast=float: cast((re.search(r"^" + k + r"\s+(\S+)", out, re.M) or [None, "0"])[1] or 0)
    return {"heavy80": g("heavy80", int), "dead": g("retired_or_parked", int), "contacts": g("contact_events", int),
            "medlap": g("laptime_median_s")}


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "d25_suite"
    files = glob.glob(f"diag_race_*_{prefix}_*.jsonl")
    pairs = {}
    for f in files:
        m = re.search(rf"{prefix}_(\w+?)_(on|off)_(\d+)\.jsonl$", os.path.basename(f))
        if not m:
            continue
        track, arm, i = m.group(1), m.group(2), int(m.group(3))
        pairs.setdefault((track, i), {})[arm] = f
    if not pairs:
        print("no suite diags found for", prefix); return
    keys = ["heavy80", "dead", "contacts", "medlap"]
    print(f"{'pair':16s} " + " ".join(f"{k+' on/off/d':>22s}" for k in keys))
    per_track = {}
    for (track, i), arms in sorted(pairs.items()):
        if "on" not in arms or "off" not in arms:
            print(f"{track}_{i:<12} incomplete ({', '.join(arms)})"); continue
        on, off = metrics(arms["on"]), metrics(arms["off"])
        row = f"{track}_{i:<12} "
        for k in keys:
            d = on[k] - off[k]
            row += f"{on[k]:>7.1f}/{off[k]:>6.1f}/{d:>+6.1f} "
            per_track.setdefault(track, {}).setdefault(k, {"d": [], "off": []})
            per_track[track][k]["d"].append(d); per_track[track][k]["off"].append(off[k])
        print(row)
    print()
    for track, ks in per_track.items():
        verdict = []
        for k in ("heavy80", "dead"):
            d, off = ks[k]["d"], ks[k]["off"]
            spread = (max(off) - min(off)) if len(off) > 1 else None
            md = statistics.mean(d)
            worse = spread is not None and md > spread
            verdict.append(f"{k}: mean on-off {md:+.1f} vs off spread {spread if spread is not None else 'n/a'}{'  WORSE' if worse else ''}")
        ml = statistics.mean(ks["medlap"]["d"])
        verdict.append(f"medlap: mean on-off {ml:+.1f} s{'  SLOWER' if ml > 0.5 else ''}")
        verdict.append(f"contacts: mean on-off {statistics.mean(ks['contacts']['d']):+.1f} (reported, not gated)")
        n = len(ks["dead"]["d"])
        print(f"{track} (n={n}{', informational' if n < 2 else ''}): " + " | ".join(verdict))


if __name__ == "__main__":
    main()
