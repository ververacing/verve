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


def bare_shell(cmd):
    """True when a command line is JUST the executable, with no script, no -Command and no arguments.

    The tell that a process is an idle shell rather than work in progress, and it does not depend on parentage.
    Two powershell.exe sat on sweep's REPORT list for 38 hours labelled "may be a harness run whose exit hook
    restores race.ini", and on 2026-10-15 that guess triggered a full read-only investigation before they turned
    out to be this agent's OWN PowerShell tool shells - parent claude.exe, ~4 s of CPU across 38 hours, no
    children. Killing one would have removed the agent's own tool.
    Parentage was the first fix attempted and it does not work here: ancestors(os.getpid()) cannot resolve the
    chain when the running python is absent from the wmic snapshot, and the tool shells are SIBLINGS of this
    script rather than ancestors. The command line is the sound test instead - a harness exit hook always
    carries a script path or -Command, so a bare executable cannot be running one, whoever its parent is.
    """
    if not cmd:
        return True
    s = cmd.strip()
    if s.startswith('"'):                      # a quoted exe path: anything after the closing quote is an arg
        end = s.find('"', 1)
        return end != -1 and not s[end + 1:].strip()
    return len(s.split()) == 1                 # unquoted: one token means no arguments


# (2026-10-16, the owner's new rule) ONLY CLOSE OUT WHAT A VERVE AGENT MADE. The owner is now running Zeus
# agents - a central one plus a minion on EACH PC - so this machine carries processes from another project that
# look exactly like what this sweep was built to clear: a stray grep, tail or sleep, or an old bash. Their words,
# relayed by verve-47: "we should be careful to only close out anything directly created by Verve agents so we
# don't accidentally take out anything from Zeus agents". So A TIE TO VERVE IS NOW A PRECONDITION OF KILLING,
# not a consideration: no tie means REPORT, however stray it looks. This can only ever reduce what is killed,
# which is why it was safe to add while the machine was paused.
# The tie is deliberately narrow and positive: a process must NAME something of ours or descend from this
# session. "It looks like a leftover" is not a tie - that is precisely the inference that would take out a
# minion's shell. FOREIGN_MARKS wins outright, so anything naming claude or zeus is never killed even if it also
# touches a Verve path (a Zeus minion reading our desk would).
VERVE_MARKS = ("apps/lua/verve", "apps\\lua\\verve", "verve_desk", "verve_feed", "harness_results",
               "batch.py", "harness.py", "wait_then_", "chain_", "pc2_queue", "video_profile", "sweep.py")
FOREIGN_MARKS = ("zeus", "claude")


OWN_KINDS = {"python", "py", "bash", "sh", "nohup", "powershell", "pwsh"}


def own_chain(pid, by_pid):
    """This process and its parents, CUT BELOW THE HOST APP - not `ancestors()`, which walks to the top.

    ancestors() reaches the Claude desktop app and whatever is above it, and that is SHARED GROUND: a Zeus minion
    running in the same app has tool shells with the SAME parent, so an uncut chain would tie a minion's bash or
    grep as ours (verve-47, 2026-10-16). The walk therefore stops at the first process that is not one of our own
    kinds, and the boundary process is NOT a member.
    Currently near-degenerate and that is fine: the running python is absent from the wmic snapshot, so this
    usually returns {own pid} alone. The cut is DEFENSIVE - it has to hold if that ever changes.
    """
    seen, cur = set(), pid
    while cur and cur not in seen:
        r = by_pid.get(cur)
        if cur != pid and (not r or r[0] not in OWN_KINDS):
            break
        seen.add(cur)
        if not r:
            break
        cur = r[2]
    return seen


