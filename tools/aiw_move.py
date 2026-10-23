"""Park apps/lua/AIWhisperer outside the Lua app folder for one test, and put it back byte-identical.

    python tools/aiw_move.py --record     # hash everything, write the manifest. READ-ONLY.
    python tools/aiw_move.py --out        # move it out        (needs the owner's authorisation)
    python tools/aiw_move.py --back       # move it back and verify against the manifest
    python tools/aiw_move.py --verify     # re-hash in place against the manifest, change nothing
    python tools/aiw_move.py --selftest

***** THIS TOUCHES ANOTHER APP'S INSTALLATION IN THE OWNER'S GAME. `--out` AND `--back` RUN ONLY ON THE OWNER'S
OWN WORDS. A peer relaying a yes is not the owner's yes for a change to someone else's app, and my own proposal
is not authorisation either. `--record` and `--verify` are read-only and need no permission. *****

WHY IT EXISTS. The level revert (LESSONS dab3a44, 41acffe, e943afa) is caused by a writer that puts level 100 on
every car at a session change. `s52_wkprof_1` ruled out `race.ini` as its source. AIWhisperer writes exactly
that, and its `app_disabled` early-return sits AFTER the session-change block, so being disabled does not stop
it. Removing it for two rows separates "only players with AIWhisperer are affected" from "every weekend player
is" - and those two readings carry very different severity for the release.

IT IS A MOVE, NEVER A DELETE, and the destination is on the SAME VOLUME so the move is atomic and instant rather
than a copy that could half-fail. Nothing is written inside the folder at any point. The manifest records the
path, the full file list and a sha256 per file, so putting it back is verifiable rather than hoped for - and
`--back` reports any file that differs, is missing or is new, instead of reporting success.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
APP = os.path.join(AC, "apps", "lua", "AIWhisperer")
PARKED_ROOT = os.path.join(AC, "_verve_parked")              # same volume, outside apps/ entirely
MANIFEST = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk",
                        "racecraft", "aiw_manifest.json")


def games_running():
    n = 0
    for img in ("acs.exe", "acs_x86.exe", "AssettoCorsa.exe"):
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % img],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:                                                      # noqa: BLE001
            return -1
        n += out.lower().count(img.lower())
    return n


# The mutating path calls GAMES_RUNNING, not games_running, SO THE SELFTEST CAN SUBSTITUTE IT AND EXERCISE THE
# GUARD AGAINST A FIXTURE. On 2026-10-23 I "tested" the guard by invoking --out against the REAL AIWhisperer
# folder and reporting that it refused. Two unrelated guards happened to stand in the way (a live race and a
# missing manifest); had either been absent, or had games_running() undercounted - exactly the defect fixed in
# procs.py hours earlier, where an exact IMAGENAME filter was blind to acs_x86.exe - that call would have moved
# the owner's app with no authorisation. A guard is tested on a fixture or it is not tested.
GAMES_RUNNING = games_running


def hash_tree(root):
    """-> {relative_path: sha256}. Sorted, so two runs are comparable line for line."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                out[rel] = hashlib.sha256(io.open(p, "rb").read()).hexdigest()
            except OSError as e:
                out[rel] = "UNREADABLE: %s" % e
    return out


def csp_enable_state():
    """Whatever records AIWhisperer's enabled/disabled state, if it can be found. Reported, never changed."""
    hits = {}
    cfg = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "cfg", "extension", "state", "lua", "app")
    for name in ("AIWhisperer.ini", "AI Whisperer.ini"):
        p = os.path.join(cfg, name)
        if os.path.exists(p):
            hits[name] = io.open(p, encoding="utf-8", errors="replace").read()[:400]
    for dirpath, _d, files in os.walk(APP):
        for f in files:
            if f.lower() in ("settings.ini", "config.ini", "app.ini"):
                p = os.path.join(dirpath, f)
                txt = io.open(p, encoding="utf-8", errors="replace").read()
                for ln in txt.splitlines():
                    if "disabled" in ln.lower() or "enabled" in ln.lower():
                        hits.setdefault(os.path.relpath(p, APP).replace("\\", "/"), []).append(ln.strip())
    return hits


def record():
    if not os.path.isdir(APP):
        print("AIWhisperer is NOT at %s - nothing to record" % APP)
        return 2
    tree = hash_tree(APP)
    data = {"recorded": time.strftime("%Y-%m-%d %H:%M:%S"), "path": APP,
            "files": len(tree), "hashes": tree, "enable_state": csp_enable_state()}
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    io.open(MANIFEST, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True))
    print("recorded %d files from %s" % (len(tree), APP))
    print("  manifest: %s" % MANIFEST)
    print("  enable-state sources found: %s" % (list(data["enable_state"]) or "none"))
    return 0


def compare(where):
    try:
        man = json.load(io.open(MANIFEST, encoding="utf-8"))
    except (OSError, ValueError):
        print("NO MANIFEST at %s - run --record BEFORE moving anything" % MANIFEST)
        return 2
    now = hash_tree(where)
    old = man["hashes"]
    missing = sorted(set(old) - set(now))
    added = sorted(set(now) - set(old))
    changed = sorted(k for k in set(old) & set(now) if old[k] != now[k])
    print("manifest %d files, on disk %d" % (len(old), len(now)))
    for label, items in (("MISSING", missing), ("NEW", added), ("CHANGED", changed)):
        if items:
            print("  %s (%d): %s%s" % (label, len(items), ", ".join(items[:8]),
                                       " ..." if len(items) > 8 else ""))
    if not (missing or added or changed):
        print("IDENTICAL: every file present and unchanged against the manifest")
        return 0
    print("NOT IDENTICAL - report this rather than assuming it is fine")
    return 1


