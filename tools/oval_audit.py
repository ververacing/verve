"""Which installed layouts does `detectOval` call an oval? Offline, read-only, no races.

    python tools/oval_audit.py                      # every installed layout, ranked by ratio
    python tools/oval_audit.py --track acu_unitedstates
    python tools/oval_audit.py --near 0.1           # only layouts within this of the 0.6 threshold
    python tools/oval_audit.py --selftest

WHY IT MATTERS. `isOval` does not merely label a track: `strategy.lua:292` SUBSTITUTES `BOOK.nascar` for any
class without a slingshot key, so a mislabelled layout loses the road-course manoeuvres - and the oval book's
own corner-entry lunge and switchback are unreachable behind `strategy.lua:335-344`'s unconditional `return nil`.
The owner drove COTA's Club layout 14 times with `isOval` TRUE, attempting 15 manoeuvres and completing 1
(LESSONS 889977f).

WHAT IT COMPUTES, and why it is a PROXY rather than the real thing. `detectOval` (racecraft.lua:601) samples
`ac.trackProgressToWorldCoordinate` at 96 points around the lap and tests `|sum of signed turns| / total turning
> 0.6`. That is a CSP runtime API and cannot be called offline, so this reads the AI spline
(`<track>/<layout>/ai/fast_lane.ai`) and samples 96 points evenly by CUMULATIVE LENGTH, which is what track
progress is. Same arithmetic, same threshold, different source for the geometry.

    A PROXY IS WORTH NOTHING UNTIL IT IS CHECKED AGAINST THE REAL ANSWER.

So `--selftest` is not a unit test of the maths: it asserts this computation REPRODUCES the runtime verdict on
the two layouts where we have one from the game itself - `acu_unitedstates/a` False across 15 races' diags and
`acu_unitedstates/east` True across 14. If either flips, the proxy is wrong and nothing it prints may be quoted.

FILE FORMAT, verified rather than assumed: header `int32 version, detailCount, lapTime, sampleCount`, then
`detailCount` records of `float x, y, z, float length, int32 id` at a 20-byte stride. Checked on COTA GP: ids
run 0..detailCount-1, cumulative length reaches 5411 m, and the last point closes the loop onto the first. The
rest of the file is the AI "extra" section and is not read.
"""
import argparse
import glob
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
TRACKS = os.path.join(AC, "content", "tracks")
THRESHOLD = 0.90                     # MIRRORS R.OVAL_ONEWAY in lib/racecraft.lua - KEEP THESE TWO IN STEP.
                                     # Was a hardcoded 0.6 on both sides until 2026-10-25 (item 13). At 0.6 this
                                     # tool called 7 of 160 layouts ovals and 5 were wrong, including
                                     # acu_unitedstates/east, which the owner races.