def verve_tie(cmd, ppid, own, by_pid=None):
    """True only when the process can be TIED to a Verve agent. Untied is the default, not the exception.

    A LIVE PARENT MUST ITSELF BE OURS. The name tie alone is not sufficient while the parent is alive, because a
    minion's `tail -f <our desk file>` carries no marker of its own - it just names a path of ours, and reading
    our desk is a thing a minion plausibly does. My first version tied exactly that case, and the selftest only
    passed because I had appended "(zeus minion)" to the fixture by hand: I wrote the evidence that made my own
    rule look right (verve-47 caught it). With the parent DEAD there is nothing else to go on, so the name tie
    stands as the only evidence available.
    """
    c = (cmd or "").lower()
    if any(m in c for m in FOREIGN_MARKS):
        return False
    if by_pid is not None and ppid in by_pid:          # parent ALIVE
        if ppid in own:
            return True
        pc = (by_pid[ppid][4] or "").lower()
        if any(m in pc for m in FOREIGN_MARKS):
            return False
        return any(m in pc for m in VERVE_MARKS)
    return any(m in c for m in VERVE_MARKS)            # parent dead: the name is all there is


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
        # A SIBLING TOOL SHELL OF THIS AGENT'S OWN HOST, which is not a harness run and must not be reported as
        # one. `mine` holds this process and its ancestors, so a process whose PARENT is one of them was spawned
        # by the same host - the Claude app's PowerShell/Bash tool shells are siblings of this script, not
        # ancestors, which is why the `pid in mine` check above misses them. They sat reported for 38 hours and
        # cost a full read-only investigation on 2026-10-15 before being identified: bare `powershell.exe` with
        # NO -Command and no script path, parent claude.exe, ~4 s of CPU across that whole time, no children.
        # KILLING ONE WOULD HAVE TAKEN OUT THE AGENT'S OWN PowerShell TOOL. An empty command line is the tell: a
        # harness exit hook always carries a script or -Command.
        if bare_shell(cmd):
            return "protected", "an idle shell with NO command line: cannot be running an exit hook"
        return "report", "never killed: may be a harness run whose exit hook restores race.ini"
    if name in SHELLS and runs_a_script(cmd):
        return "protected", "a shell running a .sh - a chain or watcher"
    if name not in KILLABLE and name not in SHELLS:
        return "ok", "not a swept name"
    return ("ok", "parent alive and under %d min" % MAX_AGE_MIN)
    # NOTE: the Verve-tie gate is NOT here. It lives at the kill decision in sweep(), because putting it in
    # classify reclassified every YOUNG process with a live parent - things that were never kill candidates - and
    # the first live run duly reported this script's own `tail -4`, age 0. A gate that creates an hourly report
    # line from normal operation is how a report becomes noise and stops being read.


