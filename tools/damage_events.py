"""DAMAGE EVENTS per race and per arm, split into TWO-CAR and LONE, with the band of each.

WHAT IT IS, stated so nobody reads it as a second finding: a damage event is a jump of >= 8 in a car's body
damage between consecutive diag snapshots, a fall to zero excluded as a repair. That is the SAME threshold on the
SAME quantity as `feed.lua:22`'s `INCIDENT_MIN = 8`, so this reproduces the `incidents` column - verified exactly,
per race, on s49 (ON 12/10/12, OFF 1/5/7). The value here is the SPLIT and the BAND, not the total.

WHY THE COLUMN IS TRUSTWORTHY WHERE THE FEED'S INCIDENT EVENTS WERE NOT: the feed's events take two sources,
`dmg` and `hit` (feed.lua:292-300), and `hit` needs `Contacts.update`, which sat below the disabled return in
Verve.lua - so a Verve-OFF arm counted only `dmg` and every cross-arm comparison used two different instruments.
The diag's `dmg` field is written for every car in every snapshot whether Verve is enabled or not, so counting
jumps from the diag is symmetric by construction.

TWO-CAR against LONE (the PC #2 rule): an event is TWO-CAR when another car's damage also jumps in the SAME
snapshot within 15 m of along-track distance; otherwise LONE, which is a wall or a kerb. 15 m is converted to
spline through the track's own length, so it means the same thing on every track - the diag's `spline` is
x1000, so 15 m at Monza is 2.6 units and at COTA 2.7.

    python tools/damage_events.py monza s49_tcr_rep_on s49_tcr_rep_off
    python tools/damage_events.py acu_unitedstates s51_cota_on s51_cota_off --track-m 5513
    python tools/damage_events.py --selftest
"""
import collections
import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V = os.path.dirname(HERE)
JUMP = 8          # feed.lua:22 INCIDENT_MIN
NEAR_M = 15.0     # the PC #2 rule for "the same contact"
BAND = 0.02       # excursions.py's own band width, so bands are comparable across tools
BANDS = None      # --bands=lo:hi, the pre-registered window (COTA primary: 0.02:0.06)
LAPS = None       # --laps=lo:hi  (COTA primary: 0:1)
TRACK_M = {"monza": 5793.0, "spa": 7004.0, "singapore_2020": 5063.0, "acu_unitedstates": 5513.0,
           "barcelona": 4655.0, "imola": 4909.0}


def band_of(s):
    return round(s / BAND) * BAND


def events(path, track_m, bands=None, laps=None):
    """[(car, t_rel, delta, band, two_car)] for every damage jump after the first snapshot.

    `bands` = (lo, hi) keeps only events whose band falls in [lo, hi]; `laps` = (lo, hi) keeps only events where
    the damaged car's own lap is in [lo, hi]. Added 2026-10-23 for COTA's PRE-REGISTERED primary - lap-1 Turn 1,
    bands 0.02 to 0.06 on laps 0 and 1 - so the primary is cut from the same instrument as the whole-race figure
    rather than from a second script that could drift from it.
    """
    snaps = []
    try:
        for ln in io.open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if "running" in d and d.get("grid"):
                snaps.append(d)
    except OSError:
        return [], 0
    if not snaps:
        return [], 0
    t0 = snaps[0]["t"]
    prev, out = {}, []
    for s in snaps:
        hits = []                                  # every jump in THIS snapshot, so pairing is possible
        for c in s["grid"]:
            i, dmg = c.get("i"), c.get("dmg")
            if i in (None, 0) or dmg is None:
                continue
            if i in prev:
                d0 = prev[i]
                if dmg == 0 and d0 > 0:
                    pass                           # a repair
                elif dmg - d0 >= JUMP:
                    hits.append((i, dmg - d0, (c.get("spline") or 0) / 1000.0, c.get("lap")))
            prev[i] = dmg
        for i, delta, spl, lap in hits:
            # THE WINDOW IS APPLIED AFTER PAIRING, so a two-car hit at the window's edge is still recognised as
            # two-car even when only one of the pair is inside it.
            if bands is not None and not (bands[0] - 1e-9 <= band_of(spl) <= bands[1] + 1e-9):
                continue
            if laps is not None and not (lap is not None and laps[0] <= lap <= laps[1]):
                continue
            two = False
            for j, _d2, spl2, _l2 in hits:
                if j == i:
                    continue
                gap = abs(spl - spl2)
                gap = min(gap, 1.0 - gap) * track_m       # wrap at the line
                if gap <= NEAR_M:
                    two = True
                    break
            out.append((i, s["t"] - t0, delta, band_of(spl), two))
    return out, len(snaps)


def collisions(ev):
    """How many DISTINCT collisions the two-car events represent.

    A contact damages BOTH cars, so the per-car counter books it twice. Grouping the two-car events by snapshot
    time collapses each contact to one. Added 2026-10-23 because the cloud asked the obvious question I had not:
    "is one collision counted twice?" - it was, and 15 two-car events is not 15 collisions.
    """
    return len(set(t for _c, t, _d, _b, two in ev if two))


