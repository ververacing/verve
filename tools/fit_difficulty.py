"""Fit the AI level -> lap-time mapping from the single-make calibration runs (labels vcal_*), and print the
Lua table lib/difficulty.lua should carry.

    python tools/fit_difficulty.py [results.csv]

Reads results.csv rows whose label starts with "vcal_", takes ai_level (the level Verve applied, x100) and the
AI best / median-of-best lap, expresses each as % slower than the level-100 run, and fits a monotone piecewise
table. Output: the % slower at 60/70/80/90/100 and the inverse (level for a wanted % slower), which is what the
career band needs.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(path=None):
    import glob
    paths = [path] if path else sorted(glob.glob(os.path.join(HERE, "harness_results", "results*.csv")))   # results.csv rotates when columns change
    rows = []
    for pth in paths:
        rows += [r for r in csv.DictReader(open(pth, encoding="utf-8")) if r.get("label", "").startswith("vcal_") and r.get("ai_best_lap_s")]
    pts = {}
    for r in rows:
        lvl = int(float(r["ai_level"]))
        pts[lvl] = (float(r["ai_best_lap_s"]), float(r["ai_median_best_lap_s"] or r["ai_best_lap_s"]))
    if 100 not in pts:
        print("no level-100 reference run yet"); return
    b100, m100 = pts[100]
    print(f"{'level':>5} {'best':>7} {'median':>7} {'best%':>7} {'med%':>7}")
    table = []
    for lvl in sorted(pts, reverse=True):
        b, m = pts[lvl]
        pb, pm = (b / b100 - 1) * 100, (m / m100 - 1) * 100
        table.append((lvl, pb, pm))
        print(f"{lvl:5d} {b:7.2f} {m:7.2f} {pb:7.1f} {pm:7.1f}")
    # monotone in level (enforce: lower level never faster than a higher one)
    table.sort(key=lambda t: -t[0])
    fixed = []
    run = 0.0
    for lvl, pb, pm in table:
        p = max(run, (pb + pm) / 2)     # blend best+median; clamp non-decreasing as level falls
        run = p
        fixed.append((lvl, p))
    print("\n-- Lua: PCT_AT_LEVEL (level*100 -> % slower than level 100), fitted", len(fixed), "points")
    print("local PCT_AT_LEVEL = { " + ", ".join(f"[{lvl}] = {p:.1f}" for lvl, p in fixed) + " }")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
