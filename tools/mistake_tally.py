"""Visible-mistake scorecard (lib/human.lua H.MISTAKE_V2) for the mv29 lines (spec 0151, section 6 'Mistakes'). Read-only.

    python tools/mistake_tally.py "diag_race_*mv29_*.jsonl" [--group] [--profiles all=arch_midfield,2=arch_rookie,...] [--level 100]

Each diag file is paired with its race feed (verve_feed/<stamp>_<track>.jsonl by the diag's timestamp; a feed file can be
given directly). Slot 0 (the harness autopilot) is left out everywhere. Per race, by tier:
  rate      visible mistakes per car-lap, lap index 1+ (car-laps = race distance past the first lap), shown as laps per
            mistake next to the model's own laps_per (mistake_model events); drops = mistake_drop / (fired + dropped)
  own       own_moment share of the fired mistakes (a forced kind always reads 100 %)
  cost      the mistake lap's time minus the car's median clean lap (laps 2+ with no mistake, incident, off or pit stop),
            laps with exactly one mistake; median per kind and the share costing 0.25 s or more
  offs      the mistake car's off_track within 5 s (ordinary / big = the event's "off"), per 100 car-laps
  spins     a 1 Hz state under 40 % of the previous sample's speed (that one above 40 km/h) within 5 s of a mistake
  passed    an overtake with over = the mistake car within 8 s, over the mistakes that had a rival behind (behind >= 0)
  incidents incident events of the mistake car (or naming it in contact) within 5 s
  sd        lap-time SD of each car's clean laps (laps 2+), median per tier - control arms too
Tiers: the model's own (the mistake_model events) where V2 ran; otherwise --profiles (archetype and roster keys, the tier
V2 would give them) and --level for the unprofiled rest (100 = veteran, 90 = midfield, 80 = rookie, as V2 reads a level).
"""
import argparse
import glob
import json
import os
import re
import statistics
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
FEED_DIRS = [os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed"), "D:/verve_archive/verve_feed"]
TIERS = ["rookie", "midfield", "veteran", "top", "wild", "?"]
KINDS = ["lockup", "missed_apex", "lift", "spin"]


def stamp_of(p):
    m = re.search(r"(\d{8}_\d{6})", os.path.basename(p))
    return m.group(1) if m else None


def feed_for(p):
    if not os.path.basename(p).startswith("diag_race_"):
        return p
    s = stamp_of(p)
    for d in FEED_DIRS:
        h = glob.glob(os.path.join(d, (s or "?") + "_*.jsonl"))
        if h:
            return h[0]
    return None


def label_of(p):
    m = re.match(r"diag_race_\d{8}_\d{6}_(.+)\.jsonl$", os.path.basename(p))
    return m.group(1) if m else os.path.basename(p)[:-6]


# ---- tiers for arms without mistake_model events (V2's own rule: lib/human.lua H.mvSkill)
def roster():
    """key -> (bucket, pace, wild) from lib/drivers.lua D.DRIVERS."""
    out = {}
    try:
        src = open(os.path.join(HERE, "..", "lib", "drivers.lua"), encoding="utf-8").read()
    except OSError:
        return out
    for m in re.finditer(r"\{\s*key\s*=\s*'([^']+)'(.*?)\}", src):
        body = m.group(2)
        b = re.search(r"bucket\s*=\s*'([^']+)'", body)
        p = re.search(r"pace\s*=\s*([\d.]+)", body)
        if b and p:
            out[m.group(1)] = (b.group(1), float(p.group(1)), "wild=true" in body.replace(" ", ""))
    return out


def tier_of_pace(pace, top=False):
    if top:
        return "top"
    return "rookie" if pace < 0.45 else ("midfield" if pace < 0.725 else ("veteran" if pace < 0.90 else "top"))


def profile_tiers(spec, n, level, ros):
    unprof = tier_of_pace(min(0.85, max(0.30, 0.90 - (100 - level) * 0.5 / 16.67)))
    keys = {}
    for part in (spec or "").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "all":
            for i in range(n):
                keys[i] = v
        elif ".." in k:
            a, b = k.split("..")
            for i in range(int(a), int(b) + 1):
                keys[i] = v
        else:
            keys[int(k)] = v
    tops = {}
    for key, (bucket, pace, wild) in ros.items():
        if bucket != "archetype" and not wild:
            tops.setdefault(bucket, []).append(pace)
    th = {b: sorted(ps, reverse=True)[max(0, -(-len(ps) // 10) - 1)] for b, ps in tops.items()}
    out = {}
    for i in range(n):
        v = keys.get(i)
        if v is None or v not in ros:
            out[i] = unprof if v is None else "?"
            continue
        bucket, pace, wild = ros[v]
        out[i] = "wild" if wild else tier_of_pace(pace, bucket != "archetype" and pace >= th.get(bucket, 9))
    return out


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


def analyse(feed, spec, level, ros):
    hdr, states, events = read_feed(feed)
    if len(states) < 10:
        return None
    n = len((hdr or {}).get("cars", [])) or max(c["i"] for s in states for c in s["cars"]) + 1
    skip = {0} | {c["i"] for c in (hdr or {}).get("cars", []) if c.get("player")}
    tier = profile_tiers(spec, n, level, ros)
    model = {}
    for e in events:
        if e.get("type") == "mistake_model":
            model[e["car"]] = e
            tier[e["car"]] = e.get("tier", tier.get(e["car"], "?"))
    # exposure: race distance past the first lap
    rdmax = defaultdict(float)
    speeds = defaultdict(list)            # car -> [(t, spd)]
    for s in states:
        for c in s["cars"]:
            rdmax[c["i"]] = max(rdmax[c["i"]], (c.get("lap") or 0) + (c.get("spline") or 0))
            speeds[c["i"]].append((s["t"], c.get("spd") or 0))
    by = lambda k: [e for e in events if e.get("type") == k and e.get("car") not in skip]
    mistakes, drops, laps = by("mistake"), by("mistake_drop"), by("lap")
    offs, incs, overt = by("off_track"), [e for e in events if e.get("type") == "incident"], [e for e in events if e.get("type") == "overtake"]
    pits = [e for e in events if e.get("type") in ("pit_in", "pit_out")]
    # laps: (car, lapnum) -> (t_end, seconds); a lap is dirty with a mistake, incident, off or pit event inside it
    lapT = {(e["car"], e["lap"]): (e["t"], float(e["time_s"])) for e in laps if e.get("time_s")}
    mistake_laps = Counter((m["car"], (m.get("lap") or 0) + 1) for m in mistakes)
    dirty_ev = [(e["car"], e["t"]) for e in offs + pits] + [(e["car"], e["t"]) for e in incs] + \
               [(int(x), e["t"]) for e in incs for x in (e.get("contact") or [])]

    def dirty(car, lapnum):
        t1, sec = lapT[(car, lapnum)]
        return mistake_laps[(car, lapnum)] > 0 or any(c == car and t1 - sec < t <= t1 for c, t in dirty_ev)
    clean = defaultdict(list)
    for (car, ln), (t1, sec) in lapT.items():
        if ln >= 2 and car not in skip and not dirty(car, ln):
            clean[car].append(sec)
    med = {c: statistics.median(v) for c, v in clean.items() if len(v) >= 2}

    R = {"cnt": Counter(), "cost": defaultdict(list), "sd": defaultdict(list), "laps": Counter(), "model": defaultdict(list)}
    cnt = R["cnt"]
    for car, rd in rdmax.items():
        if car in skip:
            continue
        R["laps"][tier.get(car, "?")] += max(0.0, rd - 1.0)
        if len(clean.get(car, [])) >= 3:
            R["sd"][tier.get(car, "?")].append(statistics.pstdev(clean[car]))
    for car, e in model.items():
        if car not in skip:
            R["model"][tier.get(car, "?")].append(e.get("laps_per") or 0)
    cnt["drops"] = len(drops)
    for d in drops:
        cnt["drop_" + str(d.get("why"))] += 1
    for m in mistakes:
        car, t, tr, kind = m["car"], m["t"], tier.get(m["car"], "?"), m.get("kind", "?")
        cnt["n"] += 1
        cnt["n_" + tr] += 1
        cnt["k_" + kind] += 1
        cnt["own"] += m.get("own_moment") is True
        big = m.get("off") is True
        cnt["big"] += big
        if any(o["car"] == car and 0 <= o["t"] - t <= 5 for o in offs):
            cnt["off_big" if big else "off_ord"] += 1
            cnt["off_" + tr] += 1
        sp = [(ts, v) for ts, v in speeds.get(car, []) if t - 1.5 <= ts <= t + 5]
        if any(b[1] < 0.4 * a[1] and a[1] > 40 and b[0] > t for a, b in zip(sp, sp[1:])):
            cnt["spin"] += 1
            cnt["spin_" + tr] += 1
        if any((e.get("car") == car or car in [int(x) for x in (e.get("contact") or [])]) and 0 <= e["t"] - t <= 5 for e in incs):
            cnt["inc5"] += 1
        if (m.get("behind") if m.get("behind") is not None else -1) >= 0:
            cnt["rival_behind"] += 1
            if any(o.get("over") == car and 0 <= o["t"] - t <= 8 for o in overt):
                cnt["passed"] += 1
        ln = (m.get("lap") or 0) + 1
        if mistake_laps[(car, ln)] == 1 and (car, ln) in lapT and car in med:
            R["cost"][kind].append(lapT[(car, ln)][1] - med[car])
    return R


def merge(a, b):
    a["cnt"].update(b["cnt"])
    a["laps"].update(b["laps"])
    for k in ("cost", "sd", "model"):
        for kk, v in b[k].items():
            a[k][kk] += v


def show(label, R):
    c, laps = R["cnt"], R["laps"]
    fired = c["n"]
    tot = sum(laps.values())
    print("== %s: %d mistakes over %.0f car-laps (%.1f laps each), drops %d (%.0f%% of draws: %s), own moment %.0f%%" % (
        label, fired, tot, tot / fired if fired else 0, c["drops"], 100.0 * c["drops"] / max(1, fired + c["drops"]),
        ", ".join("%s %d" % (k[5:], v) for k, v in sorted(c.items()) if k.startswith("drop_")) or "-", 100.0 * c["own"] / max(1, fired)))
    print("   kinds: " + "  ".join("%s %d" % (k, c["k_" + k]) for k in KINDS) +
          " | big %d | offs: ordinary %d (%.1f%% of ordinary), big %d | spins %d | incidents within 5 s %d | passed within 8 s %d of %d with a rival behind (%.0f%%)" % (
              c["big"], c["off_ord"], 100.0 * c["off_ord"] / max(1, fired - c["big"]), c["off_big"], c["spin"], c["inc5"],
              c["passed"], c["rival_behind"], 100.0 * c["passed"] / max(1, c["rival_behind"])))
    for tr in TIERS:
        if laps[tr] <= 0 and not c["n_" + tr]:
            continue
        nt, lt = c["n_" + tr], laps[tr]
        mp = R["model"].get(tr) or []
        sd = R["sd"].get(tr) or []
        print("   %-8s %6.0f car-laps  %4d mistakes = 1 per %5.1f laps (model %s)  offs %.2f / 100 laps  spins %d  clean-lap SD %s" % (
            tr, lt, nt, lt / nt if nt else 0, ("%.1f" % statistics.median(mp)) if mp else "-", 100.0 * c["off_" + tr] / lt if lt else 0,
            c["spin_" + tr], ("%.2f s (n %d)" % (statistics.median(sd), len(sd))) if sd else "-"))
    for k in KINDS:
        v = R["cost"].get(k) or []
        if v:
            print("   cost %-12s median %+.2f s over %d single-mistake laps, %.0f%% >= 0.25 s" % (
                k, statistics.median(v), len(v), 100.0 * sum(1 for x in v if x >= 0.25) / len(v)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--group", action="store_true", help="pool a label's runs (trailing _<n> stripped)")
    ap.add_argument("--profiles", default="", help="the harness --profiles string, for arms without mistake_model events")
    ap.add_argument("--level", type=float, default=100, help="the harness --ai-level (the tier of the unprofiled cars)")
    a = ap.parse_args()
    paths = []
    for f in a.files:
        paths += glob.glob(f) or [f]
    ros = roster()
    groups = {}
    for p in sorted(set(paths)):
        feed = feed_for(p)
        if not feed or not os.path.exists(feed):
            print("== %s: no race feed found" % label_of(p))
            continue
        R = analyse(feed, a.profiles, a.level, ros)
        if not R:
            continue
        show(label_of(p), R)
        k = re.sub(r"_\d+$", "", label_of(p))
        if k in groups:
            merge(groups[k][0], R)
            groups[k][1] += 1
        else:
            groups[k] = [R, 1]
    if a.group:
        print("\n---- pooled by label ----")
        for k in sorted(groups):
            show("%s x%d" % (k, groups[k][1]), groups[k][0])


if __name__ == "__main__":
    main()