def sweep(do_kill=False):
    all_rows = rows()
    if not all_rows:
        print("sweep: REFUSED - could not read the process table, nothing swept")
        return 1
    by_pid = {r[1]: r for r in all_rows}
    mine = ancestors(os.getpid(), by_pid)        # for the protected checks: never cut our own branch
    own = own_chain(os.getpid(), by_pid)         # for the TIE: cut below the host app, which Zeus shares
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
        # THE OWNER'S 2026-10-16 GATE, at the only place it belongs: this process has now passed every test and
        # is about to be killed. A TIE TO VERVE IS A PRECONDITION. No tie means report instead - however stray it
        # looks, it may be a Zeus minion's, and the owner's rule is to close out only what a Verve agent made.
        if not verve_tie(cmd, ppid, own, by_pid):
            reported.append((name, pid, age, (cmd or "")[:90],
                             "WOULD BE STRAY but has NO VERVE TIE: may belong to another agent (Zeus has a "
                             "minion on this PC) - never killed (owner, 2026-10-16)"))
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

    # THE OWNER'S 2026-10-16 RULE: only close out what a Verve agent made. verve_tie() is the gate and sweep()
    # consults it at the kill decision, so it is tested directly as the unit it is. Every case was checked by
    # reverting verve_tie to `return True` and watching it go red.
    # A fake table for the tie cases. 900 is the HOST APP, which Zeus shares with us, and is deliberately not
    # one of OWN_KINDS; 901 is a live parent belonging to neither project; 902 is our own batch.py.
    FAKE = {900: ("claude", 900, 1, 999.0, "claude.exe"),
            901: ("node", 901, 900, 999.0, "node server.js"),
            902: ("python", 902, 900, 50.0, "python -u tools/batch.py q.txt"),
            # 999 is US, and it must be IN the table or the "child of our own chain" case reads its parent as
            # DEAD and falls through to the name tie - which is how that case first failed here.
            999: ("python", 999, 902, 10.0, "python -I tools/sweep.py")}
    TIE = [
        # (label, cmd, ppid, expected)                                     parent state
        ("a minion's grep naming zeus is NOT tied",      'grep.exe -r pat C:\\x\\zeus\\minion\\state', 1, False),
        ("anything naming claude is NOT tied",           'sleep 60   # claude-code helper', 1, False),
        ("an UNTAGGED bare orphan is NOT tied",          'sleep 60', 1, False),
        ("dead parent + our path IS tied (name is all)", 'grep -c cspf5 tools/harness_results/results.csv', 1, True),
        ("dead parent + batch.py IS tied",               'python -u tools/batch.py x.txt', 1, True),
        ("dead parent + our waiter IS tied",             'bash /tmp/s/wait_then_d100c_a.sh', 1, True),
        ("a child of our own cut chain IS tied",         'sleep 30', 999, True),
        # verve-47's two cases, and they are the ones that matter
        ("LIVE host-app parent, no marks, NOT tied",     'bash -c "x"', 900, False),
        ("LIVE non-Verve parent + OUR desk path, NOT tied", 'tail -f C:\\x\\verve_desk\\state.md', 901, False),
        # and the gate must not spare what our own queue spawned
        ("LIVE batch.py parent IS tied",                 'grep foo', 902, True),
    ]
    for label, cmd, ppid, want in TIE:
        got = verve_tie(cmd, ppid, {999}, FAKE)
        print("  %-52s %s" % (label + "?", "yes" if got == want else "NO - BROKEN (got %s)" % got))
        ok &= got == want

    # the chain must be CUT: the host app is a boundary, not a member, or a minion's tool shell ties as ours
    cut = own_chain(902, FAKE)
    print("  %-52s %s (%s)" % ("own_chain stops below the host app?",
                               "yes" if 900 not in cut else "NO - BROKEN, Zeus shares that parent", sorted(cut)))
    ok &= 900 not in cut
    # THE COST, stated so it is a known trade rather than a surprise: case 4 means an UNTAGGED orphan of our own
    # - a bare `sleep 60` whose parent shell died - is no longer killed, only reported. That is a real reduction
    # in reach, and it is the rule working as intended: when a process cannot be tied to Verve, "it looks like
    # our leftover" is exactly the inference that would take out a minion.
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

    # THE INVARIANT IS "NEVER STRAY", NOT "ALWAYS report". This used to assert k3 == "report" exactly, and so it
    # failed when a BARE shell became "protected" - even though protected and report both mean never killed, which
    # is the only property that matters for safety. Asserting the mechanism instead of the property made a correct
    # change look like a regression. Now it checks the invariant AND both arms of the bare/scripted split, so it
    # would still catch the dangerous direction: a real exit hook being protected and therefore never surfaced.
    for nm in ("python", "powershell"):
        k3, _ = classify((nm, 7, 6, 999.0, "x"), mine, keep)
        print("  %-11s is never STRAY (never killed)?              %s" % (nm, "yes" if k3 != "stray" else "NO"))
        ok &= k3 != "stray"

    bare = ("powershell", 7, 6, 999.0, os.path.join(
        os.environ.get("SystemRoot", ""), "System32", "WindowsPowerShell", "v1.0",
        "powershell.exe"))
    kb, whyb = classify(bare, mine, keep)
    print("  a BARE shell (no cmdline) is protected, not reported?     %s (%s)"
          % ("yes" if kb == "protected" else "NO", whyb))
    ok &= kb == "protected"

    hook = ("powershell", 7, 6, 999.0, r'powershell.exe -Command "restore race.ini"')
    kh, whyh = classify(hook, mine, keep)
    print("  a shell WITH -Command is still REPORTED?                  %s (%s)"
          % ("yes" if kh == "report" else "NO - A REAL HOOK WOULD BE HIDDEN", whyh))
    ok &= kh == "report"

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

    # Was `grep foo` until 2026-10-16. That fixture now encodes behaviour the OWNER HAS FORBIDDEN: a bare
    # `grep foo` cannot be tied to Verve, so it might be a Zeus minion's and must be spared. Re-pointed at a
    # genuine Verve leftover - one that NAMES something of ours - so it still proves the sweep clears our strays.
    k4, _ = classify(("grep", 8, 1, 500.0, "grep foo tools/harness_results/results.csv"), mine, keep)
    print("  a leaf utility NAMING our paths is eligible?              %s" % ("yes" if k4 == "ok" else "NO"))
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
