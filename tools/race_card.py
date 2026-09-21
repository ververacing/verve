"""Race card: a one-page, anonymised description of a race, built from the harness's files, for a blind critic.

    python tools/race_card.py <diag_race_*.jsonl> [--out card.md] [--label "Race A"]

The card shows only what a spectator with a timing screen would know: the class and circuit, the lap chart of the top
positions, gaps at the flag, retirements, cars that stopped on track and rejoined, incidents per lap, overtakes per
lap and where they happened, the first thirty seconds, lap-time spread and pit stops. No app names, no driver names,
no settings, no mechanics. A real race's timing data can be turned into the same card, and a critic who sees two cards
should not be able to tell which came from the simulator by the format.

Sources: the diag file (8 s snapshots + contact events), the matching race_out_*.json (per-lap times, results) and the
matching verve_feed (1 Hz states, overtake / incident / lead-change events), found by timestamp when present.
"""
import argparse
import glob
import json
import os
import re
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
DOCS = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa")
CLASS_WORDS = {
    "gt3": "GT3", "gt4": "GT4", "sf70h": "Formula 1", "formula": "Formula 1", "f317": "Formula 3", "f312": "Formula 3",
    "dallara": "Formula 3", "tatuus": "Formula 4", "499p": "Hypercar", "valkyrie": "Hypercar", "sc63": "Hypercar",
    "919": "LMP1", "r18": "LMP1", "ts040": "LMP1", "787b": "Group C", "962": "Group C", "nascar": "Stock car",
    "camaro": "Stock car", "tcr": "Touring", "dtm": "Touring", "btcc": "Touring", "gokart": "Kart", "rally": "Rally",
    "lotus_49": "Vintage F1", "312_67": "Vintage F1", "lotus_25": "Vintage F1", "cobra": "Vintage GT", "gt40": "Vintage GT",
    "giulia": "Road", "m4": "Road", "corvette": "Road", "gt3_cup": "Cup", "clio": "Cup", "mx5": "Cup", "ginetta": "Cup",
}
TRACK_WORDS = {
    "spa": "Spa-Francorchamps", "monza": "Monza", "ks_barcelona": "Barcelona", "imola": "Imola", "mugello": "Mugello",
    "ks_silverstone": "Silverstone", "ks_nurburgring": "Nurburgring GP", "ks_brands_hatch": "Brands Hatch",
    "ks_zandvoort": "Zandvoort", "ks_red_bull_ring": "Red Bull Ring", "bahrain_international_circuit": "Bahrain",
    "baku_2022": "Baku", "daytona_2017": "Daytona", "ks_nordschleife": "Nordschleife", "ks_highlands": "Highlands",
    "magione": "Magione", "ks_vallelunga": "Vallelunga", "ks_laguna_seca": "Laguna Seca", "ks_monza66": "Monza 1966",
}


def class_of(models):
    votes = {}
    for m in models:
        ml = m.lower()
        for k, v in CLASS_WORDS.items():
            if k in ml:
                votes[v] = votes.get(v, 0) + 1
                break
    if not votes:
        return "unknown class"
    names = sorted(votes, key=lambda k: -votes[k])
    return names[0] if len(names) == 1 else " + ".join(names[:2]) + " (multi-class)"


