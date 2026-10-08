"""How far apart does recovery SET CARS DOWN? The scorer for the gateSafe stagger question.

Every other recovery metric we have answers "did the drop succeed" (drops_ok), and on our own machines the answer is
always yes - 81 of 81 on PC #2 on 8 Oct, 70 of 70 pooled across both builds. That is why six hypotheses died in one
day: we were measuring the wrong thing. The thing that IS visibly wrong is WHERE cars land. gateSafe walks back from
the last timing split to "the first straight-ish spot", which is deterministic, and it adds its per-car 0-45 m stagger
only on the gate-first path - so on the ordinary path every gated car lands on ONE spline. Traced 8 Oct: three cars
placed at spline 0.305 / lat +0.20 in the same instant, a 4-car pile all landing at 0.303-0.307, and every reposition
in two imola races at 0.299-0.311 regardless of where the car had stopped.

So this reads the diag drop windows and reports, per race and pooled per arm:
  near_at_landing   - metres to the NEAREST car at the moment of the drop. THE PRIMARY NUMBER. Stacking is a small
                      `near`; the fix must raise it. (diag's `near` is to the nearest ANY car, parked ones included.)
  landing splines   - the distinct spots used, their range and spread. The mechanism check: the stagger should widen
                      this by up to 45 m (9 units of spline/1000 on imola's 4,909 m).
  co-landings       - pairs of cars set down within CO_SPLINE units and CO_SECONDS of each other: the actual pile-up
                      events, which is what a player sees.

diag logs a drop row only while the verdict is pending (d.ok == nil), several rows per drop as the car ages, so a
landing is the row with the smallest `age` in each episode. A new episode starts when `age` stops increasing.

Usage:
  python tools/drop_spread.py                                  # every diag file, grouped by label
  python tools/drop_spread.py --labels stag_off,stag_on        # A/B: pool by label prefix and compare arms
  python tools/drop_spread.py --files diag_race_*imola*.jsonl
"""
import argparse
import glob
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)

CO_SPLINE = 3       # units of spline/1000 (~15 m on imola) - "the same spot" for a co-landing
CO_SECONDS = 10     # within this long of each other
# imola; only used to print metres alongside spline units. Pass --track-len for another track.
DEFAULT_TRACK_LEN = 4909.0


def episodes(rows):
    """Split one car's drop rows into episodes; yield the row with the smallest age in each (the landing)."""
    cur = []
    prev_age = None
    for r in rows:
        age = r.get("age", 0)
        if prev_age is not None and age < prev_age:   # age reset -> a new drop
            if cur:
                yield min(cur, key=lambda x: x.get("age", 0))
            cur = []
        cur.append(r)
        prev_age = age
    if cur:
        yield min(cur, key=lambda x: x.get("age", 0))


def read_race(path):
    """-> (label, [landing rows]). Label comes from the filename: diag_race_<stamp>_<track>_<label>.jsonl"""
    per_car = {}
    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or '"drop"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("ev") != "drop":
            continue
        per_car.setdefault(o.get("car"), []).append(o)
    landings = []
    for car, rows in sorted(per_car.items()):
        for land in episodes(rows):
            landings.append(land)
    landings.sort(key=lambda r: r.get("t", 0))
    base = os.path.basename(path)
    label = base.replace("diag_race_", "").replace(".jsonl", "")
    parts = label.split("_")
    label = "_".join(parts[3:]) if len(parts) > 3 else label   # drop stamp (date_time) and track
    return label, landings


def co_landings(landings):
    """Pairs set down at the same spot within CO_SECONDS - the pile-up events."""
    out = []
    for a in range(len(landings)):
        for b in range(a + 1, len(landings)):
            la, lb = landings[a], landings[b]
            if abs(lb.get("t", 0) - la.get("t", 0)) > CO_SECONDS:
                break   # sorted by t
            d = abs(lb.get("spline", 0) - la.get("spline", 0))
            if d <= CO_SPLINE:
                out.append((la.get("car"), lb.get("car"), la.get("spline"), d,
                            abs(lb.get("t", 0) - la.get("t", 0))))
    return out


