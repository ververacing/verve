"""Which rows of a batch are actually FINISHED? Ask the LOG, never the diag files.

WHY THIS EXISTS, and it cost a published number on 2026-10-24: a scorer that
decides an arm is complete by counting diag files is wrong, because a diag
file is created when a race STARTS. At 07:06:29 s60_cmthold's arm 1x had
three diag files and only TWO finished races - step 5 had started 06:42:44
and step 6 did not start until 07:07:25 - so the third was read mid-race. The
arm was reported 3/3 and "complete and reportable", and its totals then moved
(attempts 229 -> 231, completions 30 -> 31) once the race actually ended.
Rows 1 and 2 were byte-identical across both reads; only the running one
changed.

A row is COMPLETE iff its `=== step N/M` line is followed in the log by
either a later step line or `=== batch done`. That is the only evidence that
the race ended rather than merely began.

AND A SECOND DEFECT, FOUND 2026-10-24 12:08 THE OTHER WAY ROUND: `s64`'s
`100a` row ENDED normally and so read COMPLETE, but produced NO DIAGNOSTICS AND
NO race_out - the log says `!! no diagnostics file produced (is diag.lua
present? did the session start?)`. A finished row is not a row with data in it.
Counting diag files called a running race complete; counting step lines calls a
DEAD race complete. Both are wrong, in opposite directions.

So a row whose block carries that warning is reported DEAD: finished, and NOT
usable. Nothing about it can be scored, and it is not a null - it is a row that
did not happen.

Read-only. Usage:
    python tools/complete_rows.py <batch.log>              # list finished labels
    python tools/complete_rows.py <batch.log> --running     # also name the in-flight row
"""
import io
import re
import sys

STEP = re.compile(r'^=== step (\d+)/(\d+) [\d:]+: harness\.py (.*)$')
END = re.compile(r'^=== batch (done|stopped)')
LABEL = re.compile(r'--label (\S+)')
# the harness's own words when a race produced nothing
NODIAG = re.compile(r'no diagnostics file produced')


def parse(path):
    """-> (finished_labels, running_label_or_None, total, dead_labels)

    `finished_labels` EXCLUDES dead rows: a caller that only reads the first
    return value must not be handed a row with no data in it.
    """
    steps, ended, total, dead = [], False, None, []
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            m = STEP.match(line)
            if m:
                total = int(m.group(2))
                lab = LABEL.search(m.group(3))
                steps.append(lab.group(1) if lab else '?')
                continue
            if NODIAG.search(line) and steps:
                # the warning sits inside the CURRENT step's block
                if steps[-1] not in dead:
                    dead.append(steps[-1])
                continue
            if END.match(line):
                ended = True
    if not steps:
        return [], None, total, dead
    if ended:
        done, run = steps, None              # every started row also finished
    else:
        # the LAST started row has no successor and no batch-done: in flight
        done, run = steps[:-1], steps[-1]
    return [s for s in done if s not in dead], run, total, dead


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[-3])
        return 2
    path = argv[0]
    finished, running, total, dead = parse(path)
    print('finished rows: %d of %s%s' % (
        len(finished), total if total else '?',
        '   (%d DEAD, excluded)' % len(dead) if dead else ''))
    for lab in finished:
        print('  COMPLETE  %s' % lab)
    for lab in dead:
        print('  DEAD      %s   <- finished but produced NO diagnostics and no'
              ' race_out. NOT a null: the race did not happen.' % lab)
    if running:
        print('  RUNNING   %s   <- DO NOT SCORE THIS ROW' % running)
    if '--running' not in argv and running:
        print('\nAn arm containing the RUNNING row is NOT complete, whatever the'
              ' diag files suggest.')
    if dead:
        print('\nA DEAD row must be RE-RUN, not interpreted. An arm missing one is'
              ' short by one, and any per-arm figure quoted from it is quoted from'
              ' a smaller n than the queue file claims.')
    return 0


