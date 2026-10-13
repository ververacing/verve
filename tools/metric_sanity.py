"""Can this metric support the claim I am about to make with it? Check BEFORE quoting a number, not after.

    python tools/metric_sanity.py                  # every numeric column in results.csv
    python tools/metric_sanity.py laptime_median_s # one column, in detail
    python tools/metric_sanity.py --selftest       # prove it detects quantisation it is shown

WHY THIS EXISTS. On 2026-10-13 the release gate refused a release on "medlap 120.3 vs 120.0-120.0". Checking the
METRIC instead of adjusting the threshold showed that `laptime_median_s` is not a lap time at all: race_metrics
derives it from the difference between DIAG SNAPSHOT timestamps, and diag writes every 8 s, so every value it can
ever produce is a multiple of 8 and a median over an even-length list lands on multiples of 4. Every Monza 12-lap row
in results.csv is a whole number - 120, 121, 124, 128 - with spreads of exactly 8, 12 or 16, while a real GT3 Monza
lap is about 110 s.

The evidence had been sitting in the CSV for weeks. It cost a withdrawn pace claim (the cold-tyre rejection's
"+1.0 s slower" sub-claim, which an 8 s metric cannot support) and would have cost a blocked release. One more
threshold tweak would have buried it permanently.

WHAT IT REPORTS, per column:
  n, distinct   - how many values, how many DIFFERENT values. Few distinct values over many rows is the first smell.
  range         - min to max.
  quantum       - the greatest common divisor of the gaps between sorted distinct values. A quantum of 8 on a metric
                  quoted to one decimal place means the decimal place is fiction.
  resolvable    - the smallest difference the metric can express: the quantum. Any claim finer than this is unfounded.

It does NOT know what a metric SHOULD look like - no tool can. It makes the granularity visible so the person
quoting it has to notice. `--ref` states an expected real-world value for a sanity comparison.
"""
import csv
import io
import os
import sys
from math import gcd

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results", "results.csv")

# Columns worth flagging loudly, because a claim gets made from them and a coarse one is dangerous rather than
# merely useless. Each maps to a note about what the number is actually for.
WATCH = {
    "laptime_median_s": "pace claims - KNOWN COARSE, derived from 8 s diag snapshots; use the feed's lap_ms instead",
    "laptime_median_spread_s": "field spread - same 8 s derivation as the median",
    "incidents": "contact/incident rates",
    "contact_events": "contact rates",
    "heavy80": "heavy-hit counts (rare events: a zero baseline resolves nothing)",
    "retired_or_parked": "DNF rates",
}


def quantum(vals):
    """The granularity of a set of values: the GCD of the gaps between sorted distinct values.

    Scaled to thousandths so decimals work in integer arithmetic. Returns 0.0 when there is nothing to compare
    (fewer than two distinct values) - which is itself worth reporting, not a pass.
    """
    uniq = sorted({round(v * 1000) for v in vals})
    if len(uniq) < 2:
        return 0.0
    g = 0
    for a, b in zip(uniq, uniq[1:]):
        g = gcd(g, b - a)
    return g / 1000.0


def worst_cell_quantum(rows, col, by=("track", "leader_laps")):
    """The quantum WITHIN a comparable cell, which is the only one that matters.

    Pooling the whole CSV understates granularity badly: across 471 rows and every track, laptime_median_s reports a
    quantum of 0.25 s, because different tracks land on different quarter-seconds. Within one cell - same track,
    same race length, which is how the suite and the gate actually compare - it is 4 to 8 s. A tool that pools would
    have declared the metric fine and missed the whole problem, so this reports the WORST (coarsest) cell and names
    it, because a comparison is only ever made inside a cell.
    """
    cells = {}
    for r in rows:
        v = r.get(col)
        if v in (None, ""):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        key = tuple(r.get(b, "?") for b in by)
        cells.setdefault(key, []).append(f)
    # A GCD OVER A FEW VALUES IS COINCIDENCE, NOT GRANULARITY, and the first version of this function did not know
    # that. Run across results.csv it "found" a quantum of 18 in incidents, 34 in contact_events and 22.5 in
    # inc_per_car_100laps - all spurious: with three or four integers in a cell, any two of them share a divisor.
    # Reporting that batch as findings would have been precisely the error this tool exists to prevent.
    # A quantum is only believable when enough DISTINCT values occupy the range to rule out a shared divisor by
    # chance: with k distinct values spanning R, a real step q implies about R/q+1 available levels, so demand that
    # k be a decent fraction of them. MIN_DISTINCT is the floor; below it the cell is reported as "too few".
    MIN_DISTINCT = 5
    worst = (0.0, None, 0, 0)
    for key, vals in cells.items():
        uniq = {round(v, 6) for v in vals}
        if len(uniq) < MIN_DISTINCT:
            continue
        q = quantum(vals)
        if q <= 0:
            continue
        span = max(vals) - min(vals)
        levels = span / q + 1
        if len(uniq) < levels / 3.0:           # too sparsely occupied for the divisor to mean anything
            continue
        if q > worst[0]:
            worst = (q, key, len(vals), len(uniq))
    return worst


