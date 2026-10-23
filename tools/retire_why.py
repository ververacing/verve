"""WHY each car retired, from the race feed - the classified retirement outcome F2's spec commits to.

    python tools/retire_why.py monza --label f2_
    python tools/retire_why.py monza --label f2_ --arms f2_tcr_k0_on,f2_tcr_kd_on,f2_gt3_k0_on
    python tools/retire_why.py --selftest

THE FEED ALREADY CLASSIFIES RETIREMENTS, so this does NOT invent a parallel taxonomy. lib/feed.lua:344 emits
`reason` as one of three, and the three mean different things about Verve:
  `hopeless`  Verve's recovery GAVE UP on the car (the `park` flag). Only reachable with Verve ON, because
              recovery is Verve - so a `hopeless` in an OFF arm would be a bug in our reading, not a result.
  `damage`    the car's worst body damage was >= 150 at the moment it retired.
  `ac`        AC retired it, with neither condition. **In a Verve-OFF arm this is the ABANDONMENT case** - the
              standing finding is that every OFF retirement was a car stranded off-track that nothing came for.
Taking the field rather than re-deriving it is deliberate: this morning I re-implemented an archive lookup that
tools/paths.py already provided, and the home-made version was worse. Use what exists.

NO INVENTED THRESHOLD. The obvious way to answer "was it stranded after going off?" is to bucket on a time
window, and then the window is a number I chose, which quietly decides the answer. Instead this REPORTS THE
MEASURED GAP: seconds from that car's last `off_track` to its retirement, and from its last `stuck`. A reader can
see 9 s and 400 s for what they are. The only structural facts asserted are whether such an event existed at all
and what the car's damage was doing.

RATES ARE NOT COMPUTED HERE. Retirements are a SEPARATE outcome in F2's spec, never folded into an excursion
rate, precisely so a retirement and the off-track that preceded it cannot be reported as two findings when they
are one event. This tool shows the join so that can be seen; it deliberately prints no per-100 anything.
"""
import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)            # python -I drops the script dir from sys.path
import paths                        # noqa: E402  - live + archived feeds, de-duplicated

DIAG_RE = re.compile(r"^diag_race_(\d{8}_\d{6})_(.+?)_(.+)\.jsonl$")


