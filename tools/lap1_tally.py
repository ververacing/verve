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
lab = f.split("_", 4)[-1].replace(".jsonl", "")
print(f"{lab}: lap-1 contact {len(hit)}/{n} (heavy {len(heavy)}), lap-1 position changes {gains}, repairs {snaps[-1].get('crashRepairs', 0)}")
