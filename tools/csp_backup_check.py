"""Check that harness.py never overwrites an existing CSP user-config backup.

    python tools/csp_backup_check.py              # source check + the cascade scenario both ways
    python tools/csp_backup_check.py --selftest   # same thing; the scenario IS the selftest

WHY THIS IS A SEPARATE FILE RATHER THAN A --selftest ON harness.py: importing or running harness.py taskkills
acs.exe, so a test that lives inside it cannot be run while a race is on - which is most of the time. This file
imports nothing from it and is safe at any moment.

THE DEFECT IT GUARDS, found 2026-10-14. apply_csp_overrides writes each run's --csp values into CSP's per-user
config (Documents/Assetto Corsa/cfg/extension/<module>.ini, which CSP reads LAST so it beats the shipped
defaults) and backs the user's file up first. restore_csp_overrides puts it back with os.replace, which CONSUMES
the backup - so after any COMPLETED run no backup exists. It follows that a backup present at run start is PROOF
the previous run never restored: a hard kill, a power cut or a reboot, none of which the `finally` in main()
covers. The original code copied over that backup, which backs up the ALREADY-MODIFIED file as if it were the
original; from then on the harness's test values are permanent and indistinguishable from a deliberate user
setting. The Pure path in the same file has always had this check (the last_used.json guard), so the CSP path
was the odd one out.

WHY IT MATTERS BEYOND TIDINESS: this project injects NEW_LATERAL_GRIP_ESTIMATION=0 and FIX_GRIP_MULT=0 into
every row on purpose - CSP ships both at 1, and at 1 the measured result was 11 of 20 cars retired at Monza
against 0 of 20 with the lateral key off. If those values leak into the owner's own config, the owner's game
quietly runs a regime they never chose; and if they leak back IN as a "backup", nobody can tell afterwards what
the owner had set.
"""
import io
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "harness.py")

ORIGINAL = "[RAIN]\nAVOID_PUDDLES=1\n"
HARNESS_WROTE = "[RAIN]\nAVOID_PUDDLES=1\n\n[AI_TWEAKS]\nNEW_LATERAL_GRIP_ESTIMATION=0\nFIX_GRIP_MULT=0\n"


def source_check():
    """Assert the guard is actually in apply_csp_overrides. Reads the file as TEXT - never imports it."""
    try:
        src = io.open(HARNESS, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("  REFUSED: cannot read harness.py (%s)" % e)
        return False
    m = re.search(r"\ndef apply_csp_overrides\(.*?\n(?=\ndef |\nARCHIVE_DIR)", src, re.S)
    if not m:
        print("  REFUSED: apply_csp_overrides not found - this check has gone stale, fix it before trusting it")
        return False
    body = m.group(0)
    if "shutil.copy2(path, bak)" not in body:
        print("  REFUSED: the backup copy is gone from apply_csp_overrides - check has gone stale")
        return False
    guarded = re.search(r"if os\.path\.exists\(bak\):", body) is not None
    print("  apply_csp_overrides guards an existing backup?        %s"
          % ("yes" if guarded else "NO - it will overwrite the true original after an interrupted run"))
    return guarded


def backup(path, guarded):
    bak = path + ".harness-backup"
    if os.path.exists(path):
        if not (guarded and os.path.exists(bak)):
            shutil.copy2(path, bak)
        return (path, bak)
    return (path, None)


def restore(entry):
    path, bak = entry
    if bak and os.path.exists(bak):
        os.replace(bak, path)
    elif os.path.exists(path):
        os.remove(path)


def scenario(guarded):
    """Run 1 is INTERRUPTED (killed, no restore). Run 2 completes. What does the user end up with?"""
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "new_behaviour.ini")
        io.open(p, "w", encoding="utf-8", newline="\n").write(ORIGINAL)
        backup(p, guarded)
        io.open(p, "w", encoding="utf-8", newline="\n").write(HARNESS_WROTE)
        # killed here - no restore
        e2 = backup(p, guarded)
        io.open(p, "w", encoding="utf-8", newline="\n").write(HARNESS_WROTE)
        restore(e2)
        return io.open(p, encoding="utf-8").read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    ok = source_check()
    g, u = scenario(True), scenario(False)
    print("  with the guard, an interrupted run's original is recovered?  %s"
          % ("yes" if g == ORIGINAL else "NO -- got %r" % g))
    ok &= g == ORIGINAL
    # Rule 4: a check is not trusted until it has been made to fail. Without the guard the original MUST be
    # lost - if it survives, the scenario is not exercising the cascade and proves nothing either way.
    print("  without it, is the original LOST (the test can fail)?        %s"
          % ("yes" if u == HARNESS_WROTE else "NO - THIS TEST IS USELESS, it cannot detect the defect"))
    ok &= u == HARNESS_WROTE
    print("\n  %s" % ("all cases correct" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
