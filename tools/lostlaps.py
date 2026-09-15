"""Lost laps after a Verve reposition (diag files). For every line crossing (spline wraps), was car.lapCount
incremented by the next snapshot or the one after (AC's timing line sits a little past spline 0)? Split by
whether the car was dropped in the last 150 s, with the drop's spline -- and the no-drop control group.

    python tools/lostlaps.py diag_race_*.jsonl
"""
import json, sys


def analyse(f):
    rows = []
    for l in open(f, encoding="utf-8"):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    snaps = [r for r in rows if "grid" in r]
    drops = [r for r in rows if r.get("ev") == "drop" and r["age"] == 0]
    hdr = next((r for r in rows if "hdr" in r), {})
    dropT = {}
    for d in drops:
        dropT.setdefault(d["car"], []).append((d["t"], d["spline"]))
    res = {"drop": [0, 0], "ctl": [0, 0]}
    detail = []
    for k in range(len(snaps) - 2):
        s0, s1, s2 = snaps[k], snaps[k + 1], snaps[k + 2]
        for a in s0["grid"]:
            c = next(x for x in s1["grid"] if x["i"] == a["i"])
            c2 = next(x for x in s2["grid"] if x["i"] == a["i"])
            if c["spline"] < a["spline"] - 500 and c["spd"] > 10 and not c["pit"] and not a["pit"]:
                rec = [(t, sp) for (t, sp) in dropT.get(a["i"], []) if 0 <= s1["t"] - t < 150]
                inc = c["lap"] > a["lap"] or c2["lap"] > a["lap"]
                key = "drop" if rec else "ctl"
                res[key][0 if inc else 1] += 1
                if rec:
                    detail.append((a["i"], rec[-1][1], s1["t"] - rec[-1][0], "OK" if inc else "LOST"))
    name = f.replace("\\", "/").split("/")[-1]
    print("== %s  splits=%s  gateMoves=%s" % (name, hdr.get("splits"), snaps[-1].get("gateN")))
    print("   first crossing after a drop: counted %d, lost %d   |   no recent drop: counted %d, lost %d"
          % (res["drop"][0], res["drop"][1], res["ctl"][0], res["ctl"][1]))
    for d in sorted(detail, key=lambda x: x[1]):
        print("   car %2d dropped at spline %3d, line %3d s later: %s" % d)
    return res


if __name__ == "__main__":
    for f in sys.argv[1:]:
        analyse(f)
