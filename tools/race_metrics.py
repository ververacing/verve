"""Score one Verve diagnostics file (diag_race_*.jsonl) into a flat dict of race-quality metrics.

Used by tools/harness.py; also handy on its own:  python tools/race_metrics.py <file.jsonl>
The metrics are the ones that map onto the project goal -- a field that stays consistent and finishes
close together -- plus the recovery health numbers (repositions, frozen cars) that decide whether it can.
"""
import json
import statistics
import sys
import collections


def load(path):
    raw = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    hdr = next((r for r in raw if "hdr" in r), None)
    rows = [r for r in raw if "hdr" not in r and "ev" not in r]
    drops = [r for r in raw if r.get("ev") == "drop"]
    contacts = [r for r in raw if r.get("ev") == "contact"]     # diag's contact ring (damage jump OR collision event, dmg = severity)
    return hdr, rows, drops, contacts


def metrics(path):
    hdr, rows, drops, contacts = load(path)
    if len(rows) < 3:
        return {"file": path, "error": "too few frames"}
    t0 = rows[0]["t"]
    last = rows[-1]
    ll = last["leaderLap"]
    n = rows[0]["cars"]
    has = "dmg" in rows[0]["grid"][0]

    # incidents: damage/suspension jumps between snapshots (AI cars only)
    prev, inc, low = {}, [], 0
    for r in rows:
        for c in r["grid"]:
            p = prev.get(c["i"])
            if has and p and c["i"] != 0 and not c["pit"] and (c["dmg"] - p["dmg"] >= 8 or c["susp"] - p["susp"] >= 5):
                inc.append(p["lap"])
                if p["spd"] < 40:
                    low += 1
            prev[c["i"]] = c
    # damage OFF in the launcher (no car ever shows damage): incidents come from the contact events instead
    # (written on a collision event since 2026-09-19, severity = speed lost; AI cars, the same 8 threshold)
    damage_seen = has and any(c["dmg"] > 0 for r in rows for c in r["grid"])
    if not damage_seen and contacts:
        inc = [e.get("lap", 0) for e in contacts if e.get("car", 0) != 0 and e.get("dmg", 0) >= 8]
        low = 0

    # stationary episodes >= 40 s (a "frozen" car)
    frozen, longest = 0, 0
    for ci in range(n):
        run = 0
        for r in rows:
            c = next(x for x in r["grid"] if x["i"] == ci)
            if c["spd"] < 3 and not c["pit"] and (r["t"] - t0) > 30:
                run += 8
            else:
                if run >= 40:
                    frozen += 1
                longest = max(longest, run)
                run = 0
        if run >= 40:
            frozen += 1
        longest = max(longest, run)

    # lap-time medians of cars that were still going at the end
    meds = []
    for ci in range(n):
        times, lastT, lastLap = [], None, None
        for r in rows:
            c = next(x for x in r["grid"] if x["i"] == ci)
            if lastLap is not None and c["lap"] > lastLap and lastT is not None:
                times.append(r["t"] - lastT)
            if lastLap is None or c["lap"] > lastLap:
                lastT, lastLap = r["t"], c["lap"]
        fin = next(x for x in last["grid"] if x["i"] == ci)
        if len(times) >= 3 and not fin.get("park") and not fin["ret"]:
            meds.append(statistics.median(times))

    classified = [c for c in last["grid"] if not c["ret"] and not c.get("park")]
    out = {
        "file": path.split("/")[-1].split("\\")[-1],
        "label": (hdr or {}).get("label"),
        "track": (hdr or {}).get("track"),
        "duration_s": last["t"] - t0,
        "leader_laps": ll,
        "cars": n,
        "running_at_end": len(classified),
        "within_1_lap": sum(1 for c in classified if c["lap"] >= ll - 1),
        "within_2_laps": sum(1 for c in classified if c["lap"] >= ll - 2),
        "retired_or_parked": n - len(classified),
        "incidents": len(inc),
        "incidents_lap0_1": sum(1 for l in inc if l <= 1),
        "incidents_low_speed": low,
        "contact_events": len(contacts),
        "damage_on": bool(damage_seen),
        "crash_repairs": last.get("crashRepairs", 0),
        "drops": last.get("dropN", 0),
        "drops_ok": last.get("dropOK", 0),
        "drops_off": bool(last.get("dropsOff", False)),
        "frozen_cars": frozen,
        "longest_stationary_s": longest,
        "laptime_median_spread_s": (max(meds) - min(meds)) if len(meds) >= 2 else 0,
        "laptime_median_s": statistics.median(meds) if meds else 0,
    }
    # yield trains: snapshots where 3+ cars were yielding at once (a conga line behind a lapper)
    trains = sum(1 for r in rows if sum(1 for c in r["grid"] if c.get("yl")) >= 3)
    out["yield_train_snaps"] = trains
    # planned manoeuvres (diag >= 2026-09-14 "mvN"/"mvOK" session tallies from lib/strategy.lua)
    out["gate_moves"] = last.get("gateN", 0)
    out["mv_attempts"] = last.get("mvN", 0)
    out["mv_ok"] = last.get("mvOK", 0)
    out["mv_types"] = last.get("mvT", "")
    out.update(tyre_views(rows, n))
    out.update(lapping_views(rows, n))
    out.update(reality_score(out, hdr))
    return out


