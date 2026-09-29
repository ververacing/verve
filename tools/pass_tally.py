"""Passing scorecard for the passing-package A/B (spec 0151, section 6: P1, P2, P3, P5 and lead changes). Read-only.

    python tools/pass_tally.py "diag_race_*pk29_*.jsonl" [--group] [--gap 40] [--edge 0.005]

Each diag file is paired with its race feed (verve_feed/<stamp>_<track>.jsonl, the diag's timestamp; a feed file can
also be given directly). From the feed:
  real      `overtake` events with the passer on lap index 2+ (lapCount >= 2), not over a car that was yielding
            (verve.yield in the state at or one before the pass), a lap down, or in the pit lane (P1)
  fake      passes over a SAME-LAP car that was yielding (P5), from lap index 1 (the pace yield acts from there; "lap1" =
            how many of them were on lap index 1); `lapped` and `pit` passes (lap 2+) are counted apart
  ttp       time to pass (P2): a follower within --gap m of the next car ahead in race distance, same lap, whose best lap
            so far (feed `lap` events, laps 2+) is at least --edge quicker. Ends with a pass (5 m ahead), a fall-back
            (beyond 2 x gap), abandoned (pit / retire / park) or unresolved at the flag. Median over the passes
  lead      `lead_change` events
  attacks   P3's baseline: an attack episode opens when a car's state turns `attack` within 1.5 s of the car ahead in
            position (the feed's own `attack` decision test), passer on lap index 1+, same lap, neither car the player; its
            target is that car. `planned` if the car announces a plan (verve switchback / lunge / setup / slingshot /
            divebomb) while it lasts, else `plain`. Won = a pass on the target (not over a yielding, lapped or pit-lane car)
            within 20 s of the start and before the car's next episode
From the diag `mv` rows (lib/strategy.lua episodes, P3): attempts and wins per manoeuvre and per `how` (run / left /
abort / clear), strict (`won`: S.VERDICT_V2 when on) and legacy (`lw`, the old place-gained test). Rows from an
unpatched diag.lua carry neither: they are counted as `untagged`, the legacy column reads n/a and a warning is printed.

--group pools the runs of a label (trailing _<n> stripped): counts are summed, medians pooled over episodes.
"""
import argparse
import bisect
import glob
import json
import os
import re
import statistics
from collections import Counter, defaultdict

