"""Score a weather race against its dry twin: lap-time delta, incidents, DNFs, wetness read, compound used.

    python tools/weather_score.py --dry "diag_race_*e18_wx_spa_clear.jsonl" --wet "diag_race_*e18_wx_spa_*.jsonl"
"""
import argparse, glob, json, os, re, statistics as st, collections
FEED = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")

def feed_for(diag):
    stamp = re.search(r"diag_race_(\d{8}_\d{6})", diag).group(1)
    best, bd = None, 1e9
    for f in glob.glob(os.path.join(FEED, "*.jsonl")):
        m = re.search(r"(\d{8}_\d{6})", os.path.basename(f))
        if m and m.group(1)[:8] == stamp[:8]:
            d = abs(int(m.group(1)[-6:]) - int(stamp[-6:]))
            if d < bd: best, bd = f, d
    return best if bd < 130 else None

def summarise(p):
    snaps = [json.loads(l) for l in open(p, encoding="utf-8") if l.startswith('{"t"')]
    if not snaps: return None
    wet = st.median(s.get("wet", 0) for s in snaps); rain = st.median(s.get("rain", 0) for s in snaps)
    cmp_ = collections.Counter(x["cmp"] for s in snaps for x in s["grid"]).most_common(1)[0][0]
    last = snaps[-1]; retired = sum(1 for x in last["grid"] if x["ret"] or x["park"])
    f = feed_for(p); laps = collections.defaultdict(list)
    if f:
        for line in open(f, encoding="utf-8"):
            o = json.loads(line)
            if o.get("type") == "lap" and o["lap"] >= 3: laps[o["car"]].append(o["time_s"])
    best = [min(v) for v in laps.values()] if laps else []
    contacts = sum(1 for l in open(p, encoding="utf-8") if l.startswith('{"ev":"contact"'))
    return dict(label=os.path.basename(p)[27:-6], wet=wet, rain=rain, cmp=cmp_, retired=retired, contacts=contacts,
                best=min(best) if best else None, median_best=st.median(best) if best else None, cars=len(last["grid"]))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", required=True); ap.add_argument("--wet", required=True)
    a = ap.parse_args()
    dry = summarise(sorted(glob.glob(a.dry), key=os.path.getmtime)[-1])
    print("%-32s %5s %5s %4s %7s %9s %9s %8s %4s" % ("race", "wet", "rain", "cmp", "best", "vs dry", "med best", "contacts", "DNF"))
    for p in sorted(glob.glob(a.wet), key=os.path.getmtime):
        s = summarise(p)
        if not s: continue
        d = ("%+.1f%%" % (100 * (s["best"] / dry["best"] - 1))) if (s["best"] and dry["best"]) else "-"
        print("%-32s %5.2f %5.2f %4d %7s %9s %9s %8d %4d" % (s["label"], s["wet"], s["rain"], s["cmp"],
              ("%.1f" % s["best"]) if s["best"] else "-", d, ("%.1f" % s["median_best"]) if s["median_best"] else "-", s["contacts"], s["retired"]))

if __name__ == "__main__":
    main()
