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
    return hdr, rows, drops


def metrics(path):
    hdr, rows, drops = load(path)
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
        "crash_repairs": last.get("crashRepairs", 0),
        "drops": last.get("dropN", 0),
        "drops_ok": last.get("dropOK", 0),
        "drops_off": bool(last.get("dropsOff", False)),
        "frozen_cars": frozen,
        "longest_stationary_s": longest,
        "laptime_median_spread_s": (max(meds) - min(meds)) if len(meds) >= 2 else 0,
        "laptime_median_s": statistics.median(meds) if meds else 0,
    }
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        m = metrics(p)
        w = max(len(k) for k in m)
        for k, v in m.items():
            print(f"{k:<{w}}  {v}")
        print()
