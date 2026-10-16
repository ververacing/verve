"""Race pace in milliseconds, so the release gate can finally judge it.

    python tools/pace.py --labels rc16d_mon_off_1,rc16d_mon_off_2 --ref 112.1
    python tools/pace.py --cell mon --write          # update harness_results/pace.csv for the gate
    python tools/pace.py --selftest

WHY THIS EXISTS. The release gate does not judge pace AT ALL, and says so on every verdict line. The only pace
column we had, `laptime_median_s`, is not a lap time: race_metrics derives it from the gap between DIAG SNAPSHOTS,
which are written every 8 s, so every value it can produce is a multiple of 4 (tools/metric_sanity.py proves it on
the real data). It was quoted to 0.1 s in pace conclusions for weeks, and a cold-tyre claim of "+1.0 s slower" had
to be withdrawn because an 8 s metric cannot support it.

The feed has had the right number all along: the `lap` event carries AC's own `previousLapTimeMs` as `lap_ms`, plus
a `cuts` count. MEASURED on the two gating cells, this metric's quantum is 0.001 s and the fastest clean lap repeats
to 0.17 s across three Monza races - against contact counts whose cells span 6.8x to 22x. It is the sharpest
instrument in the project, and it was sitting unused.

WHAT IT MEASURES, and why each choice:
  best_s   - the field's fastest clean lap. The pace CEILING: what the quickest car could do with clear track.
  p50_s    - the MEDIAN CAR's own best clean lap. The honest "how fast is this field" number.
  p90_s    - the slow end of the field, for spread.
Each car's figure is its BEST clean lap, never its median, because a median lap is contaminated by traffic: a car
stuck in a train posts slow laps that say nothing about its pace. Per-car best is the standard race-pace proxy and
is what makes p50 comparable between a race that spread out and one that did not.

EXCLUDED: cut laps (`cuts > 0` - a lap gained by leaving the track is not a pace sample), the first lap (a standing
start is not a lap time), and cars with fewer than MIN_LAPS clean laps, because one lap is not a pace.

A reference from verve_desk/racecraft/reality.md can be passed with --ref (e.g. Monza GT3 RSR median hotlap 112.1,
Spa GT3 142.4) and the delta is printed. The tool does NOT decide whether a delta is acceptable - that is the gate's
job, against a measured baseline arm, never against a threshold picked by hand.
"""
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results", "results.csv")
PACE_CSV = os.path.join(HERE, "harness_results", "pace.csv")
FEEDDIR = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")

MIN_LAPS = 3          # clean laps a car needs before its best counts as pace
COLUMNS = ["label", "cars", "clean_laps", "best_s", "p50_s", "p90_s", "spread_s"]


def lap_events(path):
    out = []
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if '"lap"' not in ln:
                continue
            try:
                j = json.loads(ln)
            except ValueError:
                continue
            if j.get("type") == "lap":
                out.append(j)
    return out


def best_clean_per_car(laps, min_laps=MIN_LAPS, exclude=None):
    """-> ({car: best clean lap in ms}, total clean laps seen).

    `first` marks the lap-1 event that dev016 added; released feeds simply have no lap-1 event, so BOTH builds are
    handled by skipping it when present and never relying on it being there.

    `exclude` drops one car index from both the dict AND the lap count (see player_car for why).
    """
    per = {}
    for e in laps:
        ms, i = e.get("lap_ms"), e.get("car")
        if i is None or not ms or (e.get("cuts") or 0) > 0 or e.get("first") or i == exclude:
            continue
        per.setdefault(i, []).append(ms)
    total = sum(len(v) for v in per.values())
    return {i: min(v) for i, v in per.items() if len(v) >= min_laps}, total


CLEAR_GAP_S = 2.0     # a lap only counts as clear-track pace if the car was never closer than this to the car ahead


