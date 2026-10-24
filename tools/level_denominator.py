"""How many kept race logs COULD have seen a foreign AI-level write?

watch.lua:51 compares the sim's level against VERVE'S OWN TARGET:

    if wl and ... math.abs(c.aiLevel - wl) > W.TOL_LVL then s.lvlBad = ...

So when Verve's target is 100 and something else writes 100 (AIWhisperer
writes 1.0), the difference is zero and the watchdog is BLIND. A race at
target 100 can neither corroborate nor refute a foreign write. The races
that can are the ones where Verve aimed BELOW 100, and that set is the real
denominator for any claim about how often the watchdog fires.

Verve's target comes from --ai-level and --profiles. NOT from --car-level,
which is the STOCK arm's level in an A/B: `--ai-level 80 --car-level 100`
means Verve raced at 80 against stock's 100.

Read-only. Joins tools/harness_results/results.csv to the kept logs in
tools/harness_results/aclogs by label.
"""
import argparse
import collections
import csv
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'harness_results', 'results.csv')
# csp_logs, NOT aclogs. This tool first read aclogs and reported a clean 0 of
# 109 because the watchdog line does not appear there AT ALL, while
# watch_tally.py - four weeks of established use - reads csp_logs and finds it
# in 59 races. A denominator tool pointed at the wrong directory returns a
# plausible zero rather than an error, so the guard is the selftest below:
# it asserts the watch line is present in the live directory.
ACLOGS = os.path.join(HERE, 'harness_results', 'csp_logs')

# the byte-identical watchdog line (watch.lua:71); watch_tally.py groups four
# weeks of logs by its shape, so it is matched and never reproduced
WATCH = 'Verve watch: Something else is changing the AI'
LVL_ON = re.compile(r'level on (\d+) cars')


def verve_target(cmd):
    """(target, why) - the level Verve aimed at, or None when cmd cannot say."""
    if '--profiles' in cmd:
        # per-car archetypes; every archetype sits below 100 by construction
        return 'profiles', 'profiles'
    m = re.search(r'--ai-level\s+(\d+(?:\.\d+)?)', cmd)
    if m:
        return float(m.group(1)), 'ai-level'
    return None, 'unstated'


def log_label(name):
    """20261024_0212_s59_lunget_base_1.log -> s59_lunget_base_1"""
    base = name[:-4] if name.endswith('.log') else name
    parts = base.split('_')
    if len(parts) > 2 and len(parts[0]) == 8 and parts[0].isdigit():
        return '_'.join(parts[2:])
    return base


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', help='only rows whose log is stamped on/after YYYYMMDD')
    ap.add_argument('--verbose', action='store_true', help='list the sub-100 races')
    args = ap.parse_args(argv)

    logs = {}
    for name in sorted(os.listdir(ACLOGS)):
        if not name.endswith('.log'):
            continue
        if args.since and name[:8] < args.since:
            continue
        logs.setdefault(log_label(name), []).append(name)

    rows = list(csv.DictReader(io.open(RESULTS, encoding='utf-8', errors='replace')))

    tally = collections.Counter()
    sub100 = []
    for r in rows:
        label = (r.get('label') or '').strip()
        cmd = r.get('cmd') or ''
        if label not in logs:
            continue                       # no kept log for this row
        tally['kept'] += 1
        if not cmd:
            tally['no_cmd'] += 1           # pre-dates the cmd column: unknowable
            continue
        if '--quali' in cmd:
            tally['not_race_only'] += 1    # a quali session reverts levels (dab3a44)
            continue
        tally['race_only'] += 1
        target, why = verve_target(cmd)
        if target is None:
            tally['target_unstated'] += 1
            continue
        if target == 'profiles' or target < 100:
            tally['sub100'] += 1
            sub100.append((label, target, why, logs[label]))
        else:
            tally['at_100_blind'] += 1

    warned_lvl, warned_any, quiet, unreadable = [], [], [], []
    for label, target, why, names in sub100:
        hit_lvl = hit_any = False
        for name in names:
            try:
                with io.open(os.path.join(ACLOGS, name), encoding='utf-8',
                             errors='replace') as fh:
                    for line in fh:
                        if WATCH in line:
                            hit_any = True
                            m = LVL_ON.search(line)
                            if m and int(m.group(1)) > 0:
                                hit_lvl = True
            except (IOError, OSError):
                unreadable.append(label)
        if hit_lvl:
            warned_lvl.append((label, target))
        elif hit_any:
            warned_any.append((label, target))
        else:
            quiet.append((label, target))

    print('kept logs joined to a results.csv row : %d' % tally['kept'])
    print('  no cmd recorded (pre-dates column)  : %d  <- UNKNOWABLE, not zero'
          % tally['no_cmd'])
    print('  carried --quali (not race-only)     : %d' % tally['not_race_only'])
    print('  race-only with a cmd                : %d' % tally['race_only'])
    print('    target unstated in cmd            : %d' % tally['target_unstated'])
    print('    target AT 100 - watchdog BLIND    : %d' % tally['at_100_blind'])
    print('    target BELOW 100 - THE DENOMINATOR: %d' % tally['sub100'])
    print()
    print('  of those %d, carrying a LEVEL warning : %d' % (tally['sub100'], len(warned_lvl)))
    print('  carrying the line for aggression only: %d' % len(warned_any))
    print('  silent                               : %d' % len(quiet))
    if unreadable:
        print('  unreadable logs                      : %d' % len(unreadable))

    if args.verbose:
        print('\n--- sub-100 races carrying a LEVEL warning ---')
        for label, target in warned_lvl:
            print('  %-34s target %s' % (label, target))
        print('--- sub-100 races silent ---')
        for label, target in quiet:
            print('  %-34s target %s' % (label, target))


