"""Per-model best laps and revs peak for the gearshift probes.

    python tools/shift_probe.py "diag_race_*shiftclean*.jsonl"

Reads each race's feed (matched by timestamp in Documents/Assetto Corsa/verve_feed) for lap times per car, and the diag
snapshots for the per-car revs peak as a fraction of the limiter (rpmx). One row per car per race.
"""
import glob, json, os, sys, re, statistics as st
FEED = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")

def feed_for(diag):
    stamp = re.search(r"diag_race_(\d{8}_\d{6})", diag).group(1)
    best, bd = None, 1e9
    for f in glob.glob(os.path.join(FEED, "*.jsonl")):
        m = re.search(r"(\d{8}_\d{6})", os.path.basename(f))
        if not m: continue
        d = abs(int(m.group(1)[-6:]) - int(stamp[-6:])) if m.group(1)[:8] == stamp[:8] else 1e9
        if d < bd: best, bd = f, d
    return best if bd < 130 else None

paths = []
for a in sys.argv[1:]: paths += glob.glob(a) or [a]
for p in sorted(paths, key=os.path.getmtime):
    hdr, last = None, None
    for line in open(p, encoding="utf-8"):
        if line.startswith('{"hdr"'): hdr = json.loads(line)
        elif line.startswith('{"t"'): last = line
    if not hdr or not last: continue
    snap = json.loads(last); rpmx = {c["i"]: c.get("rpmx", 0) for c in snap["grid"]}
    f = feed_for(p); laps = {}
    if f:
        for line in open(f, encoding="utf-8"):
            o = json.loads(line)
            if o.get("type") == "lap" and o["lap"] >= 2: laps.setdefault(o["car"], []).append(o["time_s"])
    label = os.path.basename(p)[len("diag_race_YYYYMMDD_HHMMSS_"):-6]
    print("== %s (feed %s)" % (label, os.path.basename(f) if f else "none"))
    for c in hdr["cars"]:
        i = c["i"]; l = laps.get(i, [])
        print("   car %2d %-28s best %s  laps %s  revs peak %s%% of limiter" % (i, c["model"], ("%.1f" % min(l)) if l else "  -  ", [round(x, 1) for x in l], rpmx.get(i, 0)))
