"""Refuse to launch a queue when a pre-launch check fails OR THROWS.

WHY IT EXISTS, and the distinction is the whole point: on 2026-10-24 I verified a
one-row addendum was byte-identical to the row it repeats, the check RAISED a
TypeError (a regex matched nothing and the comparison got None), and the launch
command in the same shell block RAN ANYWAY. The row happened to be correct, so it
cost nothing - but that was luck, not process.

**A GUARD WHOSE FAILURE MODE IS "THE CHECK ERRORED, SO PROCEED" IS WORSE THAN NO
GUARD, because it reports confidence it has not earned.** So every check here runs
inside a try/except and an exception is a REFUSAL, reported as "CHECK CRASHED",
never as a pass. That is the one behaviour its selftest is built around.

Built the way the pre-commit hook is built: one gate, unskippable in the sense
that the launch happens only through it.

    python tools/launch_guard.py <queue.txt>                      # check, then launch
    python tools/launch_guard.py <queue.txt> --dry-run            # check only
    python tools/launch_guard.py <queue.txt> --vary ai-level,label
    python tools/launch_guard.py --selftest
"""
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BRANCH = 'dev016'
GAMES = ('acs.exe', 'AssettoCorsa.exe', 'F1_25.exe', 'F1_24.exe',
         'AC2-Win64-Shipping.exe')


def _tasklist():
    """Image names currently running. NO SWITCHES: MSYS rewrites /FI into a path
    and the resulting error goes to STDOUT, so the filtered form once counted
    zero processes with a race running (LESSONS, 22 Oct and again 24 Oct)."""
    out = subprocess.check_output(('tasklist',), stderr=subprocess.DEVNULL)
    return out.decode('utf-8', 'replace').lower()


def rows_of(path):
    """Runnable rows: a header comment is not a row."""
    return [l.rstrip('\n') for l in io.open(path, encoding='utf-8', errors='replace')
            if l.strip() and not l.lstrip().startswith('#')]


# ---- the checks. Each returns (ok, message) and may raise; raising is a refusal.

def check_queue_readable(path, vary):
    rows = rows_of(path)
    if not rows:
        return False, 'the queue file declares NO runnable rows'
    labels = [re.search(r'--label (\S+)', r) for r in rows]
    if not all(labels):
        return False, 'a row has no --label'
    names = [m.group(1) for m in labels]
    if len(set(names)) != len(names):
        return False, 'duplicate labels: %s' % [n for n in names if names.count(n) > 1]
    return True, '%d row(s), %d distinct labels' % (len(rows), len(set(names)))


def check_rows_vary_only(path, vary, optional=()):
    """Every row identical except the flags the caller DECLARED may vary.

    This is the check that crashed. It now normalises by substituting each
    declared flag's value, and **a flag ABSENT from a row where others have it
    is itself a difference** - which a naive regex substitution hides, and which
    is the "unstated difference inside one cell" that voids an A/B.

    `optional` NAMES the flags whose presence-or-absence IS the manipulation.
    The ON/OFF convention in this project is exactly that: 172 archived rows
    pass `--settings {"enabled":false}` to switch Verve off and NONE passes
    `enabled:true` to switch it on - absence is ON. Declaring the exception by
    name keeps the strict default for every other flag, rather than loosening
    the rule for all of them or inventing an untested flag value to satisfy it.
    """
    if not vary and not optional:
        return True, 'no --vary given, row-identity not checked (say so in the verdict)'
    rows = rows_of(path)
    if len(rows) < 2:
        return True, 'single row, nothing to compare'
    norm = []
    for r in rows:
        s = r
        for f in vary:
            s = re.sub(r'--%s(\s+\S+)?' % re.escape(f), '--%s X' % f, s)
        for f in optional:
            # REMOVE it entirely, so present-and-absent normalise alike
            s = re.sub(r'\s*--%s(\s+\S+)?' % re.escape(f), '', s)
        norm.append(s)
    if len(set(norm)) != 1:
        # name the first differing pair rather than just failing
        base = norm[0]
        for i, s in enumerate(norm[1:], 1):
            if s != base:
                return False, ('row 1 and row %d differ in something other than %s'
                               % (i + 1, ', '.join('--' + f for f in vary)))
    # and every declared-VARYING flag must be PRESENT in every row or absent in
    # all. Declared-OPTIONAL flags are exempt by definition - that is what the
    # declaration means - and are reported so the exemption is visible.
    for f in vary:
        have = [bool(re.search(r'--%s\b' % re.escape(f), r)) for r in rows]
        if any(have) and not all(have):
            return False, ('--%s is present in some rows and absent in others,'
                           ' which is an unstated difference' % f)
    note = ', '.join('--' + f for f in vary) or 'nothing'
    if optional:
        note += '; %s exempt from the present-in-all rule' % ', '.join(
            '--' + f for f in optional)
    return True, 'all %d rows identical except %s' % (len(rows), note)


