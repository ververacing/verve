"""Run batch files one after another: waits for the previous batch's log to say "batch done", then starts
the next.  python tools/queue.py <prev batch .txt> <next batch .txt> [...]"""
import os
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
prev = sys.argv[1]
for nxt in sys.argv[2:]:
    log = os.path.splitext(prev)[0] + ".log"
    while True:
        try:
            if "=== batch done" in open(log, encoding="utf-8").read():
                break
        except OSError:
            pass
        time.sleep(30)
    time.sleep(10)
    subprocess.run([sys.executable, "-u", os.path.join(here, "batch.py"), nxt], cwd=root)
    prev = nxt