def clear_laps(path, gap_s=CLEAR_GAP_S):
    """-> {car: set of lap numbers the car ran with clear track throughout}.

    WHY THIS IS NEEDED, and it is the difference between a pace metric and a traffic metric. A car's best lap is
    only a pace sample if it had room; a midfield car stuck in a train posts nothing that reflects what it could do.
    That matters here specifically because dev016 produces MORE passing than the baseline, so the arm under test
    systematically gives its midfield FEWER clear laps - which depresses the field-median best lap even if pace is
    identical. Without this filter the Monza field median read 1.0-1.7 s "slower" on dev016 with non-overlapping
    ranges, which is exactly what a pace regression looks like and is not distinguishable from more racing.

    Lap boundaries come from the state stream's own counter (AC counts COMPLETED laps, so during racing lap k the
    counter reads k-1), never from lap events - released feeds have no lap-1 event, and an event-derived boundary is
    the trap that cost a whole measurement earlier today.
    """
    out = {}
    for _, cars in _states(path):
        for i, c in cars.items():
            lp, gap = c.get("lap"), c.get("gap_ahead_s")
            if lp is None:
                continue
            racing = lp + 1                      # the lap this car is CURRENTLY on
            d = out.setdefault(i, {})
            # A lap is clear only if the car was NEVER inside the gap during it: once blocked, always blocked.
            # A missing gap means nothing ahead (the leader), which is clear track rather than a dirty lap.
            if gap is not None and gap < gap_s:
                d[racing] = False
            elif racing not in d:
                d[racing] = True
    return {i: {k for k, v in d.items() if v} for i, d in out.items()}