def check_owner_not_playing(path, vary):
    tl = _tasklist()
    up = [g for g in GAMES if ('\n' + g.lower()) in tl or tl.startswith(g.lower())]
    if up:
        return False, 'a game is running (%s) - the owner always wins' % ', '.join(up)
    return True, 'no game process running'


def check_branch_and_tree(path, vary):
    br = subprocess.check_output(('git', 'rev-parse', '--abbrev-ref', 'HEAD'),
                                 cwd=REPO).decode().strip()
    if br != BRANCH:
        return False, 'on branch %s, expected %s' % (br, BRANCH)
    dirty = subprocess.check_output(
        ('git', 'status', '--porcelain', '--untracked-files=no'),
        cwd=REPO).decode().strip()
    if dirty:
        return False, 'tracked changes uncommitted:\n    %s' % dirty.replace('\n', '\n    ')
    return True, 'on %s, no tracked changes' % BRANCH


def check_no_stale_harness_lua(path, vary):
    p = os.path.join(REPO, 'harness.lua')
    if os.path.exists(p):
        return True, 'harness.lua PRESENT (the harness rewrites it at launch) - noted, not blocking'
    return True, 'no stale harness.lua'


CHECKS = (check_queue_readable, check_rows_vary_only, check_owner_not_playing,
          check_branch_and_tree, check_no_stale_harness_lua)


def run_checks(path, vary, checks=CHECKS, optional=()):
    """-> (all_ok, lines). AN EXCEPTION IS A REFUSAL, never a pass."""
    ok_all, lines = True, []
    for fn in checks:
        name = fn.__name__.replace('check_', '')
        try:
            try:
                ok, msg = fn(path, vary, optional)
            except TypeError:
                ok, msg = fn(path, vary)
        except Exception as e:                      # noqa - deliberate catch-all
            ok_all = False
            lines.append('  CHECK CRASHED  %-22s %s: %s'
                         % (name, type(e).__name__, str(e)[:90]))
            continue
        if not ok:
            ok_all = False
        lines.append('  %-6s %-22s %s' % ('ok' if ok else 'REFUSE', name, msg))
    return ok_all, lines


