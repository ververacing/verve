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
