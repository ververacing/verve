"""THE FIX_LOW_LEVEL A/B SCORER: mid-race AI-level changes per race, with Verve's own write log beside each one.

ONE METRIC, and the cloud set it: level changes AFTER the first write, per race, ON against OFF. Pace and
incidents WILL move in the OFF arm - low-level cars shift gears differently, which is the whole point of the key -
so this tool does not print them and nobody should read them from these rows.

WHAT MAKES A BLIP COUNTABLE, and why the rule is not "any change":
  the FIRST change per car is the t+0 value giving way to Verve's first write (every row starts {100: 17} - a real
  read-back of 1.0, not an artefact: diag.lua's num(v, mult, dflt) returns `dflt or 0`, so an unreadable level
  prints 0). Counting it would score every race as 17 blips. Skipping every change whose previous value was 100
  would be worse: it would hide a RETURN from 100, which is the half of a blip that proves it was transient.
  So: skip exactly one change per car, the first.

AND THE SECOND COLUMN IS THE POINT. `lvlwrite` lines come from drivers.lua's own log on any level write after the
first, and the harness keeps every race's Verve lines in csp_logs/<stamp>_<label>.log. A blip with NO lvlwrite
line beside it did not come from Verve. **That inference is worthless unless the line CAN appear**, which is why
the OFF queue opens with a `--drivers random` row: outside career Verve's level is static after its first write,
so the blip cells cannot test their own detector. Check the detector row FIRST; if it logged nothing, this tool's
second column means nothing either and the run proves only that blips happen.

    python tools/blip_score.py s45_blip s46_flloff            # the two arms
    python tools/blip_score.py --selftest
"""
import csv
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "harness_results")


def blips(path, skip_first=True):
    """[(car, t_rel, from, to)] for every applied-level change after the first write."""
    snaps = []
    try:
        for ln in io.open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if "running" in d and d.get("grid"):
                snaps.append(d)
    except OSError:
        return [], 0
    if not snaps:
        return [], 0
    t0 = snaps[0]["t"]
    prev, out, seen = {}, [], set()
    for s in snaps:
        for c in s["grid"]:
            i = c.get("i")
            if i in (None, 0):
                continue
            v = c.get("lvl")
            if i in prev and v is not None and v != prev[i]:
                if skip_first and i not in seen:
                    seen.add(i)
                else:
                    out.append((i, s["t"] - t0, prev[i], v))
            if v is not None:
                prev[i] = v
    return out, len(snaps)


def kept_log(label):
    hits = sorted(glob.glob(os.path.join(RESULTS, "csp_logs", "*_" + label + ".log")))
    return hits[-1] if hits else None


def lvlwrites(label):
    p = kept_log(label)
    if not p:
        return None                      # no log kept - NOT the same as zero lines
    n, lines = 0, []
    for ln in io.open(p, encoding="utf-8", errors="replace"):
        if "lvlwrite" in ln:
            n += 1
            if len(lines) < 4:
                lines.append(ln.strip()[-150:])
    return n, lines


def csp_ai(label):
    """The effective AI_TWEAKS block the harness recorded for this row - so the arms are DIFFED, not assumed."""
    for p in sorted(glob.glob(os.path.join(RESULTS, "results*.csv")), reverse=True):
        try:
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    if (row.get("label") or "").strip() == label:
                        return row.get("csp_ai") or ""
        except (OSError, csv.Error):
            continue
    return None


def arm(prefix):
    rows = []
    for p in sorted(glob.glob(os.path.join(V, "diag_race_*%s*.jsonl" % prefix))):
        label = re.sub(r"^\d{8}_\d{6}_", "", os.path.basename(p)[10:-6])
        label = label.split("_", 1)[1] if label.startswith("monza_") else label
        m = re.search(r"(%s\w*)" % re.escape(prefix), os.path.basename(p))
        label = m.group(1) if m else label
        ev, nsnap = blips(p)
        lw = lvlwrites(label)
        rows.append({"label": label, "events": ev, "snaps": nsnap,
                     "lvl": (lw[0] if lw else None), "lines": (lw[1] if lw else []),
                     "csp": csp_ai(label)})
    return rows


