"""Career detection, offline (read-only; needs the lupa package): build each installed career event's race.ini the way the career
launcher (and tools/harness.py --career) does - event.ini + opponents.ini, names and models included - then run lib/career.lua's
detection in LuaJIT with a mocked ac. Reports events read as another event or not read as career at all.

    python tools/career_detect_check.py [path/to/career.lua]
"""
import configparser, io, os, re, sys
import lupa.luajit21 as lj
VERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.normpath(os.path.join(VERVE, "..", "..", "..")).replace(os.sep, "/")   # apps/lua/Verve -> the AC folder
CAREER = ROOT + "/content/career"
LUA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VERVE, "lib", "career.lua")
def rd(p):
    c = configparser.ConfigParser(strict=False, interpolation=None, inline_comment_prefixes=(";",)); c.optionxform = str
    try: c.read_string(open(p, encoding="utf-8", errors="replace").read())
    except Exception: pass
    return c
def build(series, event):
    ev = rd(CAREER + "/%s/%s/event.ini" % (series, event)); opp = rd(CAREER + "/%s/opponents.ini" % series)
    ini = configparser.ConfigParser(strict=False, interpolation=None); ini.optionxform = str
    for sec in ev.sections():
        if sec.startswith("CONDITION_") or sec in ("EVENT", "SPECIAL_EVENT"): continue
        ini.add_section(sec)
        for k, v in ev.items(sec): ini.set(sec, k, v)
    model = ev.get("RACE", "MODEL", fallback=""); cars = int(ev.get("RACE", "CARS", fallback="1")); level = float(ev.get("RACE", "AI_LEVEL", fallback="90"))
    k = 1
    while ini.has_section("CAR_%d" % k): ini.remove_section("CAR_%d" % k); k += 1
    if not ini.has_section("CAR_0"): ini.add_section("CAR_0")
    ini.set("CAR_0", "MODEL", "-")
    n = 1
    for a in range(1, 40):
        if n >= cars or not ev.has_section("CAR_%d" % a): break
        ini.add_section("CAR_%d" % n)
        for kk, vv in ev.items("CAR_%d" % a): ini.set("CAR_%d" % n, kk, vv)
        if not ini.get("CAR_%d" % n, "DRIVER_NAME", fallback=""): ini.set("CAR_%d" % n, "DRIVER_NAME", "AI %d" % a)
        n += 1
    for a in range(1, 40):
        if n >= cars: break
        sec = "AI%d" % a
        if not opp.has_section(sec): break
        omodel = opp.get(sec, "MODEL", fallback="") or model
        oname = opp.get(sec, "NAME", fallback="") or opp.get(sec, "DRIVER_NAME", fallback="") or "AI %d" % a
        ini.add_section("CAR_%d" % n)
        ini.set("CAR_%d" % n, "MODEL", omodel); ini.set("CAR_%d" % n, "DRIVER_NAME", oname); ini.set("CAR_%d" % n, "AI_LEVEL", "90")
        n += 1
    ini.set("RACE", "CARS", str(n))
    b = io.StringIO(); ini.write(b); return b.getvalue(), n
pairs = []
for s in sorted(os.listdir(CAREER), key=lambda x: int(re.sub(r"\D", "", x) or 0)):
    if re.match(r"series\d+$", s):
        for e in sorted(os.listdir(CAREER + "/" + s)):
            if re.match(r"event\d+$", e) and os.path.exists(CAREER + "/%s/%s/event.ini" % (s, e)): pairs.append((s, e))
ok = wrong = notcar = single = 0; bad = []
for series, ev in pairs:
    raceini, ncars = build(series, ev)
    if ncars <= 1: single += 1; continue
    L = lj.LuaRuntime(unpack_returned_tuples=True); g = L.globals()
    def load(path, default="", raceini=raceini):
        if path == "CFG/race.ini": return raceini
        try: return open(path, encoding="utf-8", errors="replace").read()
        except OSError: return default
    def scandir(d, mask, cb=None):
        try: names = os.listdir(d)
        except OSError: names = []
        if cb:
            for x in names: cb(x)
        return L.table_from(names)
    g.PYLOAD = load; g.PYSCAN = scandir; g.ROOT = ROOT; g.NCARS = ncars
    L.execute("""
    ac = {FolderID = {Root = 1, Cfg = 2}}
    function ac.getSim() return {currentSessionIndex = 0, carsCount = NCARS} end
    function ac.getFolder(id) if id == 1 then return ROOT else return 'CFG' end end
    function ac.log(s) LOGS = s end
    io.load = function(p, d) return PYLOAD(p, d) end
    io.scanDir = function(d, m, cb) return PYSCAN(d, m, cb) end
    """)
    C = L.execute(open(LUA, encoding="utf-8").read()); C.detect()
    m = re.search(r"Career (series\d+)/(event\d+)", g.LOGS or "")
    if not m: notcar += 1; bad.append("%s/%s: not career" % (series, ev))
    elif (m.group(1), m.group(2)) != (series, ev): wrong += 1; bad.append("%s/%s -> %s/%s" % (series, ev, m.group(1), m.group(2)))
    else: ok += 1
print("%s: correct %d | wrong event %d | not detected %d | single-car events skipped %d" % (LUA, ok, wrong, notcar, single))
print(bad[:60])
