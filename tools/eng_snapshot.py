"""Keep PC #2's copy of verve-engineer current, since it cannot clone or pull the private repo itself.

    python tools/eng_snapshot.py            # fetch, fast-forward, re-drop the desk snapshot if the head moved
    python tools/eng_snapshot.py --check    # say whether a re-drop is needed, change nothing

The arrangement (owner, 2026-10-11, decision 0024): github.com/ververacing/verve-engineer is private and PC #2 has no
credential for it, and it is not getting one. So PC #1 is the gateway - it drops a source snapshot on the shared desk
for PC #2 to install from, and it pushes PC #2's transcripts. The weakness of a snapshot is that it goes stale while
the engineer's author keeps committing (four commits in one evening), which is what this exists to prevent: run it in
the hourly check and the desk copy is never more than an hour behind.

Deliberately NOT copied: .git (so this is a snapshot, not a clone), .venv (machine-specific), models/ (a 68 MB vosk
speech-recognition model, needed only for voice INPUT, not for `run --tts null`), and the recording folders.
"""
import os
import shutil
import subprocess
import sys
import time

REPO = r"C:\Users\Tyler\Desktop\verve-engineer"
BRANCH = "claude/engineer-groundwork"
DESK = r"C:\Users\Tyler\Documents\Assetto Corsa\verve_desk\pc2\eng_tool"
WANTED = ("pyproject.toml", "src", "tests", "docs", "README.md")
STAMP = "PROVENANCE.md"


def git(*args, repo=REPO):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def desk_head():
    """The short head recorded in the snapshot we last dropped, or None."""
    p = os.path.join(DESK, STAMP)
    if not os.path.isfile(p):
        return None
    for line in open(p, encoding="utf-8", errors="replace"):
        if line.strip().startswith("short "):   # the SHORT hash: comparing it to the full one re-dropped every run
            return line.split()[-1]
    return None


def drop(head, short):
    os.makedirs(os.path.dirname(DESK), exist_ok=True)
    tmp = DESK + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for item in WANTED:
        src = os.path.join(REPO, item)
        if not os.path.exists(src):
            continue
        dst = os.path.join(tmp, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"))
        else:
            shutil.copy2(src, dst)
    with open(os.path.join(tmp, STAMP), "w", encoding="utf-8") as f:
        f.write(f"""# verve-engineer source snapshot for PC #2

Dropped by PC #1's racecraft agent, {time.strftime('%Y-%m-%d %H:%M')}, because github.com/ververacing/verve-engineer
is PRIVATE and PC #2 has no credential for it (owner's decision 0024: it is not getting one - PC #1 is the gateway,
and PC #2's transcripts come back across the desk for PC #1 to commit and push).

    repo   github.com/ververacing/verve-engineer
    branch {BRANCH}
    head   {head}
    short  {short}

A SNAPSHOT, not a clone: no .git here, so `git pull` is impossible on PC #2. PC #1 runs tools/eng_snapshot.py in its
hourly check, so this folder is never more than an hour behind the branch. If the short head above is not what PC #1
reports, ask for a re-drop.

LEFT OUT: .git, .venv (machine-specific), models/ (68 MB vosk model, voice INPUT only - not needed for --tts null),
and the live_test_*/ recording folders.

INSTALL: make a venv, then `pip install -e .` here. The core package has NO dependencies on Python >= 3.11 (only
tomli below it), so nothing is built and 3.15 is fine. The voice extras are optional and every import of them is
guarded by try/except ImportError, so `run --tts null` needs none of them.
""")
    shutil.rmtree(DESK, ignore_errors=True)
    os.rename(tmp, DESK)


def main():
    check_only = "--check" in sys.argv
    if not os.path.isdir(os.path.join(REPO, ".git")):
        print(f"eng_snapshot: {REPO} is not a git repo - nothing done")
        return 1
    rc, _, err = git("fetch", "origin", BRANCH)
    if rc != 0:
        print("eng_snapshot: fetch failed:", err.splitlines()[-1] if err else rc)
    behind = git("rev-list", "--count", f"HEAD..origin/{BRANCH}")[1] or "0"
    if behind != "0" and not check_only:
        rc, out, err = git("pull", "--ff-only")
        if rc != 0:
            print(f"eng_snapshot: {behind} commits behind but fast-forward FAILED (local work in that tree?):",
                  (err or out).splitlines()[-1] if (err or out) else rc)
        else:
            print(f"eng_snapshot: fast-forwarded {behind} commits")
    head = git("rev-parse", "HEAD")[1]
    short = git("rev-parse", "--short", "HEAD")[1]
    have = desk_head()
    if have == short:
        print(f"eng_snapshot: desk snapshot current at {short} (branch {behind} ahead of us)")
        return 0
    if check_only:
        print(f"eng_snapshot: RE-DROP NEEDED - desk has {have or 'nothing'}, repo is at {short}")
        return 0
    drop(head, short)
    print(f"eng_snapshot: dropped {short} to the desk (was {have or 'nothing'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
