"""Docs drift check - run inside the HOURLY check (decision 0019). Read-only; prints OK or a short list of fixes.

The 2026-09-28 docs set drifted for 12 days because nothing noticed. This notices:
  1. a switch ADDED in the last 14 days of commits with no entry in docs/switch_status.json
  2. docs/SWITCHES.md older than the newest commit touching Lua (re-run tools/switch_registry.py)
  3. docs/LESSONS.md older than the newest commit touching Lua (a behaviour change that never became a lesson?)
  4. racecraft/state.md longer than 200 lines (it is rewritten, not appended) or not touched in 24 h
  5. uncommitted changes in the docs folder's own git older than a day
  6. racecraft/state.md (and the other living documents) NOT TRACKED BY ANY GIT, or tracked and left uncommitted.
     Until 2026-10-12 state.md was in no repo at all: it is rewritten wholesale under decision 0019, twice on a busy
     day, so it was always one bad overwrite from gone - and check 4 above happily reported it "current" the whole
     time, because length and freshness say nothing about recoverability. The daily "docs committed" line was only
     ever true of docs/. A check that cannot tell "versioned" from "merely present" will keep calling this fine.

  7. verve_desk/nightly/ has no file for today (from 08:00) or yesterday - the morning email never reached the desk.
     Added 2026-10-19 after the mirror sat five days behind while the email went out daily from the cloud session:
     six checks were green throughout because not one of them looked at nightly/.

    python tools/docs_check.py              # the hourly check
    python tools/docs_check.py --selftest    # check 7 against fixtures, including the real 5-day gap
Exit code 0 = current, 1 = something to fix (the hourly check fixes it before anything else).
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
DESK = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk")
DOCS = os.path.join(DESK, "docs")
STATE = os.path.join(DESK, "racecraft", "state.md")


def git(*a, cwd=VERVE):
    return subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True).stdout


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def nightly_flags(nightly_dir, now_ts, desk_top="", desk=None):
    """Check 7: is the morning email reaching the desk? Returns a list of flags.

    The nightly/ mirror stopped on 2026-10-13 and nothing noticed for five days, while the email went out on every
    one of them - it was being sent by the CLOUD session, so no step on this machine wrote it to the desk, and
    checks 1-6 stayed green the whole time because not one of them looks at nightly/. What the owner was TOLD is
    the only record here that cannot be rebuilt from the repo; for those five days it existed only in Gmail.

    The DATE IN THE FILENAME is the test, not the mtime: five days of mirror recovered in one sitting all carry
    today's mtime, so freshness-by-mtime would have called that gap current the moment it was patched.
    """
    out = []
    try:
        names = os.listdir(nightly_dir)
    except OSError:
        return ["verve_desk/nightly is missing - the morning email has nowhere to land"]
    dates = sorted(f[:-3] for f in names if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", f))
    if not dates:
        return ["verve_desk/nightly holds no YYYY-MM-DD.md - the morning email is not reaching the desk"]
    lt = time.localtime(now_ts)
    today = time.strftime("%Y-%m-%d", lt)
    yesterday = time.strftime("%Y-%m-%d", time.localtime(now_ts - 86400))
    # Before the morning send window there is legitimately no file for today, so today's is required only from
    # 08:00 - late enough that a slow send cannot flap the check, early enough to catch a miss the same day.
    want = today if lt.tm_hour >= 8 else yesterday
    if dates[-1] < want:
        out.append("verve_desk/nightly newest is %s, expected %s - mirror the morning email to the desk "
                   "(CLAUDE.md step 8: one email a day, the same text to nightly/)" % (dates[-1], want))
    newest = "nightly/%s.md" % dates[-1]
    if desk_top and subprocess.run(["git", "ls-files", "--error-unmatch", newest], cwd=desk,
                                   capture_output=True, text=True).returncode != 0:
        out.append("%s is in no git - the record of what the owner was told has no history" % newest)
    return out


def selftest():
    """Rule 4: a checking tool is not trusted until it has been MADE TO FAIL."""
    noon = time.mktime((2026, 10, 19, 12, 0, 0, 0, 0, -1))
    early = time.mktime((2026, 10, 19, 6, 30, 0, 0, 0, -1))
    cases = [  # name, folder, files in it, create the folder?, now, must it flag?
        ("no nightly folder", "nope", [], False, noon, True),
        ("folder but empty", "empty", [], True, noon, True),
        ("the real 5-day gap", "stale", ["2026-10-13.md"], True, noon, True),
        ("yesterday, at noon", "yday", ["2026-10-18.md"], True, noon, True),
        ("yesterday, at 06:30", "early", ["2026-10-18.md"], True, early, False),
        ("today, at noon", "today", ["2026-10-19.md"], True, noon, False),
        ("other files ignored", "other", ["2026-10-19.md", "notes.md", "README"], True, noon, False),
        ("newest wins, not count", "many", ["2026-10-13.md", "2026-10-19.md"], True, noon, False),
    ]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, folder, files, create, now, want in cases:
            path = os.path.join(tmp, folder)
            if create:
                os.makedirs(path, exist_ok=True)
                for f in files:
                    open(os.path.join(path, f), "w").close()
            got = nightly_flags(path, now)
            if bool(got) != want:
                print("SELFTEST FAIL: %s - expected %s, got %r" % (name, "a flag" if want else "clean", got))
                bad += 1
            else:
                print("  ok  %-24s -> %s" % (name, "flags" if got else "clean"))
    print("docs_check selftest: " + ("FAILED %d of %d" % (bad, len(cases)) if bad
                                     else "all %d cases as expected" % len(cases)))
    return 1 if bad else 0


if "--selftest" in sys.argv:
    sys.exit(selftest())

flags = []
notices = []   # things to SEE, not faults to fix: they must never block the hourly routine

# 1. new switches with no status
try:
    status = json.load(open(os.path.join(DOCS, "switch_status.json"), encoding="utf-8"))
except (OSError, ValueError):
    status = {}
    flags.append("docs/switch_status.json missing or unreadable")
added = set()
for line in git("log", "--since=14 days ago", "-p", "--", "lib", "Verve.lua").splitlines():
    m = re.match(r"^\+([A-Z])\.([A-Z][A-Z0-9_]+)\s*=", line)
    if m:
        added.add("%s.%s" % (m.group(1), m.group(2)))
known = set(status)
plumbing = re.compile(r"^(?:R\.(bgN|bgPassN|gateMoves|NOSTATE)|D\.SEED|T\.SAVE_EVERY|F\.DEC_HOLD.*)$")
missing = sorted(s for s in added if s not in known and not plumbing.match(s))
if missing:
    flags.append("switches added in the last 14 days with NO status in docs/switch_status.json: " + ", ".join(missing))

# 2/3. registry and lessons v the newest commits
try:
    lua_t = int(git("log", "-1", "--format=%ct", "--", "lib", "Verve.lua").strip() or 0)
except ValueError:
    lua_t = 0
if mtime(os.path.join(DOCS, "SWITCHES.md")) < lua_t:
    flags.append("docs/SWITCHES.md is older than the newest Lua commit - run: python tools/switch_registry.py")
if mtime(os.path.join(DOCS, "LESSONS.md")) < lua_t:
    flags.append("docs/LESSONS.md is older than the newest Lua commit - did a behaviour change land without a lesson line?")

# 4. state.md short and fresh
try:
    n = sum(1 for _ in open(STATE, encoding="utf-8", errors="replace"))
except OSError:
    n = 0
    flags.append("racecraft/state.md missing")
if n > 200:
    flags.append("racecraft/state.md is %d lines - it is REWRITTEN, not appended (decision 0019); archive and rewrite it" % n)
if mtime(STATE) and time.time() - mtime(STATE) > 24 * 3600:
    flags.append("racecraft/state.md not touched in over 24 h")

# 5. the docs folder's own git
if os.path.isdir(os.path.join(DOCS, ".git")):
    dirty = git("status", "--porcelain", cwd=DOCS).strip()
    last = git("log", "-1", "--format=%ct", cwd=DOCS).strip()
    # An uncommitted docs change is drift THE MOMENT IT EXISTS - decision 0019 says write it when it happens, never
    # batched - so this is not conditional on when the last commit was. It used to be: the test was `dirty AND the
    # last commit is over 24 h old`, which made the guard WEAKER the more diligently the folder was committed, and
    # could essentially never fire while the daily routine was being followed. On 2026-10-13 it duly reported "docs
    # current" with a just-written LESSONS line sitting uncommitted, while check 6 - the same property, guarded
    # without a time clause, two lines below - correctly flagged an uncommitted backlog.md in the same run.
    # Two checks for one property should not disagree, and the strict one was the one that worked.
    if dirty:
        # Take the path as the field AFTER the status code, not as a fixed offset: `dirty` has already been
        # .strip()ed above, so the first line has lost the leading space of " M path" and a flat l[3:] ate a
        # character off it - the first report this produced named "ESSONS.md". Check 6 uses the same offset and is
        # correct only because it never strips the whole blob first.
        flags.append("docs/ has uncommitted changes - commit the docs folder: "
                     + ", ".join(l.strip().split(None, 1)[-1] for l in dirty.splitlines()[:5]))
    if dirty and last and time.time() - int(last) > 24 * 3600:
        flags.append("docs/ ALSO has had no commit in over 24 h - the daily docs commit was missed")

# 6. the living documents are versioned AND committed
# A HARDCODED LIST WAS THE DEFECT (2026-10-23): this check passed "living documents tracked and committed"
# for months while TWENTY-SIX other files in racecraft/ sat in no git at all - coverage.md, the state_log
# archives CLAUDE.md points readers at, and both csp_user_config_record files, which are the baselines the
# owner's machine gets verified against. A list you have to remember to extend is not a check. So: the five
# named files stay named (they carry extra rules elsewhere), and EVERY .md in racecraft/ and docs/ must be
# tracked, discovered rather than listed.
LIVING = ["racecraft/state.md", "racecraft/backlog.md", "racecraft/reality.md",
          "requests_for_racecraft.md", "requests_for_broadcast.md"]


def _whitelisted(desk):
    """Paths the desk .gitignore CLAIMS to track, read from its own `!/...` lines.

    (2026-10-23) The first version of this asked "is every .md under racecraft/ and docs/ tracked?" and told me
    to `git add -f` whatever was not. That advice was WRONG and I had just finished undoing the damage of
    following it: the desk .gitignore ignores everything and whitelists BY HAND, with comments explaining each
    entry, and two files are excluded ON PURPOSE because they carry a real email address and absolute paths. A
    blanket add put the owner's real first name into the repo sixteen times. So the question is not "is
    everything tracked" - it is "is everything the whitelist PROMISES actually tracked", and the whitelist is
    the single source of truth rather than a second list kept here.
    """
    out = []
    gi = os.path.join(desk, ".gitignore")
    if not os.path.exists(gi):
        return out
    with io.open(gi, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("!/") or line.endswith("/"):
                continue
            rel = line[2:]
            if rel.endswith(".md") or rel.endswith(".jsonl") or rel.endswith(".txt"):
                out.append(rel)
    return out


def _undecided(desk, whitelisted):
    """Documents on the desk that the whitelist says nothing about - a NOTICE, never a drift error.

    A new document nobody has made a decision about should be visible, but it is not a fault: the decision may
    well be "leave it out". Printing it as drift would block the hourly routine forever on files I chose to
    exclude, which is how a check gets ignored.
    """
    out = []
    for sub in ("racecraft",):
        d = os.path.join(desk, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".md") and (sub + "/" + name) not in whitelisted:
                out.append(sub + "/" + name)
    return out
desk_top = git("rev-parse", "--show-toplevel", cwd=DESK).strip()
if not desk_top:
    flags.append("verve_desk is NOT a git repo - state.md and the other living documents have no history at all")
else:
    # docs/ IS ITS OWN REPO (its own git, synced to PC #2, never in the public repo), so a file under docs/
    # must be asked about in THAT repo. My first version of this check asked the desk repo about all of them
    # and promptly reported four tracked files as untracked - which is the tool failing the way rule 4 wants
    # it to, before the output was believed. Each path is checked where its history actually lives.
    def _tracked(rel):
        if rel.startswith("docs/"):
            cwd, arg = os.path.join(DESK, "docs"), rel[len("docs/"):]
        else:
            cwd, arg = DESK, rel
        return subprocess.run(["git", "ls-files", "--error-unmatch", arg], cwd=cwd,
                              capture_output=True, text=True).returncode == 0

    wl = _whitelisted(DESK)
    must_track = LIVING + [f for f in wl if f not in LIVING]
    untracked = [f for f in must_track
                 if os.path.exists(os.path.join(DESK, f)) and not _tracked(f)]
    if untracked:
        shown = ", ".join(untracked[:6]) + ("" if len(untracked) <= 6 else " (+%d more)" % (len(untracked) - 6))
        flags.append("the .gitignore whitelists these but git does not have them (%d): %s - `git add -f` them"
                     % (len(untracked), shown))
    undecided = _undecided(DESK, wl)
    if undecided:
        notices.append("%d racecraft document(s) the whitelist says nothing about - decide each ON ITS CONTENT "
                       "(a real name or a work email means LEAVE IT OUT; .gitignore's comments carry the "
                       "reasons): %s%s" % (len(undecided), ", ".join(os.path.basename(f) for f in undecided[:4]),
                                           "" if len(undecided) <= 4 else " and %d more" % (len(undecided) - 4)))
    dirty = [l[3:].strip() for l in git("status", "--porcelain", cwd=DESK).splitlines()
             if l[3:].strip() in LIVING]
    if dirty:
        flags.append("living documents changed but not committed: " + ", ".join(dirty)
                     + " - commit the desk repo")

# 7. the morning email reached the desk (see nightly_flags; needs desk_top from check 6)
flags += nightly_flags(os.path.join(DESK, "nightly"), time.time(), desk_top, DESK)

for _n in notices:
    print("docs notice: " + _n)

if flags:
    print("DOCS DRIFT - fix before anything else:")
    for f in flags:
        print("  - " + f)
    sys.exit(1)
# The pass line names the COMPARAND, because the old wording ("newer than the last commit") named the wrong one:
# the test is each doc's MTIME against the newest LUA commit (lib/, Verve.lua), not against the newest commit of
# any kind. A `any_t` holding exactly that broader figure sat beside it unused, which is how the label drifted.
print("docs current: switches %d with status, state.md %d lines, LESSONS and SWITCHES modified since the newest "
      "lib/Verve.lua commit, living documents tracked and committed" % (len(status), n))
sys.exit(0)
