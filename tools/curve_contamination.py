"""Could a foreign AI-level write have landed on a CALIBRATION row unnoticed?

AIWhisperer was installed 2026-09-06, so it was present on 14 Sep (`vcal_*`) and
21 Sep (`d21_curve_*`). "Last writer wins": if its 1.00 landed AFTER Verve's
write in one of those rows, that row ran at level 100 whatever its label says.

The CSP logs for those dates are gone (csp_logs starts 2026-09-25), the diag
files only reach back to 22 Oct and the feed to 22 Oct, so the per-car `lvl`
read-back cannot be inspected for September. TWO things do survive:

  1. the ROTATED results_until_*.csv archives - reading only the live
     results.csv finds nothing and looks like lost data;
  2. **AC's OWN race_out_*.json for all 22 calibration races**, which carry
     `sessions[0].bestLaps` as `{car, time_ms, lap}`.

THE TEST, in two sections. Both ask the same question - does a row labelled 90
actually race at 90, or at 100? - but only the second can answer it:

  SECTION 1 (the coarse view, kept to show WHY it cannot decide): within one
  curve, laptime_median_s must FALL as the level RISES. metric_sanity reports
  this column's coarsest WITHIN-CELL quantum as 8 s, so only gaps WIDER than 8 s
  are evidence and a tie is UNRESOLVED - neither contaminated nor clean.

  SECTION 2 (authoritative): the SAME CAR INDEX across two rows of one family,
  compared on its own best lap in MILLISECONDS from AC. The grid is built by
  `grid_from_models` with `--seed` defaulting to 0, so car N is the same model in
  every row of a family - the comparison is PAIRED and model-controlled, and the
  coarse median never enters it. A row that really ran at a lower level is
  slower than its own 100-row counterpart on car after car; a row whose 1.00
  landed sits on top of it.

Car 0 is EXCLUDED everywhere: the autopilot ignores Verve's level and starts on
a different fuel load, so its pace is not the field's.

Read-only. Run from anywhere: the archive is found relative to this file.
"""
import csv
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH = os.path.join(HERE, 'harness_results')

# laptime_median_s, COARSEST within-cell quantum, from
# `python tools/metric_sanity.py laptime_median_s` (monza/10, n=33). Read from
# the tool, never from memory: a remembered 4 would have called three rows clean
# that this column cannot separate at all.
QUANTUM = 8.0
CURVES = ('vcal_', 'd21_curve_', 'curve_m3_')
LEVEL_IN_LABEL = re.compile(r'_(\d{2,3})$')


def rows():
    """Every calibration row in every results CSV, live and rotated."""
    out = []
    for path in sorted(glob.glob(os.path.join(ARCH, 'results*.csv'))):
        with io.open(path, encoding='utf-8', errors='replace') as fh:
            for r in csv.DictReader(fh):
                lab = (r.get('label') or '')
                if any(lab.startswith(p) for p in CURVES):
                    r['_file'] = os.path.basename(path)
                    out.append(r)
    return out


def level_of(r):
    """The level the row was ASKED for: the cmd's --ai-level, else the label."""
    m = re.search(r'--ai-level\s+(\d+)', r.get('cmd') or '')
    if m:
        return int(m.group(1)), 'cmd'
    m = LEVEL_IN_LABEL.search(r.get('label') or '')
    if m:
        return int(m.group(1)), 'label'
    return None, 'none'


def family(label):
    """Rows comparable to each other: strip the trailing level."""
    return LEVEL_IN_LABEL.sub('', label)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def judge(fam, pts):
    """pts = [(level, laptime, label)] sorted by level. -> list of lines."""
    lines = []
    top = [p for p in pts if p[0] == 100]
    ref = top[0][1] if top and top[0][1] is not None else None
    for lvl, lap, lab in pts:
        if lap is None:
            lines.append('    %-26s level %3d   lap   n/a   NO LAP TIME' % (lab, lvl))
            continue
        tag = ''
        if ref is not None and lvl < 100:
            d = lap - ref
            if d > QUANTUM:
                tag = 'CLEAN   (%.1f s slower than the 100 row, > the %.0f s quantum)' % (d, QUANTUM)
            elif d < -QUANTUM:
                tag = '*** FASTER THAN THE 100 ROW by %.1f s - look at this row ***' % (-d)
            else:
                tag = 'UNRESOLVED (within %.0f s of the 100 row; this column cannot separate them)' % QUANTUM
        elif lvl == 100:
            tag = '(the reference row)'
        else:
            tag = 'no 100 row in this family - nothing to compare against'
        lines.append('    %-26s level %3d   lap %7.1f s   %s' % (lab, lvl, lap, tag))
    return lines


