"""Split a race's incidents into SOLO losses of control and CAR-TO-CAR contact, with severity for each.

    python tools/incident_split.py spa                    # every spa feed, one row per race
    python tools/incident_split.py singapore_2020 --label kxs_sgp
    python tools/incident_split.py monza --pool            # one pooled line as well

WHY. `contact_events`, and the feed's `incident` count that tracks it, are NOT car-to-car contact counts: the feed
promotes any collision with speed drop >= 3 to an incident (feed.lua:274-279), which catches kerb strikes, spins and
wall taps. Measured here and on PC #2, 42-70 % of incident records carry `solo: true` - no other car within range.
So the two phenomena have to be reported apart, and the `solo` flag is how.

SOLO IS NOT NOISE. Excluding one pathological race, solo severity median 12 against car-to-car 12, heavy (>=20) 20 %
against 26 % - a solo event is a real loss of control, not a kerb tap. Do not "remove solo to clean the data";
report both. (Pooling that pathological race HAD made solo look heavier - median 18 v 13 - on the strength of one
race contributing 90 of 195 solo events. Check what a pooled severity is made of.)

WHAT IT IS FOR. Two standing uses, both pre-registered 2026-10-12:
  1. The CSP grip keys cause cars to lose control ALONE, not to collide: same uniform SF70H field at Singapore, keys
     on v off, solo 90 v 10 (9.0x) against car-to-car 39 v 14 (2.8x). So score key arms on the SOLO RATIO, not only
     on parks - an affected car that keeps recovering never parks. The falsifier: raised car-to-car with a FLAT solo
     ratio is NOT that mechanism and must not be attributed to the keys.
  2. Verve ON/OFF proximity claims. The solo share DIFFERS BY ARM (ON 68 %, OFF 53 % across a mismatched corpus here),
     so it does not cancel, and every contact_events ratio is inflated in the ON arm's favour. The honest proximity
     measure is the ON-v-OFF ratio of the CAR-TO-CAR count on a matched pair.

WHAT IT COUNTS, exactly - PC #2 guessed this wrong and was about to describe the column as de-duplicating:
  - SLOT 0 IS EXCLUDED. It is the harness autopilot, not an AI car being measured, and it is the whole of the gap
    between a raw record count and this one (1, 5, 0 and 13 records across four races). Nothing else is dropped
    except a record with no numeric severity, which has never yet occurred.
  - IT DOES NOT DE-DUPLICATE. The feed emits one incident record per CAR whose damage jumped, so a collision in which
    both cars take damage appears twice, once from each side. Measured: 0-5 reciprocal pairs per race, roughly 5-10 %
    of the car-to-car total. So the car-to-car figure is CAR-INVOLVEMENTS, not collisions - fine for an ON-v-OFF ratio
    applied consistently, wrong if you call it "number of collisions". The pooled line prints the reciprocal count.

Run tools/arm_check.py first: these numbers are only comparable between races with the same arm.
"""
import collections
import glob
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FEEDS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
# Housekeeping archives feeds after 2 days and a glob over a missing directory returns NOTHING rather than
# raising, so globbing FEEDS alone answered any question about an older race from a fraction of the data, with no
# warning. paths.track_feeds() reads live + archive, de-duplicated. (2026-10-22; 13 more tools still to migrate.)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I drops the script dir from sys.path
import paths                                                     # noqa: E402

try:                                     # one implementation of the label lookup, not two (see excursions.py)
    from excursions import label_for
except ImportError:                      # pragma: no cover
    def label_for(stem):
        return stem


def read(path):
    """(solo severities, car-to-car severities, closing speeds, models by car index)."""
    solo, con, closing = [], [], []
    models = {}
    raw = slot0 = 0
    recs = []
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ty = d.get("type")
                if ty == "header":
                    for c in (d.get("cars") or []):
                        # key by the car's OWN i, never by list position: the entries carry it, and a tool that
                        # assumes header order == car index silently scrambles every per-car join if that ever
                        # changes. tools/park_models.py has always done it this way.
                        if isinstance(c, dict) and "i" in c:
                            models[c["i"]] = c.get("model") or "?"
                elif ty == "incident":
                    raw += 1
                    if d.get("car") == 0:
                        slot0 += 1
                        continue                      # slot 0 is the harness autopilot
                    sev = d.get("severity")
                    if not isinstance(sev, (int, float)):
                        continue
                    if d.get("solo"):
                        solo.append(sev)
                    else:
                        con.append(sev)
                        recs.append(d)
                        cl = d.get("closing")
                        if isinstance(cl, (int, float)):
                            closing.append(abs(cl))
    except OSError:
        return None
    # one collision seen from both sides: A names B in its contact list and B names A, within 2 s
    pairs = 0
    for a in recs:
        for b in recs:
            if b is a:
                continue
            ta, tb = a.get("t") or 0, b.get("t") or 0
            if abs(ta - tb) <= 2 and b.get("car") in (a.get("contact") or [])                     and a.get("car") in (b.get("contact") or []):
                pairs += 1
                break
    return solo, con, closing, models, raw, slot0, pairs


def med(xs):
    return statistics.median(xs) if xs else 0.0


def heavy(xs, bar=20):
    return 100.0 * sum(1 for x in xs if x >= bar) / len(xs) if xs else 0.0


