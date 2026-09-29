"""Wrecking Crew scorecard: what one chaos driver (a wild profile: lib/drivers.lua wrecking_crew, racecraft R.WILD) did in
each race, and what the rest of the field paid for it. Read-only: the diag files, their race feeds and the CSP logs the
harness keeps (tools/harness_results/csp_logs).

    python tools/wild_tally.py "diag_race_*wc_spa_*.jsonl" --slot 9 [--group]

Per race:
  start fin gain win   grid slot at the lights, finishing position, places gained, won
  dnf pw               retired or parked at the end, and Verve's park reason (diag "pw")
  laps inc100          his laps, and his incidents per 100 laps (caused + suffered + side + solo)
  caused suff side solo  feed incident events (other / noseAhead / closing, closing = the damaged car's speed minus the
                       other's); each pair once per 2 s, since both cars can log the same contact:
                         damaged him,   other ahead  (noseAhead true),  closing >= 3  -> caused
                         damaged him,   other behind (noseAhead false), closing <= -3 -> suffered
                         damaged other, he is behind (noseAhead false), closing <= -3 -> caused
                         damaged other, he is ahead  (noseAhead true),  closing >= 3  -> suffered
                       anything else between the two -> side; his incident with no other car -> solo
  offs                 his off_track events (feed)
  flt fmed             'Verve fault:' verdicts naming him (CSP log), and the field's median per car (without him)
  lunge lwon           lunges attempted / completed (diag "mv" episodes)
  caut agg             his median applied caution and aggression (x100) from lap 2 on, at speed, not recovering
  rn                   crash repairs (diag "rn")
  tilt live            'tilt' decisions (R.WILD_TILT) and whether the feed's one-off 'wild' decision appeared (layer live)
  fh80 fout            the field without him: contact events at 80+ km/h (diag), cars retired or parked at the end
  doff                 repositioning switched itself off this race (diag dropsOff)
"""
import argparse, glob, json, os, re, statistics as stats
from collections import Counter, defaultdict

FEED = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
CSP_LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness_results", "csp_logs")
FAULT = re.compile(r"Verve fault: lap -?\d+ (\w+) -> (.+?) \((-?[\d.]+)\)")


def stamp_of(p):
    m = re.match(r"diag_race_(\d{8})_(\d{6})_(.+)\.jsonl$", os.path.basename(p))
    return m.groups() if m else (None, None, None)


def feed_for(p):
    d, t, _ = stamp_of(p)
    h = glob.glob(os.path.join(FEED, "%s_%s_*.jsonl" % (d, t))) if d else []
    return h[0] if h else None


def csp_log_for(p):
    """The harness keeps a race's Verve log lines as <YYYYmmdd_HHMM>_<label>.log, stamped at launch (a few minutes before
    the diag file's session start). Take the latest one whose label ends the diag name and whose stamp is not after it."""
    d, t, rest = stamp_of(p)
    if not d:
        return None
    best = None
    for f in glob.glob(os.path.join(CSP_LOGS, "*.log")):
        m = re.match(r"(\d{8})_(\d{4})_(.+)\.log$", os.path.basename(f))
        if not m or not ("_" + rest).endswith("_" + m.group(3)):
            continue
        key = m.group(1) + m.group(2)
        if key <= d + t[:4] and (best is None or key > best[0]):
            best = (key, f)
    return best[1] if best else None


def classify(ev, hero):
    car, other = ev.get("car"), ev.get("other")
    if other is None:
        return "solo" if car == hero else None
    ahead, cl = ev.get("noseAhead"), ev.get("closing", 0) or 0
    if car == hero:
        if ahead and cl >= 3: return "caused"
        if not ahead and cl <= -3: return "suffered"
        return "side"
    if other == hero:
        if not ahead and cl <= -3: return "caused"
        if ahead and cl >= 3: return "suffered"
        return "side"
    return None


