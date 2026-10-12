"""Find 'stuck behind' and 'stuck behind, then passes' moments in a race feed (verve_feed/*.jsonl), for broadcast clips.

A follow = car B running directly behind car A (B's position = A's + 1) within FOLLOW_S seconds, second by second from the
1 Hz state rows. It ends when the gap opens past END_S, when B passes A (an overtake event, or the positions swap), or
when either car pits or retires. Pace = each car's median lap time over laps 2+ (the lap events), so 'quick' means B's
own race pace beats A's.

Printed per race, best first:
  PASSED  - follows that ended with B passing A, B quicker, lasting MIN_S+ seconds, no incident for either car within
            5 s of the pass (the clean 'stuck behind, then passes')
  STUCK   - the longest follows where B is quicker and never got by (the stock-AI problem)
Both skip a pace gap over MAX_EDGE s/lap or a car with damage >= MAX_DMG (a crippled car being passed is not the clip).
Times are seconds from the race start marker (the launch) and the feed's own clock; lap and spline locate it on track.

Usage: python tools/follow_finder.py FEED.jsonl [FEED2.jsonl ...] [--top 5] [--min-s 8]"""
import argparse
import json
import statistics
import sys

FOLLOW_S, END_S = 1.0, 1.6
MAX_EDGE, MAX_DMG = 5.0, 40   # a bigger pace gap or a damaged car is a crippled car being passed, not a quick car held up


def load(path):
    header, states, laps, overtakes, incidents, start_t = None, [], {}, [], [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "header":
            header = e
        elif t == "state":
            states.append(e)
        elif t == "lap" and e.get("time_s") and e.get("lap", 0) >= 2:
            laps.setdefault(e["car"], []).append(e["time_s"])
        elif t == "overtake":
            overtakes.append(e)
        elif t == "incident":
            incidents.append(e)
        elif t == "race_start" and start_t is None:
            start_t = e["t"]
    return header, states, laps, overtakes, incidents, start_t or 0.0


def episodes(states):
    """Yield (a, b, t0, t1, rows) follows: b directly behind a within FOLLOW_S, ended by a gap, a pass or a pit/retire."""
    open_ep, done = {}, []
    for s in states:
        by_pos = {c["pos"]: c for c in s.get("cars", []) if not c.get("pit") and not c.get("ret")}
        now = set()
        for pos, b in by_pos.items():
            a = by_pos.get(pos - 1)
            g = b.get("gap_ahead_s")
            if a is None or g is None:
                continue
            key = (a["i"], b["i"])
            if key in open_ep:
                if g <= END_S:
                    open_ep[key]["t1"] = s["t"]; open_ep[key]["gaps"].append(g); open_ep[key]["lap"] = b.get("lap"); now.add(key)
                    open_ep[key]["dmg"] = max(open_ep[key]["dmg"], a.get("dmg") or 0, b.get("dmg") or 0)
            elif g <= FOLLOW_S:
                open_ep[key] = {"a": a["i"], "b": b["i"], "t0": s["t"], "t1": s["t"], "gaps": [g], "lap0": b.get("lap"),
                                "sp0": b.get("spline"), "lap": b.get("lap"), "dmg": 0}
                now.add(key)
        for key in list(open_ep):
            if key not in now:
                done.append(open_ep.pop(key))
    done.extend(open_ep.values())
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feeds", nargs="+")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-s", type=float, default=8.0)
    a = ap.parse_args()
    for path in a.feeds:
        header, states, laps, overtakes, incidents, t_start = load(path)
        cars = {c["i"]: c for c in (header or {}).get("cars", [])}
        name = lambda i: f"#{i} {cars.get(i, {}).get('driver', '?')} ({cars.get(i, {}).get('model', '?').replace('ks_', '')})"
        pace = {i: statistics.median(v) for i, v in laps.items() if len(v) >= 2}
        eps = episodes(states)
        passed, stuck = [], []
        for ep in eps:
            dur = ep["t1"] - ep["t0"]
            pa, pb = pace.get(ep["a"]), pace.get(ep["b"])
            edge = (pa - pb) if pa and pb else None          # > 0: the follower is quicker
            ep.update(dur=dur, edge=edge, gap=statistics.median(ep["gaps"]))
            ov = [o for o in overtakes if o["car"] == ep["b"] and o.get("over") == ep["a"] and ep["t0"] <= o["t"] <= ep["t1"] + 3]
            if ov:
                tp = ov[0]["t"]
                dirty = [x for x in incidents if abs(x["t"] - tp) <= 5 and ({x["car"], x.get("other")} & {ep["a"], ep["b"]})]
                ep.update(pass_t=tp, pass_spline=ov[0].get("spline"), dirty=bool(dirty))
                if dur >= a.min_s and edge is not None and 0 < edge <= MAX_EDGE and ep["dmg"] < MAX_DMG and not dirty and (ep["lap0"] or 0) >= 1:
                    passed.append(ep)
            elif edge is not None and 0.2 < edge <= MAX_EDGE and ep["dmg"] < MAX_DMG and (ep["lap0"] or 0) >= 1:
                stuck.append(ep)
        rel = lambda t: f"{t - t_start:6.0f}s from start (feed t {t:.0f})"
        print(f"== {path.replace(chr(92), '/').split('/')[-1]}  cars {len(cars)}  follows {len(eps)}  passes-after-follow {len(passed)}  quick-stuck {len(stuck)}")
        print("  PASSED (quicker car stuck, then clean pass):")
        for ep in sorted(passed, key=lambda e: (-(e['edge'] or 0) * min(e['dur'], 40)))[:a.top]:
            print(f"    {rel(ep['t0'])}  lap {ep['lap0']} spline {ep['sp0']:.3f}: {name(ep['b'])} behind {name(ep['a'])} for {ep['dur']:.0f} s "
                  f"(median gap {ep["gap"]:.2f} s, pace edge {ep["edge"]:.2f} s/lap, max dmg {ep["dmg"]}), passes at {ep['pass_t'] - t_start:.0f}s spline {ep['pass_spline']}")
        print("  STUCK (quicker car never got by):")
        for ep in sorted(stuck, key=lambda e: -e["dur"])[:a.top]:
            print(f"    {rel(ep['t0'])}  lap {ep['lap0']}-{ep['lap']} spline {ep['sp0']:.3f}: {name(ep['b'])} behind {name(ep['a'])} for {ep['dur']:.0f} s "
                  f"(median gap {ep["gap"]:.2f} s, pace edge {ep["edge"]:.2f} s/lap, max dmg {ep["dmg"]})")


if __name__ == "__main__":
    main()
