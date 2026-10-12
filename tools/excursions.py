"""Separate REAL EXCURSIONS from wide lines and chicane cuts, per corner, from the race feed.

    python tools/excursions.py spa                      # every spa feed, one row per race
    python tools/excursions.py spa --label c2_spa12     # only races whose diag label contains this
    python tools/excursions.py spa --bands              # also print the speed map (which band is which corner)

WHY THIS EXISTS. A raw off_track count ranks troublespots WRONGLY. At Spa, wide-running outnumbers real excursions
about four to one, so the biggest count (Raidillon exit) is cars running marginally wide and carrying on, while the
genuine ones (Les Combes, the Bus Stop) are smaller. I withdrew a finding over that on 2026-10-12 and PC #2 withdrew
one the same morning. The discriminator is SPEED: a cut or a wide line holds the band speed, an excursion collapses
and stays collapsed.

THIS FILE IS THE DEFINITION, not a prose spec - both machines run it so the columns cannot drift apart.
  an EXCURSION = an off_track where the car is below the threshold AT the event (median of the state samples within
  +/-1.5 s) AND still below it 3-8 s LATER (median of the samples in that window, NOT a single point at t+8: states
  are 1 Hz, so one sample is noise and may be missing entirely).
  TWO thresholds, because an absolute one is track-position dependent - PC #2 raised this, and it is right: the Bus
  Stop's own speed is ~71 km/h, so a benign cut there is already under an absolute 90.
    ABS  below 90 km/h            - comparable across tracks, unreliable in slow corners
    REL  below 60 % of that band's own median speed - correct in slow corners, needs enough samples in the band
  If the two disagree about a band, believe REL and say which you quoted.

RATES are per 100 CAR-LAPS, with ALL-LAPS and LAP-2+ separate: lap 0-1 is 17 % of a 12-lap race but 3 % of a 60-lap
one, so the all-laps figure flatters whoever ran shorter races.

SPREAD: on two arm-identical clean Spa GT3 races this metric gave 3.89 and 1.11 lap-2+ excursions per 100 car-laps -
a 3.5x spread on nothing. Use three runs a side; one race cannot carry a reference. Check comparability first with
tools/arm_check.py.
"""
import collections
import glob
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
FEEDS = os.path.join(DOCS, "verve_feed")

ABS_KMH = 90.0
REL_FRAC = 0.60
BAND = 0.02


def band_of(s):
    return round(s / BAND) * BAND


def read_feed(path):
    """(offs, speed samples per car, speed samples per band, max leader lap, cars, leader-lap timeline)."""
    st = collections.defaultdict(list)
    bysp = collections.defaultdict(list)
    offs, leader = [], []
    maxlap, ncars = 0, 0
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue          # a half-written tail line while the race is still running
                ty = d.get("type")
                if ty == "header":
                    cs = d.get("cars")
                    ncars = len(cs) if isinstance(cs, list) else 0
                elif ty == "state":
                    t, lap = d.get("t"), d.get("leader_lap")
                    if t is not None and isinstance(lap, (int, float)):
                        leader.append((t, lap))
                        if lap > maxlap:
                            maxlap = lap
                    for c in (d.get("cars") or []):
                        v, s = c.get("spd"), c.get("spline")
                        if isinstance(v, (int, float)):
                            st[c.get("i")].append((t, v))
                            if isinstance(s, (int, float)) and v > 5:
                                bysp[band_of(s)].append(v)
                elif ty == "off_track" and isinstance(d.get("spline"), (int, float)):
                    offs.append((d.get("car"), d.get("t"), d["spline"]))
    except OSError:
        return None
    return offs, st, bysp, maxlap, ncars, leader


def classify(path):
    r = read_feed(path)
    if not r:
        return None
    offs, st, bysp, maxlap, ncars, leader = r
    bmed = {b: statistics.median(v) for b, v in bysp.items() if len(v) >= 30}
    cars = max(ncars, 1)
    out = dict(maxlap=maxlap, ncars=ncars, n_off=len(offs), wide=0, unjoined=0,
               exc_abs=collections.Counter(), exc_rel=collections.Counter(), abs_l2=0, rel_l2=0,
               carlaps=maxlap * cars, carlaps_l2=max(0, maxlap - 2) * cars, bands=bmed)

    def lap_at(t):
        best = 0
        for tt, lap in leader:
            if tt is not None and t is not None and tt <= t:
                best = lap
        return best

    for car, t, s in offs:
        sm = st.get(car) or []
        at = [v for (tt, v) in sm if tt is not None and t is not None and abs(tt - t) <= 1.5]
        later = [v for (tt, v) in sm if tt is not None and t is not None and 3 <= (tt - t) <= 8]
        if not at:
            out["unjoined"] += 1
            continue
        a = statistics.median(at)
        n = statistics.median(later) if later else a
        b = band_of(s)
        ref = bmed.get(b)
        is_abs = a < ABS_KMH and n < ABS_KMH
        is_rel = ref is not None and a < REL_FRAC * ref and n < REL_FRAC * ref
        if is_abs:
            out["exc_abs"][b] += 1
            if lap_at(t) >= 2:
                out["abs_l2"] += 1
        if is_rel:
            out["exc_rel"][b] += 1
            if lap_at(t) >= 2:
                out["rel_l2"] += 1
        if not is_abs and not is_rel:
            out["wide"] += 1
    return out


