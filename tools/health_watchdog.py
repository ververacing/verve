"""PC health watchdog for unattended batches: logs GPU temperature / load / power / fan (nvidia-smi)
every INTERVAL seconds to tools/harness_results/health.log; if the GPU stays at or above HOT_C for
HOT_SAMPLES consecutive readings, stops the batch (kills batch.py, harness.py and acs.exe), writes
tools/harness_results/HEALTH_STOP with the reason, and keeps logging so the cool-down is visible.

CPU temperature isn't readable without a sensor driver (LibreHardwareMonitor / HWiNFO); CPU load is.
    python tools/health_watchdog.py
"""
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "harness_results", "health.log")
STOP = os.path.join(HERE, "harness_results", "HEALTH_STOP")
INTERVAL = 60
HOT_C = 92          # GPU HOT SPOT (from LibreHardwareMonitor when available; core + 12 as a fallback)
CPU_HOT_C = 88      # Ryzen Tctl
HOT_SAMPLES = 2
LHM = "http://127.0.0.1:8085/data.json"   # LibreHardwareMonitor's sensor server (optional)


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


def stop_batch(reason):
    with open(STOP, "w", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {reason}\n")
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '*batch.py*' "
          "-or $_.CommandLine -like '*harness.py*' -or $_.CommandLine -like '*queue.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    hot = 0
    stopped = os.path.exists(STOP)
    while True:
        g = gpu()
        h = lhm()
        cl = h.get("cpu_load", cpu_load())
        line = time.strftime("%H:%M:%S")
        t = None
        if g:
            t, u, p, f, c = g
            hot_c = h.get("gpu_hot_c", t + 12)
            line += f"  GPU {t}C hot {hot_c:.0f}C load {u}% {p:.0f}W fan {f}% {c}MHz"
        else:
            hot_c = h.get("gpu_hot_c", 0)
            line += "  GPU n/a"
        cpu_c = h.get("cpu_c")
        line += f"  CPU {cpu_c:.0f}C load {cl:.0f}%" if cpu_c is not None else f"  CPU load {cl:.0f}%"
        over = hot_c >= HOT_C or (cpu_c is not None and cpu_c >= CPU_HOT_C)
        hot = hot + 1 if over else 0
        if hot >= HOT_SAMPLES and not stopped:
            stopped = True
            line += f"  >> GPU hot spot {hot_c:.0f}C / CPU {cpu_c}C over limit for {HOT_SAMPLES} samples: STOPPING BATCH"
            stop_batch(f"GPU hot {hot_c:.0f}C CPU {cpu_c}C")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
