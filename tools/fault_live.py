"""Fault attribution from the 4 Hz contact traces (the design for the live penalty system, run offline first).

    python tools/fault_live.py diag_race_*.jsonl [--ledger]

Every {"ev":"contact"} record carries a car's last 4 s at 4 Hz: [t x10, aheadIdx, gap m, dLat x100, spd, aheadSpd, myBrake,
myGas, aheadBrake, convoyThr, guard, nearIdx, nearD m, nearLong m, nearLat x100]. Contacts within 1.5 s and 60 m of each
other are one INCIDENT. For each incident the rules below give a verdict, a culprit and a confidence; a strike is
confidence x severity (worst damage in the incident: <20 -> 0.5, <60 -> 1.0, else 1.5). The --ledger prints the per-car
strikes and a proposed time penalty (5 s per strike point above 1.0, rounded) -- shown, never enforced.

Rules (conservative, in this order; the first that fits wins):
  rear_end      A's trace shows B directly ahead (|dLat| < 0.3) within 6 m in the last 0.5 s, A closing by 8+ km/h,
                A's brake below 40 % -> A at fault, 0.8 (0.6 if B was braking hard: a brake-check share)
  hit_stopped   B's speed under 25 km/h at the moment, A above 60 -> A, 0.6
  squeeze       the two were alongside (|nearLong| < 5 m, nearD < 3 m) and one car's dLat toward the other shrank
                by 0.15+ over the last second -> the mover, 0.7
  dropped_into  a "drop" event for either car within 12 s before -> system (Verve's reposition), 1.0
  pileup        3+ cars within the window -> only clear rear-enders charged, the rest racing incident
  racing        everything else -> nobody
"""
import argparse, glob, json, os, re, sys
from collections import defaultdict, Counter


def load(path):
    hdr, contacts, drops = None, [], []
    for line in open(path, encoding="utf-8"):
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
    return hdr, contacts, drops


def ring_rows(c):
    return [dict(zip(["t", "ahead", "gap", "dlat", "spd", "aspd", "brake", "gas", "abrake", "thr", "guard", "near", "nearD", "nearLong", "nearLat"], r)) for r in c.get("ring", [])]


def judge(inc, drops, track_len):
    """inc: list of contact records (same incident). Returns (verdict, culprit, confidence, detail)."""
    cars = [c["car"] for c in inc]
    t = min(c["t"] for c in inc)
    for d in drops:
        if d["car"] in cars and 0 <= t - d["t"] <= 12:
            return "dropped_into", "system", 1.0, "car %d repositioned %d s before" % (d["car"], t - d["t"])
    rows = {c["car"]: ring_rows(c) for c in inc}
    # rear-end: A's last rows show B ahead on the same line, close, closing
    best = None
    for c in inc:
        r = rows[c["car"]]
        if len(r) < 3:
            continue
        last = r[-3:]
        for x in last:
            if x["ahead"] >= 0 and x["ahead"] in cars and abs(x["dlat"]) < 30 and x["gap"] <= 6 and x["spd"] - x["aspd"] >= 8:
                # not braking: 0.8; braking hard but still closing at 8+ km/h: braked too late, 0.7; the car ahead brake-checking
                # (hard on the brakes while I was not): a shared one, 0.6
                if x["brake"] < 40:
                    conf = 0.6 if x["abrake"] > 60 else 0.8
                else:
                    conf = 0.7
                cand = ("rear_end", c["car"], conf, "car %d closing on %d at +%d km/h, gap %d m, brake %d%% (theirs %d%%)" % (c["car"], x["ahead"], x["spd"] - x["aspd"], x["gap"], x["brake"], x["abrake"]))
                if best is None or cand[2] > best[2]:
                    best = cand
    if best and len(inc) <= 2:
        return best
    # hit a stopped / crawling car
    for c in inc:
        r = rows[c["car"]]
        if r:
            x = r[-1]
            if x["ahead"] in cars and x["aspd"] < 25 and x["spd"] > 60:
                return "hit_stopped", c["car"], 0.6, "car %d at %d km/h into car %d at %d km/h" % (c["car"], x["spd"], x["ahead"], x["aspd"])
    # squeeze: alongside, and one moved into the other
    for c in inc:
        r = rows[c["car"]]
        if len(r) < 5:
            continue
        last, prev = r[-1], r[-5]
        if last["near"] in cars and abs(last["nearLong"]) < 5 and last["nearD"] < 3 and prev["near"] == last["near"]:
            if abs(prev["nearLat"]) - abs(last["nearLat"]) >= 15:
                # this car's lateral distance to the other shrank: did THIS car move, or the other? we only know the relative
                # value from this car's ring; check the other car's ring for the mirror image
                other = last["near"]
                ro = rows.get(other, [])
                if len(ro) >= 5 and abs(ro[-5]["nearLat"]) - abs(ro[-1]["nearLat"]) >= 15:
                    # both traces show the pair converging and the ring holds only the RELATIVE offset, so the mover cannot be
                    # named from here: a mutual squeeze, both charged lightly (the live version will carry each car's own lateral)
                    return "squeeze", (c["car"], other), 0.35, "cars %d and %d converged from %.2f to %.2f of the track side by side at %d km/h" % (c["car"], other, abs(prev["nearLat"]) / 100, abs(last["nearLat"]) / 100, last["spd"])
                else:
                    return "squeeze", c["car"], 0.7, "car %d closed the gap to %d from %.2f to %.2f of the track" % (c["car"], other, abs(prev["nearLat"]) / 100, abs(last["nearLat"]) / 100)
    if len(inc) >= 3:
        if best:
            return "pileup", best[1], best[2] * 0.8, "%d cars; clearest rear-ender charged: %s" % (len(inc), best[3])
        return "pileup", None, 0.0, "%d cars, no clear culprit" % len(inc)
    if best:
        return best
    return "racing", None, 0.0, "no rule fits"


