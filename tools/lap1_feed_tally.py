"""The OPENING LAP from the race feed, with the four figures item 16 pre-registered, one row per race.

    python tools/lap1_feed_tally.py monza --label rs16_          # every matching race, grouped by arm
    python tools/lap1_feed_tally.py monza --label rs16_ --arms calm,racing,stock
    python tools/lap1_feed_tally.py --selftest

WHY A SECOND LAP-1 TOOL. tools/lap1_tally.py reads a DIAG file: 8 s snapshots, so it sees damage deltas and
coarse position changes and nothing finer. The pre-registered metrics for a race-start A/B need the 1 Hz feed:
  1. lap 0-1 incidents, SPLIT solo v car-to-car (the feed's `incident` carries `solo`; the diag cannot)
  2. cars off track on lap 0-1 - RAW off_track events, and the count is reported as RAW on purpose
  3. places gained by cars STARTING 10th OR LOWER by the end of lap 1 (the backmarker-progress figure)
  4. lap 1 time of the leader and the median car

READ THIS BEFORE QUOTING COLUMN `off01`. A raw off_track count is mostly WIDE RUNNING, not loss of control -
measured 3.8:1 to 18.6:1 wide:excursion across our own cells, and two findings have been withdrawn over it (both
machines, 2026-10-12). This tool CANNOT split them: the discriminator is a speed join over the 3-8 s after the
event, which needs more of the race than lap 1 contains. **Use tools/excursions.py for any off-track claim** and
treat `off01` as a tie-break at best. It is here because the dispatch pre-registered it, and it is labelled raw.

INCIDENT LAPS ARE INFERRED. The feed's `incident` and `off_track` events carry car and spline but no lap, so the
lap comes from the nearest 1 Hz state record for that car. At 1 Hz that is exact enough for a lap boundary except
within a second of the line; a race is reported as `lap_est` when any event fell in that window.

SLOT 0 IS EXCLUDED from every per-car figure: it is the harness autopilot, not an AI car, and it ignores Verve's
level and grip (it also starts on a different fuel load). Its events are counted separately as `slot0`.
"""
import collections
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)            # python -I drops the script dir from sys.path
import paths                        # noqa: E402  - live + archived feeds, de-duplicated


