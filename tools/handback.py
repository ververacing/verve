"""Give the owner's game back after a harness run - all four files, checked by HASH, never by mtime.

    python tools/handback.py                 # check and restore; one verdict line
    python tools/handback.py --check         # check only, change nothing
    python tools/handback.py --baseline      # record the current files AS the owner's (see the guard)
    python tools/handback.py --selftest

WHY IT EXISTS. On 2026-10-23 a race was stopped mid-run for the owner's pause. `restore_assists`,
`restore_csp_overrides` and `restore_pure` all live in `main()`'s `finally` (harness.py:1325), **and a `finally`
does not survive a `taskkill`** - so the stop left `cfg/assists.ini` on the harness's `DAMAGE=100` and the owner
raced for 37 minutes at full damage against their own `DAMAGE=0`. The procedure in use named only two leftovers
(a stale `harness.lua` and `cfg/video.ini`); both were fixed, and the two that were not on the list were not.

    A LIST THAT CAN BE HALF-REMEMBERED UNDER TIME PRESSURE IS NOT A PROCEDURE. THIS IS THE LIST.

THE FOUR FILES the harness writes in the owner's own config:
  cfg/assists.ini                  DAMAGE / FUEL_RATE / TYRE_WEAR      (apply_assists)
  cfg/race.ini                     the whole race definition           (written fresh every run by design)
  cfg/extension/new_behaviour.ini  CSP AI_TWEAKS keys                  (apply_csp_overrides, only with --csp)
  cfg/video.ini                    resolution / windowing              (video_profile, its own marker + backup)

HASHES, NOT TIMESTAMPS. `shutil.copy2` preserves mtime, so a harness backup carries the mtime of the OWNER'S
file and says nothing about when the copy was made. Reading one as a history produced two near-false reports
about the owner's machine in a single day, one of which was minutes from an email. Every judgement here is a
sha256 against a recorded value, or the presence of a backup file - never a date.

RACE.INI IS DELIBERATELY NOT RESTORED. The harness rewrites it per run and Content Manager rewrites it whenever
the owner launches, so there is no "original" to put back. It is still CHECKED, because a leftover
`race.ini.harness-backup` means an interrupted run and is worth seeing.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
CFG = os.path.join(DOCS, "cfg")
BASELINE = os.path.join(DOCS, "verve_desk", "racecraft", "owner_files_baseline.json")

# (name, path, how to hand it back). "replace" consumes the backup, as the harness's own restore does.
# "copy" leaves the backup in place, and race.ini MUST be copy - see below.
FILES = [
    ("assists.ini", os.path.join(CFG, "assists.ini"), "replace"),
    # race.ini: CORRECTED TWICE within the hour, and the second correction matters more than the first.
    # First I wrote it unrestorable ("nothing owns an original"). The disk refuted that: the surviving
    # race.ini.harness-backup described CONFIG_TRACK=east with CARS=10 - the OWNER'S COTA East grid - while the
    # live file held the harness's 20-car GP row, so the backup IS theirs and the live file is ours.
    # Then I nearly made it "replace" like the others, WHICH WOULD HAVE BEEN A REAL BUG: harness.py:1193 builds
    # every row's race.ini FROM that backup as its TEMPLATE, and there is no race.ini restore anywhere in the
    # harness at all. os.replace would CONSUME the template; the next run would find no backup, copy the
    # harness's own race.ini as "the original", and every later row would be built from our file instead of
    # theirs - the 14 Oct cascade, caused by the tool meant to prevent it.
    # So: hand it back by COPY, never touch the backup. A surviving race.ini backup is NORMAL and PERMANENT by
    # design, and is NOT evidence of a failed restore (unlike the other three, where os.replace consumes it).
    ("race.ini", os.path.join(CFG, "race.ini"), "copy"),
    ("new_behaviour.ini", os.path.join(CFG, "extension", "new_behaviour.ini"), "replace"),
    ("video.ini", os.path.join(CFG, "video.ini"), "replace"),
]


def sha(path):
    try:
        return hashlib.sha256(io.open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def races_running():
    """The game process count, both executables. A hand-back must never run mid-race."""
    n = 0
    for img in ("acs.exe", "acs_x86.exe"):
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % img],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:                                                      # noqa: BLE001
            return -1
        n += out.lower().count(img)
    return n


def load_baseline():
    try:
        return json.load(io.open(BASELINE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def report(do_restore):
    base = load_baseline()
    lines, bad, left = [], 0, []
    for name, path, how in FILES:
        bak = path + ".harness-backup"
        has_bak = os.path.exists(bak)
        cur = sha(path)
        want = base.get(name)
        note = ""
        if has_bak and do_restore:
            try:
                if how == "copy":
                    shutil.copy2(bak, path)          # race.ini: the backup is the harness's TEMPLATE. Keep it.
                    note = "   (handed back by COPY; the backup is the harness's template and is kept)"
                else:
                    os.replace(bak, path)            # the harness's own call; consumes the backup
                    has_bak = False
                cur = sha(path)
            except OSError as e:
                lines.append("  %-18s RESTORE FAILED: %s" % (name, e))
                bad += 1
                continue
        if cur is None:
            state = "ABSENT"
            bad += 1
        elif want is None:
            state = "no recorded value (run --baseline when the game is closed and no backup needs restoring)"
        elif cur == want:
            state = "MATCHES the recorded owner value"
        elif name == "race.ini":
            # (owner item 27) the harness rewrites cfg/race.ini every session by design, so it ~always differs from
            # the owner's recorded baseline. Keep LISTING it, labelled, but do NOT count it as a change/failure.
            state = "rewritten every launch by the harness (expected; not counted as a change)"
        else:
            state = "DIFFERS from the recorded owner value"
            bad += 1
        # A surviving race.ini backup is normal and by design; the others surviving means a run did not restore.
        if has_bak and how != "copy":
            left.append(name)
        lines.append("  %-18s %s%s%s" % (name, state, note,
                                         "   [.harness-backup PRESENT]" if has_bak else ""))
    return lines, bad, left


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--baseline", action="store_true", help="record the current files as the owner's own")
    ap.add_argument("--force", action="store_true", help="act even with a race running (do not)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    import time
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    n = races_running()
    if n != 0 and not args.force:
        print("REFUSING: %d game process(es) running - a hand-back mid-race would break the row and the owner's "
              "settings both. Stop the queue first, or pass --force knowingly. (time of read %s)" % (n, now))
        return 2

    if args.baseline:
        # THE GUARD THAT MATTERS: never record a value while a backup exists. That is how the 14 Oct cascade
        # happened - a modified file was backed up as "the original" and the real one was lost.
        stale = [name for name, path, how in FILES
                 if how != "copy" and os.path.exists(path + ".harness-backup")]
        if stale:
            print("REFUSING to take a baseline: a .harness-backup exists for %s, so the live file may still "
                  "carry a test value. Restore first, then baseline. (time of read %s)" % (", ".join(stale), now))
            return 2
        data = {name: sha(path) for name, path, _how in FILES if sha(path)}
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        io.open(BASELINE, "w", encoding="utf-8").write(json.dumps(data, indent=2, sort_keys=True))
        print("baseline recorded for %d files -> %s  (time of read %s)" % (len(data), BASELINE, now))
        return 0

    lines, bad, left = report(do_restore=not args.check)
    print("HANDBACK %s   time of read %s" % ("CHECK" if args.check else "RESTORE", now))
    for l in lines:
        print(l)
    print("  no consuming .harness-backup left: %s" % ("yes" if not left else "NO - " + ", ".join(left)))
    print("  (race.ini.harness-backup is the harness's build template and is kept on purpose)")
    print("VERDICT: %s" % ("the owner's game is as they left it" if not bad and not left
                           else "NOT CLEAN - %d file(s) off their recorded value%s"
                                % (bad, ", backups left" if left else "")))
    return 0 if (not bad and not left) else 1


def selftest():
    ok = True
    names = [f[0] for f in FILES]
    for must in ("assists.ini", "race.ini", "new_behaviour.ini", "video.ini"):
        if must not in names:
            print("SELFTEST FAIL: %s is not in the check list - the list is the whole point" % must)
            ok = False
    if len(FILES) != 4:
        print("SELFTEST FAIL: expected 4 files, found %d" % len(FILES))
        ok = False
    # race.ini must be handed back by COPY: harness.py:1193 builds every row from that backup as its template,
    # so consuming it would make the next run adopt a harness file as the owner's original.
    how = {f[0]: f[2] for f in FILES}
    if how.get("race.ini") != "copy":
        print("SELFTEST FAIL: race.ini must be handed back by COPY, not replace - os.replace consumes the "
              "backup that harness.py:1193 uses as its build template")
        ok = False
    if any(how[n] != "replace" for n in ("assists.ini", "new_behaviour.ini", "video.ini")):
        print("SELFTEST FAIL: these three must consume their backup, as the harness does")
        ok = False
    # the negative control: a baseline must be refused while a backup exists. Prove the guard by faking one.
    probe = os.path.join(CFG, "assists.ini") + ".harness-backup"
    made = False
    try:
        if not os.path.exists(probe) and os.path.exists(os.path.join(CFG, "assists.ini")):
            shutil.copy2(os.path.join(CFG, "assists.ini"), probe)
            made = True
        if os.path.exists(probe):
            stale = [n for n, p, _ in FILES if os.path.exists(p + ".harness-backup")]
            if not stale:
                print("SELFTEST FAIL: a present .harness-backup was not detected, so the baseline guard "
                      "cannot fire")
                ok = False
            else:
                print("  negative control OK: the baseline guard sees %s" % ", ".join(stale))
        else:
            print("  (negative control skipped: no assists.ini to copy)")
    finally:
        if made:
            try:
                os.remove(probe)
            except OSError:
                print("  !! left a probe backup behind at %s - REMOVE IT" % probe)
                ok = False
    print("handback selftest: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
