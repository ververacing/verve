"""Verve test harness -- launch AI-only Assetto Corsa races unattended and score them.

Maintainer tool, Windows only. Not shipped. Needs: AC + CSP installed, Steam running, diag.lua present
in the Verve app folder (the local diagnostics logger), and nobody using the game.

What one run does
  1. writes cfg/race.ini for the requested track / grid / laps / temperatures (the grid is copied from
     the current race.ini unless --grid points at another race.ini),
  2. writes apps/lua/Verve/harness.lua -- a self-expiring config Verve reads at load: put the player's
     car on autopilot, override settings for this run only, label the diagnostics file,
  3. launches acs.exe and waits for the race to finish (out/race_out.json is rewritten at session end),
  4. kills acs.exe, deletes harness.lua, scores the diagnostics file (tools/race_metrics.py) and appends
     a row to tools/harness_results/results.csv.

Examples
  python tools/harness.py --laps 6                                 # one run, current settings, label "A"
  python tools/harness.py --laps 6 --runs 3 --label baseline --settings '{"enabled": false}'
  python tools/harness.py --laps 8 --ab A.json B.json --runs 4     # alternate two arms, 4 runs each
  python tools/harness.py --track ks_silverstone --laps 5 --ambient 22 --road 30

An arm file (A.json) is {"label": "...", "settings": {...G keys...}, "recovery": {"DRIVE": false},
"racecraft": {...}} -- keys under "settings" are Verve's global toggles/sliders (enabled, crashRepair,
troubleSpots, racecraft, recovery, humanVar, humanErrors, classPhys, controlGrip, intensity, rcIntensity,
baseGrip); "recovery"/"racecraft" set fields on those modules directly.
"""
import argparse
import atexit
import configparser
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time

AC_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa"
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
CFG = os.path.join(DOCS, "cfg")
RACE_INI = os.path.join(CFG, "race.ini")
RACE_OUT = os.path.join(DOCS, "out", "race_out.json")
VERVE = os.path.join(AC_DIR, "apps", "lua", "Verve")
HARNESS_LUA = os.path.join(VERVE, "harness.lua")
RESULTS_DIR = os.path.join(VERVE, "tools", "harness_results")

sys.path.insert(0, os.path.join(VERVE, "tools"))
from race_metrics import metrics  # noqa: E402


class Ini(configparser.RawConfigParser):
    """AC's ini files: case-sensitive keys, no interpolation, duplicate-tolerant."""
    def __init__(self):
        super().__init__(strict=False, interpolation=None, allow_no_value=True)
        self.optionxform = str


def acs_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq acs.exe"], capture_output=True, text=True).stdout
    return "acs.exe" in out


def cleanup():
    """Whatever happens (Ctrl+C, crash, kill), never leave a game instance or a live harness.lua behind --
    a leftover blocks the next run and a stale harness.lua could hijack a real race (it self-expires, but
    don't rely on it)."""
    subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)
    if os.path.exists(HARNESS_LUA):
        try:
            os.remove(HARNESS_LUA)
        except OSError:
            pass


atexit.register(cleanup)


def read_ini(path):
    ini = Ini()
    ini.read(path, encoding="utf-8")
    return ini


def write_ini(ini, path):
    with open(path, "w", encoding="utf-8") as f:
        ini.write(f, space_around_delimiters=False)


FIRST_NAMES = ["Alex", "Sam", "Jo", "Chris", "Dana", "Robin", "Kim", "Lee", "Max", "Nico", "Toni", "Luca", "Andi", "Jules", "Rene", "Noor", "Kai"]
LAST_NAMES = ["Vermeer", "Okafor", "Lindqvist", "Moreau", "Tanaka", "Silva", "Novak", "Haddad", "Bauer", "Rossi", "Kowalski", "Dubois", "Ferreira", "Nilsen", "Costa", "Ahmed", "Weber"]


