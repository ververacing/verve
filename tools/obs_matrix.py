"""Observation matrix: a randomised, community-weighted harness queue across classes, tracks, grid sizes, mixed fields,
formats and difficulty (owner 2026-09-30: "a ton of cars, a ton of tracks, same class, mixed class, tons of combos").

Reads a content inventory (cars.csv / tracks.csv: columns id, matrix_class, matrix_subclass, bhp, usable, community_installs;
track, layout, length_m, pitboxes, usable, kind, community_installs_any_layout) and writes one harness line per race.

    python tools/obs_matrix.py --cars cars.csv --tracks tracks.csv --pc pc1 --n 200 --seed 1 --out batch_obs_pc1.txt
    python tools/obs_matrix.py ... --pc pc2 --cap 24 --no-wet --allow pc2_content_inventory.txt

--allow: a file of "car <id>" / "track <id> <layout|->" lines; only content listed there is used (PC #2's install).
Every line carries --settings {"classV2":true} (the v2 class detector) and --shuffle (random grid order: no slot bias).
"""
import argparse
import csv
import json
import math
import random

SPEED = {"gt": 165, "formula": 205, "formula_jr": 170, "prototype": 190, "hypercar": 195, "touring": 145, "road": 135,
         "vintage": 125, "kart": 70, "nascar": 185}   # km/h, a typical AI race average (for laps and budgets only)

# field type -> (weight, [(matrix_class, matrix_subclass or None = any), ...], band)  band: pick models within +-30 % bhp
FIELDS = {
    "gt3":          (20, [("gt", "GT3"), ("gt", "GT3/GTE")], False),
    "gt4":          (5,  [("gt", "GT4")], False),
    "gte_gt2":      (3,  [("gt", "GTE"), ("gt", "GT2")], False),
    "cup":          (3,  [("gt", "Cup"), ("gt", "GT3 Cup"), ("touring", "touring")], True),
    "f1":           (12, [("formula", "F1")], True),
    "indy":         (3,  [("formula", "Indy")], False),
    "junior":       (4,  [("formula", "F3"), ("formula_jr", None)], True),
    "tcr":          (6,  [("touring", "TCR")], False),
    "touring_90s":  (4,  [("touring", "DTM"), ("touring", "BTCC"), ("touring", "Supertouring")], False),
    "touring_old":  (3,  [("touring", "Vintage touring")], True),
    "road":         (12, [("road", "")], True),
    "road_hyper":   (3,  [("road", "hypercar (road)"), ("road", "hypercar (track special)")], False),
    "lmp1":         (3,  [("prototype", "LMP1")], False),
    "groupc":       (2,  [("prototype", "Group C")], False),
    "vintage":      (5,  [("vintage", "")], True),
    "kart":         (2,  [("kart", "")], True),
    "nascar":       (2,  [("nascar", "Cup")], False),
    # mixed classes: each part fills about half the grid
    "mix_gt3_gt4":  (3,  [("gt", "GT3"), "|", ("gt", "GT4")], False),
    "mix_hyp_gt3":  (2,  [("hypercar", None), "|", ("gt", "GT3")], False),
    "mix_lmp1_gte": (2,  [("prototype", "LMP1"), "|", ("gt", "GTE"), ("gt", "GT2")], False),
    "mix_gc_gt1":   (1,  [("prototype", "Group C"), "|", ("gt", "GT1")], False),
    "mix_tcr_gt4":  (1,  [("touring", "TCR"), "|", ("gt", "GT4")], False),
}
FORMATS = [("sprint", 25), ("race", 40), ("long", 10), ("timed", 15), ("weekend", 10)]
PROFILES = [("none", 40), ("random", 30), ("mixed", 20), ("rookies", 5), ("veterans", 5)]
LEVELS = [(100, 55), (95, 15), (90, 15), (80, 15)]
AGGR = [(30, 25), (60, 50), (90, 25)]


