"""One line per ablation race: dead, incidents, laps-2+ rate, heavy hits (>= 80 km/h) and how many at Baku's 0.74-0.76 kink,
median lap, queue behind a crawler. python tools/ablation_table.py 'diag_race_*d24_abl_*.jsonl'"""
import glob, json, re, subprocess, sys
from collections import Counter
files = sorted(f for pat in sys.argv[1:] for f in glob.glob(pat))
print(f"{'race':16s} {'dead':>4s} {'inc':>4s} {'l2+':>5s} {'hvy80':>5s} {'kink':>4s} {'medlap':>6s} {'held_s':>6s}  dead by cause")
for f in files:
    m = subprocess.run([sys.executable, "tools/race_metrics.py", f], capture_output=True, text=True).stdout
    g = lambda k: (re.search(r"^" + k + r"\s+(\S+)", m, re.M) or [None, "-"])[1]
    heavy = Counter(); tot = 0
    for l in open(f, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        if r.get("ev") == "contact" and r.get("dmg", 0) >= 80:
            tot += 1; heavy[int((r.get("spline") or 0) / 20)] += 1
    t = subprocess.run([sys.executable, "tools/train.py", f], capture_output=True, text=True).stdout.splitlines()[1].split()
    cause = {k[5:]: v for k, v in re.findall(r"^(dead_\w+)\s+(\d+)", m, re.M)}
    lab = re.search(r"d24_abl_(\w+)", f).group(1)
    print(f"{lab:16s} {g('retired_or_parked'):>4s} {g('incidents'):>4s} {g('inc_per_car_100laps_lap2plus'):>5s} {tot:5d} {heavy[37]:4d} {g('laptime_median_s'):>6s} {t[2]:>6s}  {cause}")
