"""Star-from-the-lights scorecard: for a protagonist (slot 0 by default) in each diag file, its position at the start of
each lap, its opening-lap road use and how often the road-space rule fired, passes made / re-passed (feed), contacts.

    python tools/star_lights.py "diag_race_*p15_starlights_*.jsonl" [--hero 0] [--group]
"""
import argparse, glob, json, os, re, sys
from collections import Counter, defaultdict

FEED = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")


def feed_for(p):
    m = re.search(r"diag_race_(\d{8}_\d{6})_", os.path.basename(p))
    h = glob.glob(os.path.join(FEED, m.group(1) + "_*.jsonl")) if m else []
    return h[0] if h else None


def score(p, hero):
    lines = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    snaps = [r for r in lines[1:] if "grid" in r]
    cs = [r for r in lines[1:] if r.get("ev") == "contact"]
    if not snaps:
        return None
    lapstart, atk, rs, wide = {}, Counter(), Counter(), Counter()
    for s in snaps:
        g = next((c for c in s["grid"] if c["i"] == hero), None)
        if not g:
            continue
        lapstart.setdefault(g["lap"], g["pos"])
        if g["st"] == 1:
            atk[g["lap"]] += 1; rs[g["lap"]] += g.get("rs", 0); wide[g["lap"]] += abs(g.get("off", 0)) >= 30
    last = next(c for c in snaps[-1]["grid"] if c["i"] == hero)
    made = lost = 0
    f = feed_for(p)
    if f:
        for l in open(f, encoding="utf-8"):
            if '"overtake"' not in l:
                continue
            d = json.loads(l)
            if d.get("type") != "overtake":
                continue
            if d.get("car") == hero: made += 1
            elif d.get("over") == hero: lost += 1
    a01 = atk[0] + atk[1]
    label = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", os.path.basename(p)).group(1)
    return {"label": label, "p_lap1": lapstart.get(1), "p_lap2": lapstart.get(2), "final": last["pos"],
            "ol_road_pct": 100.0 * (wide[0] + wide[1]) / a01 if a01 else 0.0, "ol_rs_pct": 100.0 * (rs[0] + rs[1]) / a01 if a01 else 0.0,
            "made": made, "lost": lost, "contacts": len(cs), "heavy": sum(1 for c in cs if c["dmg"] >= 25),
            "hero_contacts": sum(1 for c in cs if c["car"] == hero)}


COLS = ["label", "p_lap1", "p_lap2", "final", "ol_road_pct", "ol_rs_pct", "made", "lost", "contacts", "heavy", "hero_contacts"]


def fmt(r):
    return f"{str(r['label'])[:28]:28s} " + " ".join(f"{(r[k] if r[k] is not None else '-'):>{max(len(k), 6)}}" if not isinstance(r[k], float) else f"{r[k]:>{max(len(k), 6)}.0f}" for k in COLS[1:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+"); ap.add_argument("--hero", type=int, default=0); ap.add_argument("--group", action="store_true")
    a = ap.parse_args()
    paths = []
    for f in a.files: paths += glob.glob(f) or [f]
    rows = [r for r in (score(p, a.hero) for p in sorted(paths)) if r]
    print(f"{'label':28s} " + " ".join(f"{k:>{max(len(k), 6)}}" for k in COLS[1:]))
    for r in rows: print(fmt(r))
    if a.group:
        g = defaultdict(list)
        for r in rows: g[re.sub(r"_\d+$", "", r["label"])].append(r)
        print("\n-- mean by label --")
        for k, rs in g.items():
            m = {"label": k + " x%d" % len(rs)}
            for c in COLS[1:]:
                v = [r[c] for r in rs if r[c] is not None]
                m[c] = (sum(v) / len(v)) if v else None
            print(fmt(m))


if __name__ == "__main__":
    main()