def pick(rng, pairs):
    tot = sum(w for _, w in pairs)
    r = rng.uniform(0, tot)
    for v, w in pairs:
        r -= w
        if r <= 0:
            return v
    return pairs[-1][0]


def yes(v):
    return str(v).strip().lower() in ("1", "true", "yes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cars", required=True)
    ap.add_argument("--tracks", required=True)
    ap.add_argument("--pc", default="pc1")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cap", type=int, default=30, help="max grid on this PC")
    ap.add_argument("--no-wet", action="store_true")
    ap.add_argument("--allow", help="content list of this PC ('car <id>' / 'track <id> <layout|->' lines)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    allow_cars = allow_tracks = None
    if a.allow:
        allow_cars, allow_tracks = set(), set()
        for line in open(a.allow, encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) >= 2 and p[0] == "car":
                allow_cars.add(p[1].lower())
            elif len(p) >= 2 and p[0] == "track":
                allow_tracks.add((p[1].lower(), (p[2] if len(p) > 2 else "-").lower()))

    cars = [c for c in csv.DictReader(open(a.cars, encoding="utf-8")) if yes(c.get("usable"))
            and (allow_cars is None or c["id"].lower() in allow_cars)]
    tracks = [t for t in csv.DictReader(open(a.tracks, encoding="utf-8")) if yes(t.get("usable"))
              and (allow_tracks is None or (t["track"].lower(), (t.get("layout") or "-").lower()) in allow_tracks)
              and " " not in (t.get("layout") or "") and " " not in t["track"]   # batch.py splits on whitespace
              and not (a.no_wet and "wet" in ((t.get("kind") or "") + (t.get("layout") or "")).lower())]

    def pool(spec):
        cls, sub = spec
        return [c for c in cars if c["matrix_class"] == cls and (sub is None or (c.get("matrix_subclass") or "") == sub)]

    def weight_car(c):
        try:
            return 1 + 3 * int(c.get("community_installs") or 0)
        except ValueError:
            return 1

    def choose_models(specs, band, k):
        cands = []
        for s in specs:
            cands += pool(s)
        cands = list({c["id"]: c for c in cands}.values())
        if not cands:
            return []
        if band:
            anchor = rng.choices(cands, weights=[weight_car(c) for c in cands])[0]
            try:
                hp = float(anchor.get("bhp") or 0)
            except ValueError:
                hp = 0
            if hp > 0:
                near = []
                for c in cands:
                    try:
                        h = float(c.get("bhp") or 0)
                    except ValueError:
                        h = 0
                    if h > 0 and abs(h - hp) / hp <= 0.30:
                        near.append(c)
                if len(near) >= 2:
                    cands = near
        out = []
        while cands and len(out) < k:
            c = rng.choices(cands, weights=[weight_car(x) for x in cands])[0]
            out.append(c)
            cands = [x for x in cands if x is not c]
        return out

    def track_ok(t, field, cls):
        kind = (t.get("kind") or "").lower()
        try:
            L = float(t.get("length_m") or 0)
        except ValueError:
            L = 0
        if field == "kart":
            return 0 < L < 2600
        if field == "nascar":
            return True
        if "oval" in kind:
            return field in ("indy",)
        if cls == "kart":
            return False
        return L >= 1500

    def weight_track(t):
        try:
            return 1 + 2 * math.sqrt(int(t.get("community_installs_any_layout") or t.get("community_installs") or 0))   # sqrt: no one track dominates
        except ValueError:
            return 1

    fields = [(f, w) for f, (w, _, _) in FIELDS.items()]
    lines = ["# Observation matrix %s: %d races, seed %d, cap %d%s. tools/obs_matrix.py; classV2 on, --shuffle on every race."
             % (a.pc, a.n, a.seed, a.cap, ", no wet" if a.no_wet else "")]
    made = 0
    tries = 0
    while made < a.n and tries < a.n * 50:
        tries += 1
        field = pick(rng, fields)
        _, specs, band = FIELDS[field]
        if "|" in specs:
            i = specs.index("|")
            A = choose_models(specs[:i], False, rng.randint(2, 4))
            B = choose_models(specs[i + 1:], False, rng.randint(2, 4))
            models = [(m, 0) for m in A] + [(m, 1) for m in B]
            if not A or not B:
                continue
        else:
            ms = choose_models(specs, band, rng.randint(3, 7))
            if len(ms) < 2 and field not in ("indy", "nascar"):
                continue
            if not ms:
                continue
            models = [(m, 0) for m in ms]
        cls = models[0][0]["matrix_class"]
        tr = [t for t in tracks if track_ok(t, field, cls)]
        if field == "nascar":
            ov = [t for t in tr if "oval" in (t.get("kind") or "").lower()]
            if ov and rng.random() < 0.7:
                tr = ov
        if not tr:
            continue
        t = rng.choices(tr, weights=[weight_track(x) for x in tr])[0]
        try:
            boxes = int(float(t.get("pitboxes") or 0))
            L = float(t.get("length_m") or 0) or 4000
        except ValueError:
            continue
        cars_n = min(boxes, a.cap, rng.choice([12, 16, 18, 20, 24, 30]))
        if cars_n < 10:
            continue
        # the model list: mixed fields interleave the two classes so each fills about half the grid
        ids = [m["id"] for m, _ in models]
        if len(set(g for _, g in models)) == 2:
            A = [m["id"] for m, g in models if g == 0]
            B = [m["id"] for m, g in models if g == 1]
            ids = [x for pair in zip(A * 10, B * 10) for x in pair][:max(len(A), len(B)) * 2]
        lap_s = L / (SPEED.get(cls, 150) / 3.6)
        fmt = pick(rng, FORMATS)
        extra = []
        longT = L > 10000   # Nordschleife-class: fewer laps
        if fmt == "sprint":
            laps = 1 if longT else 3
        elif fmt == "race":
            laps = max(2 if longT else 4, min(20, round(900 / lap_s)))
        elif fmt == "long":
            laps = max(3 if longT else 8, min(30, round(1800 / lap_s)))
        elif fmt == "timed":
            laps = 0
            extra.append("--minutes 20")
        else:
            laps = max(1 if longT else 4, min(15, round(600 / lap_s)))
            extra += ["--practice 8", "--quali 8"]
        budget = int(lap_s * 2.5 + 60)
        prof = pick(rng, PROFILES)
        if prof == "random":
            extra.append("--drivers random")
        elif prof == "mixed":
            extra.append("--profiles all=arch_midfield,1..3=arch_rookie,%d..%d=arch_veteran" % (max(4, cars_n - 5), cars_n - 1))
        elif prof == "rookies":
            extra.append("--profiles all=arch_rookie")
        elif prof == "veterans":
            extra.append("--profiles all=arch_veteran")
        lvl, ag = pick(rng, LEVELS), pick(rng, AGGR)
        assists = {}
        if rng.random() < 0.15:
            assists["DAMAGE"] = 0
        if assists:
            extra.append("--assists " + json.dumps(assists, separators=(",", ":")))
        if not a.no_wet and rng.random() < 0.08 and field not in ("kart",):
            extra.append("--weather " + rng.choice(["lightrain", "rain"]))
        layout = (t.get("layout") or "").strip()
        tflag = "--track %s" % t["track"] + ((" --layout %s" % layout) if layout and layout != "-" else "")
        made += 1
        label = "obs_%s_%03d_%s_%s" % (a.pc, made, field, t["track"][:18])
        parts = [tflag, ("--laps %d" % laps) if laps else "", "--cars %d" % cars_n, "--models " + ",".join(ids),
                 "--player-model " + ids[0], "--ai-level %d" % lvl, "--ai-aggression %d" % ag, "--shuffle",
                 "--lap-budget-s %d" % budget, '--settings {"classV2":true}'] + extra + ["--label " + label]
        lines.append(" ".join(p for p in parts if p))
    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("wrote %d races to %s" % (made, a.out))


if __name__ == "__main__":
    main()
