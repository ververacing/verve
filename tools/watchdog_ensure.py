"""Keep tools/health_watchdog.py running: the temperature log (GPU temperature / load / power / fan every 60 s, CPU when a
sensor server is up) and its safety stop. Owner 2026-10-10: the temperature check runs all the time, built in, without
slowing races down - it went silent from 2026-09-22 to 2026-10-10 and nobody noticed.

    from watchdog_ensure import ensure      # batch.py calls ensure() at batch start and before every race
    python tools/watchdog_ensure.py         # start it by hand if it isn't running; prints the state

Cost per call: one stat of health.log. It starts the watchdog only when the log has not been written for STALE_S
(it writes every 60 s), detached, so it outlives the batch and keeps logging between queues.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "harness_results", "health.log")
PIDFILE = os.path.join(HERE, "harness_results", "health.pid")
STALE_S = 180


def pid_alive():
    """Is the recorded watchdog PID still a live process? tasklist, never PowerShell - the owner asked for no
    PowerShell, and the loop this guards was itself spawning one a minute."""
    try:
        pid = int(open(PIDFILE, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:  # noqa: BLE001
        return True      # cannot tell: do not thrash a possibly-live watchdog
    return str(pid) in out


def age():
    try:
        return time.time() - os.path.getmtime(LOG)
    except OSError:
        return None


def ensure():
    """-> 'running' (log fresh) or 'started' (watchdog launched now) or 'failed: ...'"""
    a = age()
    if a is not None and a < STALE_S and pid_alive():
        return "running"
    # Freshness ALONE is not liveness. STALE_S is 180 s, so a watchdog killed a minute ago still looked "running"
    # for three minutes and this function started nothing - which is how monitoring came to be off on 2026-10-13
    # while the hourly check reported it up. Now a dead PID forces a restart however fresh the log looks.
    try:
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, os.path.join(HERE, "health_watchdog.py")], cwd=os.path.dirname(HERE),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
        return "started"
    except Exception as e:  # noqa: BLE001
        return "failed: %s" % e


if __name__ == "__main__":
    print(ensure(), "| health.log age:", "%.0f s" % age() if age() is not None else "missing")
