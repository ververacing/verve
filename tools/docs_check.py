"""Docs drift check - run inside the HOURLY check (decision 0019). Read-only; prints OK or a short list of fixes.

The 2026-09-28 docs set drifted for 12 days because nothing noticed. This notices:
  1. a switch ADDED in the last 14 days of commits with no entry in docs/switch_status.json
  2. docs/SWITCHES.md older than the newest commit touching Lua (re-run tools/switch_registry.py)
  3. docs/LESSONS.md older than the newest commit touching Lua (a behaviour change that never became a lesson?)
  4. racecraft/state.md longer than 200 lines (it is rewritten, not appended) or not touched in 24 h
  5. uncommitted changes in the docs folder's own git older than a day

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
    if dirty and last and time.time() - int(last) > 24 * 3600:
        flags.append("docs/ has uncommitted changes and no docs commit in over 24 h - commit the docs folder")

if flags:
    print("DOCS DRIFT - fix before anything else:")
    for f in flags:
        print("  - " + f)
    sys.exit(1)
print("docs current: switches %d with status, state.md %d lines, LESSONS and SWITCHES newer than the last commit" % (len(status), n))
sys.exit(0)
