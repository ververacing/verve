"""Count every Verve warning line ACROSS all kept CSP logs, not within one race.

    python tools/watch_tally.py                 # every warning shape, ranked by RACES affected
    python tools/watch_tally.py --since 20261001
    python tools/watch_tally.py --shape level   # only shapes whose text matches this
    python tools/watch_tally.py --selftest

WHY THIS EXISTS, and it cost four weeks. `lib/watch.lua` detects another app overwriting Verve's AI levels and
logs "Verve watch: Something else is changing the AI: level on N cars". It worked perfectly. It fired fourteen
times in one race on 2026-09-25, sixty-two times in a race on the 26th, and in 40 races in all - into per-race
logs the harness keeps by design, which nothing ever grepped. The defect (a qualifying session's levels reverting
to race.ini at the race start, splitting the field in two) was then "found" on 2026-10-23 by reading a diag.

    AN ALARM THAT IS NOT AGGREGATED ACROSS RACES IS INDISTINGUISHABLE FROM SILENCE.

A per-race warning is invisible at exactly the scale where the pattern lives: one race's log looks like noise,
and forty races' logs look like a defect with a date and a trigger. So this tool is the aggregator, and it is
meant to run in the hourly pass alongside docs_check and sweep.

TWO MISTAKES IT IS BUILT NOT TO MAKE, both of which this project has made for real:
 1. RANK BY RACES, NEVER BY OCCURRENCES. One race that logs the same warning 62 times would outrank 40 races
    logging it once, and the second is the finding. Occurrences are reported too, as a separate column, because
    "62 in one race" is itself informative - but the ORDER is races. (Same error as comparing accumulated counts
    across arms with different exposure: LESSONS, 2026-10-16.)
 2. NEVER TAKE THE LABEL FROM A FIXED OFFSET - but not for the reason I first wrote down, and the selftest is
    what corrected me. `basename[14:-4]` and the regex agree on EVERY filename the regex accepts, because the
    regex pins the stamp to exactly 13 characters; the first version of this docstring claimed the offset "eats
    a character off every label" and its own negative control promptly refuted that. The real difference is at
    the EDGE: given a name that is not `<stamp>_<label>.log`, the regex returns None and the file is SKIPPED,
    while the offset happily slices a garbage label out of it and tallies warnings under it. That is what
    `--selftest` proves. A guard is worth only the failure it can actually demonstrate.
"""
import argparse
import collections
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results")
LOGS = os.path.join(RESULTS, "csp_logs")

# <stamp>_<label>.log, where the label may hold underscores and digits of its own
NAME = re.compile(r"^(?P<stamp>\d{8}_\d{4})_(?P<label>.+)\.log$")
# the warning families Verve emits; anything matching is tallied by its SHAPE
WARN = re.compile(r"(Verve (?:watch|fault|error|warn[a-z]*)\s*:[^\r\n]*)", re.I)
# A shape is the message with magnitudes replaced, so "level on 12 cars" and "level on 18 cars" are one shape.
# BUT ZERO IS KEPT AS ITSELF, and that is not a nicety - it was a real defect in the first version of this tool.
# `Verve watch` reports two counts in one line ("level on N cars, aggression on M"), and collapsing every number
# to "#" merged "level on 12 cars, aggression on 0" with "level on 0 cars, aggression on 3" into a single shape
# of 55 races. Those are DIFFERENT EVENTS: split on zero, it is 40 races with a real level conflict (every one of
# them a --quali/--practice race) and 15 with none (every one a race-only race) - which is the finding, and the
# merged shape hid it. Where a number distinguishes "happened" from "did not", it is a CATEGORY, not a magnitude.
NUM = re.compile(r"\d+(?:\.\d+)?")


def _norm(m):
    return "0" if float(m.group(0)) == 0 else "#"


def label_of(basename):
    m = NAME.match(basename)
    return m.group("label") if m else None


def _label_naive(basename):
    """The fixed-offset version, kept ONLY so --selftest can prove it is wrong. Never called otherwise."""
    return basename[14:-4]


