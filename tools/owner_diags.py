"""Score the OWNER'S OWN races - the diag files with no `--label` - read-only, for the desk.

    python tools/owner_diags.py                 # every unlabelled diag, newest first
    python tools/owner_diags.py --since 20261023
    python tools/owner_diags.py --selftest

WHY THIS EXISTS. Every scored finding in this archive comes from harness races, and the owner's own sessions
write exactly the same artefacts. On 2026-10-23 their eleven COTA East sessions turned out to hold two things
nothing had looked at: the AI-level revert firing on a RESTART (14 of 14 cars to race.ini's level, Verve never
writing again - LESSONS 4718d6d), and `isOval` TRUE in all of them, so the NASCAR manoeuvre book was live on a
road course. Both had been sitting in files the app writes for free.

    A DEFECT IN DATA WE DO NOT READ IS WORSE THAN ONE IN A CONFIGURATION WE DO NOT TEST:
    we already paid to collect it.

HOW AN OWNER RACE IS IDENTIFIED: the harness always passes `--label`, and `diag.lua` puts it in the filename, so
`diag_race_<stamp>_<track>.jsonl` with nothing after the track is a race the owner started themselves. That is a
convention, not a guarantee, so the report says how it decided and never claims more.

WHAT IT REPORTS, per session: track and layout as the filename records them, `isOval` (which decides the
manoeuvre book), cars, the class keys Verve resolved, the applied-level distribution with any REVERT called out,
`conflictLevel`/`conflictAggr`, judged manoeuvres attempted against completed, and cars lost.

NOTHING HERE GOES TO THE OWNER AUTOMATICALLY. It reports to the desk; what reaches them is a decision, not a
side effect of a tool run.
"""
import argparse
import collections
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
# diag_race_<8>_<6>_<track...>.jsonl - an owner race has NOTHING after the track, a harness race has _<label>
NAME = re.compile(r"^diag_race_(?P<stamp>\d{8}_\d{6})_(?P<track>.+)\.jsonl$")


def harness_labels():
    """Every label the harness has EVER USED - from results.csv AND from every queue file.

    THE QUEUE FILES ARE NOT OPTIONAL, and leaving them out is a bug this tool shipped with for one run: a race
    that is STILL RUNNING has no row in results.csv yet, so the first version classed the live harness race
    (`s52_wkdiag_1`) as one of the owner's. The queue file naming that label exists BEFORE the race starts, so
    the union has no lag. The diag header would be the better authority but it does not carry the label
    (checked: `label` is None in both a harness and an owner diag; only `track` is there, with its layout).
    """
    out = set()
    import csv
    for p in glob.glob(os.path.join(HERE, "harness_results", "results*.csv")):
        try:
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh):
                    lab = (r.get("label") or "").strip()
                    if lab:
                        out.add(lab)
        except Exception:                                                      # noqa: BLE001
            continue
    for p in glob.glob(os.path.join(HERE, "harness_results", "batch_*.txt")):
        try:
            for ln in io.open(p, encoding="utf-8", errors="replace"):
                s = ln.strip()
                if s and not s.startswith("#"):
                    m = re.search(r"--label\s+(\S+)", s)
                    if m:
                        out.add(m.group(1))
        except OSError:
            continue
    return out


def is_owner_race(track_part, labels):
    """-> (bool, why). A filename whose track part ENDS in a known harness label is a harness race."""
    for lab in labels:
        if track_part.endswith("_" + lab):
            return False, "ends in the harness label %r" % lab
    return True, "no harness label in the filename"


def read(path):
    hdr, snaps = None, []
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if "hdr" in d:
            hdr = d
        elif d.get("grid"):
            snaps.append(d)
    return hdr, snaps


