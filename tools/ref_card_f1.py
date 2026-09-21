"""A real-racing reference card for the gauntlet, from FastF1 timing data: the first N laps of a Grand Prix in the
same timing-screen format as tools/race_card.py --ref-format (lap chart, classification at lap N with gaps and best
laps, retirements, position changes per lap, lead changes, pit stops, lap-time spread). Car numbers are anonymised to
grid order (#1 = pole) so the card carries no names.

    python tools/ref_card_f1.py --year 2024 --gp Spain --laps 12 --out <dir>
"""
import argparse
import os
import statistics as st
import sys

# tools/queue.py shadows the standard library's queue module (urllib3 needs it): drop tools/ from the import path
sys.path[:] = [p for p in sys.path if not p.rstrip('\/').endswith('tools')]
import fastf1  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--gp", required=True, help="event name or round, e.g. Spain, Monza, 10")
    ap.add_argument("--laps", type=int, default=12, help="the first N laps of the race")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "gauntlet", "fastf1_cache"))
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "gauntlet", "refs"))
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True); os.makedirs(a.out, exist_ok=True)
    fastf1.Cache.enable_cache(a.cache)
    gp = int(a.gp) if a.gp.isdigit() else a.gp
    ses = fastf1.get_session(a.year, gp, "R")
    ses.load(telemetry=False, weather=False, messages=False)
    laps = ses.laps
    res = ses.results
    # anonymise: car number -> grid order
    grid = {}
    for _, r in res.iterrows():
        g = int(r["GridPosition"]) if r["GridPosition"] == r["GridPosition"] and r["GridPosition"] > 0 else 99
        grid[str(r["DriverNumber"])] = g
    order = sorted(grid, key=lambda d: grid[d])
    name = {d: f"#{k + 1}" for k, d in enumerate(order)}
    n = len(order)
    N = a.laps
    # per lap: position of each driver at the end of lap L, cumulative race time at the end of lap L
    pos = {}       # (driver, L) -> position
    t_end = {}     # (driver, L) -> seconds since race start
    ltime = {}     # driver -> [lap seconds]
    pits = 0
    starts = []
    for _, lp in laps.iterrows():
        d = str(lp["DriverNumber"]); L = int(lp["LapNumber"])
        if L > N:
            continue
        p = lp["Position"]
        if p == p:
            pos[(d, L)] = int(p)
        if lp["Time"] == lp["Time"]:
            t_end[(d, L)] = lp["Time"].total_seconds()
        lt = lp["LapTime"]
        if lt == lt and L >= 2:
            ltime.setdefault(d, []).append(lt.total_seconds())
        if lt == lt and L == 1 and lp["Time"] == lp["Time"]:
            starts.append(lp["Time"].total_seconds() - lt.total_seconds())   # the race start = lap 1 end - lap 1 time
        if lp["PitInTime"] == lp["PitInTime"] and L >= 1:
            pits += 1
    chart = {}
    for (d, L), p in pos.items():
        chart.setdefault(L, {})[p] = d
    # classification at lap N (or the last lap a driver completed within N)
    done = {d: max([L for (dd, L) in pos if dd == d] or [0]) for d in order}
    last_lap = max(chart) if chart else 0
    leader = chart.get(last_lap, {}).get(1)
    t_leader = t_end.get((leader, last_lap))
    cls = sorted([d for d in order if done[d] == last_lap], key=lambda d: pos[(d, last_lap)])
    lapped = sorted([d for d in order if 0 < done[d] < last_lap], key=lambda d: -done[d])
    # position changes per lap (a driver gaining places on a driver still running = an overtake, net per lap)
    changes = {}
    for L in range(2, last_lap + 1):
        k = 0
        for d in order:
            p0, p1 = pos.get((d, L - 1)), pos.get((d, L))
            if p0 and p1 and p1 < p0:
                k += p0 - p1
        changes[L] = k
    lead_changes = sum(1 for L in range(2, last_lap + 1) if chart.get(L, {}).get(1) != chart.get(L - 1, {}).get(1))
    dur = (t_leader - min(starts)) if (t_leader and starts) else (t_leader or 0)
    out = []
    out.append("# RACE")
    out.append(f"Formula, {ses.event['Location']}. {n} cars. {last_lap} laps completed by the leader in {dur // 60:.0f} min {dur % 60:.0f} s.")
    out.append("")
    out.append("## Lap chart (top 8, car numbers)")
    out.append("| lap | " + " | ".join(f"P{p}" for p in range(1, 9)) + " |")
    out.append("|---|" + "---|" * 8)
    for L in range(1, last_lap + 1):
        row = chart.get(L, {})
        out.append(f"| {L} | " + " | ".join(name[row[p]] if p in row else "-" for p in range(1, 9)) + " |")
    out.append("")
    out.append("## At the flag")
    lines = []
    for d in cls[:12]:
        g = t_end.get((d, last_lap))
        gtxt = "leader" if d == leader else (f"+{g - t_leader:.1f} s" if g and t_leader else "")
        best = min(ltime[d]) if d in ltime else None
        lines.append(f"P{pos[(d, last_lap)]} {name[d]} {gtxt}" + (f", best lap {best:.1f} s" if best else ""))
    out.append("; ".join(lines))
    ret = [d for d in order if done[d] < last_lap]
    out.append(f"Retired or off the lead lap: {len(ret)}" + (f" ({', '.join(name[d] for d in ret)})." if ret else "."))
    out.append("")
    out.append("## What happened")
    out.append(f"Overtakes for position (net, per lap): {sum(changes.values())} (" + ", ".join(f"lap {L}: {k}" for L, k in sorted(changes.items())) + ").")
    out.append(f"Lead changes: {lead_changes}.")
    out.append(f"Pit stops: {pits}.")
    meds = sorted(st.median(v) for v in ltime.values() if len(v) >= 3)
    if meds:
        out.append(f"Lap-time spread: median laps from {meds[0]:.1f} s (quickest car) to {meds[len(meds) // 2]:.1f} s (mid-field) to {meds[-1]:.1f} s (slowest).")
    card = "\n".join(out) + "\n"
    fn = os.path.join(a.out, f"f1_{a.year}_{str(gp).lower()}_{N}laps.md")
    open(fn, "w", encoding="utf-8").write(card)
    print(card); print("wrote", fn)


if __name__ == "__main__":
    main()
