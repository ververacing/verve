"""How much real passing happens, in a figure comparable to published real-world numbers.

    python tools/settled_pass.py --labels ver_dev_spa12_1,ver_dev_spa12_2 --name "Verve ON"
    python tools/settled_pass.py --arms "Verve OFF=vok_spa12_,Verve ON=ver_dev_spa12_"   # prefix match
    python tools/settled_pass.py --selftest

WHY THIS EXISTS. The owner asked how our formula racing compares with F1 25 and with real F1. Real F1 is the firmer
anchor: 39 overtakes per race in 2023 and 32.8 in 2024, over ~57-race-lap grands prix, so about 0.58-0.68 passes per
race lap. Getting a number of ours that can sit beside that took three attempts, and each failure is encoded here as
a rule, because each one produced a confident wrong answer first.

TRAP 1 - THE LAP FIELD THAT ISN'T THERE. An `overtake` event has no `lap`. Reading `o.get('lap') or 1` makes every
event lap 1, which reported "100% of overtakes happen on lap 1" for a 53-lap race. A missing field read through `or`
is not a default, it is a fabrication.

TRAP 2 - RAW EVENTS ARE NOT PASSES. Two cars swapping back and forth down a straight emit an event every swap. Counting
events counts the argument, not the result. A PASS here is an overtake whose new order still holds HOLD seconds later;
the rest is churn, and churn is 20-50% of events in every arm measured so far, on both CSP builds.

TRAP 3 - THE LAP-1 BOUND THAT ONLY ONE BUILD CAN SEE. The obvious way to exclude the start is "everything before the
first `lap` event". But the first-lap event was ADDED in dev016: released feed.lua skips lap 1 because it is not a
clean lap time. On released feeds the bound therefore never fires, lap 1 silently folds into the rest of the race,
and the arm reports 0 lap-1 passes beside 60 for dev016 on the identical cell. That 0 is what caught it.
So lap 1 is bounded from the 1 Hz STATE stream instead: a car's `lap` counter starts at 0 and ticks to 1 when it
completes its first lap. Every build writes it, it is per car, and it needs no events at all. ANY per-race boundary
taken from an event type is suspect for exactly this reason - events are a contract that changed.

WHAT IS EXCLUDED, so the figure means the same thing F1's does: lap 1 (a standing start is not overtaking), passes on
cars being lapped, passes completed while either car is in the pits or on a car that retires inside the hold window.
Each exclusion is counted and printed - a silent filter is how a denominator goes wrong unnoticed.

The headline is passes per RACE LAP (leader laps minus lap 1), which is the shape F1 quotes. Per car-lap is printed
too, because that is the one that is comparable across different grid sizes.
"""
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results", "results.csv")
FEEDDIR = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")

HOLD = 30.0          # seconds the new order must survive for a swap to count as a pass
REAL_F1_LO, REAL_F1_HI = 0.58, 0.68      # 39 passes / 57 laps (2023) and 32.8 / 57 (2024)


def feed_for(label, rows=None, names=None):
    """-> feed path for a harness label, matched on the timestamp the harness puts in the diag filename."""
    if rows is None:
        with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
            rows = {r["label"]: r for r in csv.DictReader(fh) if r.get("label")}
    if names is None:
        names = os.listdir(FEEDDIR)
    m = re.search(r"(\d{8}_\d{6})", (rows.get(label) or {}).get("file") or "")
    if not m:
        return None
    hit = next((f for f in names if f.startswith(m.group(1))), None)
    return os.path.join(FEEDDIR, hit) if hit else None


def read_feed(path):
    """-> (header, states, overtakes). states is [(t, {car: {...}}), ...] in file order."""
    header, states, overs = {}, [], []
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"type"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            k = j.get("type")
            if k == "header":
                header = j
            elif k == "state":
                cars = {c.get("i"): c for c in (j.get("cars") or ()) if c.get("i") is not None}
                if cars:
                    states.append((j.get("t"), cars))
            elif k == "overtake":
                overs.append(j)
    return header, states, overs