def level_story(snaps):
    """-> (list of (t_rel, distribution), revert_note or None). A REVERT is a snapshot where the number of cars
    at the HIGHEST level rises while no car moves down - the signature of AC reasserting race.ini."""
    steps, prev = [], None
    for s in snaps:
        dist = collections.Counter(c["lvl"] for c in s["grid"] if c["i"] != 0)
        key = tuple(sorted(dist.items()))
        if key != prev:
            steps.append((s["t"] - snaps[0]["t"], dict(sorted(dist.items()))))
            prev = key
    note = None
    for (t0, a), (t1, b) in zip(steps, steps[1:]):
        if not a or not b:
            continue
        hi = max(max(a), max(b))
        rose = b.get(hi, 0) - a.get(hi, 0)
        if rose > 0 and max(a) < hi or (rose > 0 and a.get(hi, 0) == 0):
            note = "REVERT at t+%ds: %d car(s) moved up to %s (from %s)" % (t1, rose, hi, sorted(a))
            break
    return steps, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only sessions stamped on or after this YYYYMMDD")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    labels = harness_labels()
    rows = []
    for p in sorted(glob.glob(os.path.join(VERVE, "diag_race_*.jsonl")), reverse=True):
        m = NAME.match(os.path.basename(p))
        if not m:
            continue
        if args.since and m.group("stamp")[:8] < args.since:
            continue
        owner, why = is_owner_race(m.group("track"), labels)
        if not owner:
            continue
        rows.append((p, m.group("stamp"), m.group("track"), why))

    print("owner-started sessions found: %d   (identified by: no harness label in the filename)" % len(rows))
    print("harness labels known: %d (results.csv UNION every queue file, which closes the lag where a "
          "still-running race has no results row yet)" % len(labels))
    print()
    for p, stamp, track, why in rows:
        hdr, snaps = read(p)
        if not snaps:
            print("%s  %-28s  no grid snapshots (too short to score)" % (stamp, track))
            continue
        ov = set(s.get("isOval") for s in snaps)
        last = snaps[-1]
        cls = {}
        try:
            cars = (hdr or {}).get("cars") or []
            if isinstance(cars, list) and cars and isinstance(cars[0], dict):
                cls = dict(collections.Counter(c.get("cls") or "?" for c in cars))
        except Exception:                                                      # noqa: BLE001
            pass
        steps, revert = level_story(snaps)
        print("%s  %s" % (stamp, ((hdr or {}).get("track") or track)))
        print("    duration %ds, %d snapshots, cars %s, classes %s" % (
            last["t"] - snaps[0]["t"], len(snaps), last.get("cars"), cls or "(no cls field: diag predates c4fbe6c)"))
        print("    isOval %s%s" % (sorted(str(x) for x in ov),
                                   "   <= THE OVAL MANOEUVRE BOOK WAS LIVE" if True in ov else ""))
        print("    applied levels: %s" % " -> ".join("t+%d %s" % s for s in steps[:6]))
        if revert:
            print("    %s" % revert)
        print("    conflictLevel %s  conflictAggr %s  manoeuvres %s attempted / %s completed  lost %s" % (
            max((s.get("conflictLevel") or 0) for s in snaps),
            max((s.get("conflictAggr") or 0) for s in snaps),
            last.get("mvN"), last.get("mvOK"),
            (last.get("cars") or 0) - (last.get("running") or 0)))
        print()
    return 0


def selftest():
    import shutil
    import tempfile
    ok = True
    d = tempfile.mkdtemp(prefix="owner_diags_selftest_")
    try:
        # 1. a filename ending in a known label is NOT an owner race, even though it parses the same way
        labels = {"s52_wkdiag_1", "wknd_1"}
        o1, w1 = is_owner_race("acu_unitedstates_a_s52_wkdiag_1", labels)
        o2, w2 = is_owner_race("acu_unitedstates_east", labels)
        if o1:
            print("SELFTEST FAIL: a harness race was classed as the owner's (%s)" % w1); ok = False
        if not o2:
            print("SELFTEST FAIL: an owner race was classed as the harness's (%s)" % w2); ok = False
        # 2. THE NEGATIVE CONTROL: with an EMPTY label set the harness race must be misclassified, or the test
        #    above proves nothing about the label check - it would pass on any input.
        # 2b. THE LAG CASE, which this tool got wrong on its first real run: a label that exists in a
        #     QUEUE FILE but not yet in results.csv must still be excluded.
        o_lag, _ = is_owner_race("acu_unitedstates_a_s52_wkdiag_1", {"s52_wkdiag_1"})
        if o_lag:
            print("SELFTEST FAIL: a queued-but-unscored harness label was owner-classed"); ok = False
        o3, _ = is_owner_race("acu_unitedstates_a_s52_wkdiag_1", set())
        if not o3:
            print("SELFTEST FAIL: with no labels known the harness race was still excluded, so case 1 is not "
                  "testing the label list at all"); ok = False
        else:
            print("  negative control OK: with no labels known, the harness race is (wrongly) owner-classed")
        # 3. the revert detector must fire on a rise to a higher level and NOT on Verve's normal downward apply
        def snaps_from(seq):
            return [{"t": i * 8, "grid": [{"i": n + 1, "lvl": v} for n, v in enumerate(row)],
                     "cars": len(row) + 1, "running": len(row) + 1, "mvN": 0, "mvOK": 0,
                     "conflictLevel": 0, "conflictAggr": 0, "isOval": False}
                    for i, row in enumerate(seq)]
        _, rev = level_story(snaps_from([[83, 83, 83], [100, 100, 100]]))
        if not rev:
            print("SELFTEST FAIL: a 83->100 revert was not detected"); ok = False
        _, norev = level_story(snaps_from([[100, 100, 100], [83, 83, 83]]))
        if norev:
            print("SELFTEST FAIL: Verve's normal downward apply was reported as a revert: %s" % norev); ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("owner_diags selftest: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