def score(p, hero):
    snaps, contacts, mvs = [], [], []
    for l in open(p, encoding="utf-8", errors="replace"):
        l = l.strip()
        if not l:
            continue
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if "grid" in r: snaps.append(r)
        elif r.get("ev") == "contact": contacts.append(r)
        elif r.get("ev") == "mv": mvs.append(r)
    rows = [(s, next((c for c in s["grid"] if c["i"] == hero), None)) for s in snaps]
    rows = [(s, g) for s, g in rows if g]
    if not rows:
        return None
    first, last = rows[0][1], rows[-1][1]
    dnf = bool(last.get("ret") in (True, 1) or last.get("park"))
    pw = next((g.get("pw") for _, g in reversed(rows) if g.get("pw")), "")
    laps = max(g.get("lap", 0) for _, g in rows)
    run = [g for _, g in rows if g.get("lap", 0) >= 2 and g.get("spd", 0) > 30 and not g.get("rec") and g.get("pit") in (False, 0, None)]
    caut = stats.median([g["caut"] for g in run]) if run else None
    agg = stats.median([g["agg"] for g in run]) if run else None
    out_field = sum(1 for c in snaps[-1]["grid"] if c["i"] != hero and (c.get("ret") in (True, 1) or c.get("park")))
    r = {"label": stamp_of(p)[2], "start": first.get("pos"), "fin": last.get("pos"), "gain": (first.get("pos") or 0) - (last.get("pos") or 0),
         "win": int(last.get("pos") == 1 and not dnf), "dnf": int(dnf), "pw": pw, "laps": laps,
         "caused": 0, "suff": 0, "side": 0, "solo": 0, "offs": 0, "inc100": None, "flt": None, "fmed": None,
         "lunge": sum(1 for m in mvs if m.get("car") == hero and m.get("name") == "lunge"),
         "lwon": sum(1 for m in mvs if m.get("car") == hero and m.get("name") == "lunge" and m.get("won")),
         "caut": caut, "agg": agg, "rn": max(g.get("rn", 0) for _, g in rows), "tilt": 0, "live": 0,
         "fh80": sum(1 for c in contacts if c.get("car") != hero and c.get("dmg", 0) >= 80), "fout": out_field,
         "doff": int(any(s.get("dropsOff") for s in snaps))}
    f = feed_for(p)
    if f:
        seen = {}
        for l in open(f, encoding="utf-8", errors="replace"):
            if '"type"' not in l:
                continue
            try:
                e = json.loads(l)
            except ValueError:
                continue
            typ = e.get("type")
            if typ == "incident":
                k = classify(e, hero)
                if not k:
                    continue
                pair = (hero,) if k == "solo" else tuple(sorted((e.get("car"), e.get("other"))))
                if pair in seen and e.get("t", 0) - seen[pair] < 2.0:
                    continue
                seen[pair] = e.get("t", 0)
                r["suff" if k == "suffered" else k] += 1
            elif typ == "off_track" and e.get("car") == hero:
                r["offs"] += 1
            elif typ == "verve" and e.get("car") == hero:
                if e.get("decision") == "tilt": r["tilt"] += 1
                elif e.get("decision") == "wild": r["live"] = 1
        n = r["caused"] + r["suff"] + r["side"] + r["solo"]
        r["inc100"] = 100.0 * n / laps if laps else None
    lg = csp_log_for(p)
    if lg:
        per = Counter()
        for l in open(lg, encoding="utf-8", errors="replace"):
            m = FAULT.search(l)
            if not m:
                continue
            for c in (re.findall(r"\d+", m.group(2)) if m.group(2).startswith("car") else []):   # "car 5" / "cars 5 and 7"
                per[int(c)] += 1
        field = [per.get(c["i"], 0) for c in snaps[-1]["grid"] if c["i"] != hero]
        r["flt"] = per.get(hero, 0)
        r["fmed"] = stats.median(field) if field else None
    return r


COLS = ["start", "fin", "gain", "win", "dnf", "pw", "laps", "inc100", "caused", "suff", "side", "solo", "offs", "flt", "fmed",
        "lunge", "lwon", "caut", "agg", "rn", "tilt", "live", "fh80", "fout", "doff"]


def cell(k, v):
    w = max(len(k), 5)
    if v is None: return f"{'-':>{w}}"
    if isinstance(v, float): return f"{v:>{w}.1f}"
    return f"{str(v)[:w]:>{w}}"


def fmt(r):
    return f"{str(r['label'])[:34]:34s} " + " ".join(cell(k, r.get(k)) for k in COLS)


def main():
    ap = argparse.ArgumentParser(description="Wrecking Crew scorecard (read-only)")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--slot", type=int, required=True, help="the chaos driver's car index")
    ap.add_argument("--group", action="store_true", help="also print the mean per label (the _N run suffix stripped)")
    a = ap.parse_args()
    paths = []
    for f in a.files: paths += glob.glob(f) or [f]
    rows = [r for r in (score(p, a.slot) for p in sorted(set(paths))) if r]
    print(f"{'label':34s} " + " ".join(cell(k, k) for k in COLS))
    for r in rows: print(fmt(r))
    if a.group and rows:
        g = defaultdict(list)
        for r in rows: g[re.sub(r"_\d+$", "", r["label"])].append(r)
        print("\n-- mean by label --")
        for k, rs in g.items():
            m = {"label": "%s x%d" % (k, len(rs))}
            for c in COLS:
                v = [r[c] for r in rs if isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)]
                m[c] = (sum(v) / len(v)) if v else None
            print(fmt(m))


if __name__ == "__main__":
    main()
