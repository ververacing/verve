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


def parse(path):
    """-> (finished_labels, running_label_or_None, total)"""
    steps, ended, total = [], False, None
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            m = STEP.match(line.rstrip('\n'))
            if m:
                total = int(m.group(2))
                lab = LABEL.search(m.group(3))
                steps.append(lab.group(1) if lab else '?')
                continue
            if END.match(line):
                ended = True
    if not steps:
        return [], None, total
    if ended:
        return steps, None, total            # every started row also finished
    # the LAST started row has no successor and no batch-done: it is in flight
    return steps[:-1], steps[-1], total


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[-3])
        return 2
    path = argv[0]
    finished, running, total = parse(path)
    print('finished rows: %d of %s' % (len(finished), total if total else '?'))
    for lab in finished:
        print('  COMPLETE  %s' % lab)
    if running:
        print('  RUNNING   %s   <- DO NOT SCORE THIS ROW' % running)
    if '--running' not in argv and running:
        print('\nAn arm containing the RUNNING row is NOT complete, whatever the'
              ' diag files suggest.')
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
    fin, run, total = parse(p)
    assert fin == ['a_1', 'b_1'], 'got %r' % (fin,)
    assert run == 'a_2', 'in-flight row not identified: %r' % (run,)
    assert total == 6
    # 2. with batch done, EVERY started row counts
    p = w('done.log',
          '=== step 1/2 05:02:31: harness.py --label a_1\n'
          '=== step 2/2 05:27:21: harness.py --label b_1\n'
          '=== batch done 05:52:00\n')
    fin, run, _ = parse(p)
    assert fin == ['a_1', 'b_1'] and run is None, 'got %r %r' % (fin, run)
    # 3. a STOPPED batch also closes the last row (it ran to its own end or was
    #    abandoned - either way nothing more will be written to it)
    p = w('stop.log',
          '=== step 1/3 05:02:31: harness.py --label a_1\n'
          '=== batch stopped 05:30:00\n')
    fin, run, _ = parse(p)
    assert fin == ['a_1'] and run is None
    # 4. empty / headerless log must not claim anything
    p = w('empty.log', '=== batch start 05:02:31 (6 steps)\n')
    assert parse(p) == ([], None, None)
    # 5. AND THE DISCRIMINATOR: counting STEP LINES (the naive approach, and
    #    what a diag-file count is equivalent to) would have said 3 complete
    #    for case 1. Prove the two disagree, or this tool buys nothing.
    p = os.path.join(d, 'mid.log')
    naive = sum(1 for ln in io.open(p, encoding='utf-8') if ln.startswith('=== step'))
    fin, _, _ = parse(p)
    assert naive == 3 and len(fin) == 2, (
        'naive=%d parsed=%d - the tool must DISAGREE with a step/file count '
        'mid-batch, else it cannot catch the defect' % (naive, len(fin)))
    print('selftest OK: an in-flight final row is excluded, batch done/stopped '
          'closes every row, an empty log claims nothing, and the result '
          'provably DISAGREES with a naive step count mid-batch (2 v 3) - '
          'which is the error that published a partial arm as complete')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main([a for a in sys.argv[1:]]))
