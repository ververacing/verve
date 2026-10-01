"""Observation scorecard (read-only): per race and per field type, for the obs_* matrix (tools/obs_matrix.py).

    python tools/obs_score.py                              # every diag_race_*_obs_*.jsonl in the Verve folder
    python tools/obs_score.py --glob "diag_race_*_g149b_*.jsonl" --csv out.csv

Per race: tools/race_metrics.py (incidents, heavy80, retirements, frozen cars, lap 0-1, drops, spread / dnf / incidents vs the
real class), pace from the race feed (AC's lap_ms when the feed has it; best and median race lap), the best lap against the
human hotlap reference when tools/human_baselines.json has the track|model pair, and 'Verve error' lines in the kept CSP log.
URGENT (fix during the observation period): a race that never ran (too few frames), frozen AI cars (car 0 = the autopilot is left
out: Verve never parks the player's slot), a Lua error, or a field that
lost more than 40 % of its cars.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import race_metrics  # noqa: E402
try:
    import obs_matrix  # noqa: E402
    KNOWN = sorted(obs_matrix.FIELDS, key=len, reverse=True)
except Exception:
    KNOWN = []

FEEDS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
LOGS = os.path.join(HERE, "harness_results", "csp_logs")


def feed_for(stamp):
    try:
        names = sorted(n for n in os.listdir(FEEDS) if n >= stamp and n.endswith(".jsonl"))
    except OSError:
        return None
    return os.path.join(FEEDS, names[0]) if names and names[0][:13] == stamp[:13] else None


def feed_pace(path):
    hdr, laps = None, collections.defaultdict(list)
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "header":
            hdr = d
        elif d.get("type") == "lap":
            t = (d["lap_ms"] / 1000.0) if d.get("lap_ms") else d.get("time_s")
            if t and t > 20:
                laps[d.get("car")].append(float(t))
    player = next((c["i"] for c in (hdr or {}).get("cars", []) if c.get("player")), None)
    allt = [t for c, v in laps.items() if c != player for t in v]
    if not allt:
        return None, None, hdr
    return min(allt), st.median(allt), hdr


def frozen_ai(path):
    """race_metrics' frozen-car count without car 0: the harness autopilot sits in the player's slot, which Verve never parks
    (a human may take the wheel back), so a wrecked autopilot car reads 'frozen' for the rest of the race (obs_pc1_005, 1 Oct)."""
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith('{"t"'):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if not rows:
        return 0
    t0 = rows[0]["t"]
    t_end = max((r["t"] for a, r in zip(rows, rows[1:]) if r.get("leaderLap") != a.get("leaderLap")), default=rows[-1]["t"] + 1)
    frozen = 0
    for ci in {c["i"] for r in rows for c in r.get("grid", []) if c["i"] != 0}:
        run = 0
        for r in rows:
            if r["t"] >= t_end:
                break
            c = next((x for x in r.get("grid", []) if x["i"] == ci), None)
            if c and c.get("spd", 99) < 3 and not c.get("pit") and (r["t"] - t0) > 30:
                run += 8
            else:
                frozen += 1 if run >= 40 else 0
                run = 0
        frozen += 1 if run >= 40 else 0
    return frozen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="diag_race_*_obs_*.jsonl")
    ap.add_argument("--csv", default=os.path.join(HERE, "harness_results", "obs_results.csv"))
    a = ap.parse_args()
    base = json.load(open(os.path.join(HERE, "human_baselines.json"), encoding="utf-8"))
    rows, urgent = [], []
    for p in sorted(glob.glob(os.path.join(VERVE, a.glob))):
        name = os.path.basename(p)
        stamp = name[10:25]
        k = name.find("_obs_")
        label = name[k + 1:-6] if k >= 0 else name[26:-6]   # obs_* labels; else everything after the stamp (track_label)
        fm = re.match(r"obs_(pc\d)_\d{3}_(.+)$", label)
        pc, field = ("", label)
        if fm:
            pc, rest = fm.group(1), fm.group(2)
            field = next((f for f in KNOWN if rest.startswith(f + "_")), rest.split("_")[0])   # the longest known field name
        met = race_metrics.metrics(p)
        r = {"label": label, "pc": pc, "field": field, "stamp": stamp}
        if met.get("error"):
            r["error"] = met["error"]
            urgent.append((label, "never ran / not scorable: " + met["error"]))
            rows.append(r)
            continue
        for k in ("track", "cars", "leader_laps", "running_at_end", "retired_or_parked", "incidents", "incidents_lap0_1", "heavy80",
                  "drops", "drops_ok", "frozen_cars", "reality_class", "spread_pct", "spread_vs_real", "dnf_pct", "dnf_vs_real",
                  "inc_per_car_100laps", "inc_vs_real"):
            r[k] = met.get(k)
        fp = feed_for(stamp)
        best = med = None
        if fp:
            best, med, hdr = feed_pace(fp)
            if hdr and best:
                models = collections.Counter(c.get("model") for c in hdr.get("cars", []) if not c.get("player"))
                ref = None
                for mdl, _ in models.most_common():
                    ref = base.get("%s|%s" % (hdr.get("track"), mdl))
                    if ref:
                        break
                if ref and ref.get("top10"):
                    r["best_vs_human_top10_pct"] = round((best / ref["top10"] - 1) * 100, 1)
        r["best_lap_s"], r["median_lap_s"] = best, med
        errs = 0
        for lp in glob.glob(os.path.join(LOGS, "*%s*" % label)):
            errs += sum(1 for line in open(lp, encoding="utf-8", errors="replace") if "Verve error" in line)
        r["verve_errors"] = errs
        n = r.get("cars") or 0
        r["frozen_ai"] = frozen_ai(p)
        if r["frozen_ai"] > 0:
            urgent.append((label, "frozen AI cars %s (car 0, the autopilot, not counted)" % r["frozen_ai"]))
        if errs:
            urgent.append((label, "Verve errors in the CSP log: %d" % errs))
        if n and (r.get("retired_or_parked") or 0) / n > 0.4:
            urgent.append((label, "lost %s of %s cars" % (r["retired_or_parked"], n)))
        rows.append(r)
    if not rows:
        print("no races match", a.glob)
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(a.csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    by = collections.defaultdict(list)
    for r in rows:
        if not r.get("error"):
            by[r["field"]].append(r)

    def mean(v):
        v = [x for x in v if isinstance(x, (int, float))]
        return round(sum(v) / len(v), 2) if v else None
    print("%-14s %4s %6s %8s %7s %6s %6s %7s %7s %8s" % ("field", "n", "dnf%", "inc/100", "vsReal", "heavy", "lap01", "spread", "vsReal", "vsHuman%"))
    for fld, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print("%-14s %4d %6s %8s %7s %6s %6s %7s %7s %8s" % (
            fld[:14], len(rs), mean([r.get("dnf_pct") for r in rs]), mean([r.get("inc_per_car_100laps") for r in rs]),
            mean([r.get("inc_vs_real") for r in rs]), mean([r.get("heavy80") for r in rs]), mean([r.get("incidents_lap0_1") for r in rs]),
            mean([r.get("spread_pct") for r in rs]), mean([r.get("spread_vs_real") for r in rs]),
            mean([r.get("best_vs_human_top10_pct") for r in rs])))
    print("\n%d races scored, %d not scorable -> %s" % (sum(len(v) for v in by.values()), sum(1 for r in rows if r.get("error")), a.csv))
    if urgent:
        print("\nURGENT:")
        for lab, why in urgent:
            print("  %s: %s" % (lab, why))


if __name__ == "__main__":
    main()