def first_skin(model):
    d = os.path.join(AC_DIR, "content", "cars", model, "skins")
    try:
        skins = sorted(s for s in os.listdir(d) if os.path.isdir(os.path.join(d, s)))
    except OSError:
        skins = []
    return skins[0] if skins else ""


def grid_from_models(models, count, seed=0):
    """Build CAR_1..N sections from a list of car models (cycled), with the same AI level spread AC's
    quick race uses (95-102) and generic driver names."""
    rnd = random.Random(seed)
    cars = []
    for n in range(count):
        m = models[n % len(models)]
        cars.append({
            "MODEL": m, "MODEL_CONFIG": "", "AI_LEVEL": str(rnd.randint(95, 102)), "AI_AGGRESSION": "0",
            "SKIN": first_skin(m), "DRIVER_NAME": f"{FIRST_NAMES[n % len(FIRST_NAMES)]} {LAST_NAMES[(n * 7) % len(LAST_NAMES)]}",
            "NATIONALITY": "", "NATION_CODE": "",
        })
    return cars


CAREER_DIR = os.path.join(AC_DIR, "content", "career")


def career_race_ini(spec, base_path):
    """Build a race.ini for a CAREER event ("series3/event2") the way the career launcher does: the event's
    own event.ini (track, laps, weather, the ramped AI_LEVEL) plus the series' opponents.ini for the AI grid.
    Career series are single-make, so opponents drive the event's car model."""
    series, event = spec.split("/")
    ev = read_ini(os.path.join(CAREER_DIR, series, event, "event.ini"))
    opp = read_ini(os.path.join(CAREER_DIR, series, "opponents.ini"))
    ini = read_ini(base_path)
    if ini.has_section("SPECIAL_EVENT"):
        ini.remove_section("SPECIAL_EVENT")
    for sec in ev.sections():
        # CONDITION_n / EVENT are launcher metadata. SPECIAL_EVENT makes acs.exe load THAT special event
        # (GUID 49 = a drift session in the Audi quattro) instead of this race.ini -- never copy it.
        if sec.startswith("CONDITION_") or sec in ("EVENT", "SPECIAL_EVENT"):
            continue
        if not ini.has_section(sec):
            ini.add_section(sec)
        for k, v in ev.items(sec):
            ini.set(sec, k, v)
    model = ev.get("RACE", "MODEL")
    cars = int(ev.get("RACE", "CARS"))
    level = float(ev.get("RACE", "AI_LEVEL", fallback="90"))
    k = 1
    while ini.has_section(f"CAR_{k}"):
        ini.remove_section(f"CAR_{k}")
        k += 1
    ini.set("CAR_0", "MODEL", "-")
    if not ini.get("CAR_0", "SKIN", fallback=""):
        ini.set("CAR_0", "SKIN", first_skin(model))
    n = 1
    # some series define the AI grid inline in event.ini (CAR_1..N, mixed models) instead of opponents.ini
    for a in range(1, 40):
        if n >= cars or not ev.has_section(f"CAR_{a}"):
            break
        ini.add_section(f"CAR_{n}")
        for kk, vv in ev.items(f"CAR_{a}"):
            ini.set(f"CAR_{n}", kk, vv)
        if not ini.get(f"CAR_{n}", "AI_LEVEL", fallback=""):
            ini.set(f"CAR_{n}", "AI_LEVEL", str(int(level)))
        if not ini.get(f"CAR_{n}", "DRIVER_NAME", fallback=""):
            ini.set(f"CAR_{n}", "DRIVER_NAME", f"AI {a}")
        n += 1
    for a in range(1, 40):
        if n >= cars:
            break
        sec = f"AI{a}"
        if not opp.has_section(sec):
            break
        skin = opp.get(sec, "SKIN", fallback="")
        if not os.path.isdir(os.path.join(AC_DIR, "content", "cars", model, "skins", skin)):
            skin = first_skin(model)
        lvl = float(opp.get(sec, "LEVEL", fallback="95"))
        ini.add_section(f"CAR_{n}")
        for kk, vv in [("MODEL", model), ("MODEL_CONFIG", ""), ("AI_LEVEL", str(int(round(level * lvl / 100.0)))), ("AI_AGGRESSION", "0"),
                       ("SKIN", skin), ("DRIVER_NAME", opp.get(sec, "NAME", fallback=f"AI {a}")), ("NATIONALITY", ""), ("NATION_CODE", "")]:
            ini.set(f"CAR_{n}", kk, vv)
        n += 1
    ini.set("RACE", "CARS", str(n))
    return ini, n