def main(argv):
    if not argv or argv[0].startswith('--'):
        print(__doc__.strip().split('\n\n')[-1])
        return 2
    path = argv[0]
    vary = []
    optional = []
    if '--optional' in argv:
        optional = [f.strip().lstrip('-') for f in argv[argv.index('--optional') + 1].split(',')
                    if f.strip()]
    if '--vary' in argv:
        vary = [f.strip().lstrip('-') for f in argv[argv.index('--vary') + 1].split(',')
                if f.strip()]
    dry = '--dry-run' in argv

    print('launch_guard: %s' % os.path.basename(path))
    ok, lines = run_checks(path, vary, optional=optional)
    for l in lines:
        print(l)
    if not ok:
        print('\nLAUNCH REFUSED. Fix the cause and re-run - do not launch around this.')
        print('A check that CRASHED is a refusal, not a pass: an errored check has')
        print('told you nothing, and proceeding on it is how a row gets launched')
        print('unverified.')
        return 1
    if dry:
        print('\nall checks pass; --dry-run, so nothing launched')
        return 0
    print('\nall checks pass - launching')
    subprocess.Popen(
        [sys.executable, '-u', os.path.join('tools', 'batch.py'), path],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
    print('batch.py started detached; verify acs.exe comes up within a minute')
    return 0


def selftest():
    """THE CENTREPIECE: a CRASHING check must refuse the launch."""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix='lg_')
    try:
        good = os.path.join(tmp, 'q.txt')
        io.open(good, 'w', encoding='utf-8').write(
            '# header\n'
            '--laps 3 --ai-level 80 --label a\n'
            '--laps 3 --ai-level 90 --label b\n')

        # 1. the row-identity check passes when only the declared flags vary
        ok, msg = check_rows_vary_only(good, ['ai-level', 'label'])
        assert ok, msg
        # 2. and FAILS when something undeclared differs
        bad = os.path.join(tmp, 'bad.txt')
        io.open(bad, 'w', encoding='utf-8').write(
            '--laps 3 --ai-level 80 --label a\n'
            '--laps 4 --ai-level 90 --label b\n')
        ok, msg = check_rows_vary_only(bad, ['ai-level', 'label'])
        assert not ok and 'other than' in msg, msg
        # 3. a flag present in one row and absent in another is a difference
        half = os.path.join(tmp, 'half.txt')
        io.open(half, 'w', encoding='utf-8').write(
            '--laps 3 --car-level 100 --label a\n'
            '--laps 3 --label b\n')
        ok, msg = check_rows_vary_only(half, ['label'])
        assert not ok, 'a flag missing from one row passed: %s' % msg
        # 4. no rows, and duplicate labels
        empty = os.path.join(tmp, 'e.txt')
        io.open(empty, 'w', encoding='utf-8').write('# only a comment\n')
        ok, msg = check_queue_readable(empty, [])
        assert not ok and 'NO runnable rows' in msg, msg
        dup = os.path.join(tmp, 'd.txt')
        io.open(dup, 'w', encoding='utf-8').write(
            '--laps 3 --label a\n--laps 3 --label a\n')
        ok, msg = check_queue_readable(dup, [])
        assert not ok and 'duplicate' in msg, msg

        # 4b. THE --optional EXEMPTION: it must exempt ONLY what is declared.
        #     An untested escape hatch in a guard is how the guard gets quietly
        #     weakened, which is this tool's own subject matter.
        onoff = os.path.join(tmp, 'onoff.txt')
        io.open(onoff, 'w', encoding='utf-8').write(
            '--laps 3 --label a\n'
            '--laps 3 --settings {"enabled":false} --label b\n')
        ok, msg = check_rows_vary_only(onoff, ['label'])
        assert not ok, 'present-in-some is meant to refuse without a declaration'
        ok, msg = check_rows_vary_only(onoff, ['label'], optional=['settings'])
        assert ok, 'the declared exemption did not take effect: %s' % msg
        assert 'exempt' in msg, 'the report hides that an exemption was used: %s' % msg
        #     and the exemption must NOT leak to an undeclared flag
        leak = os.path.join(tmp, 'leak.txt')
        io.open(leak, 'w', encoding='utf-8').write(
            '--laps 3 --car-level 100 --label a\n'
            '--laps 3 --settings {"enabled":false} --label b\n')
        ok, msg = check_rows_vary_only(leak, ['label'], optional=['settings'])
        assert not ok, ('the exemption LEAKED - --car-level differs in presence and'
                        ' was not declared, yet the rows passed')

        # 5. **THE ONE THIS FILE EXISTS FOR: A CHECK THAT RAISES MUST REFUSE.**
        def crasher(path, vary):
            raise TypeError("expected string or bytes-like object, got 'NoneType'")
        ok, lines = run_checks(good, [], checks=(crasher,))
        assert not ok, 'A CRASHING CHECK DID NOT REFUSE THE LAUNCH - this guard is decoration'
        assert any('CHECK CRASHED' in l for l in lines), lines
        assert any('TypeError' in l for l in lines), 'the report hides WHAT crashed: %s' % lines

        # 6. a check that returns False refuses too, and a passing set allows
        ok, _ = run_checks(good, [], checks=(lambda p, v: (False, 'no'),))
        assert not ok
        ok, _ = run_checks(good, [], checks=(lambda p, v: (True, 'yes'),))
        assert ok

        # 7. and the crash must not be rescued by a later passing check
        ok, lines = run_checks(good, [], checks=(crasher, lambda p, v: (True, 'yes')))
        assert not ok, 'a later passing check overrode an earlier crash'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest OK: a CRASHING check REFUSES the launch and the report names '
          'the exception type; a later passing check cannot override it; an '
          'undeclared row difference, a flag present in only some rows, an empty '
          'queue and duplicate labels all refuse; and a fully passing set allows')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main([a for a in sys.argv[1:]]))