def incidents(contacts):
    contacts = sorted(contacts, key=lambda c: c["t"])
    groups = []
    for c in contacts:
        placed = False
        for g in groups:
            if abs(c["t"] - g[-1]["t"]) <= 1.5 and abs(c["spline"] - g[-1]["spline"]) <= 10 and c["car"] not in [x["car"] for x in g]:
                g.append(c); placed = True; break
        if not placed:
            groups.append([c])
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--ledger", action="store_true")
    a = ap.parse_args()
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    for p in sorted(paths):
        hdr, contacts, drops = load(p)
        if not hdr or not contacts:
            continue
        names = {c["i"]: c["driver"] for c in hdr["cars"]}
        label = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", os.path.basename(p)).group(1)
        strikes, verdicts = defaultdict(float), Counter()
        print(f"== {label}: {len(contacts)} contact records")
        for inc in incidents(contacts):
            v, culprit, conf, detail = judge(inc, drops, None)
            sev = max(c["dmg"] for c in inc)
            w = 0.5 if sev < 20 else (1.0 if sev < 60 else 1.5)
            verdicts[v] += 1
            if culprit == "system": who = "system"
            elif culprit is None: who = "nobody"
            elif isinstance(culprit, tuple): who = "cars %d and %d (mutual)" % culprit
            else: who = f"car {culprit} {names.get(culprit, '?')}"
            print(f"   t={inc[0]['t'] - hdr['t']:4d}s lap {inc[0]['lap']} cars {[c['car'] for c in inc]} dmg {sev:3d}  {v:12s} -> {who:28s} conf {conf:.1f}  {detail}")
            if culprit is not None and culprit != "system":
                for cu in (culprit if isinstance(culprit, tuple) else (culprit,)):
                    strikes[cu] += conf * w
        print("   verdicts:", dict(verdicts))
        if a.ledger and strikes:
            print("   -- ledger (strike points; proposed penalty = 5 s per point above 1.0) --")
            for car, s in sorted(strikes.items(), key=lambda x: -x[1]):
                pen = 5 * max(0, round(s - 1.0))
                print(f"      car {car:2d} {names.get(car, '?')[:22]:22s} strikes {s:.1f}  penalty {pen:2d} s")


if __name__ == "__main__":
    main()