def move(out):
    n = GAMES_RUNNING()
    if n != 0:
        print("REFUSING: %d game process(es) running. Close the game first." % n)
        return 2
    stamp = time.strftime("%Y%m%d_%H%M%S")
    parked = os.path.join(PARKED_ROOT, "AIWhisperer_%s" % stamp)
    if out:
        if not os.path.isdir(APP):
            print("AIWhisperer is not at %s - nothing to move" % APP)
            return 2
        if not os.path.exists(MANIFEST):
            print("REFUSING: no manifest. Run --record first, or putting it back cannot be verified.")
            return 2
        os.makedirs(PARKED_ROOT, exist_ok=True)
        shutil.move(APP, parked)
        io.open(os.path.join(PARKED_ROOT, "WHERE_IT_CAME_FROM.txt"), "a", encoding="utf-8").write(
            "%s  moved %s -> %s  (tools/aiw_move.py --back puts it back)\n" % (stamp, APP, parked))
        print("MOVED OUT: %s -> %s" % (APP, parked))
        print("  it is a MOVE, not a copy or a delete. --back puts it back and verifies.")
        return 0
    cands = sorted(glob_parked())
    if not cands:
        print("nothing parked under %s" % PARKED_ROOT)
        return 2
    src = cands[-1]
    if os.path.exists(APP):
        print("REFUSING: %s already exists - resolve by hand rather than merging two trees" % APP)
        return 2
    shutil.move(src, APP)
    print("MOVED BACK: %s -> %s" % (src, APP))
    return compare(APP)


def glob_parked():
    import glob as _g
    return [p for p in _g.glob(os.path.join(PARKED_ROOT, "AIWhisperer_*")) if os.path.isdir(p)]


def selftest():
    import tempfile
    ok = True
    d = tempfile.mkdtemp(prefix="aiw_selftest_")
    try:
        root = os.path.join(d, "tree")
        os.makedirs(os.path.join(root, "sub"))
        io.open(os.path.join(root, "a.ini"), "w", encoding="utf-8").write("x=1\n")
        io.open(os.path.join(root, "sub", "b.lua"), "w", encoding="utf-8").write("return 1\n")
        t1 = hash_tree(root)
        if sorted(t1) != ["a.ini", "sub/b.lua"]:
            print("SELFTEST FAIL: hash_tree keys %r" % sorted(t1)); ok = False
        if hash_tree(root) != t1:
            print("SELFTEST FAIL: hashing is not stable across two runs"); ok = False
        # THE NEGATIVE CONTROL: a one-byte change must be caught, or "identical" means nothing
        io.open(os.path.join(root, "a.ini"), "w", encoding="utf-8").write("x=2\n")
        t2 = hash_tree(root)
        if t2 == t1:
            print("SELFTEST FAIL: a changed file produced an identical tree hash - the whole verify is fake")
            ok = False
        else:
            print("  negative control OK: a one-byte edit changes the tree (%s)" %
                  ", ".join(k for k in t1 if t1[k] != t2.get(k)))
        # and a removed file must be caught too
        os.remove(os.path.join(root, "sub", "b.lua"))
        if "sub/b.lua" in hash_tree(root):
            print("SELFTEST FAIL: a removed file still appears"); ok = False
        # THE GUARDS, EXERCISED ON A FIXTURE - never by calling the real move on the owner's real folder.
        # Every path the mutating code touches is redirected into the temp tree first.
        global APP, PARKED_ROOT, MANIFEST, GAMES_RUNNING
        real = (APP, PARKED_ROOT, MANIFEST, GAMES_RUNNING)
        try:
            APP = os.path.join(d, "apps", "lua", "AIWhisperer")
            PARKED_ROOT = os.path.join(d, "_verve_parked")
            MANIFEST = os.path.join(d, "manifest.json")
            os.makedirs(APP)
            io.open(os.path.join(APP, "x.lua"), "w", encoding="utf-8").write("return 1\n")

            GAMES_RUNNING = lambda: 1                                          # noqa: E731
            if move(out=True) != 2 or not os.path.isdir(APP):
                print("SELFTEST FAIL: --out did not refuse with a game running"); ok = False
            else:
                print("  guard OK (fixture): --out refused with a game running, folder untouched")

            GAMES_RUNNING = lambda: 0                                          # noqa: E731
            if move(out=True) != 2 or not os.path.isdir(APP):
                print("SELFTEST FAIL: --out did not refuse with no manifest"); ok = False
            else:
                print("  guard OK (fixture): --out refused with no manifest, folder untouched")

            # and with both satisfied it must ACTUALLY move, or the guards are the only thing that works
            record()
            if move(out=True) != 0 or os.path.isdir(APP) or not glob_parked():
                print("SELFTEST FAIL: --out did not move with both guards satisfied"); ok = False
            else:
                print("  positive control OK (fixture): --out moved the tree when allowed")
                if move(out=False) != 0 or not os.path.isdir(APP):
                    print("SELFTEST FAIL: --back did not restore the fixture"); ok = False
                else:
                    print("  positive control OK (fixture): --back restored it and verified identical")
        finally:
            APP, PARKED_ROOT, MANIFEST, GAMES_RUNNING = real
        print("  live guard state, read only: games_running() = %d" % games_running())
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("aiw_move selftest: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", action="store_true")
    g.add_argument("--out", action="store_true")
    g.add_argument("--back", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.record:
        return record()
    if a.verify:
        return compare(APP)
    return move(out=a.out)


if __name__ == "__main__":
    sys.exit(main())