def selftest():
    """A checking tool is not trusted until it has been made to FAIL."""
    # 1. --car-level must NOT be read as Verve's target. This is the exact
    #    error made on 2026-10-23: `--ai-level 80 --car-level 100` means
    #    Verve raced at 80 AGAINST stock's 100.
    t, why = verve_target('--ai-level 80 --car-level 100 --laps 12')
    assert t == 80.0, 'car-level leaked into the target: got %r' % (t,)
    assert why == 'ai-level'
    # 2. a bare --car-level race leaves the target unstated, not 100
    t, _ = verve_target('--car-level 100 --laps 12')
    assert t is None, 'car-level alone must not state a target: got %r' % (t,)
    # 3. profiles count as sub-100 even with no --ai-level
    t, _ = verve_target('--profiles all=arch_midfield --laps 12')
    assert t == 'profiles', 'profiles missed: got %r' % (t,)
    # 4. exactly 100 is BLIND, not sub-100 - the boundary this tool exists for
    t, _ = verve_target('--ai-level 100')
    assert t == 100.0 and not (t < 100), '100 must not count as sub-100'
    t, _ = verve_target('--ai-level 99')
    assert t < 100, '99 must count as sub-100'
    # 5. label join must strip the stamp and keep every underscore after it
    assert log_label('20261024_0212_s59_lunget_base_1.log') == 's59_lunget_base_1'
    assert log_label('20260920_2256_n22_imola_f3_dropcap.log') == 'n22_imola_f3_dropcap'
    # 6. the warning parser must require a NON-ZERO car count: the line is
    #    emitted when EITHER level or aggression conflicts, so "level on 0
    #    cars, aggression on 3" is an aggression warning, not a level one.
    line = WATCH + ': level on 0 cars, aggression on 3'
    m = LVL_ON.search(line)
    assert m and int(m.group(1)) == 0, 'zero-car level warning misparsed'
    line = WATCH + ': level on 2 cars, aggression on 0'
    m = LVL_ON.search(line)
    assert m and int(m.group(1)) == 2
    # 7. THE PRESENCE GUARD, and the reason it exists: this tool's first
    #    version pointed at aclogs/ and reported a clean "0 of 109" because
    #    the watchdog line does not occur there at all. A zero from the wrong
    #    directory is indistinguishable from a zero from a silent watchdog,
    #    so refuse to run against a directory where the line never appears.
    seen = 0
    for name in sorted(os.listdir(ACLOGS)):
        if not name.endswith('.log'):
            continue
        with io.open(os.path.join(ACLOGS, name), encoding='utf-8',
                     errors='replace') as fh:
            if WATCH in fh.read():
                seen += 1
                if seen >= 2:
                    break
    assert seen >= 2, (
        'the watchdog line appears in %d logs under %s - wrong directory, so '
        'any count of warnings from it would be a false zero' % (seen, ACLOGS))
    print('selftest OK: car-level cannot be read as Verve\'s target, a bare '
          'car-level leaves it unstated, profiles count sub-100, 100 is blind '
          'and 99 is not, the label join survives underscores, a '
          '"level on 0 cars" line is not counted as a level warning, and the '
          'watch line is actually PRESENT in the directory being read '
          '(%d+ logs) so a zero cannot come from a wrong path' % seen)


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main([a for a in sys.argv[1:]])
