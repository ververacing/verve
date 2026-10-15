"""Hourly stray-process sweep. Read-only by default; --kill to act.

    python tools/sweep.py              # report, kill nothing (the default, on purpose)
    python tools/sweep.py --kill       # kill the strays it names
    python tools/sweep.py --selftest   # prove it will not kill a chain

Standing task from the owner, 2026-10-15, relayed by Racecraft Cloud: leftover grep/tail/sleep processes keep
showing up in Task Manager and the owner has been asking for manual cleanups.

WHY THE OBVIOUS IMPLEMENTATION BREAKS THE QUEUE, found on the first run before anything was killed. The spec's
stray test is "not on the keep list, and EITHER its parent is gone OR it is over 2 hours old". Every chain this
project arms is launched with `nohup ... & disown`, which ORPHANS IT BY DESIGN, and a chain waits for a queue
that runs for hours, so it is over 2 hours old BY DESIGN TOO. On the first sweep the single process matching
"stray" was bash 25412 - the armed pacedefer_rest chain, 433 minutes old with a dead parent - and killing it
would have silently broken tonight's queue continuation. A keep list is therefore not a convenience; without it
the first sweep is destructive.

SO PROTECTION IS DERIVED, NOT REMEMBERED. A hand-maintained PID list drifts, and its failure mode is killing the
queue, so it is the wrong primary mechanism:
  1. OWN ANCESTOR CHAIN - never touch the shell this runs in, or anything that spawned it.
  2. NEVER KILL python, py, powershell, pwsh - the spec says report them, and the reason is good: a python
     process may be a harness run whose exit hook restores race.ini and video.ini, so killing it can leave the
     game broken for the owner's next session.
  3. NEVER KILL a bash/sh THAT IS RUNNING A SCRIPT FILE. A command line naming a .sh is a chain or a watcher,
     i.e. infrastructure, regardless of its age or whether its parent survives. This is the rule that would have
     saved the queue on the first run, and it needs no bookkeeping.
  4. The keep list (harness_results/sweep_keep.txt, one PID per line, # comments) is belt and braces on top.

WHAT IT WILL KILL: the leaf utilities only - grep, tail, head, sleep, timeout, cat, less, awk, sed, find,
xargs - and a bash/sh with NO script argument, when the parent is gone or it is over MAX_AGE_MIN. Those are the
ones that actually accumulate, and none of them holds state anything depends on.

No PowerShell is spawned to do the work: `wmic` is a separate binary, and the watchdog that spawned a PowerShell
a minute while the owner raced is the reason that matters here.
"""
import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP_FILE = os.path.join(HERE, "harness_results", "sweep_keep.txt")
LOG_FILE = os.path.join(HERE, "harness_results", "sweep.log")

KILLABLE = {"grep", "tail", "head", "sleep", "timeout", "cat", "less", "awk", "sed", "find", "xargs"}
SHELLS = {"bash", "sh"}
REPORT_ONLY = {"python", "py", "powershell", "pwsh"}
# A python RUNNING one of these is the live queue itself - identifiable infrastructure, so it is PROTECTED and
# stays out of the report. Report-only already meant it was never killed; the problem was that the running
# queue's own python pair appeared under REPORT every single hour, which is how a report becomes wallpaper.
QUEUE_SCRIPTS = {"batch.py", "harness.py"}
MAX_AGE_MIN = 120
MIN_ORPHAN_MIN = 2       # an orphan younger than this is a transient from our own pipelines, not a stray