def summarise(name, races, track_len, gated=None):
    """races: list of (label, landings).

    gated=True/False selects only gated / only ungated drops. This split is NOT optional for the stagger question:
    gateSafe converges only GATED drops onto one spline, and on 8 Oct the same cell read "12 distinct spots over
    1,429 m" with 13 landings and "3 spots over 15 m" with 4 - because the many-landing races were mostly ungated
    drops that the gate never touched. Pooling the two measures noise. Races from before diag carried `g` have no
    flag at all; they are reported as "unknown" rather than silently counted as ungated.
    """
    landings = [l for _, ls in races for l in ls]
    if gated is not None:
        if any("g" not in l for l in landings):
            n_unknown = sum(1 for l in landings if "g" not in l)
            print("  %-22s %d of %d landings predate the `g` flag - rerun on new races for a gated split"
                  % (name, n_unknown, len(landings)))
            return None
        landings = [l for l in landings if bool(l["g"]) == gated]
        races = [(lab, [l for l in ls if bool(l.get("g")) == gated]) for lab, ls in races]
    if not landings:
        print("  %-22s no landings" % name)
        return None
    near = [l["near"] for l in landings if l.get("near") is not None]
    spl = [l["spline"] for l in landings if l.get("spline") is not None]
    co = sum(len(co_landings(ls)) for _, ls in races)
    m_per_unit = track_len / 1000.0
    # how far the gate MOVED each car: |landed - requested|, only where both are known
    moved = [abs(l["spline"] - l["gs"]) * m_per_unit
             for l in landings if l.get("gs", -1) >= 0 and l.get("spline") is not None]
    row = {
        "races": len(races), "landings": len(landings),
        "near_med": statistics.median(near) if near else float("nan"),
        "near_min": min(near) if near else float("nan"),
        "near_lt10": sum(1 for n in near if n < 10),
        "spots": len(set(spl)),
        "spl_range": (max(spl) - min(spl)) if spl else 0,
        "spl_sd": statistics.pstdev(spl) if len(spl) > 1 else 0.0,
        "co": co,
    }
    row["gate_moved_med"] = statistics.median(moved) if moved else float("nan")
    print("  %-22s races %d  landings %3d | near: med %4.0f m  min %3.0f m  <10 m %2d (%2.0f%%) | "
          "spots %3d  range %3d u (%4.0f m)  sd %4.1f u | co-landings %d%s"
          % (name, row["races"], row["landings"], row["near_med"], row["near_min"], row["near_lt10"],
             100.0 * row["near_lt10"] / max(1, len(near)), row["spots"], row["spl_range"],
             row["spl_range"] * m_per_unit, row["spl_sd"], row["co"],
             ("  | gate moved med %4.0f m" % row["gate_moved_med"]) if moved else ""))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--labels", default=None, help="comma-separated label PREFIXES to pool as arms")
    ap.add_argument("--track-len", type=float, default=DEFAULT_TRACK_LEN)
    ap.add_argument("--per-race", action="store_true", help="also print every race")
    a = ap.parse_args()

    pats = a.files or [os.path.join(VERVE, "diag_race_*.jsonl")]
    files = []
    for p in pats:
        files.extend(glob.glob(p) if any(c in p for c in "*?[") else [p])
    files = sorted(set(files))
    if not files:
        print("no diag files matched", file=sys.stderr)
        return 1

    races = []
    for f in files:
        label, landings = read_race(f)
        if landings:
            races.append((label, landings))
    if not races:
        print("no drop windows in %d file(s) - nothing was repositioned" % len(files))
        return 0

    print("%d race(s) with repositions, %d landings total. near = metres to the nearest car AT THE DROP.\n"
          % (len(races), sum(len(l) for _, l in races)))

    if a.labels:
        arms = [s.strip() for s in a.labels.split(",") if s.strip()]
        print("ARMS - GATED DROPS ONLY (the only ones gateSafe can move; see summarise())")
        rows = {}
        for arm in arms:
            sel = [(lab, ls) for lab, ls in races if lab.startswith(arm)]
            rows[arm] = summarise(arm, sel, a.track_len, gated=True)
        print("\nARMS - ungated drops (should be UNCHANGED by the switch; this is the control)")
        for arm in arms:
            sel = [(lab, ls) for lab, ls in races if lab.startswith(arm)]
            summarise(arm, sel, a.track_len, gated=False)
        print("\nARMS - all drops pooled (for continuity with earlier notes)")
        for arm in arms:
            sel = [(lab, ls) for lab, ls in races if lab.startswith(arm)]
            summarise(arm, sel, a.track_len)
        if len(arms) == 2 and all(rows.values()):
            x, y = rows[arms[0]], rows[arms[1]]
            print("\nDELTA (%s -> %s): near med %+.0f m | near <10 m %+.0f pp | distinct spots %+d | "
                  "range %+.0f m | co-landings %+d"
                  % (arms[0], arms[1], y["near_med"] - x["near_med"],
                     100.0 * (y["near_lt10"] / max(1, y["landings"]) - x["near_lt10"] / max(1, x["landings"])),
                     y["spots"] - x["spots"],
                     (y["spl_range"] - x["spl_range"]) * a.track_len / 1000.0,
                     y["co"] - x["co"]))
            print("Read: the fix should RAISE near med, LOWER near <10 %, RAISE distinct spots, and LOWER co-landings.")
        print()

    if a.per_race or not a.labels:
        print("PER RACE")
        for lab, ls in sorted(races):
            summarise(lab, [(lab, ls)], a.track_len)
    return 0


if __name__ == "__main__":
    sys.exit(main())
