"""Opening-lap contact traces from a diag file: what the follower was doing in the 4 s before it took damage.

    python tools/contact_trace.py diag_race_*.jsonl [--all]

Each {"ev":"contact"} line carries a 4 Hz ring of [t, ahead, gap m, dLat x100, spd, aheadSpd, myBrake, myGas,
aheadBrake, convoyThr, guard]. Prints one line per contact and a tally of the closing pattern:
  braking   - the car ahead was on the brakes while the gap closed (a brake-zone hit)
  exit      - the car ahead was accelerating / off the brakes while the gap closed (a corner-exit concertina)
  line      - the two were more than half a lane apart at the end (a side-by-side or lane-change hit)
  none      - the gap was not closing (hit from behind, or by a third car)
  side      - (v2 traces) no car ahead on my line but one within 6 m alongside / behind: a side-by-side touch
"""
import json
import sys
from collections import Counter


def classify(ring):
    # a ring under 3 rows (4 Hz) means the previous contact write was under ~0.75 s ago: this is a CHAIN hit - the car
    # was hit again (or hit the next car) before the trace could refill - not "following too close". It was reported as
    # "chain" until 2026-09-24 and read as tailgating; at Baku chains are 36-45% of contacts in the narrow bins.
    if len(ring) < 3:
        return "chain", {}
    last = ring[-1]
    tail = ring[-6:]                                     # last ~1.5 s
    # v2 rows carry the nearest car too: [.., near, nearDist, nearLong, nearLat]. No car ahead on my line (ahead == -1)
    # but a car close alongside -> a side contact
    if len(last) >= 15 and last[1] < 0:
        if last[11] >= 0 and last[12] <= 6:
            side = "alongside" if abs(last[13]) < 4 else ("behind" if last[13] < 0 else "ahead-offline")
            return "side", {"near": last[11], "dist": f"{tail[0][12]}->{last[12]} m", "long": last[13], "dLat": round(abs(last[14]) / 100.0, 2), "where": side}
        return "none", {"near": last[11], "dist": last[12]}
    gap0, gap1 = tail[0][2], last[2]
    closing = gap0 - gap1 >= 2
    ahead_brake = sum(1 for r in tail if r[8] >= 15) >= len(tail) // 2
    dlat = abs(last[3]) / 100.0
    convoy = any(r[9] for r in tail)
    guard = any(r[10] for r in tail)
    info = {"gap": f"{gap0}->{gap1} m", "spd": f"{tail[0][4]}->{last[4]}", "ahead": f"{tail[0][5]}->{last[5]}",
            "myBrake": last[6], "aheadBrake": max(r[8] for r in tail), "dLat": round(dlat, 2), "convoy": int(convoy), "guard": int(guard)}
    if dlat > 0.15:
        return "line", info
    if not closing:
        return "none", info
    return ("braking" if ahead_brake else "exit"), info


def main():
    f = sys.argv[1]
    show_all = "--all" in sys.argv
    tally, n = Counter(), 0
    flags = Counter()
    for line in open(f, encoding="utf-8"):
        if '"ev":"contact"' not in line:
            continue
        e = json.loads(line)
        if e.get("lap", 0) > 1 and not show_all:
            continue
        kind, info = classify(e["ring"])
        tally[kind] += 1; n += 1
        flags["convoy"] += info.get("convoy", 0); flags["guard"] += info.get("guard", 0)
        print(f"car {e['car']:2d} lap {e['lap']} spline {e['spline'] / 1000:.3f} dmg {e['dmg']:3d}  {kind:8s} "
              + " ".join(f"{k}={v}" for k, v in info.items()))
    print(f"\n{n} contacts: " + ", ".join(f"{k} {v}" for k, v in tally.most_common())
          + f" | convoy active in {flags['convoy']}, guard active in {flags['guard']}")


if __name__ == "__main__":
    main()