# ---------- section 2: AC's own per-car best laps, in milliseconds ----------

def best_laps(label):
    """{car_index: best_lap_ms} from AC's race_out for this label. Car 0 out."""
    hits = sorted(glob.glob(os.path.join(ARCH, 'race_out_*_%s.json' % label)))
    if not hits:
        return {}, None
    path = hits[-1]
    try:
        with io.open(path, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
    except ValueError:
        return {}, os.path.basename(path)
    out = {}
    for s in d.get('sessions') or []:
        for b in s.get('bestLaps') or []:
            car, t = b.get('car'), b.get('time')
            if car in (None, 0) or not t or t <= 0:
                continue
            if car not in out or t < out[car]:
                out[car] = t
    return out, os.path.basename(path)


def paired(ref, other):
    """Per-car deltas in seconds, for cars present in BOTH rows. Car 0 out.

    The car-0 exclusion is repeated HERE and not left to best_laps alone: this
    function is the only place two rows are ever compared, and its own selftest
    caught car 0 passing straight through when the filter lived upstream only.
    """
    shared = sorted(c for c in set(ref) & set(other) if c != 0)
    return [(c, (other[c] - ref[c]) / 1000.0) for c in shared]


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def pair_verdict(deltas):
    """-> (verdict, detail). Slower on car after car, or sitting on top of it?"""
    if not deltas:
        return 'NO SHARED CARS', ''
    ds = [d for _, d in deltas]
    med = median(ds)
    slower = sum(1 for d in ds if d > 0.5)       # half a second, not milliseconds
    same = sum(1 for d in ds if abs(d) <= 0.5)
    detail = ('median %+.3f s over %d shared cars, %d slower by >0.5 s, %d within 0.5 s, '
              'range %+.3f to %+.3f' % (med, len(ds), slower, same, min(ds), max(ds)))
    if slower >= max(2, int(0.6 * len(ds))):
        return 'RAN SLOWER - the label is honest', detail
    if same == len(ds):
        return '*** EVERY CAR WITHIN 0.5 s OF THE 100 ROW - this row raced at 100 ***', detail
    return 'MIXED - no clean call', detail


def main():
    rs = rows()
    if not rs:
        print('no calibration rows found in any results CSV')
        return
    fams = {}
    for r in rs:
        lvl, src = level_of(r)
        if lvl is None:
            continue
        fams.setdefault(family(r['label']), []).append(
            (lvl, num(r.get('laptime_median_s')), r['label'], src, r['_file']))

    print('=== SECTION 1: laptime_median_s, the COARSE view (quantum %.0f s) ===' % QUANTUM)
    for fam in sorted(fams):
        pts = sorted(fams[fam])
        srcs = sorted(set(p[3] for p in pts))
        files = sorted(set(p[4] for p in pts))
        print('\n  %s   (%d rows, level read from %s)' % (fam, len(pts), '+'.join(srcs)))
        print('    archive: %s' % ', '.join(files))
        for line in judge(fam, [(p[0], p[1], p[2]) for p in pts]):
            print(line)
        laps = [p[1] for p in pts if p[1] is not None]
        if len(laps) >= 2:
            falling = all(laps[i] >= laps[i + 1] for i in range(len(laps) - 1))
            print('    ORDER: %s' % ('lap time falls as level rises - the curve has slope'
                                     if falling else 'NOT monotone - at least one row is out of order'))

    print('\n\n=== SECTION 2: AC\'s OWN per-car best laps, paired by car index (ms) ===')
    print('    Every row compared against its family\'s 100 row, car by car. Car 0 excluded.')
    for fam in sorted(fams):
        pts = sorted(fams[fam])
        labels = {p[0]: p[2] for p in pts}
        if 100 not in labels:
            print('\n  %s: no 100 row - nothing to pair against' % fam)
            continue
        ref, ref_file = best_laps(labels[100])
        if not ref:
            print('\n  %s: no race_out best laps for the 100 row (%s)' % (fam, ref_file or 'file missing'))
            continue
        print('\n  %s   reference %s from %s, %d cars' % (fam, labels[100], ref_file, len(ref)))
        print('    100 row best laps (s): %s' % ', '.join(
            '%.3f' % (ref[c] / 1000.0) for c in sorted(ref)))
        for lvl in sorted(labels):
            if lvl == 100:
                continue
            other, f = best_laps(labels[lvl])
            if not other:
                print('    %-26s level %3d   NO race_out (%s)' % (labels[lvl], lvl, f or 'file missing'))
                continue
            v, detail = pair_verdict(paired(ref, other))
            print('    %-26s level %3d   %s' % (labels[lvl], lvl, v))
            print('    %-26s             %s' % ('', detail))


def selftest():
    """Both sections must be able to FAIL.

    Verified to have teeth by mutation: raising QUANTUM to 100 makes the first
    assertion fail, so these are not assertions that pass regardless.
    """
    clean = [(70, 120.0, 'c_70'), (80, 114.0, 'c_80'), (100, 105.0, 'c_100')]
    out = ' | '.join(judge('c_', clean))
    assert 'CLEAN' in out, out
    assert 'FASTER THAN THE 100 ROW' not in out, 'a clean curve was flagged: %s' % out

    # a 70-label row that actually ran at 100 pace: ties the reference
    out = ' | '.join(judge('x_', [(70, 105.4, 'x_70'), (100, 105.0, 'x_100')]))
    assert 'UNRESOLVED' in out, out
    assert 'CLEAN' not in out, 'a tie must not read as clean: %s' % out

    # faster than the reference by more than the quantum
    out = ' | '.join(judge('y_', [(70, 94.0, 'y_70'), (100, 105.0, 'y_100')]))
    assert 'FASTER THAN THE 100 ROW by 11.0 s' in out, out

    # a gap of exactly the quantum must NOT be called clean (> not >=)
    out = ' | '.join(judge('z_', [(70, 113.0, 'z_70'), (100, 105.0, 'z_100')]))
    assert 'UNRESOLVED' in out, 'a gap of exactly %.0f s is the quantum, not evidence: %s' % (QUANTUM, out)

    # a family with no 100 row must say so rather than invent a reference
    out = ' | '.join(judge('w_', [(70, 120.0, 'w_70'), (80, 114.0, 'w_80')]))
    assert 'no 100 row' in out, out

    # the cmd beats the label when they disagree: the label is a name, the
    # cmd is the request.
    assert level_of({'label': 'vcal_m3_nurb_60', 'cmd': 'harness.py --ai-level 70'}) == (70, 'cmd')
    assert level_of({'label': 'vcal_m3_nurb_60', 'cmd': ''}) == (60, 'label')

    # --- section 2 ---
    ref = {1: 100000, 2: 101000, 3: 102000}
    # a genuinely slower field
    v, _ = pair_verdict(paired(ref, {1: 104000, 2: 105500, 3: 106000}))
    assert v.startswith('RAN SLOWER'), v
    # a row sitting on top of the 100 row - the contamination signature
    v, _ = pair_verdict(paired(ref, {1: 100120, 2: 100900, 3: 102300}))
    assert 'raced at 100' in v, v
    # one car slower, the rest identical: must NOT read as either
    v, _ = pair_verdict(paired(ref, {1: 100100, 2: 101050, 3: 108000}))
    assert v.startswith('MIXED'), v
    # car 0 must never enter a comparison, however fast or slow it was
    assert 0 not in paired({0: 1, 1: 100000}, {0: 999999, 1: 100100})[0], 'car 0 leaked in'
    assert len(paired({0: 1, 1: 100000}, {0: 999999, 1: 100100})) == 1
    # and cars present in only ONE row must be dropped, not counted as 0
    assert [c for c, _ in paired({1: 100000, 2: 100000}, {1: 100500})] == [1]

    # the archive must be where this file says it is, or every verdict above is
    # computed over an empty set and reads as "no rows"
    assert os.path.isdir(ARCH), 'archive directory not found: %s' % ARCH
    assert glob.glob(os.path.join(ARCH, 'results*.csv')), 'no results CSV under %s' % ARCH
    assert glob.glob(os.path.join(ARCH, 'race_out_*.json')), 'no race_out under %s' % ARCH
    print('selftest OK: section 1 calls a falling curve clean, a tie UNRESOLVED '
          '(never clean), a gap of exactly the quantum not evidence, and a '
          'family with no 100 row unusable; section 2 separates a slower field '
          'from one sitting on the 100 row, refuses a mixed case, drops car 0 '
          'and drops cars missing from either row; and both find the archive.')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main()
