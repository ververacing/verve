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
import collections
import csv
import glob
import io
import os
import re
import sys

# Both paths are DERIVED, never written out. The first version hardcoded them, which put the machine's user
# folder - the owner's real first name - into a committed file; leak_check flags exactly that, and I had not run
# it on this file before committing. Deriving them also means the tool works on PC #2 and in a checkout.
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


#: Line tags that carry a VERDICT or FINDING about a cell. ENUMERATED FROM THE FILE, not guessed - the first
#: version of this list had only six tags and immediately produced a FALSE POSITIVE: `s44`'s verdict is a
#: `DATA` line ("THE MID-RACE AI-LEVEL BLIP IS REPRODUCED..."), which the list did not know about. The real
#: vocabulary, by frequency: OPS 86, METHOD 74, RESULT 56, DATA 47, VERDICT 29, OPEN 32, TOOL 20, MEASURE 14,
#: WITHDRAWN 12, RULED OUT 9, then a long tail.
VERDICT_TAGS = ("RESULT", "DATA", "VERDICT", "WITHDRAWN", "RULED OUT", "RULED-OUT", "MEASURE", "CONFIRMED",
                "NULL", "CORRECTED", "FINDING", "ADOPTED", "ADOPTED-AS-SAFE", "CHANGE", "SUPERSEDED",
                "COVERAGE")
#: Tags that are ABOUT OUR PROCESS rather than about a cell's question. A cell whose only trace is one of these
#: has not been read: rs16's three mentions are two TOOL lines and an OPS line describing failures that happened
#: WHILE it ran, which is how a finished queue can look discussed and have no verdict.
NON_VERDICT_TAGS = ("OPS", "METHOD", "TOOL", "TOOLS", "OPEN", "METRIC", "INSTRUMENT", "IDENTITY")
#: Phrases that mark a verdict ON ANY LINE, whatever the entry's own tag. Matched CASE-SENSITIVELY: this file
#: shouts its verdicts in capitals, while lowercase "confirmed" appears mid-sentence describing a mechanism.
#: Erring toward treating a cell as scored is the deliberate direction - a false alarm costs this check its
#: credibility, which is worse than a missed queue, and that trade is this file's own standing judgement.
LINE_VERDICT_PHRASES = ("TEST RESULT", "CONFIRMED", "RULED OUT", "VERDICT", "RESULT:", "WITHDRAWN")


#: Phrases that start a FORWARD-LOOKING clause. Everything from the first of these onwards is dropped before a
#: verdict line is searched, because a verdict line very often ends by naming the NEXT cell - that mention is a
#: plan, not a reading. This is the actual shape of the false negative: the tag test alone did not fix it,
#: because the forward reference lives INSIDE a RESULT line about a different cell.
FORWARD_MARKERS = ("NEXT:", "NEXT UP", "STILL TO COME", "TO COME", "WILL TEST", "WILL RUN", "TO BE RUN",
                   "RUNS NEXT", "RUNNING NOW", "DUE ABOUT", "DUE AT", "AWAITING", "PENDING", "PROPOSAL",
                   "STILL TO DO", "STILL OPEN", "TO FOLLOW", "TONIGHT:", "NOT YET RUN")


def _tag_of(line):
    """-> (full_tag, base_tag) for a LESSONS bullet, or ('', '').

    The tag is the LEADING RUN OF UPPERCASE WORDS after the bullet, which is the house format. It is matched by
    anchoring at the start rather than by searching the first 60 characters, because a substring search finds
    "DATA" inside "METADATA" and silently re-widens the filter back to "any mention".
    Two values come back because the tag has a long form: "RULED OUT AS A DEFAULT 2026-10-10" is a RULED OUT
    line, and "OPEN/OWNER" is an OPEN line. `base` is the first word with any `/` or `-` suffix removed, so
    both the one-word and multi-word whitelists work. Date-first lines ("- RESULT 2026-10-25 (...") stop the
    run at the digit, which the earlier regex could not span - it recognised almost nothing and took the
    reported backlog from 16 to 60 before its own selftest caught it.
    """
    s = line.lstrip("- \t").lstrip("*")
    m = re.match(r"([A-Z][A-Z/-]*(?:\s+[A-Z][A-Z/-]*)*)", s)
    if not m:
        return "", ""
    tag = m.group(1).strip()
    words = tag.split()
    base = re.split(r"[/-]", words[0])[0] if words else ""
    # also expose the two-word form, since "RULED OUT" is whitelisted while "RULED" alone is not
    two = " ".join(words[:2])
    return (two if two in VERDICT_TAGS else tag), base


