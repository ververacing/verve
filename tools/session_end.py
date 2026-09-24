"""Did AC actually end this race, or did the harness score it at the budget?

PC #2 spotted it on 2026-09-24: a race AC closes boxes the whole field at once, so the feed's 1 Hz state rows show
nearly every car with pit = true within a few seconds of the leader finishing. A race AC never closes has the field
still circulating past the requested distance - 22 of 29 races here that day had the leader complete MORE laps than
asked for, and those races also write no race_out.

It matters because an overrun race is not the distance we think we tested: incidents, contacts and reposition
attempts all accumulate over the extra lap, so every absolute figure quoted against reality is computed over a
distance nobody chose. A/B arms that both overrun are still comparable with each other.

This reads the feeds we already have, so it classifies the whole back catalogue with no new races.

    python tools/session_end.py                # classify every feed
    python tools/session_end.py --glob baku    # just one track
"""
import argparse
import glob
import json
import os

FEED_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_feed")
ARCHIVE = "D:/verve_archive/verve_feed"
BOXED_FRAC = 0.8          # this share of the field in the pits at once = AC closed the session


def classify(path):
    last = None
    peak_lap = 0
    boxed_peak = 0.0
    cars = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if (d.get("type") or d.get("e")) != "state":
                continue
            grid = d.get("cars") or []
            if not grid:
                continue
            cars = max(cars, len(grid))
            peak_lap = max(peak_lap, d.get("leader_lap") or 0)
            inpit = sum(1 for c in grid if c.get("pit"))
            boxed_peak = max(boxed_peak, inpit / len(grid))
            last = d
    if last is None:
        return None
    return {
        "file": os.path.basename(path),
        "cars": cars,
        "leader_lap": peak_lap,
        "boxed_peak": boxed_peak,
        "ended": boxed_peak >= BOXED_FRAC,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glob", default="")
    a = ap.parse_args()
    paths = []
    for d in (FEED_DIR, ARCHIVE):
        paths += sorted(glob.glob(os.path.join(d, f"*{a.glob}*.jsonl")))
    ended = over = 0
    print(f"{'feed':<36} {'cars':>4} {'leader':>7} {'max boxed':>10}  verdict")
    for p in paths:
        v = classify(p)
        if not v:
            continue
        if v["ended"]:
            ended += 1
        else:
            over += 1
        print(f"{v['file']:<36} {v['cars']:>4} {v['leader_lap']:>7} {v['boxed_peak']:>9.0%}  "
              f"{'ended' if v['ended'] else 'NEVER CLOSED'}")
    total = ended + over
    if total:
        print(f"\n{ended} of {total} races were closed by AC ({100*ended/total:.0f}%); "
              f"{over} ran on and were scored at the harness budget")


if __name__ == "__main__":
    main()
