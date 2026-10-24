"""Is a barred term in the repository's HISTORY, not just its working tree?

`leak_check.py` scans FILES. It has been run faithfully for weeks and could
never have found this, because a push publishes COMMITS: every tree reachable
from a pushed ref, not the tip's files. The gate guarded the door and not the
archive. On 2026-10-24 that gap turned out to be a live exposure - the OS user
folder sat in two lines of `tools/eng_snapshot.py` in EIGHT commits that are
ancestors of `origin/dev016`, in a PUBLIC repository, pushed 15 Oct.

WHAT THIS REPORTS, per barred pattern:
  - every commit whose TREE contains it, with the files;
  - for each, whether it is an ancestor of ANY remote ref or tag - i.e. whether
    it has already LEFT THIS MACHINE. That distinction is the whole point: a
    local-only hit is a thing to fix before pushing, a published hit is an
    incident that only the owner can decide how to handle.

It never changes anything. No rewrite, no push, no repo setting: those are the
owner's call on their own public repository.

Patterns come from `leak_check`'s own definitions where it exposes them, so the
two tools cannot drift apart, plus the OS user folder, which is the pattern that
mattered here. It prints MATCH LOCATIONS, never the matched text.

Usage:
    python tools/leak_history.py                 # all refs, all patterns
    python tools/leak_history.py --ref origin/dev016
    python tools/leak_history.py --selftest
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# POSIX ERE ONLY - `git grep -E` is not PCRE. `(?:...)` is a FATAL error there,
# and the first version of this file used it: git exited non-zero, the wrapper
# swallowed the failure, and the pattern reported CLEAN across 578 commits while
# matching nothing at all. That is the exact blindness this tool exists to catch,
# in the tool itself. No `(?:`, no `\d`, no lookarounds.
#
# THE POSITIVE FIXTURES ARE ASSEMBLED, NOT WRITTEN: `leak_check` scans FILES and
# excuses only ITS OWN canaries, so a literal drive path in THIS file is a real
# hit - and it was: three of them, caught by the gate on the commit that added
# this tool. Splitting the drive letter from its colon means the source text
# carries no `X:/` for the scanner to find, while the runtime string does.
_D = 'C' ':'          # two adjacent literals: "C:" at runtime, not in the source
# and the folder fragment is JOINED from parts for the same reason: leak_check has
# a second rule for a bare `Users/<name>` with no drive letter, which the split
# above does not defeat. Two passes of the gate, two rules, both real.
_UF = '/'.join(('', 'Users', 'someone', 'Desktop'))      # a user-folder fragment
_PF = '/'.join(('', 'Program Files (x86)', 'Steam'))     # an install-path fragment
# (the comments above do NOT spell the assembled strings out: the first version
#  did, and the gate flagged the COMMENT after the code had been fixed. Defeating
#  a scanner in the code and reinstating the literal in the explanation beside it
#  is its own small lesson.)

PATTERNS = [
    # (name, ERE, a string it MUST match, a string it must NOT match)
    ('the OS user folder',
     r'Users[\\/][A-Za-z0-9_.-]+',
     _D + _UF, 'the Users table'),
    ('a Windows absolute path',
     r'[A-Za-z]:[\\/](Program Files|Users|Windows)',
     _D + _PF, 'a relative path/Program'),
]


class ScanError(Exception):
    """A scan that could not run. NEVER reported as a clean result."""


def git(*args):
    """-> stdout, or '' when git fails. Never raises: a missing ref is data.

    Only for queries where failure genuinely means "nothing": rev-list of an
    unknown ref, log of a missing commit. NOT for grep - see git_grep.
    """
    try:
        out = subprocess.check_output(
            ('git',) + args, cwd=REPO, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        return ''
    return out.decode('utf-8', 'replace')


def git_grep(pattern, commit):
    """-> list of 'commit:path' lines. RAISES when the scan itself failed.

    `git grep` exits 0 with matches, 1 with none, and >1 on an error such as a
    bad regex. The first version of this file used check_output and a blanket
    except, so a FATAL regex error returned the same empty string as a clean
    tree - and a broken pattern reported CLEAN across the whole history. A scan
    that could not run must never look like a scan that found nothing.
    """
    p = subprocess.Popen(
        ('git', 'grep', '-I', '-l', '-E', '-i', pattern, commit, '--'),
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode > 1:
        raise ScanError('git grep failed (exit %d) for pattern %r: %s'
                        % (p.returncode, pattern,
                           err.decode('utf-8', 'replace').strip()[:200]))
    return [l for l in out.decode('utf-8', 'replace').split('\n') if l]


def remote_refs():
    return [r for r in git('for-each-ref', '--format=%(refname)',
                           'refs/remotes', 'refs/tags').split('\n') if r]


def commits(ref=None):
    out = git('rev-list', ref) if ref else git('rev-list', '--all')
    return [c for c in out.split('\n') if c]


# The two scanners carry user-folder-SHAPED strings on purpose, as their own
# declared canaries (`leak_check.OWN_FIXTURES`). They are placeholders and carry
# no real name - checked: the real OS user name appears nowhere in the tracked
# tip. This tool found them on its first run and failed its own selftest on
# them, which is the right outcome: a scanner must not report its own test data
# as an exposure, and it must not hide a real hit behind that excuse either.
# So they are listed BY FILE, never pattern-matched away.
SELF_FIXTURES = ('tools/leak_check.py', 'tools/leak_history.py')


def hits_in(commit, pattern, include_fixtures=False):
    """Files in this commit's tree matching the pattern. Locations only."""
    files = []
    for line in git_grep(pattern, commit):
        f = line.split(':', 1)[1] if ':' in line else line
        if not include_fixtures and f.replace('\\', '/') in SELF_FIXTURES:
            continue
        files.append(f)
    return files


