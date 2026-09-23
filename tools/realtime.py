"""Did the machine keep real time?

Assetto Corsa's CPU occupancy warning means the physics thread is out of budget; when that happens the simulation
stops advancing one sim-second per wall-second and every wall-clock-based judgement the harness makes (lap budgets,
"stopped" detection, the pit-box timeout) drifts with it. Nothing in the diag recorded it, so this measures it after
the fact and for free: the leader's own lap times come from AC (sim seconds), the wall-clock time of each of its lap
crossings comes from the diag snapshots, and the ratio of the two is how fast the world actually ran.

1.00 = real time. Below ~0.95 the machine was behind and that race's wall-clock-derived numbers are suspect.
Resolution is the diag snapshot interval (~8 s), so read the median over several laps, not a single lap.

    python tools/realtime.py <diag_race_*.jsonl> [race_out_*.json]
    python tools/realtime.py --all          # every scored race in this folder, grouped by grid size
"""
import glob
import json
import os
import statistics
import sys

MIN_LAPS = 3          # fewer than this and the +-8 s snapshot resolution swamps the answer
SUSPECT = 0.95        # below this the race ran slower than real time


def _rows(diag_path):
    out = []
    with open(diag_path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("grid") and d.get("t"):
                out.append(d)
    return out


def ratio(diag_path, race_out_path):
    """(median, worst, laps_measured, cars) for the leader's laps, or (None, None, 0, 0) if not measurable."""
    if not race_out_path or not os.path.exists(race_out_path):
        return None, None, 0, 0
    rows = _rows(diag_path)
    if len(rows) < 8:
        return None, None, 0, 0
    try:
        with open(race_out_path, encoding="utf-8") as f:
            session = json.load(f)["sessions"][-1]
    except (ValueError, KeyError, IndexError, OSError):
        return None, None, 0, 0
    last = rows[-1]
    leader = max(last["grid"], key=lambda c: c.get("lap", 0) + c.get("spline", 0))
    car = leader.get("i")
    sim = {l["lap"]: l["time"] / 1000 for l in session.get("laps", [])
           if l.get("car") == car and l.get("time", 0) > 10000}
    if len(sim) < MIN_LAPS:
        return None, None, 0, len(last["grid"])
    crossed, prev = {}, None                      # wall-clock time of each lap increment
    for r in rows:
        c = next((x for x in r["grid"] if x.get("i") == car), None)
        if c is None:
            continue
        if prev is not None and c.get("lap", 0) > prev:
            crossed[c["lap"]] = r["t"]
        prev = c.get("lap", 0)
    rs = [sim[k] / (crossed[k] - crossed[k - 1]) for k in sorted(crossed)
          if k in sim and (k - 1) in crossed and crossed[k] - crossed[k - 1] > 5]
    if len(rs) < MIN_LAPS:
        return None, None, len(rs), len(last["grid"])
    return round(statistics.median(rs), 3), round(min(rs), 3), len(rs), len(last["grid"])


def _sibling(diag_path):
    """The race_out AC wrote for this race (race_card already knows how to find it)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    import race_card
    return race_card.sibling(diag_path, "race_out")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--all":
        import collections
        by = collections.defaultdict(list)
        for f in sorted(glob.glob("diag_race_*.jsonl")):
            med, worst, n, cars = ratio(f, _sibling(f))
            if med:
                by[cars].append(med)
        print("sim seconds per wall second (1.00 = the machine kept real time):")
        for cars in sorted(by):
            v = by[cars]
            flag = "  <-- SUSPECT" if statistics.median(v) < SUSPECT else ""
            print(f"  {cars:>2} cars  n={len(v):>3}  median {statistics.median(v):.3f}  worst {min(v):.3f}{flag}")
        return
    if not args:
        print(__doc__)
        return
    diag = args[0]
    med, worst, n, cars = ratio(diag, args[1] if len(args) > 1 else _sibling(diag))
    if med is None:
        print(f"not measurable ({n} usable laps)")
        return
    print(f"{cars} cars, {n} laps: real-time ratio median {med:.3f}, worst lap {worst:.3f}"
          + ("  -- SLOWER THAN REAL TIME, treat this race's timings as suspect" if med < SUSPECT else ""))


if __name__ == "__main__":
    main()
