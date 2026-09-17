"""AI pace against a human baseline, per race.

    python tools/pace_vs_human.py --labels "n17_reg_.*|d17_reg_.*" [--car ks_ferrari_488_gt3]

Reads tools/harness_results/results.csv and tools/human_baselines.json (RSR hotlap boards, see the desk's
reality.md). The car is taken from the batch logs when possible (the harness line that produced the label), else
from --car. Prints one row per race and flags any race where the AI leader beats the human top-10% hotlap or the AI
median-of-best beats the human median hotlap: that is the over-optimised signal the owner asked to watch.
"""
import argparse, csv, glob, json, os, re, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "harness_results", "results.csv")
BASE = os.path.join(HERE, "human_baselines.json")


def fmt(s):
    return "" if s is None else "%d:%05.2f" % (int(s // 60), s % 60)


def cars_from_logs():
    """label -> models string, from every batch log's harness lines."""
    out = {}
    for lg in glob.glob(os.path.join(HERE, "harness_results", "batch_*.log")):
        try:
            for line in open(lg, encoding="utf-8", errors="replace"):
                m = re.search(r"--models (\S+).*--label (\S+)", line)
                if m:
                    out[m.group(2)] = m.group(1).split(",")[0]
        except OSError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="regex on the label column")
    ap.add_argument("--car", default=None, help="fallback car folder when the batch log does not say")
    ap.add_argument("--level", type=float, default=None, help="only this AI level")
    a = ap.parse_args()
    base = json.load(open(BASE, encoding="utf-8"))
    cars = cars_from_logs()
    rx = re.compile(a.labels)
    rows = [r for r in csv.DictReader(open(RES, encoding="utf-8")) if rx.fullmatch(r["label"] or "")]
    if a.level is not None:
        rows = [r for r in rows if r.get("ai_level") and float(r["ai_level"]) == a.level]
    print("%-26s %-14s %-22s %7s %8s | %8s %8s %8s  %s" % ("label", "track", "car", "AIbest", "AImed", "H.top10", "H.med", "H.med+r", "verdict"))
    flags = 0
    for r in rows:
        car = cars.get(r["label"]) or a.car or "?"
        key = "%s|%s" % (r["track"].split("/")[0], car)   # layout stripped: baselines key on the track folder
        b = base.get(key)
        ab = float(r["ai_best_lap_s"]) if r.get("ai_best_lap_s") else None
        am = float(r["ai_median_best_lap_s"]) if r.get("ai_median_best_lap_s") else None
        if not b or ab is None:
            print("%-26s %-14s %-22s %7s %8s | no baseline for %s" % (r["label"], r["track"], car, fmt(ab), fmt(am), key))
            continue
        hm = b["median"] + b["race_allow_s"]
        v = []
        if ab < b["top10"]:
            v.append("LEADER FASTER THAN HUMAN TOP-10% HOTLAP"); flags += 1
        elif ab < b["median"]:
            v.append("leader between top-10% and median hotlap")
        elif ab < hm:
            v.append("leader = good regular at race pace")
        else:
            v.append("leader slower than a regular's race pace (+%.1f s)" % (ab - hm))
        if am is not None:
            if am < b["median"]:
                v.append("FIELD MEDIAN FASTER THAN HUMAN MEDIAN HOTLAP"); flags += 1
            elif am < hm:
                v.append("field median = regular race pace")
            else:
                v.append("field median +%.1f s on a regular" % (am - hm))
        print("%-26s %-14s %-22s %7s %8s | %8s %8s %8s  %s" % (r["label"], r["track"], car, fmt(ab), fmt(am), fmt(b["top10"]), fmt(b["median"]), fmt(hm), "; ".join(v)))
    bests = [float(r["ai_best_lap_s"]) for r in rows if r.get("ai_best_lap_s")]
    if bests:
        print("\n%d races; AI best median %s, min %s. %d over-optimised flags." % (len(rows), fmt(st.median(bests)), fmt(min(bests)), flags))


if __name__ == "__main__":
    main()