def carlaps_for(track, prefix):
    """ACTUAL car-laps for the arm, from the feeds' race_end standings - the same figure cell_score uses."""
    try:
        sys.path.insert(0, HERE)
        import excursions as X
        import cell_score as CS
    except ImportError:
        return None
    total = 0
    found = False
    for p in X.feed_paths(track):
        lab = X.label_for(os.path.basename(p)[:15])
        if lab == X.NO_LABEL or not lab.startswith(prefix):
            continue
        if X.feed_live(p):
            continue
        cl, _l2 = CS.real_carlaps(p)
        if cl:
            total += cl
            found = True
    return total if found else None


def arm(track, prefix, track_m, bands=None, laps=None):
    rows = []
    for p in sorted(glob.glob(os.path.join(V, "diag_race_*%s*.jsonl" % prefix))):
        ev, n = events(p, track_m, bands, laps)
        lab = os.path.basename(p)[10:-6]
        lab = lab[16:] if len(lab) > 16 else lab
        rows.append({"label": lab, "ev": ev, "snaps": n})
    return rows


def show(prefix, rows, carlaps=None):
    if not rows:
        print("  %-22s no races" % prefix)
        return
    allev = [e for r in rows for e in r["ev"]]
    tot = len(allev)
    two = sum(1 for e in allev if e[4])
    lone = tot - two
    # SUM THE PER-RACE COLLISIONS, never collapse the arm's events together. `collisions()` keys on the event's
    # time, which is RACE-RELATIVE: two races whose contacts happen at the same t+N would merge into one. Caught
    # 2026-10-23 on the COTA Turn 1 window, where the arm total read 1 while the per-race values were [1,0,0,1] -
    # an internal contradiction visible only because the per-race line is printed beside the total.
    coll = sum(collisions(r["ev"]) for r in rows)
    print("  ARM %-22s %3d damage events  (two-car %d = %d distinct collisions, lone %d)"
          % (prefix, tot, two, coll, lone))
    if carlaps:
        # RATES, not count ratios: the arms do not drive the same distance, and a count ratio quietly assumes
        # they do. Counts stay beside every rate because a rate over 2 events is not a measurement.
        print("      per 100 ACTUAL car-laps (%d car-laps): all %.2f   two-car %.2f   lone %.2f   collisions %.2f"
              % (carlaps, 100.0 * tot / carlaps, 100.0 * two / carlaps, 100.0 * lone / carlaps,
                 100.0 * coll / carlaps))
    else:
        print("      (no ACTUAL car-lap total available - counts only, no rates)")
    for r in rows:
        t2 = sum(1 for e in r["ev"] if e[4])
        bands = collections.Counter(e[3] for e in r["ev"])
        # THE FULL LIST, never a top-N. A truncated band list was read as complete on 2026-10-23 and produced a
        # false claim ("every OFF event sits at 0.46-0.52") that the output itself contradicted.
        full = ", ".join("%.2f:%d" % (b, n) for b, n in sorted(bands.items()))
        print("      %-24s %3d events  two-car %-3d (%d coll)  lone %-3d  biggest +%-4d"
              % (r["label"], len(r["ev"]), t2, collisions(r["ev"]), len(r["ev"]) - t2,
                 max([e[2] for e in r["ev"]] or [0])))
        print("          ALL bands (%d of %d events listed): %s"
              % (sum(bands.values()), len(r["ev"]), full or "-"))
    print("      PER-RACE events %s   two-car %s   collisions %s"
          % ([len(r["ev"]) for r in rows], [sum(1 for e in r["ev"] if e[4]) for r in rows],
             [collisions(r["ev"]) for r in rows]))


