"""AI anomalies: things a car did that nobody intended, from the diag snapshots (8 s) and contact traces.

    python tools/anomalies.py diag_race_20260916_*.jsonl            # one line per anomaly, then a per-race summary
    python tools/anomalies.py --summary "diag_race_*p12_*.jsonl"    # summary only (for the nightly report)

Flags (per car, per snapshot pair):
  wrong_way     heading against the racing direction at speed (fwd < -0.5, speed > 30 km/h), not being recovered
  off_track_pass  beyond the track edge (|lat| > 1.0) at speed AND gained a place since the last snapshot
  cut           beyond the track edge at speed on the racing line's inside (|lat| > 1.0, speed > 80), no place gained
  parked_on_track  stationary on the road (|lat| < 1.0, speed < 5) for 2+ snapshots after lap 0, not in the pits, not retired
  teleport      spline jump larger than the car could have covered at its speed (a reposition outside recovery's own drops)
  sudden_stop   from 100+ km/h to under 30 on the road with no contact logged (a stall, a reset, a freeze)
Each line: time, car, driver name, flag, detail. The broadcast agent wants these for "one odd clip beats a planned race".
"""
import argparse, glob, json, os, re, sys
from collections import Counter, defaultdict


def load(path):
    hdr, snaps, contacts, drops = None, [], [], []
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
            elif d.get("ev") == "drop":
                drops.append(d)
            elif "grid" in d:
                snaps.append(d)
    return hdr, snaps, contacts, drops


def label_of(path):
    m = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def analyse(path, track_len_m=None):
    hdr, snaps, contacts, drops = load(path)
    if not hdr or len(snaps) < 2:
        return None
    names = {c["i"]: c["driver"] for c in hdr["cars"]}
    contact_t = defaultdict(set)
    for c in contacts:
        contact_t[c["car"]].add(c["t"])
    drop_t = defaultdict(set)
    for d in drops:
        drop_t[d["car"]].add(d["t"])
    t0 = snaps[0]["t"]
    out = []
    parked_run = Counter()
    prev = {}
    for s in snaps:
        t = s["t"]
        for c in s["grid"]:
            i = c["i"]
            p = prev.get(i)
            rec = c.get("rec", 0) == 1
            ret = c.get("ret") is True
            pit = c.get("pit") is True
            spd, lat, fwd, lap = c.get("spd", 0), c.get("lat", 0) / 100.0, c.get("fwd", 0) / 100.0, c.get("lap", 0)
            near_contact = any(abs(t - ct) <= 10 for ct in contact_t.get(i, ()))
            near_drop = any(abs(t - dt) <= 10 for dt in drop_t.get(i, ()))
            if ret or pit:
                parked_run[i] = 0
                prev[i] = c
                continue
            if fwd < -0.5 and spd > 30 and not rec:
                out.append((t - t0, i, names.get(i, "?"), "wrong_way", f"heading {fwd:+.2f} at {spd} km/h, lat {lat:+.2f}, lap {lap}"))
            if abs(lat) > 1.0 and spd > 60 and not rec:
                if p and c.get("pos", 99) < p.get("pos", 99):
                    out.append((t - t0, i, names.get(i, "?"), "off_track_pass", f"lat {lat:+.2f} at {spd} km/h, P{p.get('pos')} -> P{c.get('pos')}, lap {lap}"))
                elif spd > 80:
                    out.append((t - t0, i, names.get(i, "?"), "cut", f"lat {lat:+.2f} at {spd} km/h, lap {lap}"))
            if spd < 5 and abs(lat) < 1.0 and lap > 0 and not rec:
                parked_run[i] += 1
                if parked_run[i] == 2:
                    out.append((t - t0, i, names.get(i, "?"), "parked_on_track", f"stationary on the road for 16 s, lat {lat:+.2f}, lap {lap}" + (" (after contact)" if near_contact else "")))
            else:
                parked_run[i] = 0
            if p:
                dt = t - p["t"] if "t" in p else 8
                ds = (c.get("spline", 0) - p.get("spline", 0)) % 1000 / 1000.0
                if track_len_m and dt > 0:
                    max_frac = (max(spd, p.get("spd", 0)) / 3.6 * dt * 1.5 + 30) / track_len_m
                    if ds > max_frac and ds < 0.9 and not near_drop and not rec:
                        out.append((t - t0, i, names.get(i, "?"), "teleport", f"spline +{ds:.3f} in {dt} s at {spd} km/h (max plausible {max_frac:.3f}), lap {lap}"))
                if p.get("spd", 0) > 100 and spd < 30 and abs(lat) < 1.0 and not near_contact and not near_drop and not rec and lap > 0:
                    out.append((t - t0, i, names.get(i, "?"), "sudden_stop", f"{p.get('spd', 0)} -> {spd} km/h in {dt} s on the road, lat {lat:+.2f}, lap {lap} (no contact logged)"))
            c["t"] = t
            prev[i] = c
    return {"label": label_of(path), "track": hdr.get("track"), "cars": len(hdr["cars"]), "events": out}


TRACK_LEN = {"monza": 5793, "spa": 7004, "ks_barcelona/layout_gp": 4655, "ks_silverstone/gp": 5891, "ks_zandvoort": 4252,
             "ks_brands_hatch/gp": 3908, "ks_brands_hatch/indy": 1929, "mugello": 5245, "imola": 4909, "ks_red_bull_ring/layout_gp": 4318,
             "monza_2022": 5793, "spa/2022": 7004}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--summary", action="store_true", help="per-race counts only")
    a = ap.parse_args()
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    for p in sorted(paths):
        r = analyse(p, None)
        if not r:
            continue
        r = analyse(p, TRACK_LEN.get(r["track"]))
        kinds = Counter(e[3] for e in r["events"])
        print(f"{r['label']}  ({r['track']}, {r['cars']} cars): " + (", ".join(f"{k} x{n}" for k, n in kinds.most_common()) if kinds else "no anomalies"))
        if not a.summary:
            for t, i, name, kind, detail in r["events"]:
                print(f"   t+{t:4d}s  car {i:2d} {name[:22]:22s} {kind:16s} {detail}")


if __name__ == "__main__":
    main()