def selftest():
    """A checking tool is not trusted until it has been made to FAIL."""
    import os
    import tempfile
    d = tempfile.mkdtemp()

    def w(name, text):
        p = os.path.join(d, name)
        io.open(p, 'w', encoding='utf-8').write(text)
        return p

    # 1. THE EXACT CASE THAT CAUSED THE DEFECT: three steps started, no
    #    batch-done. The third is IN FLIGHT and must not be counted.
    p = w('mid.log',
          '=== batch start 05:02:31 (6 steps)\n'
          '=== step 1/6 05:02:31: harness.py --laps 12 --label a_1\n'
          '=== step 2/6 05:27:21: harness.py --laps 12 --label b_1\n'
          '=== step 3/6 05:53:02: harness.py --laps 12 --label a_2\n')
    fin, run, total, dead = parse(p)
    assert fin == ['a_1', 'b_1'], 'got %r' % (fin,)
    assert run == 'a_2', 'in-flight row not identified: %r' % (run,)
    assert total == 6 and dead == []
    # 2. with batch done, EVERY started row counts
    p = w('done.log',
          '=== step 1/2 05:02:31: harness.py --label a_1\n'
          '=== step 2/2 05:27:21: harness.py --label b_1\n'
          '=== batch done 05:52:00\n')
    fin, run, _, dead = parse(p)
    assert fin == ['a_1', 'b_1'] and run is None and dead == [], 'got %r %r %r' % (fin, run, dead)
    # 3. a STOPPED batch also closes the last row (it ran to its own end or was
    #    abandoned - either way nothing more will be written to it)
    p = w('stop.log',
          '=== step 1/3 05:02:31: harness.py --label a_1\n'
          '=== batch stopped 05:30:00\n')
    fin, run, _, _ = parse(p)
    assert fin == ['a_1'] and run is None
    # 4. empty / headerless log must not claim anything
    p = w('empty.log', '=== batch start 05:02:31 (6 steps)\n')
    assert parse(p) == ([], None, None, [])
    # 5. AND THE DISCRIMINATOR: counting STEP LINES (the naive approach, and
    #    what a diag-file count is equivalent to) would have said 3 complete
    #    for case 1. Prove the two disagree, or this tool buys nothing.
    p = os.path.join(d, 'mid.log')
    naive = sum(1 for ln in io.open(p, encoding='utf-8') if ln.startswith('=== step'))
    fin, _, _, _ = parse(p)
    assert naive == 3 and len(fin) == 2, (
        'naive=%d parsed=%d - the tool must DISAGREE with a step/file count '
        'mid-batch, else it cannot catch the defect' % (naive, len(fin)))
    # 6. THE SECOND DEFECT, in the opposite direction: a row that ENDED but
    #    produced no diagnostics must be DEAD, not COMPLETE. This is s64's
    #    100a verbatim - the warning sits inside its own step block.
    p = w('deadrow.log',
          '=== step 1/3 11:00:00: harness.py --label a_1\n'
          '[a_1 #1] monza x3 laps, 8 cars, budget 840s\n'
          '  leader_laps=3  running_at_end=8\n'
          '=== step 2/3 11:51:16: harness.py --label a_2\n'
          '[a_2 #1] monza x3 laps, 8 cars, budget 840s\n'
          '  !! no diagnostics file produced (is diag.lua present? did the session start?)\n'
          '=== step 3/3 12:05:46: harness.py --label a_3\n'
          '=== batch done 12:13:00\n')
    fin, run, _, dead = parse(p)
    assert dead == ['a_2'], 'the dead row was not identified: %r' % (dead,)
    assert fin == ['a_1', 'a_3'], 'a dead row leaked into finished: %r' % (fin,)
    assert run is None
    # and the warning must be attributed to the row it belongs to, not the next
    assert 'a_3' not in dead and 'a_1' not in dead, 'warning attributed to the wrong row'
    print('selftest OK: an in-flight final row is excluded, batch done/stopped '
          'closes every row, an empty log claims nothing, the result provably '
          'DISAGREES with a naive step count mid-batch (2 v 3), and a row that '
          'ENDED but produced no diagnostics is reported DEAD and kept out of '
          'the finished list - attributed to its own step block, not a neighbour')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main([a for a in sys.argv[1:]]))
