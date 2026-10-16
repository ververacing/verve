"""Will this queue actually RUN? Check before launching, not after.

    python tools/queue_check.py tools/harness_results/batch_YYYYMMDD_name.txt
    python tools/queue_check.py --selftest

WHY THIS EXISTS. batch_20261015_pc1_cspf5.txt was recorded on the desk as "built + VERIFIED (11 seeds)" and would
have run ZERO races. Every one of its 15 rows had a MISSING SPACE - `--troublespots {"FRESH":true}--settings
{...}` - so shlex read `{"FRESH":true}--settings` as one token, the next JSON blob was left with no flag, and
harness.py exited with "unrecognized arguments" on every row. batch.py does not abort on a failing row, so it
walked the whole queue failing each one.

**THE VERIFICATION THAT WAS DONE CHECKED THE ARMS, NOT THE LAUNCH.** Eleven seeded tests proved the arm
composition was right and none of them asked whether harness.py would accept the command line. A queue that runs
zero races looks exactly like a queue that has not started yet, which is the same class of silence as a stale
status file and a tool that cannot see its own archive.

The decisive assertion is DANGLING POSITIONALS: after shlex, every token must be a flag or the value of the flag
before it. Anything left over means a flag got swallowed into a value. That one check catches the missing-space
defect, a stray quote, and a value accidentally pasted twice. Unknown-flag checking is second: the flag list is
read from harness.py's own add_argument calls, so it cannot drift from the real parser.

This does NOT run harness.py. Importing or running it taskkills acs.exe (CLAUDE.md), so a validator that calls it
would be unusable while a race is going - exactly when a queue most needs checking.
"""
import argparse
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "harness.py")


def known_flags(path=HARNESS):
    """Every --flag harness.py's argparse declares, read from the source. Never hardcoded: a hardcoded list
    drifts from the parser and then reports a real flag as unknown, which teaches you to ignore the tool."""
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    flags = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', src))
    flags |= set(re.findall(r"add_argument\(\s*'(--[a-z0-9-]+)'", src))
    return flags or None


def rows_of(path):
    """Exactly what batch.py:62 will iterate."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [l.strip() for l in fh if l.strip() and not l.strip().startswith("#")]


def check_row(row, flags):
    """-> list of problems with one row."""
    bad = []
    try:
        toks = shlex.split(row, posix=False)
    except ValueError as e:
        return ["cannot be parsed as a command line (%s)" % e]
    i, positionals = 0, []
    while i < len(toks):
        t = toks[i]
        if t.startswith("--"):
            if flags is not None and t not in flags:
                bad.append("unknown flag %s (harness.py declares no such argument)" % t)
            if i + 1 < len(toks) and not toks[i + 1].startswith("--"):
                i += 2
            else:
                i += 1
        else:
            positionals.append(t)
            i += 1
    if positionals:
        bad.append("DANGLING VALUE(S) with no flag: %s  <- usually a MISSING SPACE before the next --flag"
                   % ", ".join(p[:48] for p in positionals[:3]))
    return bad


def check(path, flags=None):
    flags = flags if flags is not None else known_flags()
    if flags is None:
        print("  (note: could not read harness.py's flag list - unknown-flag checking is OFF)")
    rows = rows_of(path)
    print("%s" % os.path.basename(path))
    print("  rows batch.py will run: %d" % len(rows))
    if not rows:
        print("  !! ZERO ROWS - this queue would run nothing")
        return False

    ok = True
    labels = []
    for n, row in enumerate(rows, 1):
        for problem in check_row(row, flags):
            print("  !! row %d: %s" % (n, problem))
            ok = False
        m = re.search(r"--label\s+(\S+)", row)
        labels.append(m.group(1) if m else None)

    missing = [n for n, l in enumerate(labels, 1) if not l]
    if missing:
        print("  !! rows with no --label (their results.csv rows cannot be told apart): %s" % missing)
        ok = False
    dupes = sorted({l for l in labels if l and labels.count(l) > 1})
    if dupes:
        print("  !! DUPLICATE labels: %s" % ", ".join(dupes))
        ok = False

    print("  %s" % ("every row is launchable" if ok else "NOT LAUNCHABLE - fix the rows above first"))
    return ok


def selftest():
    import tempfile
    flags = {"--track", "--laps", "--settings", "--troublespots", "--label", "--assists"}
    ok = True
    print("=== queue_check selftest ===")

    good = '--track spa --laps 5 --troublespots {"FRESH":true} --settings {"a":1} --label x_1'
    bad_space = '--track spa --laps 5 --troublespots {"FRESH":true}--settings {"a":1} --label x_1'

    cases = [
        ("a clean row passes", good, True, None),
        ("THE REAL DEFECT: missing space before --settings", bad_space, False, "DANGLING"),
        ("an unknown flag is caught", good + " --nosuchflag 3", False, "unknown flag"),
        ("a row with no --label is caught", '--track spa --laps 5', False, "no --label"),
    ]
    for name, row, want_ok, want_txt in cases:
        fd, p = tempfile.mkstemp(suffix=".txt", text=True)
        os.close(fd)
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("# a comment that must be skipped\n\n" + row + "\n")
            import io as _io
            from contextlib import redirect_stdout
            buf = _io.StringIO()
            with redirect_stdout(buf):
                got = check(p, flags)
            out = buf.getvalue()
            good_case = (got == want_ok) and (want_txt is None or want_txt in out)
            print("  %-48s %s" % (name + "?", "yes" if good_case else "NO - BROKEN"))
            ok &= good_case
        finally:
            os.remove(p)

    # duplicate labels across two rows
    fd, p = tempfile.mkstemp(suffix=".txt", text=True)
    os.close(fd)
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(good + "\n" + good + "\n")
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            got = check(p, flags)
        good_case = (not got) and "DUPLICATE" in buf.getvalue()
        print("  %-48s %s" % ("duplicate labels caught?", "yes" if good_case else "NO - BROKEN"))
        ok &= good_case
    finally:
        os.remove(p)

    # a comments-only file must read as ZERO ROWS, not as fine
    fd, p = tempfile.mkstemp(suffix=".txt", text=True)
    os.close(fd)
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# only comments\n#\n")
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            got = check(p, flags)
        good_case = (not got) and "ZERO ROWS" in buf.getvalue()
        print("  %-48s %s" % ("a comments-only queue caught?", "yes" if good_case else "NO - BROKEN"))
        ok &= good_case
    finally:
        os.remove(p)

    # and the flag list must really come from harness.py
    real = known_flags()
    live = real is not None and "--track" in real and "--settings" in real
    print("  %-48s %s (%s flags)" % ("flag list read from harness.py itself?", "yes" if live else "NO",
                                     len(real) if real else 0))
    ok &= bool(live)

    print("\n  %s" % ("every rule holds" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", help="the queue file to check")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.spec:
        ap.error("give a queue file, or --selftest")
    return 0 if check(a.spec) else 1


if __name__ == "__main__":
    sys.exit(main())
