"""Do cars Verve parks STAY parked? (read-only; the 0.15 parked-car hold, Recovery.holdParked)

    python tools/park_check.py diag_race_*_park15_*.jsonl

From the 8 s diag snapshots: every car with park=1, why (pw), when, and what it did afterwards. ESCAPE = after the park the
car was seen out of the pit lane above 20 km/h, or completed another lap. AC retiring the car (ret) ends the watch.
"""
import glob
import json
import sys


def check(path):
    first, after = {}, {}
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        g = d.get("grid")
        if not isinstance(g, list):
            continue
        t = d.get("t") or 0
        for c in g:
            i = c.get("i")
            if i in first:
                a = after[i]
                if c.get("ret"):
                    a["ret"] = True
                    continue
                if a.get("ret"):
                    continue
                a["n"] += 1
                if not c.get("pit") and (c.get("spd") or 0) > 20:
                    a["out"] = max(a.get("out", 0), c.get("spd") or 0)
                    a.setdefault("out_t", t - first[i]["t"])
                if (c.get("lap") or 0) > first[i]["lap"]:
                    a["laps"] = (c.get("lap") or 0) - first[i]["lap"]
            elif c.get("park"):
                first[i] = {"t": t, "lap": c.get("lap") or 0, "why": c.get("pw") or "?", "pit": c.get("pit"), "spd": c.get("spd")}
                after[i] = {"n": 0}
    bad = 0
    for i in sorted(first):
        f, a = first[i], after[i]
        esc = a.get("out") or a.get("laps")
        bad += 1 if esc else 0
        print("  car %2d parked (%s) lap %d, pit %s, %d km/h | then %d snapshots%s%s%s  %s" % (
            i, f["why"], f["lap"], f["pit"], f["spd"] or 0, a["n"], ", AC retired it" if a.get("ret") else "",
            (", out of the pits at %d km/h after %d s" % (a["out"], a["out_t"])) if a.get("out") else "",
            (", +%d laps" % a["laps"]) if a.get("laps") else "", "ESCAPE" if esc else "ok"))
    return len(first), bad


def main():
    files = []
    for p in sys.argv[1:] or ["diag_race_*park15*.jsonl"]:
        files += sorted(glob.glob(p))
    tot = bad = 0
    for p in files:
        print(p)
        n, b = check(p)
        if not n:
            print("  no car was parked")
        tot, bad = tot + n, bad + b
    print("\n%d parked car(s), %d escape(s) in %d race(s)" % (tot, bad, len(files)))


if __name__ == "__main__":
    main()