def lap1_ends(states):
    """-> {car: time its first lap ended}, from the state stream only.

    AC's lap counter is COMPLETED laps, so it reads 0 for the whole of racing lap 1 and ticks to 1 at the line. This
    is the build-independent bound of trap 3: no event type is involved, so a change to the event contract cannot
    silently move it. A car that never completes a lap gets no entry, which is correct - it has no racing laps.
    """
    first, out = {}, {}
    for t, cars in states:
        for i, c in cars.items():
            lp = c.get("lap")
            if lp is None:
                continue
            if i not in first:
                first[i] = lp
            elif i not in out and lp > first[i]:
                out[i] = t
    return out


def state_at(states, t):
    """-> the first state at or after t, else the last one. Feeds are 1 Hz so this is within a second."""
    for st in states:
        if st[0] is not None and st[0] >= t:
            return st[1]
    return states[-1][1] if states else {}


def classify(header, states, overs, hold=HOLD):
    """-> (counts, passes). One verdict per overtake event, with every exclusion counted rather than dropped."""
    ends = lap1_ends(states)
    c = dict(events=len(overs), lap1=0, churn=0, pitted=0, lapped=0, retired=0, passes=0, no_window=0)
    kept = []
    tlast = max((t for t, _ in states if t is not None), default=0.0)
    for o in overs:
        t, a, b = o.get("t"), o.get("car"), o.get("over")
        if t is None or a is None or b is None:
            continue
        # lap 1, bounded per car by the overtaker's own first-lap completion
        e = ends.get(a)
        if e is None or t <= e:
            c["lap1"] += 1
            continue
        now = state_at(states, t)
        ca, cb = now.get(a) or {}, now.get(b) or {}
        # being lapped is not racing for position, and F1's count excludes it
        if ca.get("lap") is not None and cb.get("lap") is not None and ca["lap"] != cb["lap"]:
            c["lapped"] += 1
            continue
        if ca.get("pit") or cb.get("pit"):
            c["pitted"] += 1
            continue
        if t + hold > tlast:                      # no room left to judge whether it held
            c["no_window"] += 1
            continue
        then = state_at(states, t + hold)
        la, lb = then.get(a) or {}, then.get(b) or {}
        if lb.get("ret") or la.get("ret"):
            c["retired"] += 1
            continue
        pa, pb = la.get("pos"), lb.get("pos")
        if pa is None or pb is None:
            c["retired"] += 1
            continue
        if pa < pb:                               # still ahead one hold later: a real pass
            c["passes"] += 1
            kept.append(o)
        else:
            c["churn"] += 1
    return c, kept