def set_sessions(ini, args):
    """SESSION_n sections: optional practice and qualifying (timed) ahead of the race (laps) -- a race
    weekend. Without --practice/--quali it's the plain quick race."""
    k = 0
    while ini.has_section(f"SESSION_{k}"):
        ini.remove_section(f"SESSION_{k}")
        k += 1
    sessions = []
    if getattr(args, "practice", 0):
        sessions.append({"NAME": "Practice", "TYPE": "1", "DURATION_MINUTES": str(args.practice), "SPAWN_SET": "PIT"})
    if getattr(args, "quali", 0):
        sessions.append({"NAME": "Qualifying", "TYPE": "2", "DURATION_MINUTES": str(args.quali), "SPAWN_SET": "PIT"})
    sessions.append({"NAME": "Quick Race" if not sessions else "Race", "TYPE": "3", "LAPS": str(args.laps), "DURATION_MINUTES": "0",
                     "SPAWN_SET": "START", "STARTING_POSITION": str(args.start_pos)})
    for n, sec in enumerate(sessions):
        ini.add_section(f"SESSION_{n}")
        for kk, vv in sec.items():
            ini.set(f"SESSION_{n}", kk, vv)


def build_race_ini(args, base_path):
    if args.career:
        ini, n = career_race_ini(args.career, base_path)
        if args.laps:
            ini.set("SESSION_0", "LAPS", str(args.laps)); ini.set("RACE", "RACE_LAPS", str(args.laps))
        else:
            args.laps = int(ini.get("SESSION_0", "LAPS", fallback="4"))
        ini.set("SESSION_0", "STARTING_POSITION", str(args.start_pos))
        return ini, n
    ini = read_ini(base_path)
    grid_src = read_ini(args.grid) if args.grid else ini
    # the grid (CAR_1..N): from --models, else copied from the source race.ini; optionally shuffled. CAR_0 is the player.
    cars = []
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        cars = grid_from_models(models, (args.cars or 18) - 1, seed=args.seed)
        if args.player_model:
            ini.set("CAR_0", "MODEL", "-")
            ini.set("RACE", "MODEL", args.player_model)
            ini.set("RACE", "SKIN", first_skin(args.player_model))
            ini.set("CAR_0", "SKIN", first_skin(args.player_model))
    else:
        k = 1
        while grid_src.has_section(f"CAR_{k}"):
            cars.append(dict(grid_src.items(f"CAR_{k}")))
            k += 1
    if args.shuffle:
        random.shuffle(cars)
    if args.cars:
        cars = cars[: args.cars - 1]
    k = 1
    while ini.has_section(f"CAR_{k}"):
        ini.remove_section(f"CAR_{k}")
        k += 1
    for n, c in enumerate(cars, 1):
        ini.add_section(f"CAR_{n}")
        for kk, vv in c.items():
            ini.set(f"CAR_{n}", kk, vv)
    if args.track:
        ini.set("RACE", "TRACK", args.track)
        ini.set("RACE", "CONFIG_TRACK", args.layout or "")
    ini.set("RACE", "CARS", str(len(cars) + 1))
    ini.set("RACE", "RACE_LAPS", str(args.laps))
    set_sessions(ini, args)
    if args.ambient is not None:
        ini.set("TEMPERATURE", "AMBIENT", str(args.ambient))
    if args.road is not None:
        ini.set("TEMPERATURE", "ROAD", str(args.road))
    return ini, len(cars) + 1


