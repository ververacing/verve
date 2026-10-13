"""PC health watchdog for unattended batches: logs GPU temperature / load / power / fan (nvidia-smi) and CPU and disk
temperature every INTERVAL seconds to tools/harness_results/health.log, and escalates in THREE STAGES.

    python tools/health_watchdog.py

THREE STAGES, rewritten 2026-10-12 after reading PC #2's tempwatch.py, which was better than this file in exactly
three ways. The old version had ONE stage: cross a limit for two samples and it taskkilled batch.py, harness.py AND
acs.exe. That force-kill is the one CLAUDE.md warns leaves the NEXT launch stalling for its whole budget - so the
safety mechanism caused the operational failure the rules exist to avoid, on the first breach, with no gentler step
available.
  WARN     - a line in the log saying how hot it is. batch.py already waits between rows above its own COOL_C 85.
  THROTTLE - stop batch.py ONLY. The current race finishes on its orphaned harness.py and NO NEW ROW starts. This is
             the same move used by hand three times on 2026-10-12 to hand the machine over cleanly, and it needs no
             force-kill. HEALTH_STOP is written, and batch.py now refuses to start a row while it exists, so the
             throttle cannot be undone by a chain relaunching the queue.
  KILL     - the old behaviour, now reserved for genuinely dangerous temperatures.

NO DATA IS NOT COOL. The old code defaulted the hot spot to 0 when neither nvidia-smi nor LibreHardwareMonitor
answered, so a blind watchdog computed "0 C, not over the limit" and carried on as if the machine were cold - and it
wrote a "GPU n/a" line that the hourly check's own parser skips, so the report would quote the last GOOD reading.
Blindness now has its own loud line, never resets the over-limit counter, and is visible to the parser.

DISK temperature is read from LibreHardwareMonitor. UNVERIFIED as of 2026-10-12 22:40: LHM was closed at the owner's
request while he raced, so the node names could not be confirmed against a live reading. It is written defensively -
no match means disk_c is None, which counts as a MISSING sensor and never as a cool one. Confirm the parse against a
real reading before trusting the disk thresholds.

CPU temperature needs LibreHardwareMonitor (or HWiNFO) running; CPU load does not.
"""
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "harness_results", "health.log")
STOP = os.path.join(HERE, "harness_results", "HEALTH_STOP")
INTERVAL = 60
LHM = "http://127.0.0.1:8085/data.json"   # LibreHardwareMonitor's sensor server (optional)

# Thresholds are HARDWARE-SPECIFIC and do not port between machines: PC #2 runs a GTX 1070 whose LHM hot spot is a
# frozen 55.1 C, so it reads GPU Core only. These are for PC #1's card and a Ryzen (Tctl).
WARN_HOT, WARN_CPU, WARN_DISK = 85, 80, 60          # batch.py's own cool-down threshold is 85
THROTTLE_HOT, THROTTLE_CPU, THROTTLE_DISK = 89, 85, 65
KILL_HOT, KILL_CPU, KILL_DISK = 93, 90, 70
HOT_SAMPLES = 2       # consecutive readings before THROTTLE or KILL acts
BLIND_SAMPLES = 3     # consecutive readings with NO sensor data before saying so loudly


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw,fan.speed,clocks.sm",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()
        t, u, p, f, c = [x.strip() for x in out.split(",")]
        return int(float(t)), int(float(u)), float(p), int(float(f)), int(float(c))
    except Exception:  # noqa: BLE001
        return None


def lhm():
    """{cpu_c, gpu_hot_c, gpu_c, cpu_load} from LibreHardwareMonitor, or {} if it isn't running"""
    try:
        import urllib.request
        j = json.load(urllib.request.urlopen(LHM, timeout=4))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    def walk(n, path=""):
        if n.get("Children"):
            for c in n["Children"]:
                walk(c, path + "/" + n.get("Text", ""))
        else:
            t, v = n.get("Text", ""), n.get("Value", "")
            try:
                val = float(str(v).split()[0].replace(",", "."))
            except ValueError:
                return
            if n.get("Type") == "Temperature":
                if t.startswith("Core (Tctl"):
                    out["cpu_c"] = val
                elif t == "GPU Hot Spot":
                    out["gpu_hot_c"] = val
                elif t == "GPU Core":
                    out["gpu_c"] = val
                elif any(k in path.lower() for k in ("ssd", "nvme", "hdd", "disk", "storage")):
                    # UNVERIFIED 2026-10-12: written with LHM closed, so the node names could not be checked against
                    # a live reading. Takes the WARMEST matching drive, and matches on the ancestor path rather than
                    # the sensor name because LHM labels the sensor "Temperature" and the drive model above it.
                    out["disk_c"] = max(val, out.get("disk_c", -99))
            elif n.get("Type") == "Load" and t == "CPU Total":
                out["cpu_load"] = val
    walk(j)
    return out


def cpu_load():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).LoadPercentage"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:  # noqa: BLE001
        return -1