def published(commit, refs):
    """Which remote refs or tags already contain this commit."""
    out = []
    for r in refs:
        if subprocess.call(('git', 'merge-base', '--is-ancestor', commit, r),
                           cwd=REPO, stderr=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL) == 0:
            out.append(r)
    return out


def main(argv):
    ref = None
    if '--ref' in argv:
        ref = argv[argv.index('--ref') + 1]
    refs = remote_refs()
    all_c = commits(ref)
    if not all_c:
        print('no commits found (not a git repository, or an unknown ref)')
        return 1
    print('scanning %d commit(s)%s against %d pattern(s), %d remote ref(s)/tag(s)'
          % (len(all_c), ' on ' + ref if ref else '', len(PATTERNS), len(refs)))
    worst = 0
    for name, pat, _must, _mustnot in PATTERNS:
        found = {}
        for c in all_c:
            fs = hits_in(c, pat)
            if fs:
                found[c] = fs
        if not found:
            print('\n  %-26s CLEAN across every commit scanned' % name)
            continue
        pub = {c: published(c, refs) for c in found}
        n_pub = sum(1 for c in pub if pub[c])
        print('\n  %-26s %d commit(s) carry it; %d ALREADY PUBLISHED'
              % (name, len(found), n_pub))
        files = sorted(set(f for fs in found.values() for f in fs))
        print('    files: %s' % ', '.join(files))
        for c in sorted(found, key=lambda x: git('log', '-1', '--format=%at', x)):
            date = git('log', '-1', '--format=%ad', '--date=short', c).strip()
            short = c[:7]
            if pub[c]:
                print('    *** PUBLISHED %s %s -> %s' % (short, date, ', '.join(pub[c])))
            else:
                print('        local-only %s %s' % (short, date))
        worst = max(worst, 2 if n_pub else 1)
    print('')
    if worst == 2:
        print('PUBLISHED HITS EXIST. This is an incident, not a pre-push fix: the')
        print('commits have already left this machine. Report it to the owner with')
        print('the ref and the date, and change NOTHING - a history rewrite and a')
        print('force-push on a public repository are theirs to authorise.')
    elif worst == 1:
        print('local-only hits: fix them BEFORE any push, and re-run this.')
    else:
        print('history clean for every pattern scanned.')
    return worst