# ---------------------------------------------------------------------------------------------
# LAPPING: a car on a higher lap closing on a backmarker -- how long to get by, and how much speed it loses queued
# behind it (vs its own clear-road speed at that part of the track). Conga lines show up in yield_train_snaps.
def lapping_views(rows, n):
    if not rows:
        return {}
    BIN = 0.02
    clear = {}     # (car, bin) -> [speeds] with no car within 0.03 ahead
    for r in rows:
        g = r["grid"]
        for c in g:
            if c["spd"] < 30 or c["pit"] or c["ret"]:
                continue
            sp = c["spline"] / 1000.0
            others = [((o["spline"] / 1000.0 - sp) % 1.0) for o in g if o["i"] != c["i"] and not o["ret"] and o["spd"] > 5]
            ahead = min(others) if others else 1.0     # (everyone else stopped - a point-to-point finish - crashed the harness, Trento 2026-09-20)
            if ahead > 0.03:
                clear.setdefault((c["i"], int(sp / BIN)), []).append(c["spd"])
    losses, episodes, open_ep = [], [], {}
    for r in rows:
        g = r["grid"]
        by = {c["i"]: c for c in g}
        # open episodes first: resolved (B now behind L), abandoned (L fell back, or either car pitted/retired)
        for key in list(open_ep):
            L, B = by.get(key[0]), by.get(key[1])
            if not L or not B or L["pit"] or L["ret"] or B["pit"] or B["ret"]:
                open_ep.pop(key); continue
            d = (B["spline"] / 1000.0 - L["spline"] / 1000.0) % 1.0
            if d > 0.5:
                episodes.append(r["t"] - open_ep.pop(key))          # past it: the pass is done
            elif d >= 0.02:
                open_ep.pop(key)                                     # dropped back out of range: not a pass
        for L in g:
            if L["spd"] < 30 or L["pit"] or L["ret"]:
                continue
            spL = L["spline"] / 1000.0
            for B in g:
                if B["i"] == L["i"] or B["ret"] or B["pit"] or B["lap"] >= L["lap"] or B["spd"] < 20:
                    continue
                d = (B["spline"] / 1000.0 - spL) % 1.0
                key = (L["i"], B["i"])
                if 0 < d < 0.02:
                    if key not in open_ep:
                        open_ep[key] = r["t"]
                    ref = clear.get((L["i"], int(spL / BIN)))
                    if ref and len(ref) >= 2:
                        losses.append(statistics.median(ref) - L["spd"])
    return {
        "lap_pass_n": len(episodes),
        "lap_pass_median_s": round(statistics.median(episodes), 1) if episodes else 0,
        "lap_pass_slow_n": sum(1 for e in episodes if e > 40),
        "lapper_speed_loss_kmh": round(statistics.median(losses), 1) if losses else 0,
        "lapper_queued_snaps": len(losses),
    }


