"""Did the machine keep real time?

Assetto Corsa's CPU occupancy warning means the physics thread is out of budget; when that happens the simulation
stops advancing one sim-second per wall-second and every wall-clock-based judgement the harness makes (lap budgets,
"stopped" detection, the pit-box timeout) drifts with it. Nothing in the diag recorded it, so this measures it after
the fact and for free: the leader's own lap times come from AC (sim seconds), the wall-clock time of each of its lap
crossings comes from the diag snapshots, and the ratio of the two is how fast the world actually ran.

1.00 = real time. Below ~0.95 the machine was behind and that race's wall-clock-derived numbers are suspect.
Resolution is the diag snapshot interval (~8 s), so read the median over several laps, not a single lap.

On a --practice/--quali weekend only the RACE session is measured. A weekend opens a fresh diag and feed file
per session, but the new files open a moment before AC reports the new session, so the race's files can start
with the tail of qualifying, and lap numbers from the two sessions then share one table: a qualifying lap time
gets divided by a race wall-clock interval and the answer is wrong with no warning on it. Reproduced on a
synthetic weekend 2026-09-24 (race at 1.00, qualifying tail at 0.60): before this, the tool reported worst lap
0.600 and called a race that had kept real time suspect. Reported from PC #2 as "0 usable laps" the same day.

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


def _sim_laps_from_feed(diag_path, car, lap_window=None):
    """{lap number: sim seconds} for one car, from the LAST session in the race feed.

    AC only writes race_out when a session ends cleanly, and some tracks never do - no Baku race on either machine
    has produced one. The feed's lap events carry the sim lap time, and its own `t` is SIM time (verified: the gap
    between consecutive lap events equals the lap time to 0.1 s), so the feed alone cannot give a real-time ratio -
    but combined with the diag's wall-clock `t` it can.

    Which session a feed line belongs to is written down nowhere in the feed: checked every file in verve_feed on
    2026-09-24 and the header carries only track/laps/cars, with `laps` 0 even for a race because the header is
    emitted before AC has filled raceSessionLaps in. `t` cannot mark the boundary either - battle events are
    back-dated to the start of the fight, so `t` already steps backwards by 1-3 s dozens of times inside an
    ordinary single-session file (46-263 times per file across those 93 files). The lap numbering can: per car it
    is strictly increasing within a session (no exception in any of the 93 files), so a lap event that does not
    increase is the start of a new session. Keep the last run only - the race is the last session of a weekend,
    and both files are opened by the same session reset, so the diag's last session block and the feed's last run
    are the same session.

    lap_window is (lowest, highest) lap number the diag's race rows show for this car. Laps outside it are dropped:
    sibling() pairs the feed to the diag by timestamp within 3 minutes, so a mis-paired feed is possible, and
    returning no laps - the caller then reports "not measurable" - beats returning a wrong ratio.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import race_card
    feed = race_card.sibling(diag_path, "feed")
    if not feed or not os.path.exists(feed):
        return {}
    laps = []                                     # (lap number, sim seconds), in the order the feed wrote them
    with open(feed, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if (d.get("e") or d.get("type")) != "lap" or d.get("car") != car:
                continue
            t = d.get("time_s") or d.get("time")
            n = d.get("lap") or d.get("n")
            if t and n:
                t = float(t)
                laps.append((int(n), t / 1000.0 if t > 1000 else t))
    start = 0                                     # first index of the last run of increasing lap numbers
    for k in range(1, len(laps)):
        if laps[k][0] <= laps[k - 1][0]:
            start = k
    out = dict(laps[start:])
    if lap_window:
        lo, hi = lap_window
        out = {n: t for n, t in out.items() if lo <= n <= hi}
    return out


def _race_rows(rows):
    """The last session's rows - the race on a weekend, the only session on a plain quick race.

    diag.lua stamps every row with `session` (3 = race) and `sessionIdx`, and a weekend writes one file per
    session, so normally every row here is already the race. Not always: the new file opens a moment before AC
    reports the new session, so the race's file can start with the tail of qualifying, and those rows still carry
    the previous session's LAP COUNT (race_card.build hit the same thing on 2026-09-21 and trims it the same way).
    Left in, they put one session's lap numbers into the same crossing table as another's. Files old enough to
    predate the session field are left alone - they are single-session quick races.
    """
    if not any("session" in r for r in rows):
        return rows
    race = [r for r in rows if r.get("session") == 3]
    if not race:                                  # a practice- or qualifying-only run (the solo pace runs)
        key = (rows[-1].get("session"), rows[-1].get("sessionIdx"))
        race = [r for r in rows if (r.get("session"), r.get("sessionIdx")) == key]
    # the first snapshots of a session can still carry the previous one's lap count: start at the first lap-0 row
    k0 = next((k for k, r in enumerate(race) if r.get("leaderLap", 0) == 0), 0)
    return race[k0:]


def ratio(diag_path, race_out_path):
    """(median, worst, laps_measured, cars) for the leader's laps, or (None, None, 0, 0) if not measurable."""
    use_feed = not race_out_path or not os.path.exists(race_out_path)
    rows = _rows(diag_path)
    if len(rows) < 8:
        return None, None, 0, 0
    rows = _race_rows(rows)                       # a weekend file can open with the tail of qualifying
    if len(rows) < 8:
        return None, None, 0, 0
    last = rows[-1]
    # spline is recorded x1000, so normalise before using it to pick the leader
    leader = max(last["grid"], key=lambda c: c.get("lap", 0) + min((c.get("spline", 0) or 0) / 1000.0, 1.0))
    car = leader.get("i")
    seen = [c["lap"] for r in rows for c in r["grid"] if c.get("i") == car and "lap" in c]
    window = (min(seen), max(seen)) if seen else None
    if use_feed:
        sim = _sim_laps_from_feed(diag_path, car, window)
    else:
        try:
            with open(race_out_path, encoding="utf-8") as f:
                session = json.load(f)["sessions"][-1]
        except (ValueError, KeyError, IndexError, OSError):
            return None, None, 0, 0
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
