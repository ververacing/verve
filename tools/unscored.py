"""A FINISHED QUEUE WITH NO VERDICT IS A DEFECT. This finds them. Install to tools/unscored.py when the pause lifts.

WHY IT EXISTS. On 11 October a ten-row repro of the owner's TOP-RANKED item - a shipped bug hitting real players -
ran to completion and was never read. It sat on complete data for four days while the machine worked on an
inferred priority. Nothing about the queue was wrong: the SCORING STEP HAD NO OWNER. Cloud adopted the rule on
2026-10-15; this is the mechanical half, because the day's other lesson was that a rule written in a document does
not fire by itself - I wrote the "module default is not the live value" rule in the morning and broke it again in
the afternoon.

WHAT "SCORED" MEANS HERE, and it is deliberately not "the harness wrote a row". The harness scores rows into
results.csv automatically; that is not a verdict. A verdict is a line in LESSONS.md that names the cell. So this
reports a queue as UNSCORED when every row it declares is present in results.csv - i.e. it RAN and FINISHED - but
no LESSONS line mentions its label prefix.

WHAT IT DELIBERATELY DOES NOT DO: judge a partially-run queue (that is the hourly queue check's job, not this
one), or guess at quality. It answers one question - did anything ever read this? - and it is meant to be cheap
enough to run inside the hourly pass.
"""
import csv
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # .../apps/lua/Verve
RESULTS = os.path.join(ROOT, "tools", "harness_results", "results.csv")
LESSONS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "docs", "LESSONS.md")


def labels_of(path):
    """every --label a queue file declares, runnable rows only (a header comment is not a row)."""
    out = []
    for line in io.open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.search(r"--label (\S+)", s)
        if m:
            out.append(m.group(1))
    return out


def names_of(labels):
    """EVERY plausible way LESSONS might name this cell, not one guessed prefix.

    The first version took a single common prefix and reported 30 queues, including mvint, recov and gripkeys -
    all three of which HAVE verdicts. A multi-arm queue's labels (mvint_k02_1, mvint_k05_1, mvint_k15_1) share
    only the stem "mvint_k", which no write-up ever uses; the entry says "mvint". A check that cries wolf 30
    times is worse than no check, because it trains everyone to skip it - that is this morning's leak_check
    lesson, where the identity gate failed on its own canaries on every run.
    So: collect the per-arm stems, the whole-set common prefix AND the first underscore token, and treat the
    cell as scored if ANY of them is named. Conservative on purpose: a missed unscored queue costs a day, a
    false alarm costs the check's credibility.
    """
    out = set()
    for l in labels:
        out.add(re.sub(r"_\d+$", "", l))          # mvint_k02
        out.add(l.split("_")[0])                  # mvint
    pref = os.path.commonprefix(sorted(labels)).rstrip("_")
    if pref:
        out.add(pref)
    return {n for n in out if len(n) >= 3}        # too short to be meaningful


def scan(queue_glob=None, results=RESULTS, lessons=LESSONS):
    scored = set()
    if os.path.exists(results):
        for r in csv.DictReader(io.open(results, encoding="utf-8", errors="replace")):
            if r.get("label"):
                scored.add(r["label"])
    verdicts = io.open(lessons, encoding="utf-8", errors="replace").read() if os.path.exists(lessons) else ""
    rows = []
    for q in sorted(glob.glob(queue_glob or os.path.join(ROOT, "tools", "harness_results", "batch_*.txt"))):
        labs = labels_of(q)
        if not labs:
            continue
        ran = [l for l in labs if l in scored]
        if len(ran) != len(labs):
            continue                      # still running, or died - the hourly queue check owns that
        cands = names_of(labs)
        if cands and not any(c in verdicts for c in cands):
            rows.append((os.path.basename(q), len(labs), sorted(cands)[0]))
    return rows