def collect(feed_paths, want=None):
    """-> [(label, solo, con, closing, raw, slot0, pairs)] for every readable feed, INCLUDING clean ones.

    Takes the paths as an argument so the selftest can hand it one zero-incident feed. That matters: the first
    selftest written for this function asserted something about read() instead, which the bug never touched, so
    a mutant restoring the drop passed it. An assertion has to sit on the code that was wrong.
    """
    out = []
    for p in feed_paths:
        lab = label_for(os.path.basename(p)[:15])
        if want and want not in lab:
            continue
        r = read(p)
        if not r:
            continue
        solo, con, closing, _, raw, slot0, pairs = r
        # A RACE WITH NO INCIDENTS IS STILL A RACE. This used to `continue`, which dropped the cleanest races out
        # of "POOLED n races" - so every per-race average was computed over a denominator that excluded exactly
        # the races that would pull it down. Found 2026-10-22: excursions.py pooled 12 rs16 races and this pooled
        # 11, and the missing one was the only race in the queue with zero incidents of either kind.
        out.append((lab, solo, con, closing, raw, slot0, pairs))
    return out


def selftest():
    """Asserts the defect that was there: a zero-incident race must survive into the row list."""
    import json
    import tempfile
    ok = True
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1, "t": 0, "type": "header", "track": "selftest",
                            "cars": [{"i": 0}, {"i": 1}]}) + "\n")
        for t in range(6):
            f.write(json.dumps({"v": 1, "t": float(t), "type": "state", "cars": [
                {"i": 0, "pos": 1, "lap": 0, "spline": 0.5, "spd": 100, "pit": False, "ret": False, "dmg": 0},
                {"i": 1, "pos": 2, "lap": 0, "spline": 0.5, "spd": 100, "pit": False, "ret": False, "dmg": 0}]}) + "\n")
        f.write(json.dumps({"v": 1, "t": 9.0, "type": "race_end", "results": []}) + "\n")
    r = read(p)
    if r is None:
        print("SELFTEST FAIL: a readable feed with zero incidents returned None, so it can never be counted")
        ok = False
    else:
        solo, con = r[0], r[1]
        if solo or con:
            print("SELFTEST FAIL: a feed with no incident records produced incidents: %r / %r" % (solo, con))
            ok = False
    # THE ASSERTION THAT GUARDS THE ACTUAL FIX: the clean race must survive into the row list. Asserting
    # something about read() left the bug - which lived in the collection loop - completely untested.
    kept = collect([p])
    if len(kept) != 1:
        print("SELFTEST FAIL: collect() dropped a zero-incident race (%d rows, expected 1) - "
              "every per-race average would be computed over a denominator missing the cleanest races" % len(kept))
        ok = False
    try:
        os.unlink(p)
    except OSError:
        pass
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[0])
        return 2
    track = args[0]
    want = None
    for i, a in enumerate(sys.argv):
        if a == "--label" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1]
    rows = collect(paths.track_feeds(track), want)
    if not rows:
        print("incident_split: no %s feeds matched%s" % (track, " --label " + want if want else ""))
        return 1
    print("SOLO = no other car within range (feed `solo` flag). severity is damage, or the speed drop when damage")
    print("did not jump. A solo event is a real loss of control, not a kerb tap - report both, never subtract one.\n")
    print("%-26s %6s %6s %7s %7s %8s %8s %9s" %
          ("label", "inc", "solo", "contact", "solo%", "sevSolo", "sevCon", "closeCon"))
    tot = collections.Counter()
    ps, pc = [], []
    for lab, solo, con, closing, raw, slot0, pairs in rows:
        n = len(solo) + len(con)
        print("  %-24s %6d %6d %7d %6.0f%% %8.0f %8.0f %9.0f"
              % (lab[:24], n, len(solo), len(con), 100.0 * len(solo) / max(n, 1),
                 med(solo), med(con), med(closing)))
        tot["n"] += n; tot["solo"] += len(solo); tot["con"] += len(con)
        tot["raw"] += raw; tot["slot0"] += slot0; tot["pairs"] += pairs
        ps += solo; pc += con
    if len(rows) > 1 or "--pool" in sys.argv:
        print()
        clean = sum(1 for r in rows if not r[1] and not r[2])
        print("  POOLED %d races: %d incidents = %d solo (%.0f%%) + %d car-to-car%s"
              % (len(rows), tot["n"], tot["solo"], 100.0 * tot["solo"] / max(tot["n"], 1), tot["con"],
                 ("   (%d of those races had NO incidents at all and ARE counted in the denominator)" % clean)
                 if clean else ""))
        print("  severity: solo median %.0f, heavy>=20 %.0f%% | car-to-car median %.0f, heavy>=20 %.0f%%"
              % (med(ps), heavy(ps), med(pc), heavy(pc)))
        print("  (a pooled severity can be one race: check the per-race rows before quoting it)")
        print("  %d raw records, %d excluded as slot 0 (the harness autopilot, not an AI car); NOT de-duplicated -"
              % (tot["raw"], tot["slot0"]))
        print("  %d car-to-car records are one collision seen from both sides, so this column is CAR-INVOLVEMENTS,"
              % tot["pairs"])
        print("  not collisions. Consistent for an ON-v-OFF ratio; wrong to call a collision count.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