def selftest():
    import tempfile
    ok = True
    d = tempfile.mkdtemp()
    p = os.path.join(d, "diag_race_20260101_000000_monza_selftest.jsonl")

    def snap(t, cars):
        return json.dumps({"t": t, "running": 1,
                           "grid": [{"i": i, "dmg": dm, "spline": sp} for i, dm, sp in cars]}) + "\n"
    with io.open(p, "w", encoding="utf-8") as f:
        # t0: baseline. car 0 is the autopilot and must never count.
        f.write(snap(0.0, [(0, 0, 100), (1, 0, 100), (2, 0, 102), (3, 0, 500)]))
        # t8: cars 1 and 2 both jump, 2 spline units apart = 11.6 m at Monza -> TWO-CAR.
        #     car 3 jumps alone at a different part of the lap -> LONE. car 0 jumps and is ignored.
        f.write(snap(8.0, [(0, 40, 100), (1, 20, 100), (2, 20, 102), (3, 30, 500)]))
        # t16: car 1 repaired to 0 -> NOT an event. car 3 jumps by 7 -> below the threshold, not an event.
        f.write(snap(16.0, [(0, 40, 100), (1, 0, 100), (2, 20, 102), (3, 37, 500)]))
    ev, n = events(p, TRACK_M["monza"])
    if n != 3:
        print("SELFTEST FAIL: %d snapshots, expected 3" % n); ok = False
    if any(e[0] == 0 for e in ev):
        print("SELFTEST FAIL: slot 0 counted"); ok = False
    if len(ev) != 3:
        print("SELFTEST FAIL: %d events, expected 3 (cars 1, 2, 3 at t8 only)" % len(ev)); ok = False
    two = [e for e in ev if e[4]]
    if len(two) != 2 or set(e[0] for e in two) != {1, 2}:
        print("SELFTEST FAIL: two-car set is %s, expected cars 1 and 2" % [e[0] for e in two]); ok = False
    lone = [e for e in ev if not e[4]]
    if len(lone) != 1 or lone[0][0] != 3:
        print("SELFTEST FAIL: lone set is %s, expected car 3" % [e[0] for e in lone]); ok = False
    # NEGATIVE CONTROL on the distance rule: with a track short enough that 2 spline units exceed 15 m,
    # the same data must give NO two-car event. If this still pairs them, the distance test is inert.
    ev2, _ = events(p, 1000.0)      # 2 units = 2 m... no: 0.002 * 1000 = 2 m, still near. Use a tiny track:
    ev3, _ = events(p, 100.0)       # 0.002 * 100 = 0.2 m - still near. The rule only EXCLUDES on a LONG track:
    ev4, _ = events(p, 20000.0)     # 0.002 * 20000 = 40 m > 15 m -> must NOT pair
    if any(e[4] for e in ev4):
        print("SELFTEST FAIL: at 20 km of track 2 spline units is 40 m and must not pair; the distance test"
              " is inert"); ok = False
    if not all(e[4] for e in [x for x in ev3 if x[0] in (1, 2)]):
        print("SELFTEST FAIL: at 100 m of track the two must still pair"); ok = False
    if band_of(0.1021) != 0.1:
        print("SELFTEST FAIL: band_of(0.1021) = %r, expected 0.10 (excursions.py's 0.02 grid)" % band_of(0.1021))
        ok = False
    # ONE CONTACT IS ONE COLLISION, NOT TWO EVENTS. Cars 1 and 2 jumped in the same snapshot, so the two-car
    # count is 2 and the collision count must be 1. Without this the per-car counter double-books every contact.
    if collisions(ev) != 1:
        print("SELFTEST FAIL: %d distinct collisions, expected 1 (cars 1 and 2, same snapshot)" % collisions(ev))
        ok = False
    if len([e for e in ev if e[4]]) == collisions(ev):
        print("SELFTEST FAIL: two-car events and collisions are equal, so the pairing collapse is inert")
        ok = False
    # AND THE ARM TOTAL MUST BE THE SUM OF THE RACES, not a collapse across them: two races whose contacts fall
    # at the same race-relative time must still count as two collisions.
    two_races = [{"ev": ev}, {"ev": ev}]
    if sum(collisions(r["ev"]) for r in two_races) != 2:
        print("SELFTEST FAIL: the same race counted twice gives %d collisions, expected 2"
              % sum(collisions(r["ev"]) for r in two_races)); ok = False
    if collisions([e for r in two_races for e in r["ev"]]) != 1:
        print("SELFTEST FAIL: the flat collapse of two identical races should give 1 - if it does not, the"
              " arm-total bug this guards against cannot be demonstrated"); ok = False
    os.remove(p)
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tm = None
    global BANDS, LAPS
    for a in sys.argv:
        if a.startswith("--track-m="):
            tm = float(a.split("=", 1)[1])
        elif a.startswith("--bands="):
            lo, hi = a.split("=", 1)[1].split(":"); BANDS = (float(lo), float(hi))
        elif a.startswith("--laps="):
            lo, hi = a.split("=", 1)[1].split(":"); LAPS = (int(lo), int(hi))
    if len(args) < 2:
        print(__doc__.strip().splitlines()[0])
        return 2
    track, prefixes = args[0], args[1:]
    track_m = tm or TRACK_M.get(track)
    if not track_m:
        print("no length for %r - pass --track-m=<metres> (15 m has to mean 15 m)" % track)
        return 2
    print("DAMAGE EVENTS on %s (jump >= %d, repairs excluded; %.0f m track, two-car within %.0f m)\n"
          % (track, JUMP, track_m, NEAR_M))
    print("  NOT A SECOND FINDING: this is the `incidents` column re-derived from the raw per-snapshot damage."
          "\n  The SPLIT (two-car against lone) and the BAND are the new information.\n")
    for pre in prefixes:
        show(pre, arm(track, pre, track_m, BANDS, LAPS), carlaps_for(track, pre))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
