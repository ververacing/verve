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

    python tools/docs_check.py
Exit code 0 = current, 1 = something to fix (the hourly check fixes it before anything else).
"""
import json
import os
import re
import subprocess
import sys
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


flags = []

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
    any_t = int(git("log", "-1", "--format=%ct").strip() or 0)
except ValueError:
    lua_t = any_t = 0
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
LIVING = ["racecraft/state.md", "racecraft/backlog.md", "racecraft/reality.md",
          "requests_for_racecraft.md", "requests_for_broadcast.md"]
desk_top = git("rev-parse", "--show-toplevel", cwd=DESK).strip()
if not desk_top:
    flags.append("verve_desk is NOT a git repo - state.md and the other living documents have no history at all")
else:
    untracked = [f for f in LIVING
                 if os.path.exists(os.path.join(DESK, f))
                 and subprocess.run(["git", "ls-files", "--error-unmatch", f], cwd=DESK,
                                    capture_output=True, text=True).returncode != 0]
    if untracked:
        flags.append("living documents in NO git: " + ", ".join(untracked))
    dirty = [l[3:].strip() for l in git("status", "--porcelain", cwd=DESK).splitlines()
             if l[3:].strip() in LIVING]
    if dirty:
        flags.append("living documents changed but not committed: " + ", ".join(dirty)
                     + " - commit the desk repo")

if flags:
    print("DOCS DRIFT - fix before anything else:")
    for f in flags:
        print("  - " + f)
    sys.exit(1)
print("docs current: switches %d with status, state.md %d lines, LESSONS and SWITCHES newer than the last commit, "
      "living documents tracked and committed" % (len(status), n))
sys.exit(0)