def _entries(text):
    """LESSONS as LOGICAL ENTRIES: a bullet plus its INDENTED CONTINUATION LINES, joined.

    WHY: entries here are routinely multi-line, and a cell's verdict often sits on a continuation line rather
    than on the bullet itself. `grip0`'s does - "TEST RESULT (batch_20261011_pc1_grip0.txt ...): CONFIRMED, and
    it is the biggest finding of the day" is an indented line under an earlier bullet. A line-by-line reader
    cannot see it, so the tool reported a cell that has one of the most consequential verdicts in the file.
    """
    out, cur = [], None
    for line in text.splitlines():
        if line[:1] == "-":                       # a new bullet starts at column 0
            if cur:
                out.append("\n".join(cur))
            cur = [line]
        elif cur is not None and line.strip():
            cur.append(line)                      # indented continuation of the current bullet
        elif cur:
            out.append("\n".join(cur))
            cur = None
    if cur:
        out.append("\n".join(cur))
    return out


def _verdict_lines(text):
    """The LESSONS ENTRIES that report a verdict, as (searchable_part, tag).

    `searchable_part` drops any forward-looking tail from each line, so a cell named only as "what runs next"
    does not count as having been read.
    """
    out = []
    for entry in _entries(text):
        s = entry.strip()
        if not s.startswith("-"):
            continue
        tag, base = _tag_of(s)
        entry_is_verdict = bool(tag) and base not in NON_VERDICT_TAGS and (base in VERDICT_TAGS
                                                                          or tag in VERDICT_TAGS)
        if not entry_is_verdict:
            # AN ENTRY TAGGED `OPEN` CAN STILL CARRY A VERDICT ON A CONTINUATION LINE, and one of the file's
            # most consequential results is exactly that: `grip0`'s "TEST RESULT (batch_20261011_pc1_grip0.txt
            # ...): CONFIRMED, and it is the biggest finding of the day" sits under an OPEN bullet about
            # PC #1 v PC #2. An entry-level tag test alone reported that cell as unread.
            # Matched CASE-SENSITIVELY, because this file shouts its verdicts and lowercase "confirmed" turns up
            # mid-sentence ("MECHANISM confirmed") where it is describing a mechanism, not reading a cell.
            if not any(p in s for p in LINE_VERDICT_PHRASES):
                continue
            # keep ONLY the lines that carry the phrase; the rest of an OPEN entry is not a verdict
            s = "\n".join(ln for ln in s.splitlines() if any(p in ln for p in LINE_VERDICT_PHRASES))
            tag = "line-verdict"
        # truncate PER LINE, not once for the whole entry: a forward marker on line 1 must not blind us to a
        # verdict on line 4 of the same entry.
        keep = []
        for ln in s.splitlines():
            upl = ln.upper()
            cut = len(ln)
            for fm in FORWARD_MARKERS:
                i = upl.find(fm)
                if i != -1:
                    cut = min(cut, i)
            keep.append(ln[:cut])
        out.append(("\n".join(keep), tag))
    return out


def _candidates(q):
    """Every name a verdict might call this queue by: label stems, the queue filename, and its stem."""
    labs = labels_of(q)
    out = names_of(labs) if labs else set()
    base = os.path.basename(q)
    out.add(base)
    if base.endswith(".txt"):
        stem = re.sub(r"^batch_\d*_?(pc\d_)?", "", base[:-4])
        if len(stem) >= 3:
            out.add(stem)
    return out