def numeric_columns(rows):
    cols = {}
    for r in rows:
        for k, v in r.items():
            if not k or v in (None, ""):
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            cols.setdefault(k, []).append(f)
    return cols


def report(rows, only=None, ref=None):
    cols = numeric_columns(rows)
    keys = [only] if only else sorted(cols)
    print("%-28s %6s %8s %-22s %-10s %s" % ("column", "n", "distinct", "range", "quantum", "note"))
    worst = 0
    for k in keys:
        vals = cols.get(k)
        if not vals:
            print("%-28s  (no numeric values)" % k)
            continue
        q = quantum(vals)
        note = WATCH.get(k, "")
        # A quantum well above the precision the value is PRINTED to is the signature that bit us.
        printed_decimals = any("." in (str(v)) and str(v).split(".")[1] not in ("0", "") for v in vals)
        if q >= 1 and printed_decimals:
            note = ("QUANTISED: steps of %g, so decimals are fiction. " % q) + note
            worst += 1
        elif q >= 4:
            note = ("COARSE: steps of %g. " % q) + note
            worst += 1
        print("%-28s %6d %8d %-22s %-10g %s"
              % (k, len(vals), len({round(v, 6) for v in vals}), "%g to %g" % (min(vals), max(vals)), q, note))
    if only:
        q, cell, n, k = worst_cell_quantum(rows, only)
        if cell:
            print("\n  WITHIN-CELL granularity, which is the figure that matters because every comparison is made")
            print("  inside a cell: coarsest cell is %s (n=%d) with a quantum of %g." % (" / ".join(str(c) for c in cell), n, q))
            print("  NO claim finer than %g is supportable from this column in that cell." % q)
            if q >= 1:
                print("  The pooled quantum above (%g) is MISLEADINGLY FINE - pooling tracks hides the step pattern."
                      % quantum(cols.get(only) or [0, 0]))
        vals = cols.get(only) or []
        if ref is not None and vals:
            med = sorted(vals)[len(vals) // 2]
            print("\n  reference check: you expect about %g, the metric's median is %g (%+.0f%%)"
                  % (ref, med, (med - ref) / ref * 100))
    if worst:
        print("\n  %d column(s) flagged. A claim finer than a column's quantum is not evidence, whatever the"
              " decimal places suggest." % worst)
    return 0


def selftest():
    """Show it quantisation and see whether it says so."""
    ok = True
    cases = [
        ("8 s snapshot-derived laps", [120.0, 128.0, 112.0, 120.0, 136.0], 8.0),
        ("medians of those (4 s)", [120.0, 124.0, 128.0, 120.0], 4.0),
        ("real millisecond laps", [110.234, 110.876, 111.002, 110.551], None),
        ("integer counts", [19.0, 22.0, 24.0, 21.0], 1.0),
        ("all identical", [120.0, 120.0, 120.0], 0.0),
    ]
    for name, vals, want in cases:
        got = quantum(vals)
        if want is None:
            good = got < 0.1
            print("  %-28s quantum %-8g -> fine-grained? %s" % (name, got, "yes" if good else "NO - BROKEN"))
        else:
            good = abs(got - want) < 1e-9
            print("  %-28s quantum %-8g -> expected %-6g %s" % (name, got, want, "ok" if good else "WRONG"))
        ok &= good
    # the case that matters: an 8 s metric must NOT be read as supporting a 1 s claim
    q = quantum([120.0, 128.0, 112.0])
    print("\n  an 8 s metric supporting a 1.0 s pace claim? %s (quantum %g > 1.0)"
          % ("no, correctly refused" if q > 1.0 else "YES - BROKEN", q))
    ok &= q > 1.0
    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--selftest" in sys.argv:
        return selftest()
    ref = None
    for i, a in enumerate(sys.argv):
        if a == "--ref" and i + 1 < len(sys.argv):
            ref = float(sys.argv[i + 1])
    try:
        with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as e:
        print("cannot read %s: %s" % (RESULTS, e))
        return 1
    return report(rows, only=args[0] if args else None, ref=ref)


if __name__ == "__main__":
    sys.exit(main())