def ours_running():
    """Is one of OUR unattended runs alive? The owner's own race is not ours to kill - this stop path taskkills acs.exe, and on
    2026-10-11 he was racing on this machine while the watchdog ran. Unknown -> treat as ours, i.e. behave as before."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '*batch.py*' "
          "-or $_.CommandLine -like '*harness.py*' -or $_.CommandLine -like '*queue.py*') } | Measure-Object | "
          "ForEach-Object { $_.Count }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=40).stdout
        return int(out.strip().splitlines()[0]) > 0
    except Exception:  # noqa: BLE001
        return True


def tier(hot_c, cpu_c, disk_c):
    """-> ('kill'|'throttle'|'warn'|'ok'|'blind', reason). PURE, so it can be tested without sensors or a batch.

    A None reading is MISSING, never cool: if every reading is missing the answer is 'blind', which the caller must
    not treat as safe. One missing sensor among several does not mask the others.
    """
    if hot_c is None and cpu_c is None and disk_c is None:
        return "blind", "no sensor data at all"
    def over(v, lim):
        return v is not None and v >= lim
    for name, h, c, d in (("kill", KILL_HOT, KILL_CPU, KILL_DISK),
                          ("throttle", THROTTLE_HOT, THROTTLE_CPU, THROTTLE_DISK),
                          ("warn", WARN_HOT, WARN_CPU, WARN_DISK)):
        why = []
        if over(hot_c, h):
            why.append(f"GPU hot {hot_c:.0f}C>={h}")
        if over(cpu_c, c):
            why.append(f"CPU {cpu_c:.0f}C>={c}")
        if over(disk_c, d):
            why.append(f"disk {disk_c:.0f}C>={d}")
        if why:
            return name, ", ".join(why)
    return "ok", ""


def stop_batch(reason, kill_game):
    """kill_game False = THROTTLE: stop batch.py only, so the current race finishes on its orphaned harness.py and
    no new row starts. True = KILL: the old behaviour, batch.py + harness.py + acs.exe."""
    ours = ours_running()
    with open(STOP, "w", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {reason}\n")
    if not ours:
        return False   # nothing of ours is racing: log it, leave the machine alone
    pat = "*batch.py*" if not kill_game else "*batch.py*' -or $_.CommandLine -like '*harness.py*' -or $_.CommandLine -like '*queue.py*"
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '"
          + pat + "') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    if kill_game:
        subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)
    return True


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    runs = {"kill": 0, "throttle": 0}
    blind = 0
    acted = "throttle" if os.path.exists(STOP) else None    # already throttled? do not re-act, but KILL may still escalate
    while True:
        g = gpu()
        h = lhm()
        cl = h.get("cpu_load", cpu_load())
        line = time.strftime("%H:%M:%S")
        if g:
            t, u, p, f, c = g
            hot_c = h.get("gpu_hot_c", t + 12)
            line += f"  GPU {t}C hot {hot_c:.0f}C load {u}% {p:.0f}W fan {f}% {c}MHz"
        else:
            # NOT 0. A missing reading is missing; 0 would read as "stone cold" to every threshold below.
            hot_c = h.get("gpu_hot_c")
            line += "  GPU 0C hot 0C load 0% 0W fan 0% 0MHz  [GPU SENSOR MISSING]"
        cpu_c = h.get("cpu_c")
        disk_c = h.get("disk_c")
        line += f"  CPU {cpu_c:.0f}C load {cl:.0f}%" if cpu_c is not None else f"  CPU 0C load {cl:.0f}% [CPU SENSOR MISSING]"
        line += f"  disk {disk_c:.0f}C" if disk_c is not None else "  disk n/a"

        level, why = tier(hot_c, cpu_c, disk_c)
        if level == "blind":
            blind += 1
            if blind >= BLIND_SAMPLES:
                line += (f"  >> NO SENSOR DATA for {blind} readings - nvidia-smi and LibreHardwareMonitor both silent. "
                         "NOT SAFE TO ASSUME COOL: treat this log as absent, not as evidence of a cool machine.")
        else:
            blind = 0
        for name in ("kill", "throttle"):
            runs[name] = runs[name] + 1 if level == name or (name == "throttle" and level == "kill") else 0

        if runs["kill"] >= HOT_SAMPLES and acted != "kill":
            acted = "kill"
            killed = stop_batch(f"KILL {why}", kill_game=True)
            line += f"  >> {why} for {HOT_SAMPLES} samples: " + (
                "KILLED the batch and acs.exe" if killed else "CRITICAL - nothing of ours is running, so nothing was killed")
        elif runs["throttle"] >= HOT_SAMPLES and acted is None:
            acted = "throttle"
            stoppedb = stop_batch(f"THROTTLE {why}", kill_game=False)
            line += f"  >> {why} for {HOT_SAMPLES} samples: " + (
                "stopped batch.py - the current race finishes, no new row starts"
                if stoppedb else "no batch of ours is running, so nothing was stopped")
        elif level == "warn":
            line += f"  >> WARN {why}"

        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
