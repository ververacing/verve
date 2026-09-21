"""One-line opening-lap tally for a diag file: cars hit on lap 0-1, heavy hits, lap-1 position changes, repairs."""
import json, sys
f = sys.argv[1]
snaps = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip() and '"grid"' in l]
if len(snaps) < 5:
    print("too few snapshots"); sys.exit()
n = len(snaps[0]["grid"]); prev = {}; hit = set(); heavy = set(); gains = 0
for r in snaps:
    for c in r["grid"]:
        p = prev.get(c["i"])
        if p and c["lap"] <= 1:
            d = c["dmg"] - p["dmg"]
            if d >= 8: hit.add(c["i"])
            if d >= 30: heavy.add(c["i"])
            if c["pos"] < p["pos"] and not c["pit"]: gains += 1
        prev[c["i"]] = c
# START GAIN: places the autopilot player (car 0) gains in the first 30 s of movement, from its grid slot. A human on a
# mid-grid slot gains 2-3 in real racing; "15" was an OverTake user's complaint about a too-cautious AI launch (2026-09-21).
t_move = next((r["t"] for r in snaps if any(c["spd"] > 30 for c in r["grid"])), None)
start_pos = next((c["pos"] for c in snaps[0]["grid"] if c["i"] == 0), None)
pos30 = None
if t_move is not None:
    for r in snaps:
        if r["t"] - t_move >= 30:
            pos30 = next((c["pos"] for c in r["grid"] if c["i"] == 0), None); break
start_gain = (start_pos - pos30) if (start_pos and pos30) else None
lab = f.split("_", 4)[-1].replace(".jsonl", "")
print(f"{lab}: lap-1 contact {len(hit)}/{n} (heavy {len(heavy)}), lap-1 position changes {gains}, repairs {snaps[-1].get('crashRepairs', 0)}, player start gain (30 s) {start_gain if start_gain is not None else '-'} from P{start_pos}")
