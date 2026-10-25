"""THE ONE PLACE A FINISHING POSITION COMES FROM. Added 2026-10-25.

WHY THIS EXISTS. The diag's last snapshot holds the LIVE order, and once the leader takes the chequer AC re-sorts
it so a car still on the previous lap falls behind everyone already finished. The diag also stops mid-final-lap.
So last-snapshot `pos` is not a finish. It has now cost three wrong readings:
  - LESSONS METHOD line (undated): "it misplaced a P8 as P14".
  - as151 re-score 2026-10-18: "MY POSITION FIGURES WERE READ FROM THE WRONG FIELD" - one race read P6 on track
    and P18 classified.
  - s71b stage 2, 2026-10-25: fmsc_x10_1's star read P16 from the last snapshot and classified P6. TEN PLACES.
Knowing it twice did not prevent the third, so the guard is mechanical: a tool that wants a finish calls here.

raceResult is AC's classification, ordered by finishing order, and IT CONTAINS SLOT 0 (the autopilot player).
An AI place must therefore count only AI entries ahead of the car, which is what ai_place() does.

Self-test: python tools/classify.py --selftest
"""
import glob
import io
import json
import os
import sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_RESULTS = os.path.join(_TOOLS, "harness_results")


def _session(label):
    # THE TWO FILENAME CONVENTIONS DO NOT CARRY THE SAME LABEL, which silently returned None on the first
    # functional test: a diag is `diag_race_<stamp>_<track>_<label>.jsonl` so callers deriving a label from it
    # hand us "monza_fmsc_x10_1", while race_out is `race_out_<stamp>_<label>.json` = "fmsc_x10_1". So try the
    # label as given, then strip leading tokens one at a time. A compile check passed this; only running it caught it.
    f = []
    cand = label
    while cand:
        f = sorted(glob.glob(os.path.join(_RESULTS, "race_out_*%s.json" % cand)))
        if f or "_" not in cand:
            break
        cand = cand.split("_", 1)[1]
    if not f:
        return None
    try:
        d = json.load(io.open(f[-1], encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    s = d.get("sessions") or []
    return s[0] if s else None


def race_result(label):
    """AC's classification as a list of car indices in finishing order, or None if there is no race_out.

    None means THE ARTEFACT IS MISSING, which is not the same as a bad race: a row can run a complete, clean
    race and still write no race_out (s71b's fmsc_x10_2 - 16 laps, 18 running at the end, 0 retired).
    """
    s = _session(label)
    rr = s.get("raceResult") if s else None
    if not rr:
        return None
    return [int(x) for x in rr]


def laps_count(label):
    s = _session(label)
    return s.get("lapsCount") if s else None


def ai_place(label, car):
    """`car`'s classified position counting ONLY AI cars ahead of it (slot 0 excluded). None if unavailable.

    A -1 in raceResult is a car AC lost from the classification; it is not an AI car and is not counted ahead.
    """
    rr = race_result(label)
    if not rr or car not in rr:
        return None
    return 1 + sum(1 for c in rr[:rr.index(car)] if c >= 1)


def ai_places(label):
    """{car: ai_place} for every AI car in the classification."""
    rr = race_result(label)
    if not rr:
        return {}
    return {c: ai_place(label, c) for c in rr if c >= 1}


def live_order_is_trustworthy(snapshot, label):
    """True while the live `pos` field still means what it looks like: before the leader takes the chequer."""
    lc = laps_count(label)
    return not (lc and (snapshot.get("leaderLap") or 0) >= lc)


def _selftest():
    """Made to FAIL first, per CLAUDE.md rule 4: each case asserts a behaviour and a mutant that breaks it."""
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print("  %-58s got %-18s want %-18s %s" % (name, got, want, "OK" if good else "*** FAILED ***"))

    # slot 0 must NOT count as a car ahead. [1,2,0,3,17,...] -> star has 3 AI ahead, so AI place 4, NOT 5.
    import types
    saved = globals()["race_result"]
    globals()["race_result"] = lambda lab: [1, 2, 0, 3, 17, 5]
    check("slot 0 ahead is not counted (the real x10_3 shape)", ai_place("x", 17), 4)
    globals()["race_result"] = lambda lab: [0, 1, 2, 3, 17]
    check("slot 0 leading is not counted", ai_place("x", 17), 4)
    globals()["race_result"] = lambda lab: [17, 1, 2]
    check("a winning star is P1", ai_place("x", 17), 1)
    globals()["race_result"] = lambda lab: [-1, 1, 17]
    check("a lost car (-1) is not counted ahead", ai_place("x", 17), 2)
    globals()["race_result"] = lambda lab: [1, 2, 3]
    check("a car absent from the classification is None", ai_place("x", 17), None)
    globals()["race_result"] = lambda lab: None
    check("no race_out is None, not 0 and not a guess", ai_place("x", 17), None)

    # THE MUTANT: the naive version that counts every entry ahead. It must DISAGREE on the slot-0 case,
    # otherwise this selftest proves nothing about the thing it exists to prevent.
    globals()["race_result"] = lambda lab: [1, 2, 0, 3, 17, 5]
    naive = 1 + [1, 2, 0, 3, 17, 5].index(17)
    print("  %-58s naive=%-5s correct=%-5s %s"
          % ("MUTANT: counting slot 0 as a rival must differ", naive, ai_place("x", 17),
             "OK" if naive != ai_place("x", 17) else "*** VACUOUS - the case cannot catch the bug ***"))
    ok &= naive != ai_place("x", 17)
    globals()["race_result"] = saved
    print("\nSELFTEST %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    for lab in sys.argv[1:]:
        print(lab, "->", ai_places(lab))