def shape_of(line):
    return NUM.sub(_norm, line.strip())


def queue_flags():
    """label -> the queue line that launched it, for cross-referencing flags."""
    out = {}
    for p in glob.glob(os.path.join(RESULTS, "batch_*.txt")):
        try:
            for ln in io.open(p, encoding="utf-8", errors="replace"):
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                m = re.search(r"--label\s+(\S+)", s)
                if m:
                    out.setdefault(m.group(1), s)
        except OSError:
            continue
    return out


def scan(log_dir, since=None):
    """-> (shapes, nlogs). shapes[shape] = {races: {label: occurrences}, first: stamp, last: stamp}."""
    shapes = collections.defaultdict(lambda: {"races": collections.Counter(), "first": None, "last": None})
    nlogs = 0
    for p in sorted(glob.glob(os.path.join(log_dir, "*.log"))):
        base = os.path.basename(p)
        m = NAME.match(base)
        if not m:
            continue
        stamp, label = m.group("stamp"), m.group("label")
        if since and stamp[:8] < since:
            continue
        nlogs += 1
        try:
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for line in WARN.findall(txt):
            sh = shape_of(line)
            e = shapes[sh]
            e["races"][label] += 1
            if e["first"] is None or stamp < e["first"]:
                e["first"] = stamp
            if e["last"] is None or stamp > e["last"]:
                e["last"] = stamp
    return shapes, nlogs


def flag_split(labels, qf):
    """How the affected races were launched - the thing that turns a count into a trigger."""
    c = collections.Counter()
    for lab in labels:
        cmd = qf.get(lab)
        if cmd is None:
            c["no queue row"] += 1
            continue
        q = bool(re.search(r"--(quali|practice)(\s|=)", cmd))
        pr = bool(re.search(r"--profiles(\s|=)", cmd))
        cl = bool(re.search(r"--car-level(\s|=)", cmd))
        k = ("quali/practice" if q else "race-only") + ("+profiles" if pr else "") + ("+car-level" if cl else "")
        c[k] += 1
    return c