def pace_by_car(path_or_laps):
    """-> {car: median lap_ms} from `lap` events, which carry AC's own millisecond lap time.

    Deliberately NOT results.csv's laptime_median_s: that column is derived from 8-second diag snapshots, so every
    value it can produce is a multiple of 4 (see tools/metric_sanity.py). Cut laps are dropped - a lap gained by
    leaving the track is not a pace sample.
    """
    laps = path_or_laps
    if isinstance(path_or_laps, str):
        laps = []
        with io.open(path_or_laps, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"lap"' not in ln:
                    continue
                try:
                    j = json.loads(ln)
                except ValueError:
                    continue
                if j.get("type") == "lap":
                    laps.append(j)
    per = {}
    for e in laps:
        ms, cuts, i = e.get("lap_ms"), e.get("cuts"), e.get("car")
        if i is None or not ms or (cuts or 0) > 0 or e.get("first"):
            continue
        per.setdefault(i, []).append(ms)
    return {i: sorted(v)[len(v) // 2] for i, v in per.items() if len(v) >= 3}


def _rank(d):
    """-> {key: rank}, 1 = smallest value. Ties take their average rank."""
    items = sorted(d.items(), key=lambda kv: kv[1])
    out, n = {}, len(items)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


def grid_order(states, laps):
    """-> (rho, n) Spearman correlation between STARTING position and PACE rank.

    THE GATE ON ANY COMPARISON WITH REAL RACING. Real grids are set by qualifying, so the fast cars start at the
    front and a pass has to be earned against a car of similar pace. Several of our cells deliberately INVERT that -
    `0,1..3=arch_rookie` at the front and `12..17=arch_veteran` at the back - because an inverted grid stresses the
    passing code, which is what a regression suite wants. It also manufactures overtakes by construction, so a pass
    count from an inverted grid cannot be set beside a real-world one. That nearly went out as "21.8x real F1".

    rho near +1: start order matches pace order, i.e. qualifying-like and comparable.
    rho near -1: pace inverted, fast cars at the back. A high pass count here is the DESIGN, not a finding.
    Measured from the race itself rather than from the queue file, because the profiles argument is not recorded in
    results.csv for most rows and a config can be edited after the fact - the race cannot.
    """
    start = {}
    for _, cars in states:
        for i, c in cars.items():
            if i not in start and c.get("pos") is not None:
                start[i] = c["pos"]
        if start:
            break
    pace = pace_by_car(laps)
    common = sorted(set(start) & set(pace))
    if len(common) < 5:
        return None, len(common)
    rs = _rank({i: start[i] for i in common})
    rp = _rank({i: pace[i] for i in common})
    n = len(common)
    mx = sum(rs[i] for i in common) / n
    my = sum(rp[i] for i in common) / n
    num = sum((rs[i] - mx) * (rp[i] - my) for i in common)
    dx = sum((rs[i] - mx) ** 2 for i in common) ** 0.5
    dy = sum((rp[i] - my) ** 2 for i in common) ** 0.5
    return (num / (dx * dy) if dx and dy else None), n


def denominators(header, states):
    """-> (race laps excluding lap 1, car-laps excluding lap 1). The figure is only as good as this."""
    ends = lap1_ends(states)
    # Each car's MAX lap over the WHOLE stream, not its entry in the final state. Reading the last state alone was
    # wrong twice over: a car that retired on lap 4 is absent from it and silently contributed zero car-laps, and a
    # feed whose final line is truncated or holds a single car collapsed the denominator entirely - which printed a
    # per-car-lap rate identical to the per-race-lap rate for two races, and a per-car-lap figure of 9.75.
    # A denominator that is sometimes nonsense is worse than no denominator, because it looks like a measurement.
    best = {}
    for _, cars in states:
        for i, cc in cars.items():
            if cc.get("lap") is not None:
                best[i] = max(best.get(i, 0), cc["lap"])
    leader = max(best.values()) if best else 0
    carlaps = sum(max(0, lp - 1) for i, lp in best.items() if i in ends)
    return max(0, leader - 1), carlaps


def measure(labels, rows=None, names=None, hold=HOLD):
    tot = dict(events=0, lap1=0, churn=0, pitted=0, lapped=0, retired=0, passes=0, no_window=0,
               racelaps=0, carlaps=0, races=0, cars=0)
    for lb in labels:
        p = feed_for(lb, rows, names)
        if not p or not os.path.exists(p):
            continue
        header, states, overs = read_feed(p)
        if not states:
            continue
        c, _ = classify(header, states, overs, hold)
        rl, cl = denominators(header, states)
        for k, v in c.items():
            tot[k] += v
        tot["racelaps"] += rl
        tot["carlaps"] += cl
        tot["races"] += 1
        tot["cars"] = max(tot["cars"], len(header.get("cars") or ()))
    return tot


def line(name, t):
    if not t["races"]:
        return "  %-22s no feeds found" % name
    per_race_lap = t["passes"] / t["racelaps"] if t["racelaps"] else 0.0
    per_car_lap = t["passes"] / t["carlaps"] if t["carlaps"] else 0.0
    churn = t["churn"] / (t["passes"] + t["churn"]) * 100 if (t["passes"] + t["churn"]) else 0.0
    return ("  %-22s %3d races  %5d events -> %4d passes   %5.2f /race-lap  %5.3f /car-lap   churn %2.0f%%"
            % (name, t["races"], t["events"], t["passes"], per_race_lap, per_car_lap, churn))


def excl(name, t):
    return ("  %-22s excluded: lap1 %d, lapped %d, in-pit %d, retired-in-window %d, no-hold-window %d"
            % (name, t["lap1"], t["lapped"], t["pitted"], t["retired"], t["no_window"]))


def report(arms, hold=HOLD):
    with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
        rows = {r["label"]: r for r in csv.DictReader(fh) if r.get("label")}
    names = os.listdir(FEEDDIR)
    print("settled pass = an overtake whose new order still holds %.0f s later. Lap 1 bounded from the STATE stream,"
          % hold)
    print("not from lap events (released feed.lua emits none for lap 1 - see trap 3 in this file).\n")
    out = {}
    for name, sel in arms:
        labels = sorted(l for l in rows if (l in sel) if isinstance(sel, (set, list, tuple))) if not isinstance(sel, str) \
            else sorted(l for l in rows if l.startswith(sel))
        t = measure(labels, rows, names, hold)
        out[name] = t
        print(line(name, t))
        print(excl(name, t))
    print("\n  real F1 for comparison: %.2f-%.2f passes per race lap (39 per race in 2023, 32.8 in 2024, ~57 laps)"
          % (REAL_F1_LO, REAL_F1_HI))
    for name, t in out.items():
        if t["racelaps"]:
            r = t["passes"] / t["racelaps"]
            print("  %-22s %4.1fx real F1" % (name, r / ((REAL_F1_LO + REAL_F1_HI) / 2)))
    return out


def selftest():
    """The point of this is to FAIL on the broken method, not to agree with the fixed one.

    A tool that only ever confirms what it already does is not a check. So the central case builds a RELEASED-style
    feed - 1 Hz states, overtake events, and deliberately no lap event for lap 1 - and asserts that the event-based
    bound misses lap 1 entirely while the state-based bound finds it.
    """
    ok = True

    # a 3-lap race, 2 cars, lap 1 ending at t=100 for both; one swap during lap 1, one after that sticks, one that
    # bounces straight back.
    states = []
    for t in range(0, 400, 1):
        lap = 0 if t < 100 else (1 if t < 200 else 2)
        # car 1 leads except between t=250 and t=260, when car 2 is through and stays through
        p1, p2 = (1, 2) if t < 250 else (2, 1)
        if 150 <= t < 160:            # the bounce: car 2 ahead briefly, then back
            p1, p2 = 2, 1
        states.append((float(t), {1: {"i": 1, "pos": p1, "lap": lap, "pit": False, "ret": False},
                                  2: {"i": 2, "pos": p2, "lap": lap, "pit": False, "ret": False}}))
    overs = [{"type": "overtake", "car": 2, "over": 1, "t": 50.0},    # during lap 1 -> excluded
             {"type": "overtake", "car": 2, "over": 1, "t": 150.0},   # bounce -> churn
             {"type": "overtake", "car": 2, "over": 1, "t": 250.0}]   # sticks -> the only pass
    hdr = {"cars": [{"i": 1}, {"i": 2}]}

    ends = lap1_ends(states)
    print("  state-based lap-1 bound found it?            %s (car 1 at %s s)"
          % ("yes" if ends.get(1) == 100.0 else "NO - BROKEN", ends.get(1)))
    ok &= ends.get(1) == 100.0

    # the broken method, as actually written in the throwaway script: bound lap 1 by the first lap event with lap==1.
    # A released-style feed has none, so the bound never fires.
    released_events = [{"type": "lap", "lap": 2, "t": 200.0}, {"type": "lap", "lap": 3, "t": 300.0}]
    evt_bound = next((e["t"] for e in released_events if e.get("lap") == 1), None)
    print("  event-based bound on a RELEASED-style feed:  %s"
          % ("None - correctly reproduces the bug" if evt_bound is None else "%s - test is wrong" % evt_bound))
    ok &= evt_bound is None

    c, kept = classify(hdr, states, overs)
    print("  with no lap-1 event present, state bound still excludes lap 1?  %s (lap1=%d of 3 events)"
          % ("yes" if c["lap1"] == 1 else "NO - BROKEN", c["lap1"]))
    ok &= c["lap1"] == 1
    print("  bounce counted as churn, not as a pass?      %s (passes=%d, churn=%d)"
          % ("yes" if (c["passes"], c["churn"]) == (1, 1) else "NO - BROKEN", c["passes"], c["churn"]))
    ok &= (c["passes"], c["churn"]) == (1, 1)

    # exclusions must actually fire
    pit = [(t, {1: dict(s[1][1], pit=True), 2: s[1][2]}) for t, s in ((t, (t, cs)) for t, cs in states)]
    cp, _ = classify(hdr, pit, [overs[2]])
    print("  a pass completed in the pits excluded?       %s" % ("yes" if cp["pitted"] == 1 else "NO - BROKEN"))
    ok &= cp["pitted"] == 1

    lapped = [(t, {1: cs[1], 2: dict(cs[2], lap=(cs[2]["lap"] + 1))}) for t, cs in states]
    cl, _ = classify(hdr, lapped, [overs[2]])
    print("  a pass on a lapped car excluded?             %s" % ("yes" if cl["lapped"] == 1 else "NO - BROKEN"))
    ok &= cl["lapped"] == 1

    # a swap with no room left to judge must be reported, not counted either way
    cn, _ = classify(hdr, states, [{"type": "overtake", "car": 2, "over": 1, "t": 380.0}])
    print("  a swap too late to judge reported, not counted? %s"
          % ("yes" if cn["no_window"] == 1 and cn["passes"] == 0 else "NO - BROKEN"))
    ok &= cn["no_window"] == 1 and cn["passes"] == 0

    # the grid gate: it must tell a qualifying-like grid from a deliberately inverted one, because that distinction
    # is the whole difference between a figure comparable to real racing and a figure that measures the test design.
    def synth(order):
        """order[k] = car starting k+1-th; pace is assigned by car id, car 1 fastest."""
        st = [(0.0, {c: {"i": c, "pos": p + 1, "lap": 0} for p, c in enumerate(order)})]
        lp = [{"type": "lap", "car": c, "lap": n, "lap_ms": 90000 + c * 500, "cuts": 0}
              for c in order for n in (2, 3, 4)]
        return st, lp

    sorted_grid = synth([1, 2, 3, 4, 5, 6, 7, 8])          # fastest starts first = qualifying-like
    inv_grid = synth([8, 7, 6, 5, 4, 3, 2, 1])             # fastest starts last = our suite's inversion
    r_sorted, _ = grid_order(*sorted_grid)
    r_inv, _ = grid_order(*inv_grid)
    print("  pace-SORTED grid scored as qualifying-like? %s (rho %+.2f, want near +1)"
          % ("yes" if r_sorted is not None and r_sorted > 0.9 else "NO - BROKEN", r_sorted or 0))
    ok &= r_sorted is not None and r_sorted > 0.9
    print("  pace-INVERTED grid flagged as inverted?     %s (rho %+.2f, want near -1)"
          % ("yes" if r_inv is not None and r_inv < -0.9 else "NO - BROKEN", r_inv or 0))
    ok &= r_inv is not None and r_inv < -0.9
    print("  cut laps dropped from the pace sample?      %s"
          % ("yes" if not pace_by_car([{"type": "lap", "car": 1, "lap": n, "lap_ms": 90000, "cuts": 1}
                                       for n in (2, 3, 4)]) else "NO - BROKEN"))
    ok &= not pace_by_car([{"type": "lap", "car": 1, "lap": n, "lap_ms": 90000, "cuts": 1} for n in (2, 3, 4)])

    rl, cls = denominators(hdr, states)
    print("  denominator excludes lap 1?                  %s (race laps %d, car-laps %d for 2 cars x 2 racing laps)"
          % ("yes" if (rl, cls) == (1, 2) else "NO - BROKEN", rl, cls))
    ok &= (rl, cls) == (1, 2)

    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    arms = []
    for i, a in enumerate(sys.argv):
        if a == "--arms" and i + 1 < len(sys.argv):
            for part in sys.argv[i + 1].split(","):
                if "=" in part:
                    n, p = part.split("=", 1)
                    arms.append((n, p))
        if a == "--labels" and i + 1 < len(sys.argv):
            name = "arm"
            for j, b in enumerate(sys.argv):
                if b == "--name" and j + 1 < len(sys.argv):
                    name = sys.argv[j + 1]
            arms.append((name, set(sys.argv[i + 1].split(","))))
    if not arms:
        print(__doc__)
        return 1
    report(arms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