def _states(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if '"state"' not in ln:
                continue
            try:
                j = json.loads(ln)
            except ValueError:
                continue
            if j.get("type") != "state":
                continue
            cars = {c.get("i"): c for c in (j.get("cars") or ()) if c.get("i") is not None}
            if cars:
                yield j.get("t"), cars


def best_clear_per_car(path, min_laps=1, gap_s=CLEAR_GAP_S, exclude=None):
    """-> ({car: best CLEAR clean lap in ms}, number of clear clean laps). Needs only 1, clear laps being scarce."""
    clear = clear_laps(path, gap_s)
    per = {}
    for e in lap_events(path):
        ms, i, n = e.get("lap_ms"), e.get("car"), e.get("lap")
        if i is None or not ms or (e.get("cuts") or 0) > 0 or e.get("first") or i == exclude:
            continue
        if n not in clear.get(i, ()):
            continue
        per.setdefault(i, []).append(ms)
    return {i: min(v) for i, v in per.items() if len(v) >= min_laps}, sum(len(v) for v in per.values())


def pctl(vals, q):
    """Nearest-rank percentile on a sorted list. No interpolation: with 16-20 cars it would invent precision."""
    if not vals:
        return None
    s = sorted(vals)
    k = int(round(q * (len(s) - 1)))
    return s[max(0, min(len(s) - 1, k))]


def player_car(path):
    """The index of the player/autopilot car from the feed header, or None if the feed does not mark one.

    WHY THIS EXISTS. In a harness race slot 0 is the autopilot player car, and it is NOT a member of the field being
    measured: it ignores Verve's level and grip and starts on a fixed fuel load (CLAUDE.md), so it is not governed by
    the difficulty slider and runs systematically off the AI's pace. Leaving it in moves p50_s, p90_s and spread_s
    away from the AI pace they are supposed to describe, while leaving best_s untouched - the autopilot is never the
    fastest car - which is exactly why this survived unnoticed until a slider-pace question needed the median.

    Read from the header's own per-car `player` flag, never by assuming index 0: in a real player's race the player
    can start anywhere on the grid, and a feed that marks nobody returns None so that nothing is excluded.
    """
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            head = json.loads(fh.readline())
    except (OSError, ValueError):
        return None
    if head.get("type") != "header":
        return None
    for c in head.get("cars") or ():
        if c.get("player") and c.get("i") is not None:
            return c.get("i")
    return None


def race_pace(path):
    """-> dict of pace figures for one feed, or None when the race cannot support a pace reading."""
    skip = player_car(path)
    best, clean = best_clean_per_car(lap_events(path), exclude=skip)
    if len(best) < 5:
        return None
    v = sorted(x / 1000.0 for x in best.values())
    d = dict(cars=len(v), clean_laps=clean, best_s=round(v[0], 3),
             p50_s=round(pctl(v, 0.5), 3), p90_s=round(pctl(v, 0.9), 3),
             spread_s=round(pctl(v, 0.9) - v[0], 3))
    # The traffic-corrected pair. Reported alongside rather than instead, because the clear-lap sample is small and
    # a cell where few cars ever get clear track is itself worth seeing - that is the condition under which the
    # unfiltered field median stops being a pace number at all.
    cb, cn = best_clear_per_car(path, exclude=skip)
    if len(cb) >= 5:
        cv = sorted(x / 1000.0 for x in cb.values())
        d.update(clear_cars=len(cv), clear_laps=cn, clear_best_s=round(cv[0], 3),
                 clear_p50_s=round(pctl(cv, 0.5), 3))
    else:
        d.update(clear_cars=len(cb), clear_laps=cn, clear_best_s=None, clear_p50_s=None)
    return d


def feed_for(label, rows, names):
    import re
    m = re.search(r"(\d{8}_\d{6})", (rows.get(label) or {}).get("file") or "")
    if not m:
        return None
    hit = next((f for f in names if f.startswith(m.group(1))), None)
    return os.path.join(FEEDDIR, hit) if hit else None


def load_rows():
    with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
        return {r["label"]: r for r in csv.DictReader(fh) if r.get("label")}


def measure(labels):
    rows, names = load_rows(), os.listdir(FEEDDIR)
    out = []
    for lb in labels:
        p = feed_for(lb, rows, names)
        if not p or not os.path.exists(p):
            out.append((lb, None))
            continue
        out.append((lb, race_pace(p)))
    return out


def write_csv(measured):
    """Merge into pace.csv by label, so the gate can join on it without re-reading every feed."""
    have = {}
    if os.path.exists(PACE_CSV):
        with io.open(PACE_CSV, encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if r.get("label"):
                    have[r["label"]] = r
    n = 0
    for lb, p in measured:
        if not p:
            continue
        have[lb] = dict(label=lb, **{k: p[k] for k in COLUMNS if k != "label"})
        n += 1
    with io.open(PACE_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for lb in sorted(have):
            w.writerow({k: have[lb].get(k, "") for k in COLUMNS})
    return n, len(have)


def report(measured, ref=None):
    print("%-24s %5s %6s %9s %9s %9s %9s" % ("label", "cars", "laps", "best_s", "p50_s", "p90_s", "spread"))
    vals = []
    for lb, p in measured:
        if not p:
            print("%-24s  no pace (feed missing, or under 5 cars with %d clean laps)" % (lb, MIN_LAPS))
            continue
        vals.append(p)
        print("%-24s %5d %6d %9.3f %9.3f %9.3f %9.3f"
              % (lb, p["cars"], p["clean_laps"], p["best_s"], p["p50_s"], p["p90_s"], p["spread_s"]))
    if len(vals) > 1:
        # Only summarise across races that share a track and distance. Pooling them printed "best_s across 12
        # races: 110.877 to 144.949, range 34.072 s" - a Monza lap next to a Spa lap, a 34 s "range" that reads
        # like spread and is just two different circuits. Same fault metric_sanity exists to catch, reproduced in
        # a tool written an hour after it.
        rows = load_rows()
        cells = {(rows.get(lb, {}).get("track"), rows.get(lb, {}).get("leader_laps"))
                 for lb, p in measured if p}
        if len(cells) > 1:
            print("  (no across-race summary: these labels span %d different track/distance cells, and a range "
                  "across cells is not a spread)" % len(cells))
        else:
            for k in ("best_s", "p50_s"):
                v = sorted(x[k] for x in vals)
                print("  %-8s across %d races: %.3f to %.3f, range %.3f s"
                      % (k, len(vals), v[0], v[-1], v[-1] - v[0]))
    if ref is not None and vals:
        b = sorted(x["best_s"] for x in vals)[len(vals) // 2]
        print("  reference %.2f s (reality.md): our median fastest clean lap %.3f s, %+.2f s"
              % (ref, b, b - ref))
    return 0


def selftest():
    """Shown laps it must reject, and a traffic-contaminated car it must still read correctly."""
    ok = True

    # car 1 is quick but spends the race in traffic: one clear lap, the rest slow. Per-car BEST must find the 90.0.
    laps = [{"type": "lap", "car": 1, "lap": n, "lap_ms": ms, "cuts": 0}
            for n, ms in ((2, 97000), (3, 96500), (4, 90000), (5, 98000))]
    # car 2 is genuinely slower, with clear track throughout
    laps += [{"type": "lap", "car": 2, "lap": n, "lap_ms": 94000, "cuts": 0} for n in (2, 3, 4)]
    # a cut lap that is the fastest on the sheet and must be ignored
    laps += [{"type": "lap", "car": 3, "lap": n, "lap_ms": 80000, "cuts": 2} for n in (2, 3, 4)]
    # the lap-1 event dev016 adds, which is not a lap time
    laps += [{"type": "lap", "car": 4, "lap": 1, "lap_ms": 120000, "cuts": 0, "first": True}]
    # a car with too few clean laps to have a pace
    laps += [{"type": "lap", "car": 5, "lap": 2, "lap_ms": 91000, "cuts": 0}]

    best, clean = best_clean_per_car(laps)
    print("  traffic-bound car read by its BEST lap, not its median?  %s (%s ms, want 90000)"
          % ("yes" if best.get(1) == 90000 else "NO - BROKEN", best.get(1)))
    ok &= best.get(1) == 90000
    print("  a CUT lap excluded even though it is fastest?            %s"
          % ("yes" if 3 not in best else "NO - BROKEN, cut lap became the pace"))
    ok &= 3 not in best
    print("  the lap-1 event excluded?                                %s"
          % ("yes" if 4 not in best else "NO - BROKEN"))
    ok &= 4 not in best
    print("  a car with %d clean lap excluded?                         %s"
          % (1, "yes" if 5 not in best else "NO - BROKEN, one lap is not a pace"))
    ok &= 5 not in best
    print("  clean-lap count counts only clean laps?                  %s (%d, want 8)"
          % ("yes" if clean == 8 else "NO - BROKEN", clean))
    ok &= clean == 8

    # THE PLAYER/AUTOPILOT CAR. It is not part of the field being measured and must not reach any figure.
    # Every case below was CHECKED BY NEUTERING THE EXCLUSION AND WATCHING IT GO RED, and that exercise corrected
    # this comment: a first draft asserted on p90_s, which does NOT move when the autopilot is included. With
    # nearest-rank percentiles a single tail outlier sits past the p90 index (index 5 of 7 either way), so p90_s and
    # spread_s are naturally robust to it - that assertion was vacuous and would have sat green for ever. The figures
    # that really move are `cars`, `clean_laps` and p50_s, the last by a full second here, and p50_s is precisely the
    # "median-of-best" reality.md compares against the human top-10%. Those are what is asserted.
    bx, cx = best_clean_per_car(laps, exclude=1)
    print("  an excluded car gone from the pace dict?                 %s"
          % ("yes" if 1 not in bx else "NO - BROKEN"))
    ok &= 1 not in bx
    print("  an excluded car gone from the lap COUNT too?             %s (%d, want 4)"
          % ("yes" if cx == 4 else "NO - BROKEN, sample size is overstated", cx))
    ok &= cx == 4

    import os as _os
    import tempfile as _tf
    fd0, tmp0 = _tf.mkstemp(suffix=".jsonl", text=True)
    _os.close(fd0)
    try:
        # the autopilot (car 0, flagged player) is far slower than the field, like a 30 L start on a slider it ignores
        cars = [{"i": 0, "model": "m", "class": "gt", "driver": "Autopilot", "player": True}]
        cars += [{"i": i, "model": "m", "class": "gt", "driver": "AI %d" % i, "player": False} for i in range(1, 7)]
        recs = [{"v": 1, "t": 0, "type": "header", "track": "monza", "cars": cars}]
        recs += [{"type": "lap", "car": 0, "lap": n, "lap_ms": 120000, "cuts": 0} for n in (2, 3, 4)]
        for i, ms in zip(range(1, 7), (95000, 96000, 97000, 98000, 99000, 100000)):
            recs += [{"type": "lap", "car": i, "lap": n, "lap_ms": ms, "cuts": 0} for n in (2, 3, 4)]
        with io.open(tmp0, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

        print("  player car found from the header flag?                   %s (%s, want 0)"
              % ("yes" if player_car(tmp0) == 0 else "NO - BROKEN", player_car(tmp0)))
        ok &= player_car(tmp0) == 0
        rp = race_pace(tmp0)
        print("  player car kept out of the car count?                    %s (%s, want 6 of 7)"
              % ("yes" if rp and rp["cars"] == 6 else "NO - BROKEN", rp and rp["cars"]))
        ok &= bool(rp) and rp["cars"] == 6
        print("  player car kept out of the MEDIAN-of-best?               %s (p50 %s, want 97.0 not 98.0)"
              % ("yes" if rp and rp["p50_s"] == 97.0 else "NO - BROKEN, the autopilot moved the field median",
                 rp and rp["p50_s"]))
        ok &= bool(rp) and rp["p50_s"] == 97.0
        print("  player car kept out of the clean-lap count?              %s (%s, want 18 of 21)"
              % ("yes" if rp and rp["clean_laps"] == 18 else "NO - BROKEN", rp and rp["clean_laps"]))
        ok &= bool(rp) and rp["clean_laps"] == 18

        # a feed that marks nobody (an older build) must exclude NOTHING rather than guessing index 0
        recs[0] = {"v": 1, "t": 0, "type": "header", "track": "monza",
                   "cars": [{"i": c["i"], "model": "m", "class": "gt", "driver": "d"} for c in cars]}
        with io.open(tmp0, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        rp2 = race_pace(tmp0)
        print("  unmarked feed excludes nobody, scores all 7?             %s (%s, want 7)"
              % ("yes" if player_car(tmp0) is None and rp2 and rp2["cars"] == 7 else "NO - BROKEN",
                 rp2 and rp2["cars"]))
        ok &= player_car(tmp0) is None and bool(rp2) and rp2["cars"] == 7
    finally:
        try:
            _os.remove(tmp0)
        except OSError:
            pass

    # percentile must not interpolate: with 2 values it has to return one of them
    print("  percentile returns a real observation, not an average?   %s"
          % ("yes" if pctl([90.0, 94.0], 0.5) in (90.0, 94.0) else "NO - BROKEN"))
    ok &= pctl([90.0, 94.0], 0.5) in (90.0, 94.0)

    # and a race too thin to judge must return None rather than a number
    thin = [{"type": "lap", "car": c, "lap": n, "lap_ms": 90000, "cuts": 0} for c in (1, 2) for n in (2, 3, 4)]
    b2, _ = best_clean_per_car(thin)
    print("  a 2-car race refused rather than scored?                 %s"
          % ("yes" if len(b2) < 5 else "NO - BROKEN"))
    ok &= len(b2) < 5

    # The clear-track filter has to change the answer in the RIGHT DIRECTION on a case built to trap it: a car whose
    # FASTEST lap was run in traffic and whose only clear lap was slower. If the filter is a no-op, or picks the
    # faster dirty lap, this fails. Written through a real temp feed so the JSON and state parsing are exercised too.
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".jsonl", text=True)
    os.close(fd)
    try:
        recs = []
        # car 1 on lap 2 with clear track (counter reads 1), then lap 3 stuck behind someone
        for t in range(0, 10):
            recs.append({"type": "state", "t": float(t), "cars": [{"i": 1, "lap": 1, "gap_ahead_s": 5.0}]})
        for t in range(10, 20):
            recs.append({"type": "state", "t": float(t), "cars": [{"i": 1, "lap": 2, "gap_ahead_s": 0.4}]})
        # the leader, lap 2, with no gap field at all - nothing ahead, so clear
        for t in range(0, 10):
            recs.append({"type": "state", "t": float(t), "cars": [{"i": 2, "lap": 1}]})
        recs.append({"type": "lap", "car": 1, "lap": 2, "lap_ms": 95000, "cuts": 0})   # clear but slower
        recs.append({"type": "lap", "car": 1, "lap": 3, "lap_ms": 90000, "cuts": 0})   # faster, in traffic
        recs.append({"type": "lap", "car": 2, "lap": 2, "lap_ms": 97000, "cuts": 0})
        with io.open(tmp, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

        cl = clear_laps(tmp)
        print("  lap run in traffic marked NOT clear?                     %s"
              % ("yes" if 3 not in cl.get(1, set()) else "NO - BROKEN"))
        ok &= 3 not in cl.get(1, set())
        print("  lap run with room marked clear?                          %s"
              % ("yes" if 2 in cl.get(1, set()) else "NO - BROKEN"))
        ok &= 2 in cl.get(1, set())
        print("  leader with no car ahead counted as clear?               %s"
              % ("yes" if 2 in cl.get(2, set()) else "NO - BROKEN, the leader would never have a pace lap"))
        ok &= 2 in cl.get(2, set())

        bc, n = best_clear_per_car(tmp)
        plain, _ = best_clean_per_car(lap_events(tmp), min_laps=1)
        print("  pace taken from the CLEAR lap, not the faster dirty one? %s (clear %s vs unfiltered %s)"
              % ("yes" if bc.get(1) == 95000 and plain.get(1) == 90000 else "NO - BROKEN", bc.get(1), plain.get(1)))
        ok &= bc.get(1) == 95000 and plain.get(1) == 90000
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    labels, ref, cell = [], None, None
    for i, a in enumerate(sys.argv):
        if a == "--labels" and i + 1 < len(sys.argv):
            labels = sys.argv[i + 1].split(",")
        if a == "--ref" and i + 1 < len(sys.argv):
            ref = float(sys.argv[i + 1])
        if a == "--cell" and i + 1 < len(sys.argv):
            cell = sys.argv[i + 1]
    if cell:
        labels = sorted(l for l in load_rows() if ("_%s_" % cell) in l)
    if not labels:
        print(__doc__)
        return 1
    measured = measure(labels)
    report(measured, ref)
    if "--write" in sys.argv:
        n, tot = write_csv(measured)
        print("\n  pace.csv: %d rows written, %d total" % (n, tot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