def rows():
    """-> [(name, pid, ppid, age_min, cmdline)] for every process, via wmic. Empty on any failure."""
    try:
        out = subprocess.run(["wmic", "process", "get",
                              "Name,ProcessId,ParentProcessId,CreationDate,CommandLine", "/format:csv"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=90).stdout
    except Exception:                                                  # noqa: BLE001
        return []
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    hdr = next((i for i, l in enumerate(lines) if l.lower().startswith("node,")), None)
    if hdr is None:
        return []
    cols = [c.strip() for c in lines[hdr].split(",")]
    try:
        iC, iN, iP, iPP, iD = (cols.index("CommandLine"), cols.index("Name"), cols.index("ProcessId"),
                               cols.index("ParentProcessId"), cols.index("CreationDate"))
    except ValueError:
        return []
    now = time.time()
    out_rows = []
    for l in lines[hdr + 1:]:
        f = l.split(",")
        if len(f) <= max(iC, iN, iP, iPP, iD):
            continue
        try:
            pid, ppid = int(f[iP]), int(f[iPP])
        except ValueError:
            continue
        name = re.sub(r"\.exe$", "", f[iN].strip(), flags=re.I).lower()
        age = -1.0
        m = re.match(r"(\d{14})", f[iD].strip())
        if m:
            try:
                t = time.mktime(time.strptime(m.group(1), "%Y%m%d%H%M%S"))
                age = (now - t) / 60.0
            except (ValueError, OverflowError):
                age = -1.0
        out_rows.append((name, pid, ppid, age, f[iC].strip()))
    return out_rows


def ancestors(pid, by_pid):
    """-> set of this process and every parent above it, so the sweep cannot cut its own branch."""
    seen, cur = set(), pid
    while cur and cur not in seen:
        seen.add(cur)
        r = by_pid.get(cur)
        if not r:
            break
        cur = r[2]
    return seen


def keep_list():
    out = set()
    try:
        for l in io.open(KEEP_FILE, encoding="utf-8", errors="replace"):
            l = l.split("#", 1)[0].strip()
            if l.isdigit():
                out.add(int(l))
    except OSError:
        pass
    return out


RUNNERS = {"sh", "bash", "source", ".", "python", "python3", "pythonw", "py"}


def script_run(cmdline, ext):
    """-> the basename of the `ext` file this command line RUNS, or None.

    THE DISTINCTION, and getting it backwards in either direction is expensive: `bash -c "grep foo.sh"` only
    MENTIONS a script (the procs.py self-match trap - protecting it would let any stray survive by naming a
    .sh), while `bash -c "source snap; sh watch.sh"` genuinely RUNS one and is load-bearing.

    The first version rejected every command line containing " -c ", which got the self-match right and the
    second case WRONG - and the second case is how every background shell this session launches actually looks,
    so the sweep listed its own armed queue waiter as "WOULD KILL". Read-only by default is the only reason
    that cost nothing.

    So the test is positional rather than textual: a token ending in `ext` counts as RUN only when the nearest
    preceding command word is a RUNNER and nothing but flags sits between them. `grep foo.sh` fails it because
    grep is not a runner; `python -u tools/batch.py` passes it across the -u flag.
    """
    toks = [t.strip('"\'').replace("\\", "/") for t in (cmdline or "").split()]
    base = [t.rsplit("/", 1)[-1].lower() for t in toks]
    runner = None
    for i, b in enumerate(base):
        stem = b[:-4] if b.endswith(".exe") else b
        if stem in RUNNERS:
            runner = i
        elif b.endswith(ext) and runner is not None:
            if all(base[j].startswith("-") for j in range(runner + 1, i)):
                return b
    return None


def runs_a_script(cmdline):
    """True when a shell command line names a .sh FILE to run - a chain or watcher, i.e. infrastructure."""
    return script_run(cmdline, ".sh") is not None


def classify(r, mine, keep):
    """-> ('protected'|'report'|'stray'|'ok', reason)"""
    name, pid, ppid, age, cmd = r
    if pid in mine:
        return "protected", "own shell or an ancestor of it"
    if pid in keep:
        return "protected", "on the keep list"
    if name in REPORT_ONLY:
        s = script_run(cmd, ".py")
        if s in QUEUE_SCRIPTS:
            return "protected", "the live queue (%s)" % s
        return "report", "never killed: may be a harness run whose exit hook restores race.ini"
    if name in SHELLS and runs_a_script(cmd):
        return "protected", "a shell running a .sh - a chain or watcher"
    if name not in KILLABLE and name not in SHELLS:
        return "ok", "not a swept name"
    return ("ok", "parent alive and under %d min" % MAX_AGE_MIN)


def sweep(do_kill=False):
    all_rows = rows()
    if not all_rows:
        print("sweep: REFUSED - could not read the process table, nothing swept")
        return 1
    by_pid = {r[1]: r for r in all_rows}
    mine = ancestors(os.getpid(), by_pid)
    keep = keep_list()
    killed, kept, reported = [], 0, []
    for r in all_rows:
        name, pid, ppid, age, cmd = r
        if name not in KILLABLE and name not in SHELLS and name not in REPORT_ONLY:
            continue
        kind, why = classify(r, mine, keep)
        if kind == "protected":
            kept += 1
            continue
        if kind == "report":
            reported.append((name, pid, age, cmd[:90], why))
            continue
        orphan = ppid not in by_pid
        # An orphan under MIN_ORPHAN_MIN is a TRANSIENT, not a stray. Every bash pipeline this session runs
        # leaves a `sleep 5` or similar orphaned for a few seconds as its shell exits, and such a process
        # terminates on its own. Killing it achieves nothing and makes the hourly line read "1 killed" every
        # hour from our own normal operation - which is how a report becomes noise and stops being read.
        # Anything still orphaned after two minutes is not going to exit by itself.
        if orphan and 0 <= age < MIN_ORPHAN_MIN:
            kept += 1
            continue
        if not (orphan or age > MAX_AGE_MIN):
            kept += 1
            continue
        line = "%s pid %d age %.0f min %s cmd %s" % (
            name, pid, age, "orphan" if orphan else "old", (cmd or "")[:110])
        if do_kill:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)
                killed.append(line)
            except Exception as e:                                     # noqa: BLE001
                reported.append((name, pid, age, cmd[:90], "kill failed: %s" % e))
        else:
            reported.append((name, pid, age, cmd[:90], "WOULD KILL (%s) - run with --kill" % ("orphan" if orphan else "old")))
    for k in killed:
        print("  KILLED  %s" % k)
    for name, pid, age, cmd, why in reported:
        print("  REPORT  %-11s pid %-6d age %6.0f min  %s | %s" % (name, pid, age, cmd, why))
    print("sweep: %d killed (%s), %d kept, %d reported"
          % (len(killed), ",".join(sorted({k.split()[0] for k in killed})) or "none", kept, len(reported)))
    if killed:
        try:
            with io.open(LOG_FILE, "a", encoding="utf-8", newline="\n") as fh:
                for k in killed:
                    fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), k))
        except OSError:
            pass
    return 0


