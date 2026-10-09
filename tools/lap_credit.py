"""Did AC credit the lap after each reposition? The scorer for R.GATE_MODE 'back' v 'twostep'.

AC credits a lap only if the car crosses split 1 after its last teleport (measured 2026-09-26: sector-1 landings
1,039/1,052, sector 2 19/1,865, last sector 0/80), so the reposition gate sends every landing past split 1 back to it.
Measured 8 Oct: that costs a median 629 m per gated drop, up to 3.2 km. GATE_MODE 'twostep' touches the car down before
split 1 for 0.25 s, then drops it where it stopped - IF AC counts that as crossing the split, the car keeps its lap AND
its road. Nobody has measured whether it does. This does.

HOW: every diag snapshot carries, per car, AC's own lap count (`lap` = car.lapCount) and Verve's independent count
(`vl`, which counts start-line crossings itself and is not fooled by a teleport). Normally they move together. If AC
drops a lap after a reposition, `vl - lap` steps up by one the next time the car crosses the line. So per reposition:
    before = vl - lap at the last snapshot before the drop
    after  = vl - lap at a snapshot taken once the car has crossed the line again (vl up by one, plus SETTLE_S)
    credited if after == before, lost if after > before, unresolved if the race ended first.

TWOSTEP MAKES TWO DROP RECORDS PER REPOSITION: the touch-down before the split, then the real drop 0.25 s later, which
voids the first. Records of one car within PAIR_S seconds are therefore ONE reposition, gated if either part was. (The
harness's drops_ok counts the voided half as a failure, so twostep's drops_ok will look terrible for a reason that has
nothing to do with the car. Do not read it.)

    python tools/lap_credit.py --files "diag_race_*gatemode_*.jsonl" --labels gm_back,gm_two
"""
import argparse
import glob
import io
import json
import os
import statistics
import sys

PAIR_S = 2          # drop records of one car this close together are one reposition (twostep's two halves)
SETTLE_S = 10       # after the next line crossing, wait this long for AC's count to catch up before reading it
HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
TRACK_LEN = {"imola": 4909.0, "spa": 7004.0, "monza": 5793.0, "ks_barcelona": 4655.0}


def label_of(path):
    stem = os.path.basename(path).replace("diag_race_", "").replace(".jsonl", "")
    rest = "_".join(stem.split("_")[2:])
    for t in sorted(TRACK_LEN, key=len, reverse=True):
        if rest.startswith(t + "_"):
            rest = rest[len(t) + 1:]
            break
    if rest.startswith("layout_"):
        bits = rest.split("_", 2)
        rest = bits[2] if len(bits) > 2 else rest
    return rest


def track_of(path):
    b = os.path.basename(path)
    return next((t for t in sorted(TRACK_LEN, key=len, reverse=True) if "_%s_" % t in b), None)


def score(path):
    snaps = {}      # car -> [(t, lap, vl)]
    drops = {}      # car -> [(t0, g, gs, spline)]
    for line in io.open(path, encoding="utf-8", errors="replace"):
        if '"grid"' in line:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("t")
            for c in o.get("grid", []):
                if c.get("lap") is None or c.get("vl") is None or c.get("vl", -1) < 0:
                    continue
                snaps.setdefault(c["i"], []).append((t, c["lap"], c["vl"]))
        elif '"ev":"drop"' in line:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("age") != 0:
                continue
            drops.setdefault(o["car"], []).append((o["t"], o.get("g"), o.get("gs", -1), o.get("spline")))
    out = []
    tlen = TRACK_LEN.get(track_of(path))
    for car, ds in drops.items():
        if car == 0:
            continue                                   # the harness autopilot
        ds.sort()
        events = []                                    # merge twostep's two halves
        for d in ds:
            if events and d[0] - events[-1]["t1"] <= PAIR_S:
                e = events[-1]
                e["t1"] = d[0]; e["gated"] = e["gated"] or d[1] == 1
                if d[2] is not None and d[2] >= 0: e["gs"] = d[2]
                e["land"] = d[3]                       # the LAST placement is where the car actually races from
                e["parts"] += 1
            else:
                events.append({"t0": d[0], "t1": d[0], "gated": d[1] == 1, "gs": d[2] if d[2] is not None and d[2] >= 0 else None,
                               "land": d[3], "parts": 1})
        ss = sorted(snaps.get(car, []))
        for e in events:
            before = [s for s in ss if s[0] < e["t0"]]
            if not before:
                e["verdict"] = "unresolved"; out.append(e); continue
            b = before[-1]; d0 = b[2] - b[1]
            # once Verve's own count has advanced past its value at the drop, wait SETTLE_S, then read
            cross = next((s for s in ss if s[0] > e["t1"] and s[2] > b[2]), None)
            if cross is None:
                e["verdict"] = "unresolved"; out.append(e); continue
            later = next((s for s in ss if s[0] >= cross[0] + SETTLE_S), None)
            if later is None:
                e["verdict"] = "unresolved"; out.append(e); continue
            d1 = later[2] - later[1]
            e["verdict"] = "credited" if d1 <= d0 else "LOST"
            # metres the car lost on the road: from where it stopped (gs) to where it finally races from (land)
            if e["gs"] is not None and e["land"] is not None and tlen:
                back = (e["gs"] - e["land"]) / 1000.0
                if back < -0.5: back += 1.0
                e["metres_back"] = max(0.0, back) * tlen
            out.append(e)
    return out


def summarise(name, evs):
    gated = [e for e in evs if e["gated"]]
    res = [e for e in gated if e["verdict"] != "unresolved"]
    cred = sum(1 for e in res if e["verdict"] == "credited")
    mb = [e["metres_back"] for e in gated if "metres_back" in e]
    two = sum(1 for e in gated if e["parts"] >= 2)
    print("  %-14s repositions %3d | gated %3d (twostep-paired %d) | lap CREDITED %d of %d resolved%s | metres lost on "
          "the road: median %s, max %s"
          % (name, len(evs), len(gated), two, cred, len(res),
             (" (%.0f %%)" % (100.0 * cred / len(res))) if res else "",
             ("%.0f" % statistics.median(mb)) if mb else "-", ("%.0f" % max(mb)) if mb else "-"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--labels", default=None, help="comma-separated label prefixes = arms")
    a = ap.parse_args()
    pats = a.files or [os.path.join(VERVE, "diag_race_*.jsonl")]
    files = sorted({f for p in pats for f in (glob.glob(p) if any(c in p for c in "*?[") else [p])})
    if not files:
        print("no diag files matched", file=sys.stderr); return 1
    per = [(label_of(f), score(f)) for f in files]
    print("LAP CREDIT AFTER REPOSITIONS (AC's lap count against Verve's own, per reposition)\n")
    if a.labels:
        for arm in [s.strip() for s in a.labels.split(",") if s.strip()]:
            summarise(arm, [e for lab, evs in per if lab.startswith(arm) for e in evs])
    else:
        for lab, evs in per:
            if evs: summarise(lab[:14], evs)
        summarise("ALL", [e for _, evs in per for e in evs])
    return 0


if __name__ == "__main__":
    sys.exit(main())