def lua_literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"[{lua_literal(k)}] = {lua_literal(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "{ " + ", ".join(lua_literal(x) for x in v) + " }"
    return "nil"


def write_harness_lua(arm, ttl_s):
    body = {
        "expires": int(time.time()) + ttl_s,
        "autopilot": True,
        "label": arm.get("label", "A"),
        "randomizeDrivers": bool(arm.get("drivers") == "random"),
        "shutdownAtEnd": True,        # Verve quits AC ~20 s after the flag so the replay autosaves
        "settings": arm.get("settings", {}),
        "recovery": arm.get("recovery", {}),
        "racecraft": arm.get("racecraft", {}),
    }
    with open(HARNESS_LUA, "w", encoding="utf-8") as f:
        f.write("-- written by tools/harness.py; self-expiring; never shipped\nreturn " + lua_literal(body) + "\n")


def newest_diag(after_ts):
    """The diagnostics file for the run launched at after_ts. A session end (or an app reload) opens a NEW
    file, so "newest" can be a few-frame stub written after the flag: prefer the LARGEST file of the run."""
    files = [os.path.join(VERVE, f) for f in os.listdir(VERVE) if f.startswith("diag_race_") and f.endswith(".jsonl")]
    files = [f for f in files if os.path.getmtime(f) >= after_ts - 5]
    if not files:
        return None
    return max(files, key=lambda f: (os.path.getsize(f) > 20000, os.path.getsize(f) if os.path.getsize(f) > 20000 else os.path.getmtime(f)))


def race_state(diag):
    """(leader lap, every car stopped in the pits?, seconds since the file was last written) from the
    newest snapshot in a diagnostics file, or None if it has no snapshots yet."""
    try:
        with open(diag, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200000))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
        rows = [json.loads(l) for l in tail if l.startswith('{"t"')]
        if not rows:
            return None
        r = rows[-1]
        parked = all(c["pit"] and c["spd"] < 3 for c in r["grid"])
        if r.get("session", 3) != 3:          # a practice / qualifying file: never "finished"
            return 0, False, 0
        return r["leaderLap"], parked, time.time() - os.path.getmtime(diag)
    except (OSError, ValueError, KeyError):
        return None


def force_ai_level(ini, level):
    """Overwrite AI_LEVEL on every CAR_n (n >= 1) and in [RACE]: the calibration runs need one known level."""
    if not level:
        return
    ini.set("RACE", "AI_LEVEL", str(int(level)))
    k = 1
    while ini.has_section(f"CAR_{k}"):
        ini.set(f"CAR_{k}", "AI_LEVEL", str(int(level)))
        k += 1


RACE_OUT = os.path.join(DOCS, "out", "race_out.json")


