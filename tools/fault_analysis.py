"""Fault attribution for car-to-car contacts, scored offline from Verve diagnostics logs.

Design study for the (future, optional) strikes / penalty feature. For every contact -- two or more cars
taking damage in the same snapshot within ~50 m of each other -- it reconstructs the situation from the
snapshot BEFORE the contact and assigns fault with a confidence, using conservative rules:

  rear_end        the car behind was closing hard on the same line            -> behind at fault (0.8)
  hit_stopped     a car at speed reached a car that was stopped/crawling      -> arriving car (0.6; a stopped
                                                                                  car on the road is partly the
                                                                                  situation's fault, hence < 0.8)
  squeeze         side by side, one car moved sideways INTO the other         -> the mover (0.7)
  dropped_into    one car had just been repositioned by Verve (< 12 s)        -> "system" (Verve), 1.0
  pileup          3+ cars                                                      -> only clear rear-enders are
                                                                                  charged; the rest is a racing
                                                                                  incident
  racing_incident everything else                                              -> nobody (0)

A strike = fault confidence x severity weight (impact km/h: <20 -> 0.5, <60 -> 1, else 1.5). The report
prints per-race contacts, the rule that fired, per-car strike totals, and cross-race aggregates -- so the
formula can be judged against incidents we can verify by hand before any car is ever penalised live.

    python tools/fault_analysis.py [diag files...]     (default: all of today's logs in the Verve folder)

FINDINGS (2026-09-13, 45 races, 151 contacts at 8 s resolution)
  - 61% racing incident, 17% squeeze, 14% pile-up, 7% rear-end, <1% hit-stopped. That split is the
    conservative behaviour a live penalty system needs: most contact is nobody's fault.
  - Per-car strike totals are small and flat (median 0.6, p90 1.0, max 1.6 per race): with these
    weights, a 3-strike penalty would fire on ~1 car per race, a 6-strike retirement almost never.
    Reasonable as a first calibration; tune on live data.
  - High-downforce prototypes (TS040, 919, R18) top the at-fault table: they arrive on slower cars
    fastest. Karts appear because side-by-side contact is constant in that class -- the squeeze rule
    needs a class-aware lateral threshold.
  - What the LIVE version needs that this offline pass lacks: per-zone damage (car.damage[0..3]: front/
    rear/left/right -- who hit whom is then explicit), sampling at 1-2 Hz around contacts instead of
    8 s, and lateral VELOCITY (a car moving across the track vs. holding a line). All three are
    available in Verve at runtime; none are in the diag log yet.
"""
import collections
import glob
import json
import os
import sys

VERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEAR_SPL = 12        # spline units (x1000) = ~50 m on a 4.5 km track: contact candidates
TOUCH_SPL = 4        # ~15-20 m: "right on top of"
OVERLAP_LAT = 35     # lateral (x100) difference under which two cars are on the same line
CLOSING_KMH = 12     # closing speed that makes a rear-end
STOPPED_KMH = 30
DROP_WINDOW = 12.0   # seconds after a reposition during which a contact is on Verve, not the drivers


def sev_weight(kmh):
    return 0.5 if kmh < 20 else (1.0 if kmh < 60 else 1.5)


def load(path):
    raw = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    hdr = next((r for r in raw if "hdr" in r), {})
    rows = [r for r in raw if "hdr" not in r and "ev" not in r]
    drops = {}
    for e in raw:
        if e.get("ev") == "drop":
            drops.setdefault(e["car"], set()).add(e["t"] - e["age"])
    return hdr, rows, drops


def contacts(path):
    hdr, rows, drops = load(path)
    if len(rows) < 3 or "dmg" not in rows[0]["grid"][0]:
        return hdr, []
    t0 = rows[0]["t"]
    out = []
    prev = None
    prev2 = None
    for r in rows:
        if prev is None:
            prev2, prev = prev, r
            continue
        p = {c["i"]: c for c in prev["grid"]}
        pp = {c["i"]: c for c in prev2["grid"]} if prev2 else {}
        hit = [c for c in r["grid"] if c["i"] in p and not c["pit"] and (c["dmg"] - p[c["i"]]["dmg"] >= 8 or c["susp"] - p[c["i"]]["susp"] >= 5)]
        used = set()
        for c in hit:
            if c["i"] in used:
                continue
            a = p[c["i"]]
            group = [c]
            for d in hit:
                if d["i"] != c["i"] and d["i"] not in used:
                    b = p[d["i"]]
                    if abs(((b["spline"] - a["spline"] + 500) % 1000) - 500) <= NEAR_SPL:
                        group.append(d)
            if len(group) < 2:
                # a solo damage jump might still be contact with an UNDAMAGED car right on top of it -- but
                # only if that car shows it too (a real speed drop this snapshot); a car merely passing by
                # at full speed is not contact, however close
                cur = {o["i"]: o for o in r["grid"]}
                near = [p[o["i"]] for o in r["grid"] if o["i"] != c["i"] and o["i"] in p
                        and abs(((p[o["i"]]["spline"] - a["spline"] + 500) % 1000) - 500) <= TOUCH_SPL
                        and abs(p[o["i"]]["lat"] - a["lat"]) < 60 and (p[o["i"]]["spd"] - cur[o["i"]]["spd"]) >= 15]
                if not near:
                    continue
                other = near[0]
                group = [c, {"i": other["i"], "dmg": other["dmg"], "susp": other["susp"], "spd": other["spd"]}]
                p.setdefault(other["i"], other)
            for g in group:
                used.add(g["i"])
            t = r["t"] - t0
            out.append(judge(group, p, pp, drops, t, prev["t"] - t0))
        prev2, prev = prev, r
    return hdr, out