SAMPLES = 96                         # detectOval's N
# The runtime verdicts we actually have, from diag `isOval` across many races. The selftest's whole value.
#: Layout -> the verdict the GAME ITSELF recorded (from diag `isOval`), used to validate the offline proxy.
#: A third value may be given: a REASON why a disagreement with the proxy is expected and already explained.
#: A disagreement WITHOUT a reason still fails the selftest - that is the check's whole value.
KNOWN = {
    ("acu_unitedstates", "a"): (False, None),
    # east was observed TRUE by the runtime - but at the OLD hardcoded 0.6 threshold, and its ratio is 0.6141.
    # Raising the threshold to 0.90 (item 13) is INTENDED to stop it being called an oval, so the proxy now
    # disagrees with that observation BY DESIGN. The entry stays, because it is a real observation and deleting
    # it would hide the change; it must be RE-OBSERVED on a race after the change and then updated to False.
    ("acu_unitedstates", "east"): (True, "observed at the OLD 0.6 threshold; item 13 intends this to become "
                                         "False. Re-observe on a post-change race, then set False."),
    # A GENUINE oval, added 2026-10-25 so the control has one. OBSERVED TRUE, and the proxy AGREES.
    # I SEEDED THIS WRONG FIRST TIME AND THE CORRECTION MATTERS MORE THAN THE ENTRY. I recorded it as observed
    # FALSE with "42 consecutive races read as a road course", from a glob of *daytona* PLUS *bahrain*.
    # ZERO of those 41 Bahrain races were on the OVAL layout: 37 grandprix, 2 outer, 1 paddock, 1 endurance -
    # all ROAD COURSES, all correctly classified. bahrain .../test, the 0.9737 oval this audit names, has NEVER
    # been raced. The only genuine oval ever raced here is Daytona: 10 diags, of which 2 real races False and 1
    # failed launch (2 snapshots) BEFORE 00c5c43 on 19 Sep 08:20, then 6 TRUE and 1 False after it.
    # SO: the retry worked, detection fires on a real oval 6 times in 7, THERE IS NO INVERSION, and what remains
    # is an INTERMITTENT false negative near 1 in 7 - for which the degenerate-geometry path is still the best
    # account. A glob that is too BROAD is the same defect as one that is too narrow: both answer a question
    # about the query instead of about the world.
    ("daytona_2017", "oval"): (True, None),
}


def spline(path):
    """-> [(x, z, cumulative_length)] from a fast_lane.ai, or None if it does not parse as one."""
    try:
        b = open(path, "rb").read()
    except OSError:
        return None
    if len(b) < 16:
        return None
    ver, detail, _lap, _samp = struct.unpack_from("<4i", b, 0)
    if ver != 7 or detail < 16 or 16 + detail * 20 > len(b):
        return None
    pts = []
    for k in range(detail):
        x, _y, z, L, _i = struct.unpack_from("<ffffi", b, 16 + k * 20)
        pts.append((x, z, L))
    if pts[-1][2] <= 0:
        return None
    return pts


def ratio(pts, n=SAMPLES):
    """detectOval's arithmetic, on points sampled evenly by cumulative length."""
    total_len = pts[-1][2]
    samp, j = [], 0
    for k in range(n):
        want = (k / float(n)) * total_len
        while j + 1 < len(pts) and pts[j + 1][2] < want:
            j += 1
        a, b = pts[j], pts[min(j + 1, len(pts) - 1)]
        span = (b[2] - a[2]) or 1.0
        t = max(0.0, min(1.0, (want - a[2]) / span))
        samp.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    signed = total = 0.0
    for k in range(n):
        a, b, c = samp[k], samp[(k + 1) % n], samp[(k + 2) % n]
        v1x, v1z = b[0] - a[0], b[1] - a[1]
        v2x, v2z = c[0] - b[0], c[1] - b[1]
        m1 = math.hypot(v1x, v1z)
        m2 = math.hypot(v2x, v2z)
        if m1 > 1e-3 and m2 > 1e-3:
            turn = (v1x * v2z - v1z * v2x) / (m1 * m2)
            signed += turn
            total += abs(turn)
    if total <= 1e-3:
        return None
    return abs(signed) / total


def layouts(one_track=None):
    """-> [(track, layout_or_None, path_to_fast_lane)]"""
    out = []
    for t in sorted(os.listdir(TRACKS)) if os.path.isdir(TRACKS) else []:
        if one_track and t != one_track:
            continue
        td = os.path.join(TRACKS, t)
        if not os.path.isdir(td):
            continue
        root = os.path.join(td, "ai", "fast_lane.ai")
        if os.path.exists(root):
            out.append((t, None, root))
        for lay in sorted(os.listdir(td)):
            p = os.path.join(td, lay, "ai", "fast_lane.ai")
            if os.path.exists(p):
                out.append((t, lay, p))
    return out


