"""Where on lap 0-1 the contacts happen: cars in contact per track zone, per race.

    python tools/lap0_zones.py "diag_race_*barcelona*lanes3*.jsonl" [--zones 0.2,0.7,0.8]

Default zones split the lap at 0.2 (the turn-1 complex) and 0.70-0.80 (the Barcelona hairpin); pass your own cut points.
"""
import argparse, glob, json, collections, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--zones", default="0.2,0.7,0.8", help="cut points as lap fractions")
    a = ap.parse_args()
    cuts = [float(x) for x in a.zones.split(",")]
    names = ["<%.2f" % cuts[0]] + ["%.2f-%.2f" % (cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)] + [">=%.2f" % cuts[-1]]
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    for p in sorted(paths, key=os.path.getmtime):
        cars = collections.defaultdict(set)
        for line in open(p, encoding="utf-8"):
            if not line.startswith('{"ev":"contact"'):
                continue
            o = json.loads(line)
            if o["lap"] > 1:
                continue
            s = o["spline"] / 1000.0
            z = len(cuts)
            for k, c in enumerate(cuts):
                if s < c:
                    z = k; break
            cars[names[z]].add(o["car"])
        label = os.path.basename(p)[len("diag_race_YYYYMMDD_HHMMSS_"):-6]
        print("%-52s" % label, "  ".join("%s: %d" % (n, len(cars.get(n, ()))) for n in names))

if __name__ == "__main__":
    main()