def selftest():
    import shutil
    import tempfile
    ok = True
    d = tempfile.mkdtemp(prefix="watch_tally_selftest_")
    try:
        # 1. ONE race with the same warning 50 times must not outrank 3 races with one each.
        io.open(os.path.join(d, "20261001_0101_loud_race_1.log"), "w", encoding="utf-8").write(
            "\n".join(["   1 M [Lua: App: Verve] Verve watch: level on 7 cars"] * 50))
        for i, lab in enumerate(("quiet_a_1", "quiet_b_2", "quiet_c_3")):
            io.open(os.path.join(d, "2026100%d_0202_%s.log" % (2 + i, lab)), "w", encoding="utf-8").write(
                "   1 M [Lua: App: Verve] Verve fault: evalBody 1 time\n")
        shapes, n = scan(d)
        if n != 4:
            print("SELFTEST FAIL: expected 4 logs scanned, got %d" % n); ok = False
        ranked = sorted(shapes.items(), key=lambda kv: (-len(kv[1]["races"]), kv[0]))
        top = ranked[0][0]
        if "fault" not in top:
            print("SELFTEST FAIL: ranking is by OCCURRENCES, not races - the 50-in-one-race shape won.\n"
                  "               top shape was %r" % top); ok = False
        loud = [v for k, v in shapes.items() if "watch" in k][0]
        if len(loud["races"]) != 1 or sum(loud["races"].values()) != 50:
            print("SELFTEST FAIL: expected 1 race / 50 occurrences, got %d / %d"
                  % (len(loud["races"]), sum(loud["races"].values()))); ok = False

        # 2. the shape must collapse differing MAGNITUDES into one key
        if len([k for k in shapes if "watch" in k]) != 1:
            print("SELFTEST FAIL: number normalisation broken"); ok = False

        # 2b. ...and must NOT collapse zero with non-zero, because that distinction is the finding. This is the
        #     defect the first version of this tool shipped with: it reported 55 races for one merged shape where
        #     the real answer is 40 + 15, with opposite flag profiles.
        d2 = tempfile.mkdtemp(prefix="watch_tally_zero_")
        try:
            io.open(os.path.join(d2, "20261001_0101_lvl_hit_1.log"), "w", encoding="utf-8").write(
                "Verve watch: Something else is changing the AI: level on 12 cars, aggression on 0\n")
            io.open(os.path.join(d2, "20261001_0102_agg_only_1.log"), "w", encoding="utf-8").write(
                "Verve watch: Something else is changing the AI: level on 0 cars, aggression on 3\n")
            sh2, _ = scan(d2)
            if len(sh2) != 2:
                print("SELFTEST FAIL: 'level on 12 cars, aggression on 0' and 'level on 0 cars, aggression on 3' "
                      "collapsed into %d shape(s) - zero must survive normalisation" % len(sh2)); ok = False
            else:
                print("  zero-vs-magnitude OK: the two counts stay separate shapes")
        finally:
            shutil.rmtree(d2, ignore_errors=True)

        # 3. THE NEGATIVE CONTROL. On a CONFORMING name the two agree and must - the regex pins the stamp to 13
        #    characters, so there is no width for an offset to get wrong, and the first version of this test
        #    asserted they would differ and duly failed. The control that has teeth is the NON-conforming name:
        #    the regex must return None so the file is skipped, while the offset invents a label.
        base = "20261001_0101_loud_race_1.log"
        if label_of(base) != "loud_race_1":
            print("SELFTEST FAIL: label_of gave %r" % label_of(base)); ok = False
        if _label_naive(base) != label_of(base):
            print("SELFTEST FAIL: on a conforming name the two must agree; offset=%r regex=%r"
                  % (_label_naive(base), label_of(base))); ok = False
        odd = "not_a_race_log.log"
        if label_of(odd) is not None:
            print("SELFTEST FAIL: a non-conforming name produced a label %r instead of None" % label_of(odd))
            ok = False
        elif _label_naive(odd) is None:
            print("SELFTEST FAIL: the offset extractor also rejects %r, so this control is fake" % odd)
            ok = False
        else:
            print("  negative control OK: on %r the offset invents %r where the regex returns None"
                  % (odd, _label_naive(odd)))

        # 4. a filename that is not <stamp>_<label>.log must be skipped, not guessed at
        io.open(os.path.join(d, "not_a_race_log.log"), "w", encoding="utf-8").write("Verve watch: x 1 cars\n")
        _, n2 = scan(d)
        if n2 != 4:
            print("SELFTEST FAIL: a non-conforming filename was scanned (%d != 4)" % n2); ok = False
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("watch_tally selftest: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only logs stamped on or after this YYYYMMDD")
    ap.add_argument("--shape", help="only shapes whose text contains this (case-insensitive)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    shapes, nlogs = scan(LOGS, since=args.since)
    if not nlogs:
        print("no kept CSP logs found under %s" % os.path.relpath(LOGS, HERE))
        return 0
    qf = queue_flags()
    rows = [(sh, e) for sh, e in shapes.items()
            if not args.shape or args.shape.lower() in sh.lower()]
    rows.sort(key=lambda kv: (-len(kv[1]["races"]), kv[0]))
    print("kept logs scanned: %d   distinct warning shapes: %d" % (nlogs, len(rows)))
    print("(ranked by RACES affected, which is the finding; occurrences are shown but do not order the list)")
    print()
    for sh, e in rows:
        races, occ = len(e["races"]), sum(e["races"].values())
        print("%d races, %d occurrences, %s to %s" % (races, occ, e["first"], e["last"]))
        print("    %s" % sh[:150])
        split = flag_split(e["races"], qf)
        print("    launched as: %s" % ", ".join("%s=%d" % kv for kv in split.most_common()))
        worst = e["races"].most_common(3)
        print("    most occurrences in one race: %s" % ", ".join("%s(%d)" % w for w in worst))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