FEED_DIRS = [os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed"), "D:/verve_archive/verve_feed"]
TRACK_M = {"spa": 7004, "monza": 5793, "ks_barcelona": 4655, "ks_silverstone": 5891, "ks_brands_hatch": 3908,
           "ks_zandvoort": 4252, "ks_nurburgring": 5148}
PLANS = {"switchback", "lunge", "setup", "slingshot", "divebomb"}   # feed `verve` decisions that announce a plan (lib/feed.lua MV)
ATTACK_S = 1.5        # s to the car ahead: the feed's own `attack` decision test
ATTACK_WIN_S = 20.0   # s after an attack starts for a pass on its target to count (Strategy's VERDICT_T)


def stamp_of(p):
    m = re.search(r"(\d{8}_\d{6})", os.path.basename(p))
    return m.group(1) if m else None


def feed_for(p):
    """The race feed of a diag file: same stamp, else the nearest feed stamp within 10 s."""
    if not os.path.basename(p).startswith("diag_race_"):
        return p
    s = stamp_of(p)
    if not s:
        return None
    for d in FEED_DIRS:
        h = glob.glob(os.path.join(d, s + "_*.jsonl"))
        if h:
            return h[0]
    import datetime
    t0 = datetime.datetime.strptime(s, "%Y%m%d_%H%M%S")
    best = None
    for d in FEED_DIRS:
        for f in glob.glob(os.path.join(d, s[:8] + "_*.jsonl")):
            fs = stamp_of(f)
            try:
                dt = abs((datetime.datetime.strptime(fs, "%Y%m%d_%H%M%S") - t0).total_seconds())
            except (TypeError, ValueError):
                continue
            if dt <= 10 and (best is None or dt < best[0]):
                best = (dt, f)
    return best[1] if best else None


def label_of(p):
    b = os.path.basename(p)
    m = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", b)
    return m.group(1) if m else b[:-6]


def read_feed(path):
    hdr, states, events = None, [], []
    for line in open(path, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = d.get("type")
        if t == "header":
            hdr = d
        elif t == "state":
            states.append(d)
        elif t:
            events.append(d)
    return hdr, states, events


def track_len(hdr, states):
    k = (hdr or {}).get("track")
    if k in TRACK_M:
        return float(TRACK_M[k])
    vals, prev = [], {}
    for s in states:
        for c in s.get("cars", []):
            p = prev.get(c["i"])
            if p and c["spd"] > 60 and p[1]["spd"] > 60 and not c["pit"] and not p[1]["pit"]:
                dt, ds = s["t"] - p[0], (c["spline"] - p[1]["spline"]) % 1.0
                if 0.5 < dt < 1.6 and 0.001 < ds < 0.05:
                    vals.append((c["spd"] + p[1]["spd"]) / 2 / 3.6 * dt / ds)
            prev[c["i"]] = (s["t"], c)
    return statistics.median(vals) if len(vals) > 50 else 5000.0


def rd(c):
    return (c.get("lap") or 0) + (c.get("spline") or 0.0)


def yl(c):
    return bool(c and (c.get("verve") or {}).get("yield"))


def score_feed(feed, gap_m=40.0, edge=0.005):
    hdr, states, events = read_feed(feed)
    if len(states) < 10:
        return None
    L = track_len(hdr, states)
    ts = [s["t"] for s in states]
    grids = [{c["i"]: c for c in s.get("cars", [])} for s in states]
    player = next((c["i"] for c in (hdr or {}).get("cars", []) if c.get("player")), None)

    def at(t):
        k = bisect.bisect_right(ts, t + 0.05) - 1
        return (grids[k] if k >= 0 else {}), (grids[k - 1] if k >= 1 else {})

    out = Counter()
    for e in events:
        if e.get("type") == "lead_change":
            out["lead_changes"] += 1
        if e.get("type") != "overtake":
            continue
        out["overtakes_all"] += 1
        g, g0 = at(e["t"])
        a, b = g.get(e.get("car")), g.get(e.get("over"))
        if not a or not b or (a.get("lap") or 0) < 1:
            continue
        lap2p = (a.get("lap") or 0) >= 2            # P1 counts laps 2+; P5 (fake) has no lap limit, from lap index 1
        if lap2p:
            out["passes_lap2p"] += 1
        a0, b0 = g0.get(e.get("car")) or a, g0.get(e.get("over")) or b
        if a["pit"] or b["pit"] or a0["pit"] or b0["pit"]:
            out["passes_pit"] += lap2p
        elif rd(a) - rd(b) > 0.5:
            out["passes_lapped"] += lap2p
        elif yl(b) or yl(b0):
            out["passes_fake"] += 1
            out["passes_fake_lap1"] += not lap2p
        elif lap2p:
            out["passes_real"] += 1

    # P3 baseline: attack episodes, plain against planned, and how many ended with a pass on the target
    plan_t = defaultdict(list)
    for e in events:
        if e.get("type") == "verve" and e.get("decision") in PLANS:
            plan_t[e.get("car")].append(e["t"])
    open_att, atts = {}, []          # car -> [t0, target, t1]
    for s in states:
        t = s["t"]
        cars = {c["i"]: c for c in s.get("cars", [])}
        by_pos = {c.get("pos"): c for c in cars.values()}
        for i in list(open_att):
            c = cars.get(i)
            if not c or c["pit"] or (c.get("verve") or {}).get("state") != "attack":
                open_att[i][2] = t
                atts.append(open_att.pop(i))
        for i, c in cars.items():
            if i in open_att or i == player or c["pit"] or (c.get("lap") or 0) < 1:
                continue
            if (c.get("verve") or {}).get("state") != "attack":
                continue
            ga = c.get("gap_ahead_s")
            B = by_pos.get((c.get("pos") or 0) - 1)
            if ga is None or ga >= ATTACK_S or not B or B["i"] == player or B["pit"] or abs(rd(B) - rd(c)) > 0.5:
                continue
            open_att[i] = [t, B["i"], None, i]
    for i, ep in open_att.items():
        ep[2] = states[-1]["t"]
        atts.append(ep)
    starts = defaultdict(list)
    for t0, _, _, i in atts:
        starts[i].append(t0)
    passes = [(e["t"], e.get("car"), e.get("over")) for e in events if e.get("type") == "overtake"]
    for t0, tgt, t1, i in atts:
        planned = any(t0 - 1.0 <= pt_ <= t1 for pt_ in plan_t.get(i, []))
        end = min([t0 + ATTACK_WIN_S] + [s0 for s0 in starts[i] if s0 > t0])
        won = False
        for tp, a_, o_ in passes:
            if a_ == i and o_ == tgt and t0 <= tp <= end:
                g, g0 = at(tp)
                A, B = g.get(i), g.get(tgt)
                B0 = g0.get(tgt) or B
                if A and B and not (A["pit"] or B["pit"] or yl(B) or yl(B0)) and rd(A) - rd(B) <= 0.5:
                    won = True
                    break
        k = "att_plan" if planned else "att_plain"
        out[k] += 1
        out[k + "_won"] += won

    # time to pass
    laps = sorted((e["t"], e["car"], float(e["time_s"])) for e in events
                  if e.get("type") == "lap" and (e.get("lap") or 0) >= 2 and e.get("time_s"))
    best, li = {}, 0
    open_ep, eps = {}, []            # (A, B) -> t0 ; eps: (seconds, outcome, yielding-at-pass)
    for s, g in zip(states, grids):
        t = s["t"]
        while li < len(laps) and laps[li][0] <= t:
            _, car, lt = laps[li]
            best[car] = min(best.get(car, 1e9), lt)
            li += 1
        for key in list(open_ep):
            A, B = g.get(key[0]), g.get(key[1])
            if not A or not B or A["pit"] or B["pit"] or A["ret"] or B["ret"]:
                eps.append((t - open_ep.pop(key), "abandoned", False))
                continue
            d = (rd(B) - rd(A)) * L
            if d < -5:
                eps.append((t - open_ep.pop(key), "pass", yl(B)))
            elif d > 2 * gap_m:
                eps.append((t - open_ep.pop(key), "fell_back", False))
        run = sorted((c for c in g.values() if not c["ret"] and not c["pit"] and c["spd"] > 5), key=rd)
        for A, B in zip(run, run[1:]):
            if A["i"] == player or B["i"] == player:
                continue
            key = (A["i"], B["i"])
            d = (rd(B) - rd(A)) * L
            ba, bb = best.get(A["i"]), best.get(B["i"])
            if key not in open_ep and 0 < d < gap_m and ba and bb and ba <= bb * (1 - edge):
                open_ep[key] = t
    for key, t0 in open_ep.items():
        eps.append((states[-1]["t"] - t0, "unresolved", False))
    out["ttp_episodes"] = len(eps)
    for sec, how, y in eps:
        out["ttp_" + how] += 1
        if how == "pass" and y:
            out["ttp_pass_over_yield"] += 1
    return {"counts": out, "ttp": [sec for sec, how, _ in eps if how == "pass"], "track_m": L}


def verdicts(diag):
    c = Counter()
    if not os.path.basename(diag).startswith("diag_race_"):
        return c
    for line in open(diag, encoding="utf-8"):
        if '"ev":"mv"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        name, how = e.get("name", "?"), e.get("how") or "untagged"   # untagged: an unpatched diag.lua (no "how" / "lw")
        won = int(e.get("won", 0) or 0)
        lw = int(e.get("lw", 0) or 0)
        c["untagged_how"] += "how" not in e
        c["untagged_lw"] += "lw" not in e
        c["mv_%s" % name] += 1
        c["mv_%s_won" % name] += won
        c["mv_%s_lw" % name] += lw
        c["mv_%s_%s" % (name, how)] += 1
        c["mv_%s_%s_won" % (name, how)] += won
        c["mv_all"] += 1
        c["mv_all_won"] += won
        c["mv_all_lw"] += lw
        c["mv_how_%s" % how] += 1
    return c


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def fmt_row(label, c, ttp):
    share = pct(c["ttp_pass"], c["ttp_episodes"])
    med = statistics.median(ttp) if ttp else 0.0
    legacy = "n/a" if c["untagged_lw"] else "%3d" % c["mv_all_lw"]
    return ("%-34s real %3d  fake %2d (lap1 %d)  lapped %2d  pit %2d  (lap2+ %3d, all %3d)  lead %2d | ttp %3d eps, %3d passed (%3.0f%%) "
            "median %4.0f s, fell %3d, open %2d, lost %2d | mv %3d won %3d (legacy %s) | attacks plain %3d won %3d (%3.0f%%), "
            "planned %3d won %3d (%3.0f%%)" % (
                label[:34], c["passes_real"], c["passes_fake"], c["passes_fake_lap1"], c["passes_lapped"], c["passes_pit"], c["passes_lap2p"],
                c["overtakes_all"], c["lead_changes"], c["ttp_episodes"], c["ttp_pass"], share, med, c["ttp_fell_back"],
                c["ttp_unresolved"], c["ttp_abandoned"], c["mv_all"], c["mv_all_won"], legacy,
                c["att_plain"], c["att_plain_won"], pct(c["att_plain_won"], c["att_plain"]),
                c["att_plan"], c["att_plan_won"], pct(c["att_plan_won"], c["att_plan"])))


def mv_lines(c):
    names = sorted({k.split("_")[1] for k in c if k.startswith("mv_") and not k.startswith("mv_all") and not k.startswith("mv_how")})
    lines = []
    for n in names:
        a = c["mv_%s" % n]
        parts = ["%s: %d, won %d (%.0f%%), legacy %s" % (n, a, c["mv_%s_won" % n], 100.0 * c["mv_%s_won" % n] / a if a else 0,
                                                          "n/a" if c["untagged_lw"] else str(c["mv_%s_lw" % n]))]
        for how in ("run", "left", "abort", "clear", "untagged"):
            h = c["mv_%s_%s" % (n, how)]
            if h:
                parts.append("%s %d/%d" % (how, c["mv_%s_%s_won" % (n, how)], h))
        lines.append("      " + "  ".join(parts))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--group", action="store_true")
    ap.add_argument("--gap", type=float, default=40.0, help="m: a follower this close behind opens a time-to-pass episode (P2)")
    ap.add_argument("--edge", type=float, default=0.005, help="best-lap edge the follower needs (0.005 = 0.5 %%)")
    ap.add_argument("--mv", action="store_true", help="print the manoeuvre split per race too")
    a = ap.parse_args()
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    groups = defaultdict(lambda: [Counter(), [], 0])
    for p in sorted(set(paths)):
        feed = feed_for(p)
        r = score_feed(feed, a.gap, a.edge) if feed and os.path.exists(feed) else None
        c = Counter(r["counts"]) if r else Counter()
        c.update(verdicts(p))
        lab = label_of(p)
        if not r:
            print("%-34s (no race feed found: verdicts only)" % lab[:34])
        if c["untagged_how"] or c["untagged_lw"]:
            print("%-34s !! %d of %d mv rows carry no how/lw (diag.lua not patched): the how split and legacy wins are n/a" % (
                lab[:34], max(c["untagged_how"], c["untagged_lw"]), c["mv_all"]))
        print(fmt_row(lab, c, r["ttp"] if r else []))
        if a.mv:
            for line in mv_lines(c):
                print(line)
        gk = re.sub(r"_\d+$", "", lab)
        groups[gk][0].update(c)
        groups[gk][1] += r["ttp"] if r else []
        groups[gk][2] += 1
    if a.group:
        print("\n-- pooled by label (counts summed over the runs) --")
        for k in sorted(groups):
            c, ttp, n = groups[k]
            print(fmt_row("%s x%d" % (k, n), c, ttp))
            for line in mv_lines(c):
                print(line)


if __name__ == "__main__":
    main()