def judge(group, p, pp, drops, t, t_prev):
    cars = [g["i"] for g in group]
    before = {i: p[i] for i in cars if i in p}
    dmg_gain = {g["i"]: max(g["dmg"] - p[g["i"]]["dmg"], 0) for g in group if g["i"] in p}
    res = {"t": round(t), "cars": cars, "damage": dmg_gain, "rule": "racing_incident", "fault": None, "conf": 0.0, "notes": []}

    # was anyone just dropped back on the track?
    for i in cars:
        if any(0 <= (t - d) <= DROP_WINDOW for d in drops.get(i, ())) or before[i].get("rec"):
            res.update(rule="dropped_into", fault="system", conf=1.0)
            res["notes"].append(f"car {i} was under recovery / just repositioned")
            return res

    if len(cars) >= 3:
        res["rule"] = "pileup"
    # pairwise: take the two most damaged (or the pair) and reason about them
    pair = sorted(cars, key=lambda i: -dmg_gain.get(i, 0))[:2]
    if len(pair) < 2:
        return res
    a, b = before[pair[0]], before[pair[1]]
    # order along the track
    d = ((b["spline"] - a["spline"] + 500) % 1000) - 500     # >0: b ahead of a
    behind, ahead = (a, b) if d > 0 else (b, a)
    closing = behind["spd"] - ahead["spd"]
    dlat = abs(behind["lat"] - ahead["lat"])
    res["notes"].append(f"behind car {behind['i']} {behind['spd']} km/h, ahead car {ahead['i']} {ahead['spd']} km/h, closing {closing:+d}, lat sep {dlat}")

    if ahead["spd"] < STOPPED_KMH and behind["spd"] > 60 and abs(ahead["lat"]) < 130:
        res.update(rule="hit_stopped", fault=behind["i"], conf=0.6)
        return res
    if closing > CLOSING_KMH and dlat < OVERLAP_LAT and abs(d) < NEAR_SPL:
        res.update(rule="rear_end", fault=behind["i"], conf=0.8 if res["rule"] != "pileup" else 0.6)
        return res
    if dlat < 70 and abs(d) <= TOUCH_SPL and pp and behind["spd"] > 40 and ahead["spd"] > 40:
        # side by side: who moved toward whom since the snapshot before?
        mv = {}
        for c in (behind, ahead):
            q = pp.get(c["i"])
            mv[c["i"]] = (c["lat"] - q["lat"]) if q else 0
        other = {behind["i"]: ahead, ahead["i"]: behind}
        toward = {i: (mv[i] > 0) == (other[i]["lat"] > before[i]["lat"]) and abs(mv[i]) >= 12 for i in mv}
        movers = [i for i in toward if toward[i]]
        if len(movers) == 1:
            res.update(rule="squeeze", fault=movers[0], conf=0.7 if res["rule"] != "pileup" else 0.5)
            res["notes"].append(f"car {movers[0]} moved {mv[movers[0]]:+d} toward the other")
            return res
    return res


def main(paths):
    if not paths:
        paths = sorted(glob.glob(os.path.join(VERVE, "diag_race_20260913_1*.jsonl")))
    total = collections.Counter()
    strikes_by_model = collections.defaultdict(float)
    contacts_by_model = collections.Counter()
    all_strikes = []
    for path in paths:
        hdr, cs = contacts(path)
        if not cs:
            continue
        models = {c["i"]: c["model"] for c in hdr.get("cars", [])}
        names = {c["i"]: c.get("driver", f"car {c['i']}") for c in hdr.get("cars", [])}
        label = os.path.basename(path)[27:60]
        per_car = collections.defaultdict(float)
        print(f"\n=== {label}: {len(cs)} contacts")
        for c in cs:
            total[c["rule"]] += 1
            if c["fault"] not in (None, "system"):
                s = c["conf"] * sev_weight(max(c["damage"].values()))
                per_car[c["fault"]] += s
                strikes_by_model[models.get(c["fault"], "?")] += s
                contacts_by_model[models.get(c["fault"], "?")] += 1
            who = ", ".join(f"{names.get(i, i)}(+{c['damage'].get(i, 0)})" for i in c["cars"])
            f = "-" if c["fault"] is None else ("Verve" if c["fault"] == "system" else names.get(c["fault"], c["fault"]))
            print(f"  {c['t']:5d}s  {c['rule']:16s} fault={f:22s} conf={c['conf']:.1f}  {who}")
            for n in c["notes"]:
                print(f"           {n}")
        if per_car:
            top = sorted(per_car.items(), key=lambda kv: -kv[1])[:3]
            print("  strikes: " + ", ".join(f"{names.get(i, i)} {s:.1f}" for i, s in top))
            all_strikes.extend(per_car.values())
    print("\n=== all races: contacts by rule")
    for k, v in total.most_common():
        print(f"  {k:16s} {v}")
    print("\n=== strikes per model (at-fault contacts, strike total)")
    for m, s in sorted(strikes_by_model.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {m:32s} {contacts_by_model[m]:3d}  {s:5.1f}")
    if all_strikes:
        srt = sorted(all_strikes)
        print(f"\nper-car strike totals across races: n={len(srt)} median={srt[len(srt)//2]:.1f} p90={srt[int(len(srt)*0.9)]:.1f} max={srt[-1]:.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])
