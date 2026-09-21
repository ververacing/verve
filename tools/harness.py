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
# kept replays live on D: when it exists (C: was down to 20 GB with 33 GB of replays, 2026-09-18); the old folder is the fallback
REPLAY_DIR = "D:/Verve/harness_replays" if os.path.isdir("D:/") else os.path.join(RESULTS_DIR, "replays")

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
    # "model*k" pins k consecutive slots to that model (a class-sorted multi-class grid: 'gt3a*9,gt3b*9,gt4*6'); plain
    # names cycle as before
    expanded = []
    for m in models:
        if "*" in m:
            name, k = m.split("*", 1); expanded += [name] * int(k)
        else:
            expanded.append(m)
    pinned = any("*" in m for m in models)
    for n in range(count):
        m = expanded[n] if pinned and n < len(expanded) else expanded[n % len(expanded)]
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
    minutes = getattr(args, "minutes", 0) or 0
    # a TIMED race (most outside races are timed): LAPS 0 + DURATION_MINUTES; AC adds a lap after the clock runs out
    sessions.append({"NAME": "Quick Race" if not sessions else "Race", "TYPE": "3", "LAPS": "0" if minutes else str(args.laps),
                     "DURATION_MINUTES": str(minutes) if minutes else "0",
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
    if getattr(args, "minutes", 0):
        ini.set("RACE", "VIRTUAL_LAPS", str(args.laps))   # the lap estimate AC fuels the AI with in a timed race (RACE_LAPS alone gave 4 L, 2026-09-20)
    ini.set("RACE", "RACE_LAPS", str(args.laps))     # also for a timed race: AC fuels the AI from this estimate (0 = 4 L, the field ran dry after two laps, 2026-09-20)
    set_sessions(ini, args)
    if args.weather:
        # CSP weather type (Pure/Sol controllers read __CM_WEATHER_TYPE): 12 clear, 13 few clouds, 15 broken clouds, 16 overcast,
        # 17 fog, 18 mist, 3 light drizzle, 6 light rain, 7 rain, 8 heavy rain, 1 thunderstorm, 27 hot, 26 cold, 28 windy
        WT = {"clear": 12, "clouds": 15, "overcast": 16, "fog": 17, "mist": 18, "drizzle": 3, "lightrain": 6, "rain": 7,
              "heavyrain": 8, "storm": 1, "hot": 27, "cold": 26, "windy": 28}
        wt = WT.get(args.weather.lower(), None)
        if wt is None and args.weather.isdigit():
            wt = int(args.weather)
        if wt is None:
            raise SystemExit("unknown --weather %r (use one of %s or a CSP type number)" % (args.weather, ", ".join(WT)))
        if not ini.has_section("LIGHTING"):
            ini.add_section("LIGHTING")
        ini.set("LIGHTING", "__CM_WEATHER_TYPE", str(wt))
        args.weather_type = wt
        ini.set("LIGHTING", "__CM_WEATHER_CONTROLLER", "pureCtrl")
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


def parse_profiles(spec, ncars):
    """'all=arch_rookie,last=lewis_hamilton,3=kevin_estre' -> {"all": key, "slots": {idx: key}}; 'last' = the back of the grid."""
    if not spec:
        return None
    out = {"all": "", "slots": {}}
    for part in spec.split(","):
        k, _, v = part.partition("=")
        k = k.strip(); v = v.strip()
        if k == "all":
            out["all"] = v
        elif k == "last":
            out["slots"][ncars - 1] = v
        elif ".." in k:                              # a slot range: 12..17=arch_veteran
            a, b = k.split("..")
            for i in range(int(a), int(b) + 1):
                out["slots"][i] = v
        else:
            out["slots"][int(k)] = v
    return out


def write_harness_lua(arm, ttl_s, ncars=0):
    body = {
        "expires": int(time.time()) + ttl_s,
        "autopilot": True,
        "label": arm.get("label", "A"),
        "randomizeDrivers": bool(arm.get("drivers") == "random"),
        "profiles": parse_profiles(arm.get("profiles"), ncars),   # fixed grid: {all=key, slots={[i]=key}} (nil = untouched)
        "shutdownAtEnd": True,        # Verve quits AC ~20 s after the flag so the replay autosaves
        "stopAtLap": arm.get("stop_laps") or 0,      # heavy sprint: Verve quits once the leader has done N laps (a long race's fuel, a sprint's length)
        # raceFeed is a Verve setting (1-2 Hz feed in Documents/Assetto Corsa/verve_feed): the 8 s diag can't resolve who hit whom
        "settings": {"raceFeed": True, "shareData": True, **arm.get("settings", {})},   # shareData: exercises the opt-in report path; rows are flagged unattended
        "recovery": arm.get("recovery", {}),
        "racecraft": arm.get("racecraft", {}),
        "troublespots": arm.get("troublespots", {}),   # e.g. {"FRESH": true}: this run neither loads nor saves the learned map
        "fault": arm.get("fault", {}),                 # lib/fault.lua switches, e.g. {"ENABLED": true, "ENFORCE": false}
        "human": arm.get("human", {}),                 # lib/human.lua fields, e.g. {"RAINFX_GRIP": 1.0}
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
        stopped = all(c["spd"] < 3 for c in r["grid"])       # a point-to-point finish: nobody is ever "in the pits" (Trento 2026-09-20)
        if r.get("session", 3) != 3:          # a practice / qualifying file: never "finished"
            return 0, False, 0
        return r["leaderLap"], parked or (stopped and r["leaderLap"] >= 1), time.time() - os.path.getmtime(diag)
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


CSP_USER_CFG = os.path.join(CFG, "extension")


def apply_csp_overrides(spec):
    """--csp JSON {"module": {"SECTION": {"KEY": value}}} -> Documents/Assetto Corsa/cfg/extension/<module>.ini (CSP's per-user
    overrides, read at game start). Any existing user file is backed up and restored after the run, so a test setting never
    outlives its race. Returns the list of (path, backup-or-None) to restore."""
    restore = []
    if not spec:
        return restore
    os.makedirs(CSP_USER_CFG, exist_ok=True)
    for module, sections in spec.items():
        path = os.path.join(CSP_USER_CFG, f"{module}.ini")
        bak = path + ".harness-backup"
        if os.path.exists(path):
            shutil.copy2(path, bak)
            restore.append((path, bak))
        else:
            restore.append((path, None))
        ini = configparser.RawConfigParser(); ini.optionxform = str
        if os.path.exists(path):
            ini.read(path, encoding="utf-8")
        for sec, kv in sections.items():
            if not ini.has_section(sec):
                ini.add_section(sec)
            for k, v in kv.items():
                ini.set(sec, k, str(int(v)) if isinstance(v, bool) else str(v))
        with open(path, "w", encoding="utf-8") as f:
            ini.write(f, space_around_delimiters=False)
    return restore


PURE_SETTINGS = os.path.join(AC_DIR, "extension", "weather-controllers", "pureCtrl", "settings.ini")
RAINY = {3, 4, 5, 6, 7, 8, 0, 1, 2, 9, 10, 11, 29}   # CSP types that should start on a wet track


PURE_PLANS = os.path.join(AC_DIR, "extension", "config-ext", "PurePlanner", "Plans")
# Pure weather-slot index (the "index" a plan container carries) per CSP weather type; rain fields per type
PURE_INDEX = {12: 2, 13: 3, 14: 4, 15: 5, 16: 6, 17: 17, 18: 18, 3: 30, 6: 40, 7: 50, 8: 60, 1: 70, 27: 2, 26: 2, 28: 2}
PURE_RAIN = {3: (0.10, 0.25, 0.05), 6: (0.20, 0.45, 0.12), 7: (0.45, 0.85, 0.30), 8: (0.85, 1.0, 0.6), 1: (1.0, 1.0, 0.8)}   # amount, wetness, water


def apply_pure_for_weather(wt):
    """Pure only renders weather from a running PLAN (the CM weather type alone came out bone dry twice, 2026-09-19).
    For a --weather run: write a one-slot Timed plan from the broadcast side's plan as a template (rain amount /
    wetness / standing water per type, index = Pure's weather slot), point the controller at it with autostart on
    and last-used off, and restore the controller file after the race. Plans left in the folder are harmless."""
    if wt is None or not os.path.exists(PURE_SETTINGS):
        return None
    # template: tools/pure_plan_template.json, a copy of the DAYCYCLE plan (control type 1, looping, one 24 h container)
    # that is the only kind seen to rain on this machine; a Timed (type 2) plan with a timestamp never fired
    tmpl = None
    for cand in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "pure_plan_template.json"), os.path.join(PURE_PLANS, "last_used.json")):
        if os.path.exists(cand):
            tmpl = json.load(open(cand, encoding="utf-8")); break
    if not tmpl or not tmpl.get("container"):
        print("  (no Pure plan template; weather left to the CM type)")
        return None
    plan = {"control": {"timemulti": 1, "type": 1, "loop": True}, "container": [dict(tmpl["container"][0])]}
    c = plan["container"][0]; c["data"] = dict(c["data"]); w = dict(c["data"]["weather"])
    c["data"]["duration"] = 86400
    amount, wetness, water = PURE_RAIN.get(wt, (0.0, 0.0, 0.0))
    w.update({"index": PURE_INDEX.get(wt, 2), "rain_amount": amount, "rain_wetness": wetness, "rain_water": water,
              "rain_probability": 1.0 if amount > 0 else 0, "rain_variance": 0, "mist": 0.6 if wt in (17, 18) else 0,
              "rain_amount_dyn": False, "rain_wetness_dyn": False, "rain_water_dyn": False, "mist_dyn": False,
              "rain_amount_range": 0, "rain_wetness_range": 0, "rain_water_range": 0, "rain_probability_range": 0, "mist_range": 0})
    c["data"]["weather"] = w
    # the only path that has actually rendered rain here is Pure's LAST-USED plan with autostart (the broadcast side's
    # plan did it by accident on 2026-09-18); a named PLAN with LAST_USED=0 came out dry. So the generated plan goes in
    # as last_used.json (the original is backed up and restored with the controller file).
    lu = os.path.join(PURE_PLANS, "last_used.json")
    if os.path.exists(lu) and not os.path.exists(lu + ".harness-backup"):
        shutil.copy2(lu, lu + ".harness-backup")
    with open(lu, "w", encoding="utf-8") as f:
        json.dump(plan, f)
    bak = PURE_SETTINGS + ".harness-backup"
    shutil.copy2(PURE_SETTINGS, bak)
    lines = open(PURE_SETTINGS, encoding="utf-8").read().splitlines(True)
    want = {"AUTOSTART": "1", "LAST_USED": "1", "LIVE": "0", "START_WETNESS": "1", "START_PUDDLES": "1"}
    out = []
    for ln in lines:
        key = ln.split("=", 1)[0].strip() if "=" in ln else None
        if key in want:
            rest = ln.split(";", 1)[1] if ";" in ln else chr(10)
            ln = f"{key}={want[key]} ;{rest}" if ";" in ln else f"{key}={want[key]}" + chr(10)
        out.append(ln)
    open(PURE_SETTINGS, "w", encoding="utf-8").write("".join(out))
    return bak


def restore_pure(bak):
    if bak and os.path.exists(bak):
        try:
            os.replace(bak, PURE_SETTINGS)
        except OSError as e:
            print("  (pure settings not restored:", e, ")")
    lu = os.path.join(PURE_PLANS, "last_used.json")
    if os.path.exists(lu + ".harness-backup"):
        try:
            os.replace(lu + ".harness-backup", lu)
        except OSError as e:
            print("  (pure last-used plan not restored:", e, ")")


ASSISTS_INI = os.path.join(CFG, "assists.ini")

def apply_assists(spec):
    """--assists JSON {"DAMAGE": 0, "FUEL_RATE": 2} -> [ASSISTS] keys in cfg/assists.ini for this run only (the launcher's
    damage / fuel / tyre settings; an outside install with damage OFF is what the contacts detector exists for). The file
    is backed up and restored after the run. Returns the backup path or None."""
    if not spec or not os.path.exists(ASSISTS_INI):
        return None
    bak = ASSISTS_INI + ".harness-backup"
    shutil.copy2(ASSISTS_INI, bak)
    lines = open(ASSISTS_INI, encoding="utf-8").read().splitlines(True)
    want = {str(k): str(v) for k, v in spec.items()}
    out, seen = [], set()
    for ln in lines:
        key = ln.split("=", 1)[0].strip() if "=" in ln else None
        if key in want:
            rest = ln.split(";", 1)[1] if ";" in ln else chr(10)
            ln = f"{key}={want[key]} ;{rest}" if ";" in ln else f"{key}={want[key]}" + chr(10)
            seen.add(key)
        out.append(ln)
    for k in want:
        if k not in seen:
            out.append(f"{k}={want[k]}" + chr(10))
    open(ASSISTS_INI, "w", encoding="utf-8").write("".join(out))
    return bak


def restore_assists(bak):
    if bak and os.path.exists(bak):
        try:
            os.replace(bak, ASSISTS_INI)
        except OSError as e:
            print("  (assists not restored:", e, ")")


def restore_csp_overrides(restore):
    for path, bak in restore:
        try:
            if bak and os.path.exists(bak):
                os.replace(bak, path)
            elif os.path.exists(path):
                os.remove(path)
        except OSError as e:
            print("  (csp override not restored:", e, ")")


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
    eff_laps = min(args.laps, args.stop_laps) if getattr(args, "stop_laps", 0) else args.laps
    budget = eff_laps * args.lap_budget_s + 240
    if getattr(args, "minutes", 0):
        budget = args.minutes * 60 + 2 * args.lap_budget_s + 240      # the clock, the extra lap, the load + 60 * (getattr(args, "practice", 0) + getattr(args, "quali", 0)) + (120 if (getattr(args, "practice", 0) or getattr(args, "quali", 0)) else 0)
    write_harness_lua(arm, ttl_s=int(budget) + 120, ncars=ncars)
    label = arm.get("label", "A")
    print(f"[{label} #{run_idx}] {ini.get('RACE', 'TRACK')} x{args.laps} laps, {ncars} cars, budget {budget:.0f}s")

    csp_restore = apply_csp_overrides(arm.get("csp") or {})
    assists_bak = apply_assists(arm.get("assists") or {})
    pure_bak = apply_pure_for_weather(getattr(args, "weather_type", None))
    t_launch = time.time()
    proc = subprocess.Popen([os.path.join(AC_DIR, "acs.exe")], cwd=AC_DIR)
    # AC occasionally dies at load (a crash box, or an exit within a minute); one relaunch after a pause fixes it
    csp_log = os.path.join(DOCS, "logs", "custom_shaders_patch.log")
    for attempt in range(3):
        time.sleep(45)
        if proc.poll() is None:
            # alive: but is it LOADING? On CSP preview builds the process sometimes sits with zero CPU and an empty CSP
            # log for its whole budget (2026-09-19, two races lost that way). Give it 90 s more to write the log.
            hung = False
            for _ in range(6):
                time.sleep(15)
                try:
                    fresh = os.path.getmtime(csp_log) >= t_launch - 2 and os.path.getsize(csp_log) > 2000
                except OSError:
                    fresh = False
                if fresh or proc.poll() is not None:
                    break
            else:
                hung = True
            if not hung:
                break
            print(f"  !! acs.exe hung at launch ({time.time() - t_launch:.0f}s, no CSP log); killing and relaunching (attempt {attempt + 1})")
            subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)
            time.sleep(20)
            t_launch = time.time()
            proc = subprocess.Popen([os.path.join(AC_DIR, "acs.exe")], cwd=AC_DIR)
            continue
        if acs_running():
            break                                   # someone else's game: handled below
        print(f"  !! acs.exe exited {time.time() - t_launch:.0f}s after launch (attempt {attempt + 1}); relaunching")
        time.sleep(15)
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
        stopped_checks = 0
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
            stopped_checks = stopped_checks + 1 if all_parked else 0      # a field stopped for 4 checks (40 s) is over, logger or not (point-to-point finish)
            lap_done = (leader_lap > args.laps) if not getattr(args, "minutes", 0) else False   # timed: the flag is 'all parked'
            if lap_done or (getattr(args, "stop_laps", 0) and leader_lap >= args.stop_laps) or (all_parked and (age > 40 or stopped_checks >= 4) and leader_lap >= 1):
                finished = True
                # let Verve close AC itself (replay autosave); fall back to the kill after 90 s
                for _ in range(18):
                    if proc.poll() is not None:
                        break
                    time.sleep(5)
                break
    finally:
        restore_pure(pure_bak)
        restore_assists(assists_bak)
        restore_csp_overrides(csp_restore)
        if ours:
            subprocess.run(["taskkill", "/IM", "acs.exe", "/F"], capture_output=True)
        if os.path.exists(HARNESS_LUA):
            os.remove(HARNESS_LUA)
    time.sleep(3)
    # keep the replay: AC's autosave only retains the last two race replays, and the broadcast pipeline
    # needs them later (Documents/Assetto Corsa/replay/temp -> tools/harness_results/replays/<label>.acreplay)
    try:
        rdir = os.path.join(DOCS, "replay", "temp")
        cands = [os.path.join(rdir, f) for f in os.listdir(rdir) if f.endswith(".acreplay") and os.path.getmtime(os.path.join(rdir, f)) >= t_launch]
        if cands:
            newest = max(cands, key=os.path.getmtime)
            keep = REPLAY_DIR
            os.makedirs(keep, exist_ok=True)
            dst = os.path.join(keep, f"{time.strftime('%Y%m%d_%H%M')}_{label}.acreplay")
            shutil.copy2(newest, dst)
            print(f"  replay kept: {os.path.basename(dst)} ({os.path.getsize(dst) / 1e6:.0f} MB)")
    except OSError as e:
        print("  (replay not kept:", e, ")")
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
    if "error" in m:      # e.g. the session never got going: log it as a failed run instead of crashing the batch
        print(f"  !! run not scorable: {m['error']} ({os.path.basename(diag)})")
        keys = ["leader_laps", "running_at_end", "within_1_lap", "within_2_laps", "retired_or_parked", "incidents", "incidents_lap0_1",
                "incidents_low_speed", "crash_repairs", "drops", "drops_ok", "drops_off", "frozen_cars", "laptime_median_spread_s"]
        m = {"file": os.path.basename(diag), **{k: "" for k in keys}, "error": m["error"]}
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
    m["arm"] = json.dumps({k: arm.get(k) for k in ("settings", "recovery", "racecraft", "drivers", "troublespots", "fault", "csp", "human")}, sort_keys=True)
    m["weather"] = args.weather or ""
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
    ap.add_argument("--weather", help="CSP weather type by name (clear, clouds, overcast, fog, mist, drizzle, lightrain, rain, heavyrain, storm, hot, cold, windy) or number; Pure must be the weather controller")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--label", default="A")
    ap.add_argument("--settings", help="JSON of Verve global settings to override for the run")
    ap.add_argument("--recovery", help="JSON of Recovery module fields to override for the run, e.g. {\"DROP_API\":\"car\"}")
    ap.add_argument("--racecraft", help="JSON of Racecraft module fields to override for the run")
    ap.add_argument("--troublespots", help="JSON of Troublespots module fields, e.g. {\"FRESH\":true} = clean learned map for this run")
    ap.add_argument("--human", help="JSON of Human module fields, e.g. {\"RAINFX_GRIP\":1.0,\"RAINFX_CAUT\":1.0}")
    ap.add_argument("--csp", help="JSON of CSP per-user config overrides for this run only, e.g. {\"new_behaviour\":{\"AI_RACE_RUBBERBANDING\":{\"ENABLED\":1}}}")
    ap.add_argument("--minutes", type=int, default=0, help="TIMED race of N minutes (LAPS 0; AC adds a lap after the clock). --laps is then only the fuel/budget estimate")
    ap.add_argument("--stop-laps", type=int, default=0, help="heavy sprint: end the race gracefully once the leader completes N laps (fuel load of --laps, duration of N)")
    ap.add_argument("--assists", help="JSON of launcher assists for this run only (cfg/assists.ini [ASSISTS]), e.g. {\"DAMAGE\":0} = damage off")
    ap.add_argument("--fault", help="JSON of Fault module fields (penalties), e.g. {\"ENABLED\":true,\"ENFORCE\":false}")
    ap.add_argument("--drivers", choices=["none", "random"], default="none", help="random: assign Verve driver profiles to the whole grid (the Randomize button)")
    ap.add_argument("--profiles", help="fixed profiles: 'all=arch_rookie,last=lewis_hamilton,3=kevin_estre' (slot 0 = the autopilot player car; 'last' = back of the grid)")
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
        arms = [{"label": args.label, "settings": json.loads(args.settings) if args.settings else {}, "drivers": args.drivers, "profiles": args.profiles,
                 "recovery": json.loads(args.recovery) if args.recovery else {}, "racecraft": json.loads(args.racecraft) if args.racecraft else {},
                 "troublespots": json.loads(args.troublespots) if args.troublespots else {}, "fault": json.loads(args.fault) if args.fault else {}, "csp": json.loads(args.csp) if args.csp else {}, "human": json.loads(args.human) if args.human else {},
                 "assists": json.loads(args.assists) if args.assists else {}, "stop_laps": args.stop_laps}]

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