def best_laps_from_race_out(t_launch):
    """AC writes out/race_out.json when the session ends cleanly (Verve's graceful shutdown makes that happen
    in unattended runs). Returns {car_index: best_lap_s} for the race session, or {} if there is no fresh file."""
    try:
        if os.path.getmtime(RACE_OUT) < t_launch:
            return {}
        d = json.load(open(RACE_OUT, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    best = {}
    for sess in d.get("sessions", []):
        for l in sess.get("laps", []):
            t = l.get("time", 0) / 1000.0
            if t > 10:
                best[l["car"]] = min(best.get(l["car"], 1e9), t)
    return best


def run_once(args, arm, run_idx):
    if acs_running():
        raise SystemExit("acs.exe is already running -- close the game first (a run must own it)")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    backup = RACE_INI + ".harness-backup"
    if not os.path.exists(backup):
        shutil.copy2(RACE_INI, backup)
    ini, ncars = build_race_ini(args, backup if args.grid is None else RACE_INI)
    force_ai_level(ini, getattr(args, "ai_level", 0))
    write_ini(ini, RACE_INI)
    budget = args.laps * args.lap_budget_s + 240 + 60 * (getattr(args, "practice", 0) + getattr(args, "quali", 0)) + (120 if (getattr(args, "practice", 0) or getattr(args, "quali", 0)) else 0)
    write_harness_lua(arm, ttl_s=int(budget) + 120)
    label = arm.get("label", "A")
    print(f"[{label} #{run_idx}] {ini.get('RACE', 'TRACK')} x{args.laps} laps, {ncars} cars, budget {budget:.0f}s")

    t_launch = time.time()
    proc = subprocess.Popen([os.path.join(AC_DIR, "acs.exe")], cwd=AC_DIR)
    finished = False
    ours = True
    try:
        # Someone may have started the game in the same second (the user, from the launcher): a second acs.exe
        # exits at once. If OUR process is gone within 30 s the running game is not ours -- leave it alone,
        # never kill it, and don't score its diagnostics (2026-09-13: a harness run killed the user's drift session).
        for _ in range(6):
            time.sleep(5)
            if proc.poll() is not None:
                break
        if proc.poll() is not None and acs_running():
            ours = False
            print("  !! another Assetto Corsa instance is running (not ours) -- aborting this run without touching it")
            if os.path.exists(HARNESS_LUA):
                os.remove(HARNESS_LUA)
            return None
        # End of race is read from the diagnostics file (AC only rewrites out/race_out.json on exit to the
        # menu, so that signal never fires in an unattended run): the leader has completed all the laps,
        # or every car is stationary in the pits and the logger has gone quiet.
        while time.time() - t_launch < budget:
            time.sleep(10)
            if proc.poll() is not None:
                break
            diag = newest_diag(t_launch)
            if not diag:
                continue
            state = race_state(diag)
            if state is None:
                continue
            leader_lap, all_parked, age = state
            if leader_lap > args.laps or (all_parked and age > 40 and leader_lap >= 1):
                finished = True
                # let Verve close AC itself (replay autosave); fall back to the kill after 90 s
                for _ in range(18):
                    if proc.poll() is not None:
                        break
                    time.sleep(5)
                break
    finally:
        if ours:
            subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)
        if os.path.exists(HARNESS_LUA):
            os.remove(HARNESS_LUA)
    time.sleep(3)
    diag = newest_diag(t_launch)
    if diag and (getattr(args, "practice", 0) or getattr(args, "quali", 0)):
        # a weekend writes one file per session; score the race's
        cands = [os.path.join(VERVE, f) for f in os.listdir(VERVE) if f.startswith("diag_race_") and os.path.getmtime(os.path.join(VERVE, f)) >= t_launch - 5]
        race_files = [c for c in cands if (race_state(c) or (0, False, 0))[0] >= 1]
        if race_files:
            diag = max(race_files, key=os.path.getmtime)
    if not diag:
        print("  !! no diagnostics file produced (is diag.lua present? did the session start?)")
        return None
    m = metrics(diag)
    m["label"] = label
    m["run"] = run_idx
    m["finished"] = finished
    # exact lap times from AC itself (only when AC exited cleanly): AI best / median-of-best, player best
    best = best_laps_from_race_out(t_launch)
    ai_best = sorted(v for k, v in best.items() if k != 0)
    m["ai_level"] = getattr(args, "ai_level", 0) or ""
    m["ai_best_lap_s"] = round(ai_best[0], 2) if ai_best else ""
    m["ai_median_best_lap_s"] = round(ai_best[len(ai_best) // 2], 2) if ai_best else ""
    m["player_best_lap_s"] = round(best[0], 2) if 0 in best else ""
    if best:
        shutil.copy2(RACE_OUT, os.path.join(RESULTS_DIR, f"race_out_{time.strftime('%Y%m%d_%H%M%S')}_{label}.json"))
    m["arm"] = json.dumps({k: arm.get(k) for k in ("settings", "recovery", "racecraft", "drivers")}, sort_keys=True)
    csv_path = os.path.join(RESULTS_DIR, "results.csv")
    new = not os.path.exists(csv_path)
    if not new:   # the columns changed (2026-09-13: ai_level + exact lap times): rotate the old file rather than misalign rows
        with open(csv_path, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != list(m.keys()):
            os.replace(csv_path, csv_path.replace(".csv", f"_until_{time.strftime('%Y%m%d_%H%M')}.csv"))
            new = True
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(m.keys()))
        if new:
            w.writeheader()
        w.writerow(m)
    keys = ["leader_laps", "running_at_end", "within_1_lap", "retired_or_parked", "incidents", "incidents_lap0_1",
            "drops", "drops_ok", "frozen_cars", "laptime_median_spread_s"]
    print("  " + "  ".join(f"{k}={m[k]}" for k in keys))
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track"); ap.add_argument("--layout")
    ap.add_argument("--laps", type=int, default=0, help="race laps (default 6; a --career event keeps its own unless set)")
    ap.add_argument("--career", help="run a CAREER event as the launcher would, e.g. series3/event2 (event.ini + opponents.ini)")
    ap.add_argument("--cars", type=int, help="cap the grid at N cars (incl. player)")
    ap.add_argument("--grid", help="race.ini to copy CAR_n sections from (default: the current one)")
    ap.add_argument("--models", help="comma-separated car models to build the AI grid from (cycled), instead of copying a race.ini grid")
    ap.add_argument("--player-model", help="with --models: the player's car model (default: keep the current one)")
    ap.add_argument("--seed", type=int, default=0, help="with --models: AI level / name seed")
    ap.add_argument("--shuffle", action="store_true", help="shuffle the AI grid order each run")
    ap.add_argument("--start-pos", type=int, default=2)
    ap.add_argument("--practice", type=int, default=0, help="minutes of practice before the race (a weekend)")
    ap.add_argument("--quali", type=int, default=0, help="minutes of qualifying before the race (a weekend)")
    ap.add_argument("--ambient", type=int); ap.add_argument("--road", type=int)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--label", default="A")
    ap.add_argument("--settings", help="JSON of Verve global settings to override for the run")
    ap.add_argument("--drivers", choices=["none", "random"], default="none", help="random: assign Verve driver profiles to the whole grid (the Randomize button)")
    ap.add_argument("--ab", nargs=2, metavar=("A.json", "B.json"), help="two arm files; runs alternate A,B,A,B...")
    ap.add_argument("--lap-budget-s", type=int, default=150, help="seconds allowed per lap before a run is killed")
    ap.add_argument("--ai-level", type=int, default=0, help="force every AI car's AI_LEVEL (career events and --models grids alike); 0 = as configured")
    args = ap.parse_args()
    if not args.laps and not args.career:
        args.laps = 6

    if args.ab:
        arms = [json.load(open(p, encoding="utf-8")) for p in args.ab]
        for i, a in enumerate(arms):
            a.setdefault("label", chr(ord("A") + i))
    else:
        arms = [{"label": args.label, "settings": json.loads(args.settings) if args.settings else {}, "drivers": args.drivers}]

    results = []
    for r in range(args.runs):
        for arm in arms:
            m = run_once(args, arm, r + 1)
            if m:
                results.append(m)
            time.sleep(5)

    if len(arms) > 1 and results:
        print("\n== summary by arm (means)")
        keys = ["running_at_end", "within_1_lap", "retired_or_parked", "incidents", "incidents_lap0_1", "drops_ok", "frozen_cars",
                "laptime_median_spread_s"]
        for arm in arms:
            rs = [m for m in results if m["label"] == arm["label"]]
            if rs:
                print(f"  {arm['label']:>8} n={len(rs)} " + "  ".join(f"{k}={sum(m[k] for m in rs) / len(rs):.1f}" for k in keys))


if __name__ == "__main__":
    main()