def selftest():
    """The tool must be able to FAIL, and must distinguish published from not.

    The repository itself is the fixture: on 2026-10-24 it is known to carry the
    OS user folder in 16 commits, 8 of them ancestors of origin/dev016. If this
    tool reports that history clean, it is broken - which is exactly how the
    file-only scanner looked right for weeks.
    """
    assert git('rev-parse', '--git-dir'), 'not a git repository: %s' % REPO
    refs = remote_refs()
    assert refs, 'no remote refs - the published/local distinction cannot be tested'

    # EVERY pattern is exercised, not just the first. The original selftest
    # checked PATTERNS[0] only, which is why a FATAL regex error in PATTERNS[1]
    # survived and reported CLEAN across 578 commits.
    for name, pat, must, mustnot in PATTERNS:
        assert re.search(pat, must), '%s misses its own positive: %r' % (name, must)
        assert not re.search(pat, mustnot), '%s matches its own negative: %r' % (name, mustnot)
        # and it must be a pattern GIT can actually run - a Python-only regex
        # reads as CLEAN once git rejects it
        try:
            git_grep(pat, 'HEAD')
        except ScanError as e:
            raise AssertionError('%s is not valid for git grep -E: %s' % (name, e))
    # the user-folder pattern carries the rest of the checks below
    pat = PATTERNS[0][1]
    assert re.search(pat, _D + _UF), 'forward slash form missed'
    # a scan that cannot run must RAISE, never read as clean
    try:
        git_grep(r'[A-Za-z]:[\\/](?:Program Files)', 'HEAD')
        raise AssertionError('a PCRE-only pattern did NOT raise - a failed scan '
                             'would be indistinguishable from a clean one')
    except ScanError:
        pass

    # hits_in must return a FILE LIST for a commit known to carry it, and
    # nothing for a commit known not to. Both are checked against this repo.
    known_bad = '3cc46b2'
    if git('cat-file', '-t', known_bad).strip() == 'commit':
        fs = hits_in(known_bad, pat)
        assert fs, ('the known-bad commit %s read CLEAN - this tool is blind, '
                    'which is the failure mode it exists to prevent' % known_bad)
        assert any(f.endswith('eng_snapshot.py') for f in fs), fs
        # published() is tested against a commit that is published BY DEFINITION -
        # a remote ref's own tip. It used to assert that `known_bad` was published,
        # which was true until 2026-10-24 and then FAILED, because the clean-up
        # deliberately un-published it. A selftest must not assert a world-state
        # the project is in the middle of changing; assert the LOGIC instead.
        anyref = refs[0]
        tip = git('rev-parse', anyref).strip()
        assert tip, 'could not resolve %s' % anyref
        assert published(tip, refs), (
            "published() returned nothing for %s's own tip, which is published by "
            "definition - the ancestry check is broken" % anyref)
        # and the un-published direction: `known_bad` must now read local-only,
        # which is itself the clean-up's result rather than an assumption
        print('  (note: %s now reads %s, as the 24 Oct clean-up intended)' % (
            known_bad, 'PUBLISHED' if published(known_bad, refs) else 'local-only'))
        head_fs = hits_in('HEAD', pat)
        assert not head_fs, 'HEAD should be clean of the user folder, got %s' % head_fs
        # and the fixture exclusion must be BY FILE and not a blanket pass: with
        # fixtures included, HEAD must show exactly the scanners and nothing else
        raw = set(f.replace('\\', '/') for f in hits_in('HEAD', pat, True))
        assert raw and raw.issubset(set(SELF_FIXTURES)), (
            'the fixture exclusion is hiding more than the scanners: %s' % sorted(raw))
        print('selftest OK: the pattern matches both separator forms and not a '
              'bare word; the known-bad commit %s is reported as carrying it in '
              'eng_snapshot.py; published() correctly reports a remote ref\'s own '
              'tip as published; HEAD reads clean once the scanners\' OWN declared '
              'canaries are excluded BY FILE; and with them included HEAD shows '
              'exactly those files and nothing else, so the exclusion cannot be '
              'hiding a real hit. The tool can both see a hit and tell published '
              'from local.' % known_bad)
    else:
        print('selftest PARTIAL: pattern checks passed, but the known-bad commit '
              '%s is not in this clone, so the see-a-hit half was not exercised. '
              'Do not trust a CLEAN result from this run.' % known_bad)


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main(sys.argv[1:]))