def selftest():
    import tempfile
    fails = []
    d = tempfile.mkdtemp()
    qa = os.path.join(d, "batch_x_scored.txt")
    qb = os.path.join(d, "batch_x_unscored.txt")
    qc = os.path.join(d, "batch_x_partial.txt")
    io.open(qa, "w", encoding="utf-8").write("# header --label notarow\n--laps 4 --label aaa_1\n--laps 4 --label aaa_2\n")
    io.open(qb, "w", encoding="utf-8").write("--laps 4 --label bbb_1\n--laps 4 --label bbb_2\n")
    io.open(qc, "w", encoding="utf-8").write("--laps 4 --label ccc_1\n--laps 4 --label ccc_2\n")
    res = os.path.join(d, "results.csv")
    # WITH-BLOCKS, NOT A BARE io.open: the first version left these handles unflushed, so scan() read an empty
    # results.csv, found no finished queues and reported nothing - and the selftest correctly failed itself.
    with io.open(res, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label"])
        for l in ("aaa_1", "aaa_2", "bbb_1", "bbb_2", "ccc_1"):
            w.writerow([l])
    les = os.path.join(d, "LESSONS.md")
    io.open(les, "w", encoding="utf-8").write("- RESULT 2026-01-01 - aaa cell: the aaa verdict is written here.\n")

    got = {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}
    if "batch_x_unscored.txt" not in got:
        fails.append("a FINISHED queue with no LESSONS verdict was NOT reported")
    if "batch_x_scored.txt" in got:
        fails.append("a queue WITH a verdict was reported as unscored")
    if "batch_x_partial.txt" in got:
        fails.append("a PARTIALLY run queue was reported - that belongs to the hourly queue check, not here")

    # a header comment carrying the text --label must not count as a row
    if labels_of(qa) != ["aaa_1", "aaa_2"]:
        fails.append("a --label inside a header comment was counted as a runnable row: %s" % labels_of(qa))

    print("=== unscored.py selftest ===")
    for f in fails:
        print("  FAIL %s" % f)
    print("  %s" % ("every rule holds" if not fails else "RULES BROKEN"))

    print("\n=== seeded defects (untrusted until each FAILS) ===")
    allok = True
    # drop the verdict for aaa: it must now be reported
    io.open(les, "w", encoding="utf-8").write("- RESULT 2026-01-01 - nothing relevant here.\n")
    g2 = {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}
    ok1 = "batch_x_scored.txt" in g2
    print("  %-46s %s" % ("verdict removed -> queue must be reported", "caught" if ok1 else "NOT CAUGHT"))
    # give the partial queue its missing row: it is now finished and unscored, so it must be reported
    with io.open(res, "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(["ccc_2"])
    g3 = {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}
    ok2 = "batch_x_partial.txt" in g3
    print("  %-46s %s" % ("partial queue completed -> now reported", "caught" if ok2 else "NOT CAUGHT"))
    allok = ok1 and ok2
    print("\n  %s" % ("every seeded defect caught" if allok else "SELFTEST NOT TRUSTWORTHY"))
    return 0 if (not fails and allok) else 1


RULE_ADOPTED = "20261015"      # Cloud adopted "a finished queue with no verdict is a defect" on this date


def _stamp(name):
    m = re.search(r"batch_(\d{8})", name)
    return m.group(1) if m else "00000000"


def main():
    if "--selftest" in sys.argv:
        return selftest()
    rows = scan()
    if not rows:
        print("unscored: every finished queue has a verdict in LESSONS")
        return 0
    # The rule was adopted 2026-10-15. Queues that finished BEFORE it are counted debt, not an hourly alarm:
    # there are ~21 of them, mostly 8-13 October exploratory cells, and a check that prints 21 lines every hour
    # is one everyone learns to skip - which is exactly how the identity gate came to be waved through while it
    # failed on its own canaries. So the hourly pass ACTS on new queues and merely COUNTS the backlog.
    new = [r for r in rows if _stamp(r[0]) >= RULE_ADOPTED]
    old = [r for r in rows if _stamp(r[0]) < RULE_ADOPTED]
    if new:
        print("UNSCORED SINCE THE RULE - these ran to completion and nothing read them. FIX THESE:")
        for name, n, pref in new:
            print("  %-48s %2d rows, no LESSONS line names %r" % (name, n, pref))
    else:
        print("unscored: nothing finished unscored since the rule was adopted (%s)" % RULE_ADOPTED)
    if old:
        print("  pre-existing backlog, COUNTED not alarmed: %d finished queue(s) with no verdict"
              " (oldest %s, newest %s)" % (len(old), old[0][0], old[-1][0]))
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
