"""How long a faster driver stays stuck behind a slower one before getting past.

    python tools/held_up.py diag_race_*.jsonl --profiles all=arch_midfield,0=arch_rookie,...,12..17=arch_veteran

From the 8 s snapshots: an EPISODE starts when car A (higher pace tier) is within GAP_M behind car B (lower tier) on the
same lap, and ends when A is ahead of B (pass), A drops back beyond 2x GAP_M (gave up / fell away), or the race ends.
Reports per episode length and the share of episodes that end in a pass; per tier pair. Pace tiers: rookie < midfield <
veteran/star. The owner's eye test 2026-09-17: "veterans get held up by slower cars; obvious overtakes happen too slowly".
"""
import argparse, glob, json, os, re, statistics as st
from collections import defaultdict

TIER = {"arch_rookie": 0, "arch_midfield": 1, "arch_veteran": 2}
GAP_M = 40.0

def parse_profiles(s, n):
    out = {}
    if not s: return out
    for part in s.split(","):
        k, v = part.split("=")
        t = TIER.get(v, 2)   # named stars count as veterans
        if k == "all":
            for i in range(n): out[i] = t
        elif ".." in k:
            a, b = k.split(".."); 
            for i in range(int(a), int(b) + 1): out[i] = t
        else:
            out[int(k)] = t
    return out

def load(p):
    hdr, snaps = None, []
    for line in open(p, encoding="utf-8"):
        if line.startswith('{"hdr"'): hdr = json.loads(line)
        elif line.startswith('{"t"'): snaps.append(json.loads(line))
    return hdr, snaps

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+"); ap.add_argument("--profiles", required=True); ap.add_argument("--gap", type=float, default=GAP_M)
    a = ap.parse_args()
    paths = []
    for f in a.files: paths += glob.glob(f) or [f]
    for p in sorted(paths, key=os.path.getmtime):
        hdr, snaps = load(p)
        if not hdr or len(snaps) < 3: continue
        n = len(hdr["cars"]); tier = parse_profiles(a.profiles, n)
        tl = 7000.0
        m = re.search(r"_(spa|monza|ks_barcelona|ks_silverstone|ks_brands_hatch|ks_zandvoort|ks_nurburgring)", p)
        tl = {"spa": 7004, "monza": 5793, "ks_barcelona": 4655, "ks_silverstone": 5891, "ks_brands_hatch": 3908, "ks_zandvoort": 4252, "ks_nurburgring": 5148}.get(m.group(1) if m else "", 7000)
        open_ep = {}   # (A,B) -> start t
        episodes = []  # (A,B, seconds, outcome)
        for s in snaps:
            g = {c["i"]: c for c in s["grid"]}
            t = s["t"]
            for A, ca in g.items():
                if ca["ret"] or ca["pit"]: continue
                for B, cb in g.items():
                    if A == B or cb["ret"] or cb["pit"]: continue
                    if tier.get(A, 1) <= tier.get(B, 1): continue
                    # progress of A relative to B in metres (A behind B = positive gap)
                    dl = (cb["lap"] + cb["spline"] / 1000.0) - (ca["lap"] + ca["spline"] / 1000.0)
                    gap_m = dl * tl
                    key = (A, B)
                    if key in open_ep:
                        if gap_m < -5:           # A is now ahead
                            episodes.append((A, B, t - open_ep.pop(key), "pass"))
                        elif gap_m > 2 * a.gap:  # fell away
                            episodes.append((A, B, t - open_ep.pop(key), "fell_back"))
                    elif 0 < gap_m < a.gap and ca["lap"] >= 1:
                        open_ep[key] = t
        for key, t0 in open_ep.items():
            episodes.append((key[0], key[1], snaps[-1]["t"] - t0, "race_end"))
        label = os.path.basename(p)[len("diag_race_YYYYMMDD_HHMMSS_"):-6]
        by = defaultdict(list)
        for A, B, sec, out in episodes: by[(tier[A], tier[B])].append((sec, out))
        print("== %s: %d episodes (faster driver within %d m of a slower one, from lap 1)" % (label, len(episodes), a.gap))
        names = {0: "rookie", 1: "midfield", 2: "veteran"}
        for (ta, tb), eps in sorted(by.items()):
            secs = [e[0] for e in eps]; passes = [e for e in eps if e[1] == "pass"]
            held = [e[0] for e in passes]
            print("   %-8s behind %-8s: %3d episodes, %3d passed (%.0f%%), time to pass median %4.0f s (max %4.0f), %d unresolved at the flag, %d fell back" % (
                names[ta], names[tb], len(eps), len(passes), 100.0 * len(passes) / max(1, len(eps)),
                st.median(held) if held else 0, max(held) if held else 0,
                sum(1 for e in eps if e[1] == "race_end"), sum(1 for e in eps if e[1] == "fell_back")))

if __name__ == "__main__":
    main()
