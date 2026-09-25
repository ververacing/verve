"""Best / median practice lap per headroom run, matched to its feed by start time.
    python tools/headroom_ladder.py tools/harness_results/batch_20260924_headroom.log"""
import glob, json, os, re, sys
log = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
steps = re.findall(r"=== step (\d+)/\d+ (\d\d):(\d\d):\d\d: harness.py (.*)", log)
feeds = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed", "*_baku_2022.jsonl")))
def laps(p):
    out = []
    for l in open(p, encoding="utf-8", errors="ignore"):
        try: r = json.loads(l)
        except Exception: continue
        if (r.get("ev") or r.get("type") or r.get("event")) == "lap" and r.get("car") == 0 and r.get("time_s"): out.append(r["time_s"])
    return out
for k, hh, mm, cmd in steps:
    t0 = int(hh) * 60 + int(mm)
    arms = " ".join(re.findall(r"--(?:settings|racecraft|human) \S+", cmd)) or "base"
    best = None
    for f in feeds:
        m = re.search(r"_(\d\d)(\d\d)\d\d_", os.path.basename(f)); ft = int(m.group(1)) * 60 + int(m.group(2))
        if 0 <= ft - t0 <= 3:
            L = laps(f)
            if len(L) >= 2: best = (min(L), sorted(L)[len(L) // 2], len(L))
    print(f"run {k} {hh}:{mm} {arms:48s} -> " + (f"best {best[0]:6.1f}  median {best[1]:6.1f}  ({best[2]} laps)" if best else "no practice laps"))
