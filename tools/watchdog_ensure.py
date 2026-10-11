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
STALE_S = 180


def age():
    try:
        return time.time() - os.path.getmtime(LOG)
    except OSError:
        return None


def ensure():
    """-> 'running' (log fresh) or 'started' (watchdog launched now) or 'failed: ...'"""
    a = age()
    if a is not None and a < STALE_S:
        return "running"
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