def label_for(stem):
    pats = [os.path.join(VERVE, "diag_race_" + stem + "*"),
            os.path.join(VERVE, "tools", "harness_results", "archive", "diag_race_" + stem + "*")]
    for pat in pats:
        for d in glob.glob(pat):
            b = os.path.basename(d).replace("diag_race_", "").replace(".jsonl", "")
            parts = b.split("_")
            return "_".join(parts[3:]) if len(parts) > 3 else b
    return stem


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[0])
        return 2
    track = args[0]
    want = None
    for i, a in enumerate(sys.argv):
        if a == "--label" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1]
    rows = []
    for p in sorted(glob.glob(os.path.join(FEEDS, "*" + track + "*.jsonl"))):
        lab = label_for(os.path.basename(p)[:15])
        if want and want not in lab:
            continue
        c = classify(p)
        if c and c["maxlap"]:
            rows.append((lab, c))
    if not rows:
        print("excursions: no %s feeds matched%s" % (track, " --label " + want if want else ""))
        return 1
    if "--bands" in sys.argv:
        bm = max((c["bands"] for _, c in rows), key=len)
        print("speed map, median km/h per %.2f band (a local minimum is a braking zone):" % BAND)
        for b in sorted(bm):
            print("   %.2f  %6.1f" % (b, bm[b]))
        print()
    print("EXCURSION = below threshold at the off AND still below it 3-8 s later (medians, never a single point).")
    print("ABS = under %.0f km/h. REL = under %.0f%% of that band's median. Rates per 100 car-laps.\n"
          % (ABS_KMH, 100 * REL_FRAC))
    print("%-26s %5s %5s %6s %7s %7s %10s %9s" % ("label", "laps", "offs", "wide", "excAbs", "excRel", "abs/100cl", "L2/100cl"))
    tot = collections.Counter()
    per_race = []
    for lab, c in rows:
        ea, er = sum(c["exc_abs"].values()), sum(c["exc_rel"].values())
        rate = 100.0 * ea / max(c["carlaps"], 1)
        per_race.append(rate)
        print("  %-24s %5d %5d %6d %7d %7d %10.2f %9.2f"
              % (lab[:24], c["maxlap"], c["n_off"], c["wide"], ea, er, rate,
                 100.0 * c["abs_l2"] / max(c["carlaps_l2"], 1)))
        tot["off"] += c["n_off"]; tot["wide"] += c["wide"]; tot["ea"] += ea; tot["er"] += er
        tot["cl"] += c["carlaps"]; tot["cl2"] += c["carlaps_l2"]; tot["l2"] += c["abs_l2"]
        tot["unjoined"] += c["unjoined"]
        for b, n in c["exc_abs"].items():
            tot["band_%.2f" % b] += n
    print()
    print("  POOLED %d races: %d offs = %d wide + %d excursions(ABS), %d excursions(REL)"
          % (len(rows), tot["off"], tot["wide"], tot["ea"], tot["er"]))
    print("  rate %.2f per 100 car-laps, LAP2+ %.2f"
          % (100.0 * tot["ea"] / max(tot["cl"], 1), 100.0 * tot["l2"] / max(tot["cl2"], 1)))
    if tot["ea"]:
        print("  wide:excursion %.1f:1 - this is why a raw off_track count ranks corners wrongly"
              % (tot["wide"] / float(tot["ea"])))
    bands = sorted(((k, v) for k, v in tot.items() if k.startswith("band_")), key=lambda x: -x[1])
    if bands:
        print("  excursions by band: " + ", ".join("%s=%d" % (k.replace("band_", ""), v) for k, v in bands[:8]))
    if len(rows) > 1:
        print("  per-race spread %.2f to %.2f per 100 car-laps - run tools/arm_check.py before pooling these"
              % (min(per_race), max(per_race)))
    if tot["unjoined"]:
        print("  (%d off_track events had no state sample within 1.5 s and were skipped, not counted either way)"
              % tot["unjoined"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
