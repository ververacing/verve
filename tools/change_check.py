"""Mid-session changes: does anything go wonky when settings or driver profiles change on the grid or halfway through a race?
Read-only. Scores harness races run with --changes (Verve.lua logs a `harness_change` feed event at each change).

    python tools/change_check.py "diag_race_*_mc15_*.jsonl"

Each race is split into windows at its changes. Per window:
  laps      the field's median lap (AC's lap_ms), laps 2+, no pit laps
  slow      car-laps over 110 % of that car's own median in the first window (a pace jump after a change)
  capped    car-laps whose top speed stays under 85 % of that car's usual top speed (a cap left behind), no pit / incident laps
  refuel    a car's fuel up by more than 3 L between two 8 s snapshots outside the pit lane, 30 s or more after the start
            (a green load written mid-race)
  level     the median AI level (diag lvl), so a profile or on/off change shows as a step
  inc, offs, stuck, pits, retire   feed events in the window
"""
import collections
import glob
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
FEEDS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")


def feed_for(stamp):
    try:
        names = sorted(n for n in os.listdir(FEEDS) if n >= stamp and n.endswith(".jsonl"))
    except OSError:
        return None
    return os.path.join(FEEDS, names[0]) if names and names[0][:13] == stamp[:13] else None


def load_feed(path):
    hdr, ev, states = None, [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ty = d.get("type")
        if ty == "header":
            hdr = d
        elif ty == "state":
            states.append(d)
        elif ty:
            ev.append(d)
    return hdr, ev, states


def med(v):
    return st.median(v) if v else None


def check(diag):
    stamp = os.path.basename(diag)[10:25]
    fp = feed_for(stamp)
    if not fp:
        print("  no feed for", stamp)
        return
    hdr, ev, states = load_feed(fp)
    player = next((c["i"] for c in (hdr or {}).get("cars", []) if c.get("player")), 0)
    ch = [e for e in ev if e.get("type") == "harness_change"]
    edges = [0.0] + [e["t"] for e in ch] + [1e12]
    names = ["start"] + ["after %d %s (lap %s, %.0f s)" % (e.get("n"), e.get("label", ""), e.get("lap"), e.get("t_race", 0)) for e in ch]

    def win(t):
        for k in range(len(edges) - 1):
            if edges[k] <= t < edges[k + 1]:
                return k
        return len(edges) - 2
    # laps per car: (window, lap, seconds, t_end)
    laps = collections.defaultdict(list)
    for e in ev:
        if e.get("type") == "lap" and e.get("car") != player:
            s = (e["lap_ms"] / 1000.0) if e.get("lap_ms") else e.get("time_s")
            if s and s > 20:
                laps[e["car"]].append((win(e["t"]), e.get("lap"), s, e["t"]))
    pitlap, inclap = set(), set()
    for e in ev:
        if e.get("type") in ("pit_in", "pit_out"):
            pitlap.add((e.get("car"), e.get("lap"))); pitlap.add((e.get("car"), (e.get("lap") or 0) + 1))
    # top speed per car-lap from the 1 Hz states
    top = collections.defaultdict(float)
    for s in states:
        for c in s.get("cars", []):
            if c.get("pit"):
                pitlap.add((c["i"], c.get("lap", 0) + 1))
            k = (c["i"], c.get("lap", 0) + 1)
            top[k] = max(top[k], c.get("spd") or 0)
    for e in ev:
        if e.get("type") == "incident":
            for car in [e.get("car")] + list(e.get("contact") or []):
                # the lap in progress at the incident: the next lap event of that car
                nxt = [l for (w, l, s, t) in laps.get(car, []) if t >= e["t"]]
                if nxt:
                    inclap.add((car, min(nxt)))
    base = {c: med([s for (w, l, s, t) in v if w == 0 and (l or 0) >= 2 and (c, l) not in pitlap]) for c, v in laps.items()}
    usual = {}
    for (car, lap), v in top.items():
        if lap >= 2 and (car, lap) not in pitlap:
            usual.setdefault(car, []).append(v)
    usual = {c: med(v) for c, v in usual.items()}
    # diag: fuel jumps and levels
    snaps = []
    for line in open(diag, encoding="utf-8", errors="replace"):
        if line.startswith('{"t"'):
            try:
                snaps.append(json.loads(line))
            except ValueError:
                pass
    t0 = snaps[0]["t"] if snaps else 0
    ft0 = (states[0]["t"] if states else 0)
    rs = next((e["t"] for e in ev if e.get("type") == "race_start"), ft0)
    refuel = collections.Counter()
    lvl = collections.defaultdict(list)
    prev = {}
    for s in snaps:
        # diag t is wall seconds; map to feed time by offset from the first snapshot / first state (both ~race load)
        tf = ft0 + (s["t"] - t0)
        tw = win(tf)
        for c in s.get("grid", []):
            i = c.get("i")
            if i == player:
                continue
            if c.get("lvl", -100) > 0:
                lvl[tw].append(c["lvl"])
            f = c.get("fuel")
            if f is not None and i in prev and not c.get("pit") and f > prev[i] + 3 and tf > rs + 30:   # (the green load itself is at the start)
                refuel[tw] += 1
            if f is not None:
                prev[i] = f
    print("  feed", os.path.basename(fp), "| changes:", len(ch))
    print("  %-34s %6s %5s %6s %6s %6s %4s %4s %5s %5s %6s" % ("window", "lap_s", "slow", "capped", "refuel", "level", "inc", "offs", "stuck", "pits", "retire"))
    for k in range(len(edges) - 1):
        ls = [s for c, v in laps.items() for (w, l, s, t) in v if w == k and (l or 0) >= 2 and (c, l) not in pitlap]
        slow = sum(1 for c, v in laps.items() for (w, l, s, t) in v
                   if w == k and (l or 0) >= 2 and base.get(c) and (c, l) not in pitlap and (c, l) not in inclap and s > 1.10 * base[c])
        capped = 0
        for c, v in laps.items():
            for (w, l, s, t) in v:
                if w == k and (l or 0) >= 2 and (c, l) not in pitlap and (c, l) not in inclap and usual.get(c) and top.get((c, l), 0) < 0.85 * usual[c]:
                    capped += 1
        cnt = collections.Counter(e.get("type") for e in ev if edges[k] <= e["t"] < edges[k + 1])
        lv = med(lvl.get(k, []))
        print("  %-34s %6s %5d %6d %6d %6s %4d %4d %5d %5d %6d" % (
            names[k][:34], ("%.2f" % med(ls)) if ls else "-", slow, capped, refuel[k], ("%.0f" % lv) if lv else "-",
            cnt["incident"], cnt["off_track"], cnt["stuck"], cnt["pit_in"], cnt["retire"]))


def main():
    files = []
    for p in sys.argv[1:] or ["diag_race_*_mc15_*.jsonl"]:
        files += sorted(glob.glob(p if os.path.isabs(p) else os.path.join(VERVE, p)))
    for p in files:
        print(os.path.basename(p))
        try:
            check(p)
        except Exception as e:   # one bad file must not hide the rest
            print("  error:", e)


if __name__ == "__main__":
    main()