def selftest():
    ok = True
    for (t, lay), spec in sorted(KNOWN.items()):
        expected, reason = spec if isinstance(spec, tuple) else (spec, None)
        p = os.path.join(TRACKS, t, lay, "ai", "fast_lane.ai")
        pts = spline(p)
        if not pts:
            print("SELFTEST FAIL: could not read the spline for %s/%s - the proxy cannot be checked at all"
                  % (t, lay))
            ok = False
            continue
        r = ratio(pts)
        got = (r is not None and r > THRESHOLD)
        if got == expected:
            mark = "agrees"
        elif reason:
            mark = "disagrees - EXPECTED AND EXPLAINED"
        else:
            mark = "*** DISAGREES ***"
        print("  %s/%-6s ratio %.4f -> offline %-5s | runtime from diags %-5s  %s"
              % (t, lay, r, got, expected, mark))
        if got != expected and reason:
            # An explained discrepancy must NOT pass silently and must NOT fail the run: printing the reason is
            # the point. An UNexplained one still fails, which is what keeps the check worth having.
            print("     reason on file: %s" % reason)
        elif got != expected:
            print("     the offline proxy does not reproduce the game's own verdict. NOTHING THIS TOOL PRINTS "
                  "MAY BE QUOTED until that is explained.")
            ok = False
    # a negative control: the threshold must actually be doing work, i.e. the two knowns must straddle it
    rs = []
    for (t, lay) in sorted(KNOWN):
        pts = spline(os.path.join(TRACKS, t, lay, "ai", "fast_lane.ai"))
        if pts:
            rs.append(ratio(pts))
    # ANY number of knowns, not exactly two. The old form was `len(rs) == 2`, so adding a third layout would
    # have made this control SILENTLY SKIP - a guard that disappears when you strengthen the data around it.
    # Found 2026-10-25 while adding daytona_2017/oval as the first genuine oval in KNOWN.
    if len(rs) < 2:
        print("SELFTEST FAIL: fewer than two readable knowns, so the threshold cannot be shown to do any work")
        ok = False
    elif not (min(rs) < THRESHOLD < max(rs)):
        print("SELFTEST FAIL: all %d known layouts fall the same side of %.2f, so agreement proves nothing "
              "about the threshold" % (len(rs), THRESHOLD))
        ok = False
    else:
        print("  negative control OK: the %d knowns straddle %.2f (%.4f .. %.4f)"
              % (len(rs), THRESHOLD, min(rs), max(rs)))
    print("oval_audit selftest: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track")
    ap.add_argument("--near", type=float, help="only layouts whose ratio is within this of the threshold")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    rows, unreadable = [], 0
    for t, lay, p in layouts(args.track):
        pts = spline(p)
        if not pts:
            unreadable += 1
            continue
        r = ratio(pts)
        if r is None:
            unreadable += 1
            continue
        rows.append((r, t, lay, pts[-1][2], len(pts)))
    # sort on the ratio and then on NAMES, never on the raw tuple: a root-level fast_lane.ai has layout None,
    # and two layouts with an equal ratio then compare None against a str, which raises.
    rows.sort(key=lambda r: (-r[0], r[1], r[2] or ""))
    ovals = [x for x in rows if x[0] > THRESHOLD]
    print("layouts read: %d   unreadable or not version 7: %d   threshold %.2f" % (len(rows), unreadable, THRESHOLD))
    print("CALLED AN OVAL: %d of %d (%.1f%%)" % (len(ovals), len(rows), 100.0 * len(ovals) / max(1, len(rows))))
    print()
    print("  %-7s %-34s %-9s %s" % ("ratio", "track/layout", "length_m", "verdict"))
    for r, t, lay, L, n in rows:
        if args.near is not None and abs(r - THRESHOLD) > args.near:
            continue
        name = "%s/%s" % (t, lay) if lay else t
        tag = "OVAL -> BOOK.nascar" if r > THRESHOLD else ""
        margin = "  (margin %+.3f)" % (r - THRESHOLD) if abs(r - THRESHOLD) < 0.1 else ""
        print("  %-7.4f %-34s %-9.0f %s%s" % (r, name[:34], L, tag, margin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
