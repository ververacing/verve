"""Tidy the metadata Content Manager groups by (brand, class, year, tags) on the F1 and IndyCar mods so they sit in the
same groups as the Kunos cars. Edits ui/ui_car.json in place with minimal text substitutions (many mod files are not
strict JSON). Idempotent. Run with the game closed.

    python tools/car_meta.py
"""
import os, re
from collections import Counter

C = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "content", "cars"))   # apps/lua/Verve/tools -> assettocorsa/content/cars

YEARS = {"ferrari_312t": 1975, "ferrari_f2002": 2002, "ks_ferrari_f138": 2013, "ks_ferrari_f2004": 2004, "ks_ferrari_sf15t": 2015,
         "ks_ferrari_sf70h": 2017, "ks_lotus_25": 1962, "ks_lotus_72d": 1972, "lotus_49": 1967, "lotus_98t": 1986, "msf_williams_fw24": 2002,
         "renault_r24": 2004, "vrc_1988_mclaren_mp4-4_r02": 1988, "vrc_1988_mclaren_mp4-4_r04": 1988, "vrc_1988_mclaren_mp4-4_r09": 1988,
         "vrc_1988_mclaren_mp4-4_r10": 1988, "vsf1_mclaren-mp413": 1998, "vrc_1991_jordan_191": 1991, "vrc_2009_williams_fw31": 2009,
         "vrc_2009_williams_fw31_s1": 2009}
SEASON = {"vrc_2009_williams_fw31": "F1 2009", "vrc_2009_williams_fw31_s1": "F1 2009", "vrc_1997_ferrari_f310b": "F1 1997",
          "vrc_1997_williams_fw19": "F1 1997", "vrc_1991_jordan_191": "F1 1991", "vrc_1988_mclaren_mp4-4_r02": "F1 1988",
          "vrc_1988_mclaren_mp4-4_r04": "F1 1988", "vrc_1988_mclaren_mp4-4_r09": "F1 1988", "vrc_1988_mclaren_mp4-4_r10": "F1 1988",
          "ks_ferrari_f138": "F1 2013", "ks_ferrari_sf15t": "F1 2015", "ks_ferrari_sf70h": "F1 2017", "syn_mercedes_w09": "F1 2018",
          "red_bull_rb19": "F1 2023", "rtt_formula_2024_rb20": "F1 2024", "F1_alpine_2024": "F1 2024", "F1_mercedes_2024": "F1 2024",
          "f1_2012_redbull": "F1 2012", "cim_2008_redbull": "F1 2008", "vrc_2005_mclaren_mp420": "F1 2005", "vrc_2005_renault_r25": "F1 2005",
          "renault_r24": "F1 2004", "msf_williams_fw26": "F1 2004", "ks_ferrari_f2004": "F1 2004", "ferrari_f2002": "F1 2002",
          "msf_williams_fw24": "F1 2002", "vsf1_mclaren-mp413": "F1 1998", "lotus_98t": "F1 1986", "ferrari_312t": "F1 1975",
          "ks_lotus_72d": "F1 1972", "lotus_49": "F1 1967", "ks_lotus_25": "F1 1962"}
for d in os.listdir(C):
    if d.startswith("fo_2013_"):
        YEARS[d] = 2013; SEASON[d] = "F1 2013"
    if d.endswith("_2014") and not d.startswith("vsfr"):
        SEASON[d] = "F1 2014"

Q = '"'
RE_BRAND = re.compile(r'("brand"\s*:\s*")[^' + Q + r']*(")')
RE_CLASS = re.compile(r'("class"\s*:\s*")[^' + Q + r']*(")')
RE_YEAR = re.compile(r'("year"\s*:\s*)"?\d*"?')
RE_NAME = re.compile(r'"name"\s*:\s*"(?:[^' + Q + r'\\]|\\.)*"\s*,')
RE_TAGS = re.compile(r'"tags"\s*:\s*\[')


def load(p):
    raw = open(p, "rb").read()
    enc = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        return raw.decode(enc), enc
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def edit(folder, brand=None, cls=None, year=None, tags=()):
    p = os.path.join(C, folder, "ui", "ui_car.json")
    if not os.path.isfile(p):
        return "MISSING"
    t, enc = load(p)
    o = t
    if brand:
        t = RE_BRAND.sub(lambda m: m.group(1) + brand + m.group(2), t, count=1)
    if cls:
        t = RE_CLASS.sub(lambda m: m.group(1) + cls + m.group(2), t, count=1)
    if year:
        if RE_YEAR.search(t):
            t = RE_YEAR.sub(lambda m: m.group(1) + str(year), t, count=1)
        else:
            m = RE_NAME.search(t)
            if m:
                t = t[:m.end()] + "\n\t\"year\": %d," % year + t[m.end():]
    for tag in tags:
        if Q + tag + Q in t:
            continue
        m = RE_TAGS.search(t)
        if m:
            t = t[:m.end()] + Q + tag + Q + ", " + t[m.end():]
    if t != o:
        open(p, "w", encoding=enc, newline="").write(t)
        return "edited"
    return "unchanged"


def has(folder, pattern):
    p = os.path.join(C, folder, "ui", "ui_car.json")
    return os.path.isfile(p) and re.search(pattern, load(p)[0]) is not None


res = Counter()
f1 = [d for d in os.listdir(C) if has(d, r'"F1 (modern|classic)"')]
for d in f1:
    res["f1 " + edit(d, brand="Formula", cls="race", year=YEARS.get(d), tags=["F1"] + ([SEASON[d]] if d in SEASON else []))] += 1
indy = [d for d in os.listdir(C) if re.search(r"^(bd_lola_t9|lola_t94_|penske_pc2[23]_|reynard_94i_)", d)]   # the 1994 CART season pack only
for d in indy:
    yr = 1994 if ("1994" in d or "t94" in d or "94i" in d or "pc23" in d) else (1993 if ("t93" in d or "pc22" in d) else 1992)
    res["indy " + edit(d, brand="IndyCar", cls="race", year=yr, tags=["IndyCar", "IndyCar 1994 season"])] += 1
print(dict(res), "| f1 cars:", len(f1), "indy cars:", len(indy))
