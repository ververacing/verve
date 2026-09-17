"""Road-space tally: did the protagonist USE THE ROAD, and did it get anywhere?

For each diag file (or a glob): the hero car (slot 0 by default) -- places gained per lap, overtakes made / lost
(from the matching feed file), how often it sat in attack and how far off-line it went while attacking, how often
the road-space rule fired (the "rs" flag, R.ROADSPACE builds only), plus the field-wide off-line distribution and the
contact count so an A/B can be read side by side.

    python tools/roadspace_tally.py diag_race_20260916_*.jsonl
    python tools/roadspace_tally.py --hero 0 --group "diag_race_*p11_rs*.jsonl"

Rows are grouped by label with the trailing _<run> stripped (p11_rs_kart_A_1 and _A_2 -> p11_rs_kart_A) and
averaged, so "A vs B" is one line each.
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict

FEED_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
OFF_WIDE = 30      # |off| (x100) at or above this counts as "used the road"


def load(path):
    hdr, snaps, contacts = None, [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("hdr"):
                hdr = d
            elif d.get("ev") == "contact":
                contacts.append(d)
            elif "grid" in d:
                snaps.append(d)
    return hdr, snaps, contacts


def feed_for(diag_path):
    m = re.search(r"diag_race_(\d{8}_\d{6})_", os.path.basename(diag_path))
    if not m:
        return None
    hits = glob.glob(os.path.join(FEED_DIR, m.group(1) + "_*.jsonl"))
    return hits[0] if hits else None


def overtakes(feed_path, hero):
    made = lost = 0
    if not feed_path:
        return None, None
    with open(feed_path, encoding="utf-8") as f:
        for line in f:
            if '"overtake"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "overtake":
                continue
            if d.get("car") == hero:
                made += 1
            elif d.get("over") == hero:
                lost += 1
    return made, lost


def label_of(path):
    b = os.path.basename(path)
    m = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", b)
    return m.group(1) if m else b


def tally(path, hero):
    hdr, snaps, contacts = load(path)
    if not snaps:
        return None
    first = next((c for c in snaps[0]["grid"] if c["i"] == hero), None)
    last = next((c for c in snaps[-1]["grid"] if c["i"] == hero), None)
    if not first or not last:
        return None
    laps = max(last.get("lap", 0), 0)
    heroAtk = heroWide = heroRs = 0
    fieldAtk = fieldWide = fieldRs = 0
    for s in snaps:
        for c in s["grid"]:
            if c.get("st") != 1:
                continue
            wide = abs(c.get("off", 0)) >= OFF_WIDE
            rs = c.get("rs", 0) == 1
            fieldAtk += 1; fieldWide += wide; fieldRs += rs
            if c["i"] == hero:
                heroAtk += 1; heroWide += wide; heroRs += rs
    made, lost = overtakes(feed_for(path), hero)
    heroContacts = sum(1 for c in contacts if c.get("car") == hero)
    heavy = sum(1 for c in contacts if c.get("dmg", 0) >= 25)
    return {
        "label": label_of(path), "cars": len(hdr["cars"]) if hdr else 0, "laps": laps,
        "start": first.get("pos", 0), "end": last.get("pos", 0),
        "gained": first.get("pos", 0) - last.get("pos", 0),
        "gained_per_lap": (first.get("pos", 0) - last.get("pos", 0)) / laps if laps else 0.0,
        "ot_made": made, "ot_lost": lost,
        "hero_atk": heroAtk, "hero_wide_pct": 100.0 * heroWide / heroAtk if heroAtk else 0.0,
        "hero_rs_pct": 100.0 * heroRs / heroAtk if heroAtk else 0.0,
        "field_wide_pct": 100.0 * fieldWide / fieldAtk if fieldAtk else 0.0,
        "field_rs_pct": 100.0 * fieldRs / fieldAtk if fieldAtk else 0.0,
        "contacts": len(contacts), "heavy": heavy, "hero_contacts": heroContacts,
        "retired": snaps[-1].get("retired", 0),
    }


COLS = [("label", 28, "s"), ("cars", 4, "d"), ("laps", 4, "d"), ("start", 5, "d"), ("end", 4, "d"), ("gained", 6, "d"),
        ("gained_per_lap", 7, ".2f"), ("ot_made", 7, "s"), ("ot_lost", 7, "s"), ("hero_atk", 8, "d"),
        ("hero_wide_pct", 9, ".0f"), ("hero_rs_pct", 8, ".0f"), ("field_wide_pct", 10, ".0f"), ("field_rs_pct", 9, ".0f"),
        ("contacts", 8, "d"), ("heavy", 5, "d"), ("hero_contacts", 8, "d"), ("retired", 7, "d")]


def fmt(row):
    out = []
    for k, w, f in COLS:
        v = row.get(k)
        if v is None:
            out.append("-".rjust(w))
        elif f == "s":
            out.append(str(v).ljust(w) if k == "label" else str(v).rjust(w))
        else:
            out.append(format(v, f).rjust(w))
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="diag files or globs")
    ap.add_argument("--hero", type=int, default=0, help="car index to follow (default 0 = the autopilot player)")
    ap.add_argument("--group", action="store_true", help="also average rows by label with the trailing _<run> stripped")
    a = ap.parse_args()
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    rows = [r for r in (tally(p, a.hero) for p in sorted(paths)) if r]
    print(" ".join((k.ljust(w) if k == "label" else k.rjust(w)) for k, w, _ in COLS))
    for r in rows:
        print(fmt(r))
    if a.group and rows:
        groups = defaultdict(list)
        for r in rows:
            groups[re.sub(r"_\d+$", "", r["label"])].append(r)
        print("\n-- by label (mean) --")
        for g, rs in groups.items():
            m = {"label": g + " x" + str(len(rs))}
            for k, _, f in COLS[1:]:
                vals = [r[k] for r in rs if r.get(k) is not None]
                if not vals:
                    m[k] = None
                elif f == "d":
                    m[k] = int(round(sum(vals) / len(vals)))
                elif f == "s":
                    m[k] = "%.1f" % (sum(vals) / len(vals))
                else:
                    m[k] = sum(vals) / len(vals)
            print(fmt(m))


if __name__ == "__main__":
    main()
