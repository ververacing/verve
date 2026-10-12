"""Score an interleaved on/off regression suite as PAIRS: each `<track>_on_i` diag against its `<track>_off_i` twin.

    python tools/suite_pairs.py d25_suite            # label prefix; finds diag_race_*<prefix>_<track>_on|off_<i>.jsonl

Per pair: heavy hits (contact events >= 80 km/h), dead cars, damage incidents (total and lap 0-1), damage incidents per
car per 100 laps, brush contacts and median lap (s), each as on, off and on-off.
Per track: the mean paired difference and the OFF arm's spread (max - min over its runs). The gate (night plan
2026-09-25): a track reads "worse" only if the mean paired difference in heavy80 or dead exceeds the off arm's spread;
median lap must stay within 0.5 s; raw contacts are reported, never gated. One-of-one tracks (Monza) are informational.
"""
import glob
import os
import re
import statistics
import subprocess
import sys


def metrics(diag):
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "race_metrics.py"), diag],
                         capture_output=True, text=True).stdout
    g = lambda k, cast=float: cast((re.search(r"^" + k + r"\s+(\S+)", out, re.M) or [None, "0"])[1] or 0)
    return {"heavy80": g("heavy80", int), "dead": g("retired_or_parked", int), "contacts": g("contact_events", int),
            "medlap": g("laptime_median_s"),
            # the DAMAGE column (race_metrics.py:258 "damage-taking incidents per car per 100 laps") - the only contact
            # measure that can be read against reality at all. `contacts` above is every touch, brushes included, and no
            # series publishes those: it is ON-v-OFF proximity evidence only, never a rate to score (LESSONS METHOD).
            "inc100": g("inc_per_car_100laps"), "inc": g("incidents", int), "inc01": g("incidents_lap0_1", int),
            # inc100 is NOT comparable across race distances: it carries the opening lap's cost, so the same cars read 7.65
            # over 12 laps and 3.70 over 50 (PC #2 GT3, 2026-10-11). inc100_l2 drops laps 0-1, which is better but still NOT
            # distance-free: measured directly, the same field runs 6.10 lap-2+ over 12 laps and 3.20 over 50 - the rate itself
            # halves as the field spreads. What IS stable is the laps-0-1 cost per car (0.308 and 0.314 in those two races), so
            # compare opening laps on inc01 and quote any lap-2+ rate WITH its race distance attached.
            "inc100_l2": g("inc_per_car_100laps_lap2plus"),
            "laps": g("leader_laps", int)}


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "d25_suite"
    files = glob.glob(f"diag_race_*_{prefix}_*.jsonl")
    pairs = {}
    for f in files:
        m = re.search(rf"{prefix}_(\w+?)_(on|off)_(\d+)\.jsonl$", os.path.basename(f))
        if not m:
            continue
        track, arm, i = m.group(1), m.group(2), int(m.group(3))
        pairs.setdefault((track, i), {})[arm] = f
    if not pairs:
        print("no suite diags found for", prefix); return
    keys = ["heavy80", "dead", "inc", "inc01", "inc100", "inc100_l2", "contacts", "medlap", "laps"]
    print(f"{'pair':16s} " + " ".join(f"{k+' on/off/d':>22s}" for k in keys))
    per_track = {}
    for (track, i), arms in sorted(pairs.items()):
        if "on" not in arms or "off" not in arms:
            print(f"{track}_{i:<12} incomplete ({', '.join(arms)})"); continue
        on, off = metrics(arms["on"]), metrics(arms["off"])
        # A race that ended early (the game killed, a power cut, a quit-hang) is not a measurement, and pooling one into
        # the per-track mean silently poisons the verdict: rc16b_mon_on_1 died at lap 4 of 12 and dragged the Monza pace
        # mean to +2.0 s when its own redone pair read +0.0 (2026-10-11). Report such a pair, never average it in.
        short = on["laps"] < 0.8 * off["laps"] or off["laps"] < 0.8 * on["laps"]
        row = f"{track}_{i:<12} "
        for k in keys:
            d = on[k] - off[k]
            row += f"{on[k]:>7.1f}/{off[k]:>6.1f}/{d:>+6.1f} "
            if short:
                continue
            per_track.setdefault(track, {}).setdefault(k, {"d": [], "off": []})
            per_track[track][k]["d"].append(d); per_track[track][k]["off"].append(off[k])
        print(row + (f" SHORT: {on['laps']} v {off['laps']} laps - left out of the track mean" if short else ""))
    print()
    for track, ks in per_track.items():
        verdict = []
        for k in ("heavy80", "dead"):
            d, off = ks[k]["d"], ks[k]["off"]
            spread = (max(off) - min(off)) if len(off) > 1 else None
            md = statistics.mean(d)
            worse = spread is not None and md > spread
            verdict.append(f"{k}: mean on-off {md:+.1f} vs off spread {spread if spread is not None else 'n/a'}{'  WORSE' if worse else ''}")
        ml = statistics.mean(ks["medlap"]["d"])
        verdict.append(f"medlap: mean on-off {ml:+.1f} s{'  SLOWER' if ml > 0.5 else ''}")
        verdict.append(f"inc01 (lap 0-1): mean on-off {statistics.mean(ks['inc01']['d']):+.1f}")
        onlaps = statistics.mean(ks['laps']['off']) if 'laps' in ks else 0
        # per-100-laps is meaningless on a 2-lap sprint: every incident is a lap-0/1 one, so the normalisation
        # explodes (Spa 2-lap ON read 25.9 against a gt reference of 8, while 12-lap Monza read a plausible 10.6).
        sprint = onlaps < 5
        inc100_note = "  [sprint - read inc01, not this]" if sprint else ""
        verdict.append(f"inc/car/100laps: mean on-off {statistics.mean(ks['inc100']['d']):+.1f} (on mean "
                       f"{statistics.mean([d + o for d, o in zip(ks['inc100']['d'], ks['inc100']['off'])]):.1f})" + inc100_note)
        verdict.append(f"inc/car/100laps LAP2+: mean on-off {statistics.mean(ks['inc100_l2']['d']):+.1f} (on mean "
                       f"{statistics.mean([d + o for d, o in zip(ks['inc100_l2']['d'], ks['inc100_l2']['off'])]):.1f}) - the"
                       f" distance-stable rate")
        verdict.append(f"contacts: mean on-off {statistics.mean(ks['contacts']['d']):+.1f} (brushes, no reference)")
        n = len(ks["dead"]["d"])
        print(f"{track} (n={n}{', informational' if n < 2 else ''}): " + " | ".join(verdict))


if __name__ == "__main__":
    main()