def selftest():
    """The case that matters: a chain with a dead parent, hours old, must NOT be classified stray."""
    ok = True
    mine, keep = {999}, {1234}
    chain = ("bash", 25412, 21136, 433.0,
             '"C:\\x\\bash.exe" /tmp/scratch/chain.sh batch_prev.log batch_next.txt chain.log')
    k, why = classify(chain, mine, keep)
    print("  an armed chain, orphaned and 433 min old, is protected?   %s (%s)"
          % ("yes" if k == "protected" else "NO - WOULD KILL THE QUEUE", why))
    ok &= k == "protected"

    shell = ("bash", 5, 4, 300.0, 'bash.exe -c "grep chain_foo.sh && tail -1 x.log"')
    k2, _ = classify(shell, mine, keep)
    print("  a bash -c whose TEXT mentions a .sh is not protected?     %s"
          % ("yes" if k2 != "protected" else "NO - self-match, it would survive as infrastructure"))
    ok &= k2 != "protected"

    # The shape every background shell this session launches actually has. The first version of script_run
    # rejected anything containing " -c " and so listed this - a live, armed queue waiter - as WOULD KILL.
    wrapped = ("bash", 13788, 1, 14.0,
               '"C:/apps/git/bin/bash.exe" -c "source /c/u/t/.claude/shell-snapshots/snap.sh; '
               'sh /tmp/scratch/wait_queue_done2.sh"')
    k9, why9 = classify(wrapped, mine, keep)
    print("  a `bash -c \"source snap; sh watch.sh\"` IS protected?      %s (%s)"
          % ("yes" if k9 == "protected" else "NO - WOULD KILL AN ARMED WAITER", why9))
    ok &= k9 == "protected"

    for nm in ("python", "powershell"):
        k3, _ = classify((nm, 7, 6, 999.0, "x"), mine, keep)
        print("  %-11s is report-only, never stray?                %s" % (nm, "yes" if k3 == "report" else "NO"))
        ok &= k3 == "report"

    queue = ("python", 11, 10, 95.0, 'C:/x/python.exe -u tools/batch.py batch_20261014_pc1_recov.txt')
    k7, why7 = classify(queue, mine, keep)
    print("  the live queue's own python is protected, not reported?   %s (%s)"
          % ("yes" if k7 == "protected" else "NO - it will be REPORTed every hour as noise", why7))
    ok &= k7 == "protected"

    fake = ("python", 12, 10, 95.0, 'python -c "print(open(\'tools/batch.py\').read())"')
    k8, _ = classify(fake, mine, keep)
    print("  a python -c whose TEXT mentions batch.py is NOT the queue? %s"
          % ("yes" if k8 == "report" else "NO - self-match, any -c mentioning a .py reads as infrastructure"))
    ok &= k8 == "report"

    k4, _ = classify(("grep", 8, 1, 500.0, "grep foo"), mine, keep)
    print("  a leaf utility is eligible?                               %s" % ("yes" if k4 == "ok" else "NO"))
    ok &= k4 == "ok"

    k5, _ = classify(("tail", 999, 1, 999.0, "tail -f x"), mine, keep)
    print("  own ancestor chain protected even when ancient?           %s" % ("yes" if k5 == "protected" else "NO"))
    ok &= k5 == "protected"

    k6, _ = classify(("sleep", 1234, 1, 999.0, "sleep 999"), mine, keep)
    print("  the keep list overrides age and orphanhood?               %s" % ("yes" if k6 == "protected" else "NO"))
    ok &= k6 == "protected"

    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not run with --kill"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(sweep(do_kill="--kill" in sys.argv))
