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
    for n, args in enumerate(lines, 1):
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
        while "acs.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq acs.exe"], capture_output=True, text=True).stdout:
            if busy == 0:
                log.write(f"=== {time.strftime('%H:%M:%S')}: Assetto Corsa is already running (someone's playing) -- waiting\n"); log.flush()
            time.sleep(60); busy += 60
        if busy:
            time.sleep(120)     # a quiet gap after they quit, in case they're just restarting a session
            if "acs.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq acs.exe"], capture_output=True, text=True).stdout:
                continue
        log.write(f"=== step {n}/{len(lines)} {time.strftime('%H:%M:%S')}: harness.py {args}\n"); log.flush()
        subprocess.run([sys.executable, os.path.join(here, "harness.py")] + args.split(), cwd=root, stdout=log, stderr=subprocess.STDOUT)
        time.sleep(15)      # let AC release its window/audio/GPU before the next launch: back-to-back launches crashed at load (2026-09-15)
        log.flush()
        time.sleep(5)
    log.write(f"=== batch done {time.strftime('%H:%M:%S')}\n")