# ---------------------------------------------------------------------------------------------
# TYRE HEALTH (diag >= 2026-09-14 carries "wear" 0..100, "cmp", "fuel" per car): do incidents cluster on worn
# tyres / late in a stint, and does the AI pit sensibly?
def tyre_views(rows, n):
    if not rows or "wear" not in rows[0]["grid"][0]:
        return {}
    inc_by_wear = collections.Counter()     # wear bucket (0-25, 25-50, 50-75, 75+) -> incidents
    exposure = collections.Counter()        # bucket -> car-snapshots (for a rate)
    prev = {}
    pits, stint_laps, max_wear = 0, [], 0
    stint_start = {}
    for r in rows:
        mass_pit = sum(1 for c in r["grid"] if c["pit"]) > len(r["grid"]) // 2   # session end teleports everyone to the pits
        for c in r["grid"]:
            i = c["i"]
            b = min(3, int(c.get("wear", 0) // 25))
            exposure[b] += 1
            p = prev.get(i)
            if p is not None and c["dmg"] - p["dmg"] >= 8 and not c["pit"]:
                inc_by_wear[b] += 1
            if p is not None and c["pit"] and not p["pit"] and c["lap"] >= 1 and not mass_pit:
                pits += 1
                stint_laps.append(c["lap"] - stint_start.get(i, 0)); stint_start[i] = c["lap"]
            max_wear = max(max_wear, c.get("wear", 0))
            prev[i] = c
    rate = {b: (inc_by_wear[b] / exposure[b] * 1000 if exposure[b] else 0) for b in range(4)}
    return {
        "tyre_max_wear_pct": max_wear,
        "pit_stops": pits,
        "stint_laps_median": statistics.median(stint_laps) if stint_laps else 0,
        "inc_per_1k_snaps_wear0_25": round(rate[0], 2), "inc_per_1k_snaps_wear25_50": round(rate[1], 2),
        "inc_per_1k_snaps_wear50_75": round(rate[2], 2), "inc_per_1k_snaps_wear75plus": round(rate[3], 2),
    }


# ---------------------------------------------------------------------------------------------
# REALITY BENCHMARKS: what real racing in this class looks like, so a run can be judged against the world and
# not only against the previous run. Rough, published-average figures; refine as better sources come in.
#   spread_pct  : (slowest regular finisher - fastest) median race lap, % of fastest
#   dnf_pct     : share of starters not classified
#   inc_per_car_100laps : damage-taking incidents per car per 100 laps (contact + solo)
#   lead_changes_per_100laps
REALITY = {
    "formula":   {"spread_pct": 3.0,  "dnf_pct": 12, "inc_per_car_100laps": 6,  "lead_changes_per_100laps": 4},
    "formula_jr":{"spread_pct": 3.5,  "dnf_pct": 15, "inc_per_car_100laps": 10, "lead_changes_per_100laps": 6},
    "gt":        {"spread_pct": 2.5,  "dnf_pct": 10, "inc_per_car_100laps": 8,  "lead_changes_per_100laps": 6},
    "prototype": {"spread_pct": 2.0,  "dnf_pct": 12, "inc_per_car_100laps": 6,  "lead_changes_per_100laps": 4},
    "touring":   {"spread_pct": 3.0,  "dnf_pct": 8,  "inc_per_car_100laps": 15, "lead_changes_per_100laps": 8},
    "road":      {"spread_pct": 6.0,  "dnf_pct": 6,  "inc_per_car_100laps": 12, "lead_changes_per_100laps": 6},
    "vintage":   {"spread_pct": 5.0,  "dnf_pct": 25, "inc_per_car_100laps": 10, "lead_changes_per_100laps": 8},
    "kart":      {"spread_pct": 4.0,  "dnf_pct": 5,  "inc_per_car_100laps": 25, "lead_changes_per_100laps": 15},
    "nascar":    {"spread_pct": 1.5,  "dnf_pct": 10, "inc_per_car_100laps": 8,  "lead_changes_per_100laps": 30},
    "default":   {"spread_pct": 3.5,  "dnf_pct": 10, "inc_per_car_100laps": 10, "lead_changes_per_100laps": 6},
}
MODEL_CLASS_HINTS = [("gt3", "gt"), ("gt2", "gt"), ("gte", "gt"), ("ts040", "prototype"), ("919", "prototype"), ("r18", "prototype"),
                     ("962", "prototype"), ("787", "prototype"), ("tcr", "touring"), ("cup", "touring"), ("dtm", "touring"), ("evo2", "touring"), ("155", "touring"),
                     ("f1", "formula"), ("formula_hybrid", "formula"), ("sf70", "formula"), ("w09", "formula"), ("renault_r2", "formula"), ("redbull", "formula"),
                     ("fw26", "formula"), ("tatuus", "formula_jr"), ("formularenault", "formula_jr"), ("gokart", "kart"), ("kart", "kart"),
                     ("312_67", "vintage"), ("250f", "vintage"), ("gt40", "vintage"), ("330_p4", "vintage"), ("lotus_49", "vintage")]


def class_of_models(hdr):
    if not hdr:
        return "default"
    votes = collections.Counter()
    for c in hdr.get("cars", []):
        m = (c.get("model") or "").lower()
        for hint, cls in MODEL_CLASS_HINTS:
            if hint in m:
                votes[cls] += 1
                break
        else:
            votes["road"] += 1
    return votes.most_common(1)[0][0] if votes else "default"


def reality_score(out, hdr):
    cls = class_of_models(hdr)
    ref = REALITY.get(cls, REALITY["default"])
    laps = max(1, out.get("leader_laps", 0))
    n = max(1, out.get("cars", 1))
    spread = 0.0
    if out.get("laptime_median_s"):
        spread = out["laptime_median_spread_s"] / out["laptime_median_s"] * 100
    dnf = out.get("retired_or_parked", 0) / n * 100
    inc = out.get("incidents", 0) / n / laps * 100
    def ratio(v, r):
        return round(v / r, 2) if r else 0
    return {
        "reality_class": cls,
        "spread_pct": round(spread, 1), "spread_vs_real": ratio(spread, ref["spread_pct"]),
        "dnf_pct": round(dnf, 1), "dnf_vs_real": ratio(dnf, ref["dnf_pct"]),
        "inc_per_car_100laps": round(inc, 1), "inc_vs_real": ratio(inc, ref["inc_per_car_100laps"]),
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        m = metrics(p)
        w = max(len(k) for k in m)
        for k, v in m.items():
            print(f"{k:<{w}}  {v}")
        print()
