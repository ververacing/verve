"""Where the feeds and the archive live, in one place.

Every tool that reads race feeds used to hard-code "D:/verve_archive/verve_feed" in its own list. That is wrong twice
over: the archive moves (the owner is taking the D: SSD out on 8 Oct 2026 to give PC #2 a working drive), and because
every one of those tools reads with glob.glob(), a missing archive returns NOTHING rather than raising - the tool
quietly analyses only the live feeds and reports a smaller number with no indication that half its data was absent.
Silent data loss is how this week produced two wrong conclusions already.

So: resolve the archive wherever it is, and SAY when it cannot be found. Tools call feed_dirs() and get back only
directories that exist, plus a one-line warning on stderr the first time the archive is missing.
"""
import os
import sys

DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
LIVE_FEED = os.path.join(DOCS, "verve_feed")
HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)

# first existing wins; add to this list rather than hard-coding a path in a tool
ARCHIVE_CANDIDATES = [
    "D:/verve_archive",
    "E:/verve_archive",
    os.path.join(VERVE, "tools", "harness_results", "archive"),
]
_warned = False


def archive_root():
    """The archive directory, or None. None is a normal answer: the drive may simply not be attached."""
    for p in ARCHIVE_CANDIDATES:
        if os.path.isdir(p):
            return p
    return None


def archive_feed_dir():
    r = archive_root()
    return os.path.join(r, "verve_feed") if r else None


def feed_dirs(warn=True):
    """Every directory holding race feeds, live first, archive second - existing ones only.

    warn=True prints one line to stderr if the archive is missing, so a tool's numbers are never quietly built from
    half the data. Pass warn=False in a tool that reports the absence itself.
    """
    global _warned
    out = [d for d in (LIVE_FEED, archive_feed_dir()) if d and os.path.isdir(d)]
    if warn and not archive_feed_dir() and not _warned:
        _warned = True
        print("  (note: no feed archive found - reading live feeds only. Looked in: %s)"
              % ", ".join(ARCHIVE_CANDIDATES), file=sys.stderr)
    return out


def track_feeds(track, warn=True, dirs=None):
    """Every feed whose name contains `track`, live and archived, each race EXACTLY ONCE (live copy wins).

    The collector lives here and not in each tool because that is how the old "D:/verve_archive" mess started -
    one copy per tool, and then the archive moved. 14 tools still glob the live directory alone (2026-10-22), so
    migrating one is a one-line change to call this.

    The de-duplication is not decorative: housekeeping MOVES a file, so during a move a feed can exist in both
    directories, and counting it twice doubles that race inside a pooled figure.

    `dirs` overrides the directory list. It exists so the selftest can pass the same directory twice and FORCE a
    duplicate: an assertion that waits for today's files to contain one guards nothing tomorrow.
    """
    import glob
    seen, out = set(), []
    for d in (dirs if dirs is not None else feed_dirs(warn=warn)):
        for p in sorted(glob.glob(os.path.join(d, "*" + track + "*.jsonl"))):
            b = os.path.basename(p)
            if b in seen:
                continue
            seen.add(b)
            out.append(p)
    return sorted(out, key=os.path.basename)


def _selftest():
    """Asserts what actually breaks: that the archive is reachable, and that a race is never counted twice.

    The duplicate condition is FORCED by passing the same directory twice, never hoped for from today's files -
    an assertion that waits for the data to supply its condition guards nothing tomorrow (learned the hard way on
    excursions.py the same day, where that mistake survived two attempts).
    """
    import glob
    ok = True
    if archive_root() is None:
        print("  (no archive found; the reachability check cannot run here)")
    else:
        if archive_feed_dir() not in feed_dirs(warn=False):
            print("SELFTEST FAIL: feed_dirs() omits the archive feed dir that archive_root() found")
            ok = False
    dirs = feed_dirs(warn=False)
    if not dirs:
        print("SELFTEST FAIL: feed_dirs() returned nothing at all")
        ok = False
    else:
        # force the duplicate: collect from one directory listed twice
        d = None
        for cand in dirs:
            if glob.glob(os.path.join(cand, "*.jsonl")):
                d = cand
                break
        if d is None:
            print("SELFTEST FAIL: no feed directory holds a single .jsonl, so nothing can be checked")
            ok = False
        else:
            # THE FORCED CONDITION: the same directory twice. Nothing about today's files can make this vacuous.
            got = [os.path.basename(p) for p in track_feeds("", warn=False, dirs=[d, d])]
            if not got:
                print("SELFTEST FAIL: track_feeds() found nothing in a directory that holds .jsonl files")
                ok = False
            elif len(got) != len(set(got)):
                print("SELFTEST FAIL: track_feeds() returned the same race twice (%d paths, %d distinct)"
                      % (len(got), len(set(got))))
                ok = False
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def archive_dir_for_housekeeping():
    """Where harness.py moves old diag/feed files. None means 'do not archive' - the caller leaves them in place."""
    r = archive_root()
    if r:
        return r
    fallback = os.path.join(VERVE, "tools", "harness_results", "archive")
    try:
        os.makedirs(fallback, exist_ok=True)
        return fallback
    except OSError:
        return None


if __name__ == "__main__":
    import sys as _s
    if "--selftest" in _s.argv:
        _s.exit(_selftest())
    print("feed dirs:")
    for _d in feed_dirs():
        print("  %s" % _d)
