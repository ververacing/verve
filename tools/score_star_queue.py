"""Score a star queue on LAPS COMPLETED first, finishing position second.

    python tools/score_star_queue.py suspfix [--star 17] [--res DIR]

Why laps first: on dev016 in F1 the star's median finish is P17 of 18, and the reason is that it does not
complete the distance - 16-17 of 18 cars finish on the leader's lap and the star is the one that does not.
Finishing position reports that as "lost the race", which is how it was misread for weeks.

Comparator is the FIELD MEDIAN lap count, not the leader's, per PC #2's catch: a snapshot taken as the leader
crosses makes every non-winner look a lap down. The median is immune and costs nothing.

Laps come from tools/racelaps.py: AC's race_out, else Verve's feed. (Until 2026-10-10 this read race_out only, and AC
writes race_out with no laps in 10-40 % of races - those star races were silently missing; at least two on 10-08.) A
feed-sourced race's finish is the live order when the feed stopped, not AC's classification: marked "~".
"""
import argparse
import collections
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from racelaps import labels, race_laps  # noqa: E402


def score(label, star, res):
    r = race_laps(label, res)
    if not r:
        return None
    laps = {car: max(idx for idx, _t, _c in ls) for car, ls in r["laps"].items() if ls}
    if not laps:
        return None
    rr = r["order"]
    med = statistics.median(laps.values())
    return {"star_laps": laps.get(star), "field_median": med, "leader": max(laps.values()),
            "finish": (rr.index(star) + 1 if star in rr else None), "field": len(rr), "src": r["src"],
            "deficit": (laps.get(star) if laps.get(star) is not None else 0) - med}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--star", type=int, default=17)
    ap.add_argument("--res", default=os.path.join(HERE, "harness_results"))
    a = ap.parse_args()

    rows = []
    for label in labels(a.prefix, a.res):
        r = score(label, a.star, a.res)
        if r:
            rows.append((label, r))
    if not rows:
        sys.exit("no scored races matching %r yet" % a.prefix)

    print("STAR QUEUE %r - LAPS COMPLETED FIRST  (star = AI slot %d)\n" % (a.prefix, a.star))
    print("  %-30s %-10s %-13s %-9s %s" % ("race", "star laps", "field median", "deficit", "finish"))
    for label, r in rows:
        print("  %-30s %-10s %-13g %-+9g %sP%s of %s  (%s)"
              % (label[:30], r["star_laps"], r["field_median"], r["deficit"], "~" if r["src"] == "feed" else "",
                 r["finish"], r["field"], r["src"]))

    arms = collections.defaultdict(list)
    for label, r in rows:
        arms[re.sub(r"_\d+$", "", label)].append(r)
    print("\nBY ARM")
    print("  %-26s %-4s %-14s %-16s %s" % ("arm", "n", "full distance", "median deficit", "median finish"))
    for arm in sorted(arms):
        v = arms[arm]
        full = sum(1 for r in v if r["deficit"] >= 0)
        fin = [r["finish"] for r in v if r["finish"]]
        print("  %-26s %-4d %-14s %-+16g P%s"
              % (arm, len(v), "%d of %d" % (full, len(v)),
                 statistics.median([r["deficit"] for r in v]),
                 ("%.0f" % statistics.median(fin)) if fin else "-"))
    print("\n  PRIMARY: 'full distance' - races where the star finished on the field's median lap or better.")
    print("  A star that does not complete the distance finishes last however well it was climbing.")
    print("  ~ = finish from the feed's live order (AC's race_out had no laps).")


if __name__ == "__main__":
    main()
