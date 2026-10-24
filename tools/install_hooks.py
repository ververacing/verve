"""Install the pre-commit leak gate into this repository's .git/hooks.

The gate's own selftest proves the CHECK works. This file's selftest proves the
HOOK WIRING works - it builds a throwaway repository, installs the hook there,
plants a barred term, and attempts a REAL `git commit`, asserting that git
refuses it. Those are different claims: a correct checker that git never calls
is worth nothing, and that is the half a function-level test cannot see.

Writing .git/hooks is a write inside .git, so install it in a GAP between races,
never while one is running (s64's 100a died during the one race in which this
session wrote to the live .git - unproven as cause, and not repeated).

    python tools/install_hooks.py             # install, then verify
    python tools/install_hooks.py --selftest  # end-to-end, in a throwaway repo
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# `$0` is .git/hooks/pre-commit, so ../.. is the repository root. Resolved at
# run time rather than baked in, because a baked-in absolute path would be an
# identity leak in a file that lives beside the one scanning for them.
HOOK = (
    '#!/bin/sh\n'
    '# Installed by tools/install_hooks.py. Refuses a commit whose STAGED\n'
    '# content carries a barred identity term. Do NOT bypass with --no-verify.\n'
    'root="$(cd "$(dirname "$0")/../.." && pwd)"\n'
    'exec python "$root/tools/pre_commit_leak_gate.py"\n'
)


def install(repo):
    """Write the hook. -> the path written."""
    hooks = os.path.join(repo, '.git', 'hooks')
    if not os.path.isdir(hooks):
        os.makedirs(hooks)
    path = os.path.join(hooks, 'pre-commit')
    with open(path, 'w', newline='\n') as fh:     # LF: it is a shell script
        fh.write(HOOK)
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass                                       # Windows: not needed
    return path


def main():
    path = install(REPO)
    with open(path) as fh:
        body = fh.read()
    print('installed: %s (%d bytes)' % (os.path.relpath(path, REPO), len(body)))
    # READ THE WRITTEN FILE BACK rather than trusting the write
    assert 'pre_commit_leak_gate.py' in body, 'the hook does not call the gate'
    assert '--no-verify' in body, 'the hook does not carry its own warning'
    print('read back: calls the gate, carries the no-verify warning')
    print('')
    print('NOTE: a hook is per-clone and is NOT version controlled, so it does')
    print('not travel with the repository. Re-run this after any fresh clone.')
    return 0


def selftest():
    """End to end: does GIT ITSELF refuse the commit?"""
    tmp = tempfile.mkdtemp(prefix='hooktest_')
    try:
        def git(*a, **kw):
            return subprocess.call(('git',) + a, cwd=tmp,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        assert git('init', '-q') == 0
        # assembled, not written - see the note in pre_commit_leak_gate.py
        git('config', 'user.email', 't' '@' 'example.org')
        git('config', 'user.name', 'T')
        # the throwaway repo needs the real tools/ to call
        os.makedirs(os.path.join(tmp, 'tools'))
        for f in ('pre_commit_leak_gate.py', 'leak_check.py'):
            shutil.copyfile(os.path.join(HERE, f), os.path.join(tmp, 'tools', f))
        install(tmp)

        # 1. a CLEAN commit must be ALLOWED
        with open(os.path.join(tmp, 'ok.py'), 'w') as fh:
            fh.write('import os\nP = os.path.expanduser("~")\n')
        git('add', 'ok.py')
        rc_clean = git('commit', '-m', 'clean')
        assert rc_clean == 0, 'the hook blocked a CLEAN commit (rc %s)' % rc_clean

        # 2. a PLANTED HIT must be REFUSED by git itself. Assembled, so this
        #    source file stays clean.
        drive = 'C' ':'
        planted = drive + '/'.join(('', 'Users', 'someone', 'secret.txt'))
        with open(os.path.join(tmp, 'bad.py'), 'w') as fh:
            fh.write('P = r"%s"\n' % planted)
        git('add', 'bad.py')
        rc_bad = git('commit', '-m', 'should be refused')
        assert rc_bad != 0, ('GIT ACCEPTED A COMMIT CARRYING A BARRED TERM - the '
                             'hook is not wired in, whatever the gate reports')

        # 3. and the commit really did not land
        log = subprocess.check_output(('git', 'log', '--oneline'), cwd=tmp)
        assert b'should be refused' not in log, 'the refused commit landed anyway'
        n = len([l for l in log.decode().split('\n') if l.strip()])
        assert n == 1, 'expected exactly the clean commit, got %d' % n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest OK: with the hook installed in a throwaway repository, git '
          'ALLOWS a clean commit and REFUSES one carrying a barred term, and the '
          'refused commit does not land. The wiring works, not just the checker.')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main())