def load_diag(path):
    hdr, rows, contacts = None, [], []
    for l in open(path, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if "hdr" in r:
            hdr = r
        elif r.get("ev") == "contact":
            contacts.append(r)
        elif "grid" in r:
            rows.append(r)
    return hdr, rows, contacts


def sibling(path, kind):
    """race_out / feed written for the same race: the closest timestamp within 3 minutes."""
    m = re.search(r"diag_race_(\d{8})_(\d{6})", os.path.basename(path))
    if not m:
        return None
    day, hms = m.group(1), m.group(2)
    stamp = int(hms[:2]) * 3600 + int(hms[2:4]) * 60 + int(hms[4:])
    if kind == "race_out":
        # written at the END of the race: match by the label in the file name instead of the timestamp
        lab = re.sub(r"^diag_race_\d{8}_\d{6}_", "", os.path.basename(path)).replace(".jsonl", "")
        lab = lab.split("_", 1)[1] if "_" in lab else lab      # drop the track prefix
        cands = [c for c in glob.glob(os.path.join(HERE, "harness_results", f"race_out_{day}_*.json")) if c.endswith(f"_{lab}.json")]
        return max(cands, key=os.path.getmtime) if cands else None
    else:
        cands = glob.glob(os.path.join(DOCS, "verve_feed", f"{day}_*.jsonl"))
    best, bd = None, 181
    for c in cands:
        mm = re.search(rf"{day}_(\d{{6}})", os.path.basename(c))
        if not mm:
            continue
        h = mm.group(1)
        t = int(h[:2]) * 3600 + int(h[2:4]) * 60 + int(h[4:])
        d = abs(t - stamp)
        if d < bd:
            best, bd = c, d
    return best


def build(path, label="Race A", ref_format=False):
    """ref_format: only the lines a real timing sheet can give (no damage counts, no first-30-s line): for a Turing
    vote against tools/ref_card_f1.py cards."""
    hdr, rows, contacts = load_diag(path)
    if not rows or len(rows) < 3:
        return None
    n = rows[0]["cars"]
    models = [c["model"] for c in hdr["cars"]] if hdr else []
    track = (hdr or {}).get("track", "")
    track_name = next((v for k, v in TRACK_WORDS.items() if track.startswith(k)), track.split("/")[0] or "circuit")
    cls = class_of(models)
    t0 = rows[0]["t"]
    last = rows[-1]
    leader_laps = last["leaderLap"]
    duration = last["t"] - t0

    # lap chart: the classification when the LEADER completes each lap (the first snapshot at leaderLap >= L). Reading
    # each car at its own lap count put lapped cars into the top 8 after the flag (a critic caught it, 2026-09-21).
    chart = {}   # lap -> {pos: car id}
    for L in range(1, leader_laps + 1):
        r = next((r for r in rows if r["leaderLap"] >= L), None)
        if r:
            chart[L] = {c["pos"]: c["i"] for c in r["grid"] if not c["ret"] and not c.get("park")}
    laps_done = sorted(chart)
    # anonymous car names: by grid slot -> "#n" is fine (a car number), keep 1..n
    def name(i): return f"#{i + 1}"

    # results at the flag
    fin = sorted((c for c in last["grid"]), key=lambda c: c["pos"])
    running = [c for c in fin if not c["ret"] and not c.get("park")]
    retired = [c for c in fin if c["ret"] or c.get("park")]
    # gaps at the flag from the feed if present, else from spline distance x an approximate lap time
    feed = sibling(path, "feed")
    gaps = {}
    overtakes, lead_changes, feed_incidents = [], [], []
    if feed:
        try:
            frows = [json.loads(l) for l in open(feed, encoding="utf-8") if l.strip()]
            states = [r for r in frows if r.get("type") == "state"]
            if states:
                # the last state in which the leader is still on track (after the flag the gaps read the pit lane)
                top = states[-1]["leader_lap"]
                pre = [st for st in states if st["leader_lap"] == top and any(not c["pit"] for c in st["cars"] if c["pos"] == 1)]
                for c in (pre[-1] if pre else states[-1])["cars"]:
                    gaps[c["i"]] = c.get("gap_ahead_s")
            overtakes = [r for r in frows if r.get("type") == "overtake"]
            lead_changes = [r for r in frows if r.get("type") == "lead_change"]
            feed_incidents = [r for r in frows if r.get("type") == "incident"]
        except (OSError, ValueError):
            pass

    # per-lap times from race_out
    ro = sibling(path, "race_out")
    lap_times = {}
    if ro:
        try:
            sess = json.load(open(ro, encoding="utf-8"))["sessions"][-1]
            for lp in sess.get("laps", []):
                if lp.get("time", 0) > 10000:
                    lap_times.setdefault(lp["car"], []).append(lp["time"] / 1000)
        except (OSError, ValueError, KeyError):
            pass

    # incidents per lap (damage jumps, AI cars, as race_metrics)
    inc_by_lap = {}
    prev = {}
    for r in rows:
        for c in r["grid"]:
            p = prev.get(c["i"])
            if p and not c["pit"] and (c.get("dmg", 0) - p.get("dmg", 0) >= 8):
                inc_by_lap[p["lap"]] = inc_by_lap.get(p["lap"], 0) + 1
            prev[c["i"]] = c
    # stopped on track and rejoined (a stationary spell >= 20 s off the pits, before the flag)
    t_end = max((r["t"] for a, r in zip(rows, rows[1:]) if r["leaderLap"] != a["leaderLap"]), default=last["t"] + 1)
    stopped = set()
    for i in range(n):
        run = 0
        for r in rows:
            if r["t"] >= t_end:
                break
            c = next(x for x in r["grid"] if x["i"] == i)
            if c["spd"] < 3 and not c["pit"] and r["t"] - t0 > 20:
                run += 8
                if run >= 16:
                    stopped.add(i)
            else:
                run = 0
    # first thirty seconds: how many cars changed position
    t_move = next((r["t"] for r in rows if any(c["spd"] > 30 for c in r["grid"])), t0)
    p_start = {c["i"]: c["pos"] for c in rows[0]["grid"]}
    r30 = next((r for r in rows if r["t"] - t_move >= 30), None)
    moved30 = sum(1 for c in (r30["grid"] if r30 else []) if c["pos"] != p_start.get(c["i"])) if r30 else None
    # pit stops: entries into the pit lane after lap 1
    pits = 0
    was = {}
    for r in rows:
        for c in r["grid"]:
            if c["pit"] and not was.get(c["i"]) and c["lap"] >= 1 and r["t"] < t_end:
                pits += 1
            was[c["i"]] = c["pit"]

    # ---- the card ----
    out = []
    out.append(f"# {label}")
    out.append(f"{cls}, {track_name}. {n} cars. {leader_laps} laps completed by the leader in {duration // 60:.0f} min {duration % 60:.0f} s.")
    out.append("")
    out.append("## Lap chart (top 8, car numbers)")
    show = [L for L in laps_done if L >= 1][:14]
    out.append("| lap | " + " | ".join(f"P{p}" for p in range(1, 9)) + " |")
    out.append("|---|" + "---|" * 8)
    for L in show:
        row = chart[L]
        out.append(f"| {L} | " + " | ".join(name(row[p]) if p in row else "-" for p in range(1, 9)) + " |")
    out.append("")
    out.append("## At the flag")
    lines = []
    cum = 0.0      # gap_ahead is to the car in front: accumulate into a gap to the leader
    for c in running[:12]:
        g = gaps.get(c["i"])
        if isinstance(g, (int, float)) and c["pos"] > 1:
            cum += g
        gtxt = "leader" if c["pos"] == 1 else (f"+{cum:.1f} s" if isinstance(g, (int, float)) else "")
        best = min(lap_times[c["i"]]) if c["i"] in lap_times else None
        lines.append(f"P{c['pos']} {name(c['i'])} {gtxt}" + (f", best lap {best:.1f} s" if best else ""))
    out.append("; ".join(lines) if lines else "(no classification)")
    if retired:
        out.append(f"Retired: {len(retired)} ({', '.join(name(c['i']) for c in retired)}).")
    else:
        out.append("Retired: none.")
    out.append("")
    out.append("## What happened")
    inc_total = sum(inc_by_lap.values())
    inc_txt = ", ".join(f"lap {L}: {k}" for L, k in sorted(inc_by_lap.items())) if inc_by_lap else "none"
    out.append(f"Cars taking damage (incidents): {inc_total} - {inc_txt}.")
    if contacts:
        # contact traces are per car and per damage jump; cluster them into touches (same 3 s, same 20 m of spline)
        touches = []
        for c in sorted(contacts, key=lambda c: c["t"]):
            for tch in touches:
                if abs(c["t"] - tch["t"]) <= 3 and abs(c.get("spline", 0) - tch["spline"]) <= 15:
                    tch["cars"].add(c["car"]); break
            else:
                touches.append({"t": c["t"], "spline": c.get("spline", 0), "lap": c.get("lap", 0), "cars": {c["car"]}})
        c_laps = {}
        for tch in touches:
            c_laps[tch["lap"]] = c_laps.get(tch["lap"], 0) + 1
        multi = sum(1 for tch in touches if len(tch["cars"]) >= 3)
        out.append(f"Car-to-car contacts (each touch once): {len(touches)} - " + ", ".join(f"lap {L}: {k}" for L, k in sorted(c_laps.items())) + f"; touches involving three or more cars: {multi}.")
    out.append(f"Cars that stopped on track and rejoined: {len(stopped)}.")
    if overtakes:
        # net passes: a swap straight back within 30 s (side by side, or a re-pass) is not two overtakes. The feed logs
        # every position change at 1 Hz, which inflated the count ~30 % (2026-09-21).
        last_pair, net, swap_backs = {}, [], 0
        for o in overtakes:
            k, rk = (o["car"], o["over"]), (o["over"], o["car"])
            if rk in last_pair and o["t"] - last_pair[rk] < 30:
                swap_backs += 1
                last_pair.pop(rk, None)
                continue
            last_pair[k] = o["t"]
            net.append(o)
        overtakes = net
        ov_laps = {}
        for o in overtakes:
            lap_guess = min(leader_laps, int(o.get("t", 0) / max(1.0, duration / max(1, leader_laps))) + 1)
            ov_laps[lap_guess] = ov_laps.get(lap_guess, 0) + 1
        zones = {}
        for o in overtakes:
            z = "first third" if o.get("spline", 0) < 0.34 else ("middle" if o.get("spline", 0) < 0.67 else "last third")
            zones[z] = zones.get(z, 0) + 1
        out.append(f"Overtakes for position: {len(overtakes)} (" + ", ".join(f"lap {L}: {k}" for L, k in sorted(ov_laps.items())) + "); where: " + ", ".join(f"{z} of the lap {k}" for z, k in zones.items()) + f". Positions swapped straight back within 30 s (not counted above): {swap_backs}.")
        out.append(f"Lead changes: {len(lead_changes)}.")
    else:
        pos_changes = 0
        pv = {}
        for r in rows:
            for c in r["grid"]:
                if c["i"] in pv and c["pos"] < pv[c["i"]] and not c["pit"]:
                    pos_changes += 1
                pv[c["i"]] = c["pos"]
        out.append(f"Position gains recorded: {pos_changes}.")
    if moved30 is not None:
        out.append(f"First thirty seconds: {moved30} of {n} cars changed position.")
    out.append(f"Pit stops: {pits}.")
    if lap_times:
        meds = sorted(statistics.median(v) for v in lap_times.values() if len(v) >= 2)
        if len(meds) >= 4:
            out.append(f"Lap-time spread: median laps from {meds[0]:.1f} s (quickest car) to {meds[len(meds)//2]:.1f} s (mid-field) to {meds[-1]:.1f} s (slowest).")
    if ref_format:
        drop = ("Cars taking damage", "Car-to-car contacts", "Cars that stopped", "First thirty seconds", "Retired:")
        out = [l for l in out if not l.startswith(drop)]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("diag")
    ap.add_argument("--out")
    ap.add_argument("--label", default="Race A")
    ap.add_argument("--ref-format", action="store_true")
    a = ap.parse_args()
    card = build(a.diag, a.label, a.ref_format)
    if card is None:
        print("(too few snapshots)"); return
    if a.out:
        open(a.out, "w", encoding="utf-8").write(card); print("wrote", a.out)
    else:
        print(card)


if __name__ == "__main__":
    main()