def scan(queue_glob=None, results=RESULTS, lessons=LESSONS):
    """-> [(queue, nrows, name, reason)]. A FINISHED queue with no VERDICT-TAGGED line naming it is reported.

    THE FALSE NEGATIVE THIS FIXES, demonstrated before it was changed: the old test was `name in whole_file`, so
    ANY mention counted - including a FORWARD REFERENCE. A finished queue whose only trace in LESSONS was
    another cell's line saying "zzz still to come tonight" was reported as SCORED. My own write-ups routinely
    name the next cell ("Spa and Barcelona still to come"), so the tool was being silenced by my own plans, and
    it is the one thing standing between a finished queue and nobody reading it.
    The discriminator is NOT headline-versus-body - a genuine verdict can live in a body line - it is the
    LINE'S OWN TAG. A verdict is tagged RESULT / RULED OUT / CONFIRMED / VERDICT / NULL / WITHDRAWN.
    AND THE REPORT DISTINGUISHES A NEAR MISS FROM SILENCE, because a check that cries wolf loses its credibility
    (this file's own earlier lesson): "mentioned, but only outside a verdict line" is a different problem from
    "never mentioned at all", and the operator needs to see which.
    """
    scored = set()
    if os.path.exists(results):
        for r in csv.DictReader(io.open(results, encoding="utf-8", errors="replace")):
            if r.get("label"):
                scored.add(r["label"])
    text = io.open(lessons, encoding="utf-8", errors="replace").read() if os.path.exists(lessons) else ""
    vlines = _verdict_lines(text)
    queues = sorted(glob.glob(queue_glob or os.path.join(ROOT, "tools", "harness_results", "batch_*.txt")))

    # A NAME SHARED BY SEVERAL QUEUES CANNOT IDENTIFY ANY OF THEM, and this bit me the moment I started
    # clearing the backlog: `rc16d`, `rc16d_rest` and `rc16d_spa12` all reduce to the first token "rc16d", so
    # the verdict I wrote for the 3-row spa12 gating cell silenced the 9-row and 7-row cells too - taking the
    # reported debt from 5 to 2 while two finished queues still had no verdict. **A fix that writes a verdict
    # must not be able to mark OTHER cells as read.** So any candidate name claimed by more than one queue is
    # dropped, leaving the distinctive ones (the queue filename, its stem, the per-arm label stems).
    shared = collections.Counter()
    for q in queues:
        for c in _candidates(q):
            shared[c] += 1

    rows, ambiguous = [], []
    for q in queues:
        labs = labels_of(q)
        if not labs:
            continue
        ran = [l for l in labs if l in scored]
        if len(ran) != len(labs):
            continue                      # still running, or died - the hourly queue check owns that
        cands = _candidates(q)
        if not cands:
            continue
        hits = {c for c in cands for line, _t in vlines if c in line}
        if hits:
            # SCORED - but if the ONLY names that matched are shared with another queue, say so. This is not an
            # alarm, it is an advisory, and it exists because of a mistake I made WITH this tool: the verdict I
            # wrote for the 3-row `rc16d_spa12` gating cell also silenced `rc16d` (9 rows) and `rc16d_rest`
            # (7 rows), because all three reduce to the shared first token "rc16d". The reported debt fell from
            # 5 to 2 while two finished queues still had no verdict.
            # The matching stays DELIBERATELY CONSERVATIVE - excluding shared names outright was tried and was
            # worse, taking the backlog from 16 to 33 by discarding the label prefixes that legitimately name
            # most cells. A false alarm costs this check its credibility, which is the worse failure; so the
            # ambiguity is REPORTED rather than acted on.
            if all(shared[c] > 1 for c in hits):
                ambiguous.append((os.path.basename(q), len(labs), sorted(hits)[0]))
            continue
        loose = sum(1 for c in cands if c in text)
        reason = ("mentioned in LESSONS but NOT in any verdict line (%d loose mention(s)) - a forward"
                  " reference or an aside is not a verdict" % loose) if loose else \
                 "never mentioned in LESSONS at all"
        rows.append((os.path.basename(q), len(labs), sorted(cands)[0], reason))
    scan.ambiguous = ambiguous
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

    # THE FALSE NEGATIVE THIS TOOL CARRIED UNTIL 2026-10-25, and the reason it is the first case anyone should
    # read: a FORWARD REFERENCE is not a verdict. Demonstrated against the old code before changing it - a
    # finished queue whose only trace was another cell's "zzz still to come tonight" was reported as SCORED.
    qf = os.path.join(d, "batch_x_fwdref.txt")
    io.open(qf, "w", encoding="utf-8").write("--laps 4 --label zzz_1\n--laps 4 --label zzz_2\n")
    with io.open(res, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["zzz_1"])
        w.writerow(["zzz_2"])
    io.open(les, "a", encoding="utf-8").write(
        "- RESULT 2026-01-02 - the yyy cell is a null. NEXT: zzz still to come, it will test the margin.\n")
    rows_f = scan(os.path.join(d, "batch_*.txt"), res, les)
    got_f = {r[0]: r[3] for r in rows_f}
    if "batch_x_fwdref.txt" not in got_f:
        fails.append("A FORWARD REFERENCE COUNTED AS A VERDICT - the tool is silenced by its own plans")
    elif "NOT in any verdict line" not in got_f["batch_x_fwdref.txt"]:
        fails.append("a loose mention was reported as 'never mentioned', hiding that it was a NEAR MISS: %s"
                     % got_f["batch_x_fwdref.txt"])
    # and a cell named in a line with no verdict tag at all (a METHOD aside) is likewise not scored
    qm = os.path.join(d, "batch_x_methodonly.txt")
    io.open(qm, "w", encoding="utf-8").write("--laps 4 --label mmm_1\n")
    with io.open(res, "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(["mmm_1"])
    io.open(les, "a", encoding="utf-8").write("- METHOD 2026-01-03 - while scoring mmm I changed the scorer.\n")
    if "batch_x_methodonly.txt" not in {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}:
        fails.append("a METHOD aside counted as a verdict - a method note is not a reading of the cell")
    # a REAL verdict line for it must then satisfy the check, or the rule above is unsatisfiable
    io.open(les, "a", encoding="utf-8").write("- RESULT 2026-01-04 - mmm is a null: no difference at n=4.\n")
    if "batch_x_methodonly.txt" in {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}:
        fails.append("a genuine RESULT line did not satisfy the check - the rule would be unsatisfiable")

    def finished(q, labels):
        io.open(q, "w", encoding="utf-8").write("".join("--laps 4 --label %s\n" % l for l in labels))
        with io.open(res, "a", encoding="utf-8", newline="") as fh:
            for l in labels:
                csv.writer(fh).writerow([l])

    def reported(q):
        return os.path.basename(q) in {r[0] for r in scan(os.path.join(d, "batch_*.txt"), res, les)}

    # A VERDICT ON AN INDENTED CONTINUATION LINE counts. Entries in LESSONS are routinely multi-line.
    qcont = os.path.join(d, "batch_x_continuation.txt")
    finished(qcont, ["ccl_1"])
    io.open(les, "a", encoding="utf-8").write(
        "- RESULT 2026-01-05 - a different cell entirely.\n"
        "  and on a second, indented line: ccl is a null at n=4.\n")
    if reported(qcont):
        fails.append("a verdict on an INDENTED CONTINUATION LINE was not seen - entries here are multi-line")

    # A VERDICT THAT NAMES THE QUEUE FILE rather than any label counts - this is grip0's real shape.
    qfile = os.path.join(d, "batch_20260101_pc1_byfile.txt")
    finished(qfile, ["xyq_1"])
    if not reported(qfile):
        fails.append("control broken: the by-filename queue counted as scored BEFORE its verdict existed")
    io.open(les, "a", encoding="utf-8").write(
        "- RESULT 2026-01-06 - the cell in batch_20260101_pc1_byfile.txt is a null.\n")
    if reported(qfile):
        fails.append("a verdict naming the QUEUE FILE was not seen - grip0's verdict has exactly this shape")

    # AN `OPEN` ENTRY CARRYING "TEST RESULT ... CONFIRMED" ON A CONTINUATION LINE counts. This is the case that
    # survived both earlier fixes: grip0's verdict sits under an OPEN bullet, so the entry's own tag is not a
    # verdict tag and the entry-level test skipped it.
    qopen = os.path.join(d, "batch_x_openentry.txt")
    finished(qopen, ["opq_1"])
    if not reported(qopen):
        fails.append("control broken: the OPEN-entry queue counted as scored BEFORE its verdict existed")
    io.open(les, "a", encoding="utf-8").write(
        "- OPEN 2026-01-07 - a standing question about two machines.\n"
        "  TEST RESULT (opq, files kept in place): CONFIRMED, and it is the finding of the day.\n")
    if reported(qopen):
        fails.append("a TEST RESULT/CONFIRMED line under an OPEN bullet was not seen as a verdict")
    #   ...but a lowercase ASIDE under an OPEN bullet must NOT count, or the phrase test is vacuous
    qopen2 = os.path.join(d, "batch_x_openaside.txt")
    finished(qopen2, ["asd_1"])
    io.open(les, "a", encoding="utf-8").write(
        "- OPEN 2026-01-08 - a standing question.\n"
        "  while asd was running the watcher misfired; the mechanism confirmed nothing about it.\n")
    if not reported(qopen2):
        fails.append("a lowercase aside under an OPEN bullet counted as a verdict - the phrase test is vacuous")

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
        for name, n, pref, reason in new:
            print("  %-48s %2d rows, %r: %s" % (name, n, pref, reason))
    else:
        print("unscored: nothing finished unscored since the rule was adopted (%s)" % RULE_ADOPTED)
    if old:
        print("  pre-existing backlog, COUNTED not alarmed: %d finished queue(s) with no verdict"
              " (oldest %s, newest %s)" % (len(old), old[0][0], old[-1][0]))
    amb = getattr(scan, "ambiguous", [])
    if amb:
        # COUNTED, NOT LISTED, unless asked. The list runs to 36 entries, and this tool's own docstring says a
        # check that prints 30 lines every hour is one everyone learns to skip - which is the failure it was
        # written to avoid. So the hourly pass gets one line; `--ambiguous` gets the detail.
        print("  ambiguous attribution, COUNTED not listed: %d queue(s) matched a verdict only via a name"
              " shared with another queue (run --ambiguous to list them)" % len(amb))
        if "--ambiguous" in sys.argv:
            for name, n, c in amb:
                print("    %-48s %2d rows, matched only on the shared name %r" % (name, n, c))
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