def _label_map():
    """diag-file stem -> label, from results.csv (the only place that pairs them exactly)."""
    import csv
    out = {}
    try:
        with io.open(os.path.join(HERE, "harness_results", "results.csv"),
                     encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                b = os.path.basename(r.get("file") or "")
                lab = r.get("label") or ""
                if b.startswith("diag_race_") and lab:
                    out[b[len("diag_race_"):len("diag_race_") + 15]] = lab
    except OSError:
        pass
    # a race still running has no results row yet: fall back to the diag filename
    import glob
    for d in (os.path.dirname(HERE), os.path.join(HERE, "harness_results", "archive", "diag")):
        for p in glob.glob(os.path.join(d, "diag_race_*.jsonl")):
            b = os.path.basename(p)
            stem = b[len("diag_race_"):len("diag_race_") + 15]
            if stem in out:
                continue
            rest = b[len("diag_race_") + 16:-len(".jsonl")]
            try:                       # strip the track the DIAG HEADER names - never split the filename, the
                with io.open(p, encoding="utf-8", errors="replace") as fh:   # track can contain underscores
                    tr = (json.loads(fh.readline()).get("track") or "").replace("/", "_")
            except (OSError, ValueError):
                tr = ""
            if tr and rest.startswith(tr + "_"):
                rest = rest[len(tr) + 1:]
            out[stem] = rest
    return out


def scan(path):
    """One race -> a dict of the pre-registered figures, or None if the feed is unusable."""
    states = []                       # (t, {i: car})
    laps = []                         # lap events
    incidents = []                    # (t, car, solo)
    offs = []                         # (t, car)
    cars_in_header = 0
    finished = False                  # a feed with no race_end is a race still on track: never pool it
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            t = d.get("type")
            if t == "header":
                cars_in_header = len(d.get("cars") or [])
            elif t == "state":
                by = {}
                for c in (d.get("cars") or []):
                    if isinstance(c.get("i"), int):
                        by[c["i"]] = c
                if by:
                    states.append((d.get("t") or 0.0, by))
            elif t == "lap":
                laps.append(d)
            elif t == "incident":
                incidents.append((d.get("t") or 0.0, d.get("car"), bool(d.get("solo"))))
            elif t == "off_track":
                offs.append((d.get("t") or 0.0, d.get("car")))
            elif t == "race_end":
                finished = True
    if len(states) < 5:
        return None

    def lap_at(car, t):
        """The car's lap at time t, from the nearest state record. (None, True) when it cannot be told."""
        best, bestdt = None, None
        for st, by in states:
            c = by.get(car)
            if c is None:
                continue
            dt = abs(st - t)
            if bestdt is None or dt < bestdt:
                best, bestdt = c, dt
        if best is None:
            return None, True
        return best.get("lap"), bestdt is not None and bestdt > 1.5

    est = False
    inc_solo = inc_contact = inc_slot0 = 0
    for t, car, solo in incidents:
        if car is None:
            continue
        lp, fuzzy = lap_at(car, t)
        est = est or fuzzy
        if lp is None or lp > 1:
            continue
        if car == 0:
            inc_slot0 += 1
        elif solo:
            inc_solo += 1
        else:
            inc_contact += 1

    off01 = 0
    for t, car in offs:
        if car is None or car == 0:
            continue
        lp, fuzzy = lap_at(car, t)
        est = est or fuzzy
        if lp is not None and lp <= 1:
            off01 += 1

    # start position: the first state record. Slot order is grid order, but read it rather than assume.
    first = states[0][1]
    start_pos = {i: c.get("pos") for i, c in first.items() if c.get("pos")}
    # position at the end of lap 1: the last state in which the car is still on lap <= 1
    end1 = {}
    for st, by in states:
        for i, c in by.items():
            if (c.get("lap") or 0) <= 1 and c.get("pos"):
                end1[i] = c["pos"]

    gain_back = 0                     # places gained by cars starting 10th or lower
    back_n = 0
    for i, sp in start_pos.items():
        if i == 0 or sp < 10 or i not in end1:
            continue
        back_n += 1
        g = sp - end1[i]              # positive = moved forward
        if g > 0:
            gain_back += g

    l1 = [(d.get("car"), (d.get("lap_ms") or 0) / 1000.0) for d in laps if d.get("lap") == 1]
    l1 = [(c, s) for c, s in l1 if c is not None and c != 0 and s > 0]
    leader = None
    if l1:
        # the leader at the end of lap 1, by position, not by the quickest lap
        pos1 = {i: p for i, p in end1.items() if i != 0}
        if pos1:
            lead_car = min(pos1, key=lambda i: pos1[i])
            for c, s in l1:
                if c == lead_car:
                    leader = s
                    break
    med = statistics.median([s for _, s in l1]) if l1 else None

    return {
        "cars": cars_in_header,
        "inc_solo": inc_solo,
        "inc_contact": inc_contact,
        "inc_slot0": inc_slot0,
        "off01_raw": off01,
        "gain_back": gain_back,
        "back_n": back_n,
        "lap1_leader_s": leader,
        "lap1_median_s": med,
        "lap_est": est,
        "finished": finished,
    }


def selftest():
    """Each case reinstates a bug this tool must not have."""
    ok = True
    import tempfile

    def feed(lines):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with io.open(p, "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d) + "\n")
        return p

    def st(t, cars):
        return {"type": "state", "t": t, "cars": cars}

    def car(i, pos, lap):
        return {"i": i, "pos": pos, "lap": lap, "spline": 0.5, "spd": 100, "pit": False, "ret": False, "dmg": 0}

    # 1. slot 0 must not be counted as an AI car, in incidents or in gains
    lines = [{"type": "header", "cars": [{"i": 0}, {"i": 1}, {"i": 11}]}]
    for t in range(6):
        lines.append(st(float(t), [car(0, 12, 0), car(1, 1, 0), car(11, 11, 0)]))
    lines.append({"type": "incident", "t": 2.0, "car": 0, "solo": True})
    lines.append({"type": "incident", "t": 2.0, "car": 1, "solo": True})
    lines.append({"type": "incident", "t": 2.0, "car": 11, "solo": False})
    r = scan(feed(lines))
    if r is None:
        print("SELFTEST FAIL: a 6-state feed was rejected"); ok = False
    else:
        if r["inc_slot0"] != 1 or r["inc_solo"] != 1 or r["inc_contact"] != 1:
            print("SELFTEST FAIL: slot 0 / solo / contact split wrong: %r" % r); ok = False

    # 2. an incident AFTER lap 1 must not be counted
    lines2 = [{"type": "header", "cars": [{"i": 1}]}]
    for t in range(6):
        lines2.append(st(float(t), [car(1, 1, 0 if t < 3 else 2)]))
    lines2.append({"type": "incident", "t": 5.0, "car": 1, "solo": True})
    r2 = scan(feed(lines2))
    if r2 and (r2["inc_solo"] or r2["inc_contact"]):
        print("SELFTEST FAIL: an incident on lap 2 was counted as lap 0-1: %r" % r2); ok = False

    # 3. only cars starting 10th or lower count toward gain_back, and only forward moves
    lines3 = [{"type": "header", "cars": [{"i": 1}, {"i": 11}, {"i": 12}]}]
    lines3.append(st(0.0, [car(1, 2, 0), car(11, 11, 0), car(12, 14, 0)]))
    lines3.append(st(1.0, [car(1, 1, 1), car(11, 8, 1), car(12, 16, 1)]))
    for t in (2.0, 3.0, 4.0):
        lines3.append(st(t, [car(1, 1, 2), car(11, 8, 2), car(12, 16, 2)]))
    r3 = scan(feed(lines3))
    if r3 is None:
        print("SELFTEST FAIL: feed 3 rejected"); ok = False
    else:
        # car 1 started 2nd: excluded. car 11: 11 -> 8 = +3. car 12: 14 -> 16 = lost places, contributes 0.
        if r3["gain_back"] != 3:
            print("SELFTEST FAIL: gain_back should be 3 (only car 11 counts), got %r" % r3["gain_back"]); ok = False
        if r3["back_n"] != 2:
            print("SELFTEST FAIL: back_n should be 2 (cars 11 and 12), got %r" % r3["back_n"]); ok = False

    # 4. the leader's lap-1 time is the LEADER's, not the quickest
    lines4 = [{"type": "header", "cars": [{"i": 1}, {"i": 2}]}]
    lines4.append(st(0.0, [car(1, 1, 0), car(2, 2, 0)]))
    for t in (1.0, 2.0, 3.0, 4.0):
        lines4.append(st(t, [car(1, 1, 1), car(2, 2, 1)]))
    lines4.append({"type": "lap", "car": 1, "lap": 1, "lap_ms": 120000})
    lines4.append({"type": "lap", "car": 2, "lap": 1, "lap_ms": 110000})
    r4 = scan(feed(lines4))
    if r4 is None:
        print("SELFTEST FAIL: feed 4 rejected"); ok = False
    elif r4["lap1_leader_s"] != 120.0:
        print("SELFTEST FAIL: leader lap-1 time should be 120.0 (car 1, who led), got %r"
              % r4["lap1_leader_s"]); ok = False

    # 5. a feed with no race_end is UNFINISHED, and one with it is finished
    lines5 = [{"type": "header", "cars": [{"i": 1}]}]
    for t in range(6):
        lines5.append(st(float(t), [car(1, 1, 0)]))
    r5 = scan(feed(lines5))
    if r5 is None or r5["finished"]:
        print("SELFTEST FAIL: a feed with no race_end was reported finished: %r" % (r5 and r5["finished"]))
        ok = False
    lines5.append({"type": "race_end", "results": []})
    r5b = scan(feed(lines5))
    if r5b is None or not r5b["finished"]:
        print("SELFTEST FAIL: a feed WITH race_end was not reported finished")
        ok = False

    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pos:
        print(__doc__.strip().splitlines()[0])
        return 2
    track = pos[0]
    want, arms = None, None
    for i, a in enumerate(sys.argv):
        if a == "--label" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1]
        if a == "--arms" and i + 1 < len(sys.argv):
            arms = sys.argv[i + 1].split(",")

    labs = _label_map()
    rows = []
    for p in paths.track_feeds(track):
        lab = labs.get(os.path.basename(p)[:15], os.path.basename(p)[:15])
        if want and want not in lab:
            continue
        r = scan(p)
        if r:
            rows.append((lab, r))
    if not rows:
        print("lap1_feed_tally: no %s feed matched %s" % (track, want or "(any)"))
        return 0

    live = [(lab, r) for lab, r in rows if not r["finished"]]
    rows = [(lab, r) for lab, r in rows if r["finished"]]
    if live:
        print("\nSTILL ON TRACK, excluded from everything below (no race_end in the feed): %s"
              % ", ".join(lab for lab, _ in live))
    if not rows:
        print("no FINISHED race matched - nothing to report yet")
        return 0
    print("\nOPENING LAP from the feed. off01 is a RAW off_track count (mostly wide running) - "
          "use excursions.py for an off-track claim.")
    print("%-24s %5s %6s %7s %6s %8s %9s %9s %s"
          % ("label", "cars", "solo", "contact", "off01", "gainBack", "lap1lead", "lap1med", "est"))
    for lab, r in rows:
        print("%-24s %5s %6d %7d %6d %8d %9s %9s %s"
              % (lab, r["cars"], r["inc_solo"], r["inc_contact"], r["off01_raw"], r["gain_back"],
                 ("%.1f" % r["lap1_leader_s"]) if r["lap1_leader_s"] else "-",
                 ("%.1f" % r["lap1_median_s"]) if r["lap1_median_s"] else "-",
                 "lap_est" if r["lap_est"] else ""))

    if arms:
        print("\nBY ARM (mean per race; n is the number of races, and a short cell's own spread is large -")
        print("three or more runs a side, and no claim finer than 1 incident per race):")
        for a in arms:
            sel = [r for lab, r in rows if a in lab]
            if not sel:
                print("  %-10s n=0" % a)
                continue
            def m(k):
                v = [r[k] for r in sel if r[k] is not None]
                return (sum(v) / float(len(v))) if v else None
            print("  %-10s n=%-2d solo %.2f  contact %.2f  off01 %.2f  gainBack %.2f  lap1lead %s  lap1med %s"
                  % (a, len(sel), m("inc_solo"), m("inc_contact"), m("off01_raw"), m("gain_back"),
                     ("%.1f" % m("lap1_leader_s")) if m("lap1_leader_s") else "-",
                     ("%.1f" % m("lap1_median_s")) if m("lap1_median_s") else "-"))
            for k in ("inc_solo", "inc_contact", "gain_back"):
                vals = sorted(r[k] for r in sel)
                print("             %-11s per race: %s" % (k, vals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