def show(prefix, rows):
    if not rows:
        print("  %-14s no races yet" % prefix)
        return
    withblip = sum(1 for r in rows if r["events"])
    total = sum(len(r["events"]) for r in rows)
    lw = [r["lvl"] for r in rows if r["lvl"] is not None]
    print("  ARM %-14s %d races, %d WITH a blip, %d blip events, %d lvlwrite lines%s"
          % (prefix, len(rows), withblip, total, sum(lw),
             "" if len(lw) == len(rows) else "  (!! %d races kept no log)" % (len(rows) - len(lw))))
    for r in rows:
        vals = " ".join("car%d t+%.0f %s->%s" % (c, t, a, b) for c, t, a, b in r["events"][:6])
        print("      %-18s %2d snaps  %d blip(s)  lvlwrite %-4s  %s"
              % (r["label"], r["snaps"], len(r["events"]), ("-" if r["lvl"] is None else r["lvl"]), vals))
        for ln in r["lines"]:
            print("          %s" % ln)
    csps = sorted(set(r["csp"] for r in rows if r["csp"] is not None))
    print("      csp_ai recorded for this arm: %s" % (csps if csps else "(no results row yet)"))


def selftest():
    """Crafted diag, both counting rules, so the skip-the-first rule is PROVEN to be doing work."""
    import tempfile
    ok = True
    d = tempfile.mkdtemp()
    p = os.path.join(d, "diag_race_20260101_000000_monza_selftest.jsonl")
    def snap(t, lv):
        return json.dumps({"t": t, "running": 1, "grid": [{"i": 0, "lvl": 90}, {"i": 3, "lvl": lv}]}) + "\n"
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(snap(100.0, 100))     # t+0: the pre-Verve read-back
        f.write(snap(108.0, 76))      # first write - must NOT count
        f.write(snap(116.0, 76))
        f.write(snap(124.0, 80))      # the blip up - counts
        f.write(snap(132.0, 76))      # and back - counts
    ev, n = blips(p, skip_first=True)
    if len(ev) != 2:
        print("SELFTEST FAIL: skip_first=True counted %d, expected 2 (the up and the return)" % len(ev)); ok = False
    if ev and ev[0][1] != 24.0:
        print("SELFTEST FAIL: first event at t+%s, expected t+24 (relative to the FIRST snapshot)" % ev[0][1]); ok = False
    # THE NEGATIVE CONTROL: the same data counted the naive way must give 3. If this returns 2 as well, the
    # skip-the-first rule is not doing anything and the 2 above proved nothing.
    ev2, _ = blips(p, skip_first=False)
    if len(ev2) != 3:
        print("SELFTEST FAIL: skip_first=False counted %d, expected 3 - the rule is inert, so the test above"
              " cannot distinguish a working implementation from a broken one" % len(ev2)); ok = False
    if len(ev) == len(ev2):
        print("SELFTEST FAIL: both rules give %d - the first write is not being skipped" % len(ev)); ok = False
    # slot 0 must never count (the autopilot ignores Verve's level)
    if any(c == 0 for c, _, _, _ in ev2):
        print("SELFTEST FAIL: slot 0 was counted"); ok = False
    if n != 5:
        print("SELFTEST FAIL: snapshot count %d, expected 5" % n); ok = False
    os.remove(p)
    print("selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    pre = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pre:
        print(__doc__.strip().splitlines()[0])
        return 2
    print("MID-RACE AI-LEVEL CHANGES, per race. Pace and incidents are NOT comparable across these arms.\n")
    for p in pre:
        show(p, arm(p))
        print()
    print("READ THE DETECTOR ROW FIRST (s46_detect_1): if it logged no lvlwrite line, the lvlwrite column is"
          " untested and proves nothing about where the blip comes from.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
