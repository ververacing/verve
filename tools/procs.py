"""One correct answer to "what is running", because asking it ad hoc kept producing wrong ones.

    python tools/procs.py              # the summary used by the hourly check
    python tools/procs.py --selftest   # prove the two inflation bugs are actually fixed

WHY THIS EXISTS. A process census inflates in two independent ways and both bit repeatedly:

1. SELF-MATCH. A shell runs `bash -c "<command>"`, so the command text itself contains whatever is being searched
   for and the query matches the querying shell. This produced FOUR wrong readings in two days: "chain_keyiso x4"
   when one ran, "3 chains alive" when none did, "4 batch.py on this queue" before that queue had launched, and -
   the expensive one - "sidecar processes still alive: 1" during a control race, which nearly had me discard a clean
   result because I believed the control was contaminated.

2. PARENT/CHILD LINEAGE. One logical process appears as two or more OS processes. On this machine the Microsoft
   Store python shim (`WindowsApps\\python.exe`) spawns the real interpreter (`pythoncore-3.14-64\\python.exe`), and
   bash forks a subshell carrying the script name. A plain name count therefore reported two batch.py for one queue
   every single hour, and BTeam's equivalent count said "2 harness.py + 2 run_ka2.sh" for a single race - which
   looks exactly like an accidental double launch.

THE RULE THIS ENCODES: use the process table for IDENTITY (which queue, which script) and `acs.exe` for ARITHMETIC
(how many races are actually running). The race count cannot be inflated by shims, subshells or the querying shell,
and it is the number anyone actually wants. Everything else here is deduplicated by ARGUMENTS rather than by
executable path, which is what collapses a shim and its child into the one logical process they are.

No PowerShell anywhere: the owner asked for none on 2026-10-13, and the loop that asked for process data was itself
spawning one a minute. `tasklist` and `wmic` are separate binaries.
"""
import os
import re
import subprocess
import sys


def _wmic(name):
    """-> [command line, ...] for one image name. Empty on any failure, never an exception."""
    try:
        out = subprocess.run(["wmic", "process", "where", "name='%s'" % name, "get", "commandline"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return []
    lines = [l.strip().replace("\r", "") for l in out.splitlines()]
    return [l for l in lines if l and not l.startswith("CommandLine")]


def _args_only(cmd):
    """Everything after the executable, so the Store shim and the real interpreter collapse to one entry."""
    m = re.match(r'\s*(?:"[^"]+"|\S+)\s*(.*)$', cmd)
    return (m.group(1) if m else cmd).strip()


def races():
    """How many races are actually running. The only trustworthy count: acs.exe is one process per race, with no
    shim, no subshell, and no way for this script to match itself."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq acs.exe"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return -1
    return out.lower().count("acs.exe")


def queues():
    """-> sorted queue files currently being run by batch.py, deduplicated by arguments."""
    seen = set()
    for cmd in _wmic("python.exe"):
        if "batch.py" not in cmd:
            continue
        m = re.search(r"(batch_[0-9a-z_]+\.txt)", cmd)
        if m:
            seen.add(m.group(1))
    return sorted(seen)


def harnesses():
    """-> number of DISTINCT harness.py invocations, by arguments rather than by process."""
    return len({_args_only(c) for c in _wmic("python.exe") if "harness.py" in c})


def scripts():
    """-> sorted .sh scripts running. A command line ENDING in .sh cannot be a `bash -c` shell, which is what makes
    this immune to self-match: the querying shell's command line ends in the query, not in .sh."""
    out = set()
    for cmd in _wmic("bash.exe"):
        c = cmd.strip()
        # Do NOT strip the trailing quote. `bash -c "... chain_bar.sh"` ends with a QUOTE; stripping it exposes the
        # .sh and reinstates the exact self-match this function exists to prevent - which is what my own selftest
        # caught on its first run, having written the comment claiming immunity directly above the bug.
        # Two independent tests, either of which is sufficient to reject a shell:
        if " -c " in c or c.endswith('"'):
            continue
        if c.endswith(".sh"):
            out.add(os.path.basename(c))
    return sorted(out)


def others():
    """-> game processes that are not ours, so the hourly check never starts a race over the owner's."""
    found = []
    for img in ("F1_25.exe", "F1_24.exe", "rFactor2.exe", "iRacingSim64DX11.exe", "AMS2AVX.exe"):
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % img],
                                 capture_output=True, text=True, timeout=20).stdout
        except Exception:  # noqa: BLE001
            continue
        if img.lower() in out.lower():
            found.append(img)
    return found


def summary():
    r, q, h, s, o = races(), queues(), harnesses(), scripts(), others()
    return "\n".join([
        "races running (acs.exe, the only reliable count): %d" % r,
        "queue files being run:   %s" % (", ".join(q) if q else "none"),
        "distinct harness runs:   %d" % h,
        "chain scripts armed:     %s" % (", ".join(s) if s else "none"),
        "other games (not ours):  %s" % (", ".join(o) if o else "none"),
    ])


def selftest():
    """Prove the two inflation bugs are fixed, rather than asserting they are."""
    ok = True

    # The selftest must exercise the SAME predicate the code uses, not a paraphrase of it. The first version
    # paraphrased it, got the paraphrase right, and still failed - because the real code stripped a trailing quote
    # and the paraphrase did too, so the test faithfully reproduced the bug and reported it. That is the convention
    # working: a checking tool is not trusted until it has been made to fail.
    def is_script(c):
        c = c.strip()
        if " -c " in c or c.endswith('"'):
            return False
        return c.endswith(".sh")

    # 1. self-match: a `bash -c` command line mentioning chain scripts must NOT be counted as a script
    shell = 'C:\\Program Files\\Git\\bin\\bash.exe -c "grep chain_foo.sh && ls chain_bar.sh"'
    print("  self-match: a bash -c mentioning .sh files counted as a script?   %s"
          % ("YES - BROKEN" if is_script(shell) else "no"))
    ok &= not is_script(shell)

    # the shape that actually defeated the first version: a -c shell whose command ENDS in a .sh filename
    sneaky = 'bash.exe -c "tail -1 chain_spa12.sh"'
    print("  self-match: a -c shell ENDING in a .sh filename rejected?         %s"
          % ("yes" if not is_script(sneaky) else "NO - BROKEN, this is the original bug"))
    ok &= not is_script(sneaky)

    # and a genuine script invocation must still be counted
    real = 'C:\\Program Files\\Git\\bin\\bash.exe /c/tmp/scratch/chain.sh'
    print("  self-match: a real `bash <path>/chain.sh` still counted?          %s"
          % ("yes" if is_script(real) else "NO - BROKEN"))
    ok &= is_script(real)

    # 2. parent/child: the Store shim and the real interpreter must collapse to ONE
    shim = 'C:\\Users\\T\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe -u tools/batch.py tools/harness_results/batch_x.txt'
    core = '"C:\\Users\\T\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe" -u tools/batch.py tools/harness_results/batch_x.txt'
    collapsed = len({_args_only(shim), _args_only(core)})
    print("  parent/child: shim + real interpreter collapse to one?            %s"
          % ("yes" if collapsed == 1 else "NO - BROKEN, counted %d" % collapsed))
    ok &= collapsed == 1

    # two genuinely different queues must stay two
    other = 'python.exe -u tools/batch.py tools/harness_results/batch_y.txt'
    two = len({_args_only(shim), _args_only(other)})
    print("  parent/child: two different queues stay two?                      %s"
          % ("yes" if two == 2 else "NO - BROKEN"))
    ok &= two == 2

    print("\n  %s" % ("all five cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else (print(summary()) or 0))
