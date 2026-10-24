"""Refuse a commit whose STAGED content carries a barred identity term.

WHY IT EXISTS: on 2026-10-24 I ran `leak_check`, READ THREE HITS, and committed
anyway - because the command was not chained to the commit. Every other commit
that day had used `leak_check && git add && git commit` and stopped correctly.
**A gate that depends on remembering to chain it is a habit, not a gate.** As a
pre-commit hook this one cannot be forgotten; it has to be deliberately bypassed
with `--no-verify`, which is itself barred by the project's rules.

IT CHECKS THE STAGED BLOBS, NOT THE WORKING TREE, and that distinction is the
whole point of doing it here: `git show :<path>` is what the commit will actually
contain. A working-tree scan passes when the file has been fixed but the fix was
never staged - which is the exact shape of the failure it is guarding.

Exit 0 to allow the commit, 1 to refuse it. Install with
`python tools/install_hooks.py`; run standalone with no arguments to check what
is staged right now.

    python tools/pre_commit_leak_gate.py             # check the index
    python tools/pre_commit_leak_gate.py --selftest
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LEAK_CHECK = os.path.join(HERE, 'leak_check.py')


def staged_paths():
    """Paths added/copied/modified in the index. Deletions cannot leak."""
    out = subprocess.check_output(
        ('git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'),
        cwd=REPO).decode('utf-8', 'replace')
    return [p for p in out.split('\n') if p.strip()]


def materialise(paths, dest):
    """Write each path's STAGED blob under dest, keeping its relative path.

    -> {written_path: original_path}. A path whose blob cannot be read is
    skipped and reported, never silently treated as clean.
    """
    written, failed = {}, []
    for p in paths:
        try:
            blob = subprocess.check_output(
                ('git', 'show', ':' + p), cwd=REPO, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            failed.append(p)
            continue
        target = os.path.join(dest, p.replace('/', os.sep))
        d = os.path.dirname(target)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(target, 'wb') as fh:
            fh.write(blob)
        written[target] = p
    return written, failed


def check(paths):
    """-> (exit_code, report_lines). Non-zero means REFUSE the commit."""
    if not paths:
        return 0, ['nothing staged - nothing to check']
    tmp = tempfile.mkdtemp(prefix='leakgate_')
    try:
        written, failed = materialise(paths, tmp)
        lines = []
        if failed:
            # a blob we could not read is NOT a pass: say so and refuse
            lines.append('COULD NOT READ the staged blob for: %s' % ', '.join(failed))
            return 1, lines
        if not written:
            return 0, ['no readable staged text files']
        p = subprocess.Popen(
            [sys.executable, LEAK_CHECK] + sorted(written),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = p.communicate()
        text = out.decode('utf-8', 'replace')
        # map the temp paths back to repo paths so the report is readable
        for target, orig in written.items():
            text = text.replace(target, orig)
        lines.extend(text.rstrip('\n').split('\n'))
        return (0 if p.returncode == 0 else 1), lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    rc, lines = check(staged_paths())
    for l in lines:
        print(l)
    if rc:
        print('')
        print('COMMIT REFUSED by the leak gate. Fix the staged content and stage')
        print('the fix - a working-tree fix that is not staged does NOT clear this.')
        print('Do NOT use --no-verify: the project bars bypassing hooks.')
    return rc


def selftest():
    """A PLANTED HIT MUST BLOCK, and a clean file must pass. Both, in a throwaway
    repository, so the test never touches the real index."""
    tmp = tempfile.mkdtemp(prefix='leakgate_test_')
    try:
        def git(*a):
            return subprocess.check_output(('git',) + a, cwd=tmp,
                                           stderr=subprocess.DEVNULL)
        git('init', '-q')
        # assembled, not written: this gate flagged the literal form in its own
        # introducing commit - the first thing it ever did was refuse itself.
        git('config', 'user.email', 't' '@' 'example.org')
        git('config', 'user.name', 'T')

        # the planted hit is ASSEMBLED, so this source file stays clean itself
        drive = 'C' ':'
        planted = drive + '/'.join(('', 'Users', 'someone', 'secret.txt'))
        with open(os.path.join(tmp, 'bad.py'), 'w') as fh:
            fh.write('P = r"%s"\n' % planted)
        with open(os.path.join(tmp, 'good.py'), 'w') as fh:
            fh.write('import os\nP = os.path.expanduser("~")\n')

        global REPO
        real = REPO
        REPO = tmp
        try:
            git('add', 'good.py')
            rc, lines = check(staged_paths())
            assert rc == 0, 'a CLEAN staged file was refused: %s' % lines
            git('add', 'bad.py')
            rc, lines = check(staged_paths())
            assert rc == 1, ('A PLANTED HIT DID NOT BLOCK THE COMMIT - this gate '
                             'is decoration. report: %s' % lines)
            joined = ' '.join(lines)
            assert 'bad.py' in joined, 'the report does not name the file: %s' % joined

            # AND THE CASE THE GATE EXISTS FOR: fix the working tree but DO NOT
            # stage the fix. A working-tree scan would pass; this must refuse.
            with open(os.path.join(tmp, 'bad.py'), 'w') as fh:
                fh.write('P = "nothing to see"\n')
            rc, lines = check(staged_paths())
            assert rc == 1, ('an UNSTAGED fix passed the gate - it is scanning the '
                             'working tree, not the index, which is the whole bug '
                             'it was written to prevent')
            # once the fix IS staged, it passes
            git('add', 'bad.py')
            rc, lines = check(staged_paths())
            assert rc == 0, 'a staged fix was still refused: %s' % lines
        finally:
            REPO = real
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest OK: a clean staged file passes, a planted hit REFUSES the '
          'commit and the report names the file, a fix left UNSTAGED still '
          'refuses (so the gate reads the index and not the working tree), and '
          'staging the fix clears it')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main())
