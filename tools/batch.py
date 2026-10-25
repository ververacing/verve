"""Run a list of harness commands sequentially, detached from any terminal, logging to a file.

    python tools/batch.py tools/harness_results/batch_20260913.txt

Each non-empty, non-# line of the file is a harness.py argument string. Progress goes to
<batchfile>.log; a final "=== batch done" line marks the end.
"""
import os
import subprocess
import sys
import time
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import atexit, signal
import video_profile
# A killed harness never runs its finally block, and the documented way to stop a batch is to kill batch.py
# (CLAUDE.md), so a plain call at the end of the file never runs on the path that needs it most. atexit plus
# a SIGTERM handler covers both; SIGINT/SIGTERM is what taskkill without /F sends.
def _hand_video_back(*_a):
    try:
        video_profile.restore()
    except Exception:  # noqa: BLE001 - never let the sweep mask the real exit
        pass
atexit.register(_hand_video_back)
for _sig in (getattr(signal, 'SIGTERM', None), getattr(signal, 'SIGINT', None)):
    if _sig is not None:
        try:
            signal.signal(_sig, lambda *a: (_hand_video_back(), _os._exit(1)))
        except (ValueError, OSError):
            pass

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
spec = sys.argv[1]
COOL_C = 85   # GPU hot-spot temperature above which the next run waits (a break between races)


def game_running():
    """Is ANY Assetto Corsa running - the owner's included. BOTH executables (2026-10-24).

    This is the gate that keeps a queue from starting a race over the owner's own session, and CLAUDE.md
    promises it: "batch.py already waits while acs.exe is running and leaves a quiet gap after, so never fight
    it for the game". It checked ONLY acs.exe, and the install ships acs_x86.exe as well - so an owner playing
    the 32-bit build was invisible to it and the next row would have launched straight over them. procs.py has
    carried the executable-pair lesson since 23 Oct, and the same blind spot was found the same afternoon in
    harness.py's acs_running() and in PC #2's own detection.
    """
    for img in ("acs.exe", "acs_x86.exe"):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % img],
                             capture_output=True, text=True).stdout
        if img in out:
            return True
    return False


def gpu_hot_spot():
    """GPU hot-spot temperature from LibreHardwareMonitor's sensor server, or None if it isn't running"""
    try:
        import json
        import urllib.request
        j = json.load(urllib.request.urlopen("http://127.0.0.1:8085/data.json", timeout=4))
    except Exception:  # noqa: BLE001
        return None
    found = []

    def walk(x):
        if x.get("Children"):
            for c in x["Children"]:
                walk(c)
        elif x.get("Text") == "GPU Hot Spot":
            try:
                found.append(float(str(x.get("Value", "0")).split()[0].replace(",", ".")))
            except ValueError:
                pass
    walk(j)
    return found[0] if found else None


log_path = os.path.splitext(spec)[0] + ".log"
lines = [l.strip() for l in open(spec, encoding="utf-8") if l.strip() and not l.strip().startswith("#")]
with open(log_path, "a", encoding="utf-8") as log:
    log.write(f"=== batch start {time.strftime('%H:%M:%S')} ({len(lines)} steps)\n"); log.flush()
    try:
        import watchdog_ensure   # the temperature log + safety stop runs ALL the time (owner 2026-10-10); one stat per race
    except Exception:  # noqa: BLE001
        watchdog_ensure = None
    for n, args in enumerate(lines, 1):
        # HEALTH_STOP: the watchdog's THROTTLE stage stops batch.py and writes this file, so the current race
        # finishes and no new row starts. Until 2026-10-12 nothing read it - batch.py only had the COOL_C wait below -
        # so the watchdog's only working enforcement was a force-kill of acs.exe, and any chain relaunching the queue
        # would have driven straight back into the heat. Refuse to start a row while it exists; the hourly check
        # removes it deliberately after finding out why (that is the rule in the hourly prompt).
        stop_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness_results", "HEALTH_STOP")
        if os.path.exists(stop_file):
            try:
                why = open(stop_file, encoding="utf-8").read().strip().splitlines()[0]
            except (OSError, IndexError):
                why = "(unreadable)"
            log.write(f"=== HEALTH_STOP present, refusing to start step {n}: {why}\n")
            log.write("=== find out why, fix it, then delete tools/harness_results/HEALTH_STOP to resume\n")
            log.write(f"=== batch stopped {time.strftime('%H:%M:%S')}\n"); log.flush()
            raise SystemExit(3)
        if watchdog_ensure:
            try:
                st = watchdog_ensure.ensure()
                if st != "running":
                    log.write(f"=== {time.strftime('%H:%M:%S')}: temperature watchdog {st}\n"); log.flush()
            except Exception:  # noqa: BLE001
                pass
        # cool-down break: don't start the next run while the GPU hot spot is above COOL_C
        waited = 0
        while waited < 600:
            hot = gpu_hot_spot()
            if hot is None or hot < COOL_C:
                break
            log.write(f"=== cool-down: GPU hot spot {hot:.0f}C >= {COOL_C}C, waiting 60 s\n"); log.flush()
            time.sleep(60); waited += 60
        # the game is someone else's if it's already running (the user playing): wait, don't fight for it
        busy = 0
        while game_running():
            if busy == 0:
                log.write(f"=== {time.strftime('%H:%M:%S')}: Assetto Corsa is already running (someone's playing) -- waiting\n"); log.flush()
            time.sleep(60); busy += 60
        if busy:
            time.sleep(120)     # a quiet gap after they quit, in case they're just restarting a session
            if game_running():
                continue
        log.write(f"=== step {n}/{len(lines)} {time.strftime('%H:%M:%S')}: harness.py {args}\n"); log.flush()
        subprocess.run([sys.executable, os.path.join(here, "harness.py")] + args.split(), cwd=root, stdout=log, stderr=subprocess.STDOUT)
        time.sleep(15)      # let AC release its window/audio/GPU before the next launch: back-to-back launches crashed at load (2026-09-15)
        log.flush()
        time.sleep(5)
    log.write(f"=== batch done {time.strftime('%H:%M:%S')}\n")