def label_map():
    """diag stem -> label. results.csv first (it pairs them exactly), then the diag filename."""
    import csv
    import glob
    out = {}
    try:
        with io.open(os.path.join(HERE, "harness_results", "results.csv"),
                     encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                b = os.path.basename(r.get("file") or "")
                lab = r.get("label") or ""
                if b.startswith("diag_race_") and lab:
                    out[b[len("diag_race_"):len("diag_race_") + 15]] = lab
    except OSError:
        pass
    for d in (os.path.dirname(HERE), os.path.join(HERE, "harness_results", "archive", "diag")):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = DIAG_RE.match(fn)
            if m and m.group(1) not in out:
                out[m.group(1)] = m.group(3)
    return out


def scan(path):
    """-> (finished, [retirement dicts]) or (None, None) if the feed is unusable."""
    rets, offs, stucks = [], collections.defaultdict(list), collections.defaultdict(list)
    dmg_at = collections.defaultdict(list)       # (t, dmg) per car
    finished = False
    n_state = 0
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            t = d.get("type")
            if t == "state":
                n_state += 1
                for c in (d.get("cars") or []):
                    if isinstance(c.get("i"), int) and isinstance(c.get("dmg"), (int, float)):
                        dmg_at[c["i"]].append((d.get("t") or 0.0, c["dmg"]))
            elif t == "retire":
                rets.append(d)
            elif t == "off_track":
                if isinstance(d.get("car"), int):
                    offs[d["car"]].append(d.get("t") or 0.0)
            elif t == "stuck":
                if isinstance(d.get("car"), int):
                    stucks[d["car"]].append(d.get("t") or 0.0)
            elif t == "race_end":
                finished = True
    if n_state < 5:
        return None, None

    out = []
    for r in rets:
        car, rt = r.get("car"), r.get("t") or 0.0
        if not isinstance(car, int):
            continue
        prior_off = [x for x in offs.get(car, []) if x <= rt]
        prior_stuck = [x for x in stucks.get(car, []) if x <= rt]
        dmgs = [v for (tt, v) in dmg_at.get(car, []) if tt <= rt]
        out.append({
            "car": car,
            "t": rt,
            "lap": r.get("lap"),
            "reason": r.get("reason"),
            "off_before": len(prior_off),
            "s_since_off": (rt - max(prior_off)) if prior_off else None,
            "stuck_before": len(prior_stuck),
            "s_since_stuck": (rt - max(prior_stuck)) if prior_stuck else None,
            "dmg_at_retire": dmgs[-1] if dmgs else None,
            "dmg_max_before": max(dmgs) if dmgs else None,
        })
    return finished, out


def selftest():
    import tempfile
    ok = True

    def feed(lines):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with io.open(p, "w", encoding="utf-8") as f:
            for d in lines:
                f.write(json.dumps(d) + "\n")
        return p

    base = [{"type": "header", "cars": [{"i": 1}]}]
    for t in range(6):
        base.append({"type": "state", "t": float(t),
                     "cars": [{"i": 1, "pos": 1, "lap": 0, "spline": 0.5, "spd": 10, "dmg": 12}]})

    # 1. an off_track BEFORE the retirement is joined; one AFTER it is not
    lines = list(base) + [
        {"type": "off_track", "t": 2.0, "car": 1},
        {"type": "off_track", "t": 9.0, "car": 1},          # after the retire: must be ignored
        {"type": "retire", "t": 5.0, "car": 1, "lap": 0, "reason": "ac"},
        {"type": "race_end", "results": []},
    ]
    fin, r = scan(feed(lines))
    if not r or len(r) != 1:
        print("SELFTEST FAIL: expected exactly one retirement, got %r" % (r,)); ok = False
    else:
        if r[0]["off_before"] != 1:
            print("SELFTEST FAIL: off_before should count only the off_track BEFORE the retire, got %r"
                  % r[0]["off_before"]); ok = False
        if r[0]["s_since_off"] != 3.0:
            print("SELFTEST FAIL: s_since_off should be 3.0 (5.0 - 2.0), got %r" % r[0]["s_since_off"]); ok = False
        if not fin:
            print("SELFTEST FAIL: a feed with race_end was not reported finished"); ok = False

    # 2. no off_track at all -> None, NOT 0, so "no event" cannot read as "0 seconds ago"
    lines2 = list(base) + [{"type": "retire", "t": 5.0, "car": 1, "lap": 0, "reason": "ac"}]
    fin2, r2 = scan(feed(lines2))
    if not r2 or r2[0]["s_since_off"] is not None or r2[0]["off_before"] != 0:
        print("SELFTEST FAIL: with no off_track, s_since_off must be None and off_before 0, got %r"
              % (r2 and r2[0])); ok = False
    if fin2:
        print("SELFTEST FAIL: a feed with no race_end was reported finished"); ok = False

    # 3. the reason is taken from the feed, never re-derived from damage
    lines3 = list(base) + [{"type": "retire", "t": 5.0, "car": 1, "lap": 0, "reason": "hopeless"},
                           {"type": "race_end", "results": []}]
    _, r3 = scan(feed(lines3))
    if not r3 or r3[0]["reason"] != "hopeless":
        print("SELFTEST FAIL: reason must come from the feed verbatim, got %r" % (r3 and r3[0].get("reason")))
        ok = False
    if r3 and r3[0]["dmg_at_retire"] != 12:
        print("SELFTEST FAIL: dmg_at_retire should be the last state at or before the retire (12), got %r"
              % r3[0]["dmg_at_retire"]); ok = False

    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pos:
        print(__doc__.strip().splitlines()[0])
        return 2
    track = pos[0]
    want, arms = None, None
    for i, a in enumerate(sys.argv):
        if a == "--label" and i + 1 < len(sys.argv):
            want = sys.argv[i + 1]
        if a == "--arms" and i + 1 < len(sys.argv):
            arms = sys.argv[i + 1].split(",")

    labs = label_map()
    races, live = [], []
    for p in paths.track_feeds(track):
        lab = labs.get(os.path.basename(p)[:15], os.path.basename(p)[:15])
        if want and want not in lab:
            continue
        fin, rr = scan(p)
        if rr is None:
            continue
        (races if fin else live).append((lab, rr))
    if live:
        print("STILL ON TRACK, excluded (no race_end): %s" % ", ".join(l for l, _ in live))
    if not races:
        print("retire_why: no finished %s race matched %s" % (track, want or "(any)"))
        return 0

    print("\nWHY EACH CAR RETIRED. `reason` is the FEED's own field (feed.lua:344): hopeless = Verve's recovery")
    print("gave up (ON arms only), damage = dmg >= 150 at the retirement, ac = AC retired it with neither -")
    print("which in a Verve-OFF arm is the abandonment case. Gaps are MEASURED, not bucketed: no threshold here.")
    print("%-20s %4s %4s %10s %7s %9s %7s %10s %8s"
          % ("label", "car", "lap", "reason", "offs<=t", "s_since", "stucks", "s_since", "dmg@ret"))
    tally = collections.Counter()
    for lab, rr in sorted(races):
        if not rr:
            print("  %-18s %s" % (lab[:18], "- no retirement -"))
            continue            # the race is counted by len(races). This used to register a TUPLE key in the
                                # tally, which made sorted() compare a tuple with a str and crash the summary.
        for d in rr:
            print("  %-18s %4s %4s %10s %7d %9s %7d %7s %8s"
                  % (lab[:18], d["car"], d["lap"], d["reason"], d["off_before"],
                     ("%.1f" % d["s_since_off"]) if d["s_since_off"] is not None else "-",
                     d["stuck_before"],
                     ("%.1f" % d["s_since_stuck"]) if d["s_since_stuck"] is not None else "-",
                     d["dmg_at_retire"]))
            tally[d["reason"] or "?"] += 1
    print("\n  %d finished races, %d retirements: %s"
          % (len(races), sum(tally.values()),
             ", ".join("%s %d" % (k, v) for k, v in sorted(tally.items())) or "none"))
    print("  Races with NO retirement are listed above and counted in the race total - a clean race is a race.")

    if arms:
        print("\nBY ARM (retirement COUNTS, never a rate - retirements are a separate outcome in F2's spec):")
        for a in arms:
            sel = [(lab, rr) for lab, rr in races if a in lab]
            c = collections.Counter()
            for _, rr in sel:
                for d in rr:
                    c[d["reason"] or "?"] += 1
            print("  %-18s races=%-2d retirements=%-2d  %s"
                  % (a, len(sel), sum(c.values()), ", ".join("%s %d" % kv for kv in sorted(c.items())) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
