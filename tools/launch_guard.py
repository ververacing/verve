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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BRANCH = 'dev016'
#: DERIVED, never written out - a hardcoded path here would put the machine's user folder, and so the owner's
#: real first name, into a committed file. leak_check flags exactly that.
DESK = os.path.join(os.path.expanduser('~'), 'Documents', 'Assetto Corsa', 'verve_desk')
GAMES = ('acs.exe', 'acs_x86.exe', 'AssettoCorsa.exe', 'F1_25.exe', 'F1_24.exe',
         'AC2-Win64-Shipping.exe')      # acs_x86.exe added 2026-10-24: the install ships both, and a guard that
                                        # misses the 32-bit build would clear a launch while the owner is racing on it


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


#: Declarations a queue header must carry. EVERY ONE IS HERE BECAUSE ITS ABSENCE COST A REAL DEFECT, and the
#: defect is named so nobody deletes a line thinking it is ceremony.
REQUIRED_HEADER = (
    ('PRIOR CELLS', 'the archive search for cells that already ran this experiment'),
    ('TERMS', 'the search TERMS used - a grep on the cell NAME missed every prior cell that ran the same '
              'experiment under a different word, and an archived finding was nearly reported as new (25 Oct)'),
    ('MUTANT', 'the premise gate was made to FAIL before being trusted, WITH A CONTROL CASE - on 25 Oct four '
               'mutants behaved while the real gate excluded every row, and only the control exposed it'),
    ('MEASURABLE', 'what this n can and cannot resolve, stated BEFORE the result exists'),
    ('SPEC CLAUSE', 'which FIELD each measure reads - the diag last snapshot\'s live pos misread a star\'s '
                    'finish by TEN PLACES, three times now (use tools/classify.py)'),
    ('SCORER DRY-RUN', 'the scorer run on partial rows before the cell lands - it caught a ladder gate copied '
                       'from a cell of a different design, which would have voided ten sound races'),
    ('PREMISE TEST', 'is the quantity the gate reads one the TREATMENT CAN MOVE? If yes it is an OUTCOME, not a '
                     'premise - gating on it lets the treatment disqualify its own cell, biased toward a null'),
)

#: How long a named cell must sit before it may be armed, so a peer can object in time.
NAMED_WAIT_S = 600


def check_header_guard(path, vary):
    """The queue's COMMENT header must carry every declaration in REQUIRED_HEADER."""
    head = '\n'.join(l for l in io.open(path, encoding='utf-8', errors='replace').read().splitlines()
                     if l.lstrip().startswith('#')).upper()
    if not head.strip():
        return False, 'the queue has NO comment header at all - it must declare what it is and how it is scored'
    missing = [(k, why) for k, why in REQUIRED_HEADER if k not in head]
    if missing:
        return False, ('header is missing %d declaration(s):\n%s'
                       % (len(missing), '\n'.join('      %-15s %s' % (k, why) for k, why in missing)))
    # THE PRIOR-CELLS SEARCH MUST SHOW ITS OUTPUT, NOT CLAIM IT WAS RUN. s72's header listed eight search terms
    # and a hits list I had compiled FROM MEMORY; running the terms afterwards returned 42 lines for one of
    # them and a result that spoke directly against the cell's premise (LESSONS:997). The guard accepted it
    # because it only checked that the word TERMS was present. A list of terms is a claim like any other.
    # So: require at least two checkable line references - `LESSONS:997`, `docs/decisions/0027`, `s71b` with a
    # line number - because a reference with a number can be verified against the file and prose cannot.
    refs = re.findall(r'(?:LESSONS|lessons)[^\n]{0,12}?:\s*(\d{1,5})', head) + re.findall(r':(\d{2,5})\b', head)
    if len(set(refs)) < 2:
        return False, ('PRIOR CELLS names no checkable line references. Paste the grep OUTPUT - e.g.'
                       ' "LESSONS:997, LESSONS:1234" - not a prose summary. Found %d; need 2.'
                       ' A list of search terms is a claim, not evidence that they were run.' % len(set(refs)))
    return True, ('header carries all %d declarations and %d checkable line reference(s)'
                  % (len(REQUIRED_HEADER), len(set(refs))))


#: Where a prior cell's verdict can live. The guard greps these itself.
ARCHIVE_PATHS = (
    os.path.join(DESK, 'docs', 'LESSONS.md'),
    os.path.join(DESK, 'racecraft', 'state.md'),
    os.path.join(DESK, 'pc2', 'LESSONS_pending.md'),
    os.path.join(DESK, 'pc2', 'state.md'),
)
#: A term yielding more than this many hits was not really searched, it was waved at. Narrow it.
MAX_TERM_HITS = 25


def _varied_keys(raw):
    """Keys inside the JSON-bearing flags whose VALUE differs between rows, or which only some rows carry.

    These are the things the batch is actually testing, so they are the things its archive search must cover.
    Read from the row text rather than from `--vary`, because the levers live inside `--racecraft {...}`,
    `--csp {...}`, `--settings {...}` and friends, and `--vary` only ever names the outer flag.
    """
    rows = [l.strip() for l in raw.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    if len(rows) < 2:
        return set()
    # NAMES FIRST, VALUES SECOND, because a single scanning regex gets this wrong on NESTED JSON: matching
    # `"KEY"\s*:\s*[^,}]+` against `"AI_TWEAKS":{"FIX_GRIP_MULT":0}` consumes the inner key inside the outer
    # key's value, so the leaf lever is never seen and the container is flagged instead. The selftest caught
    # exactly that - it demanded FIX_GRIP_MULT and got AI_TWEAKS.
    names = set()
    for r in rows:
        names |= set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]{2,40})"\s*:', r))
    out = set()
    for k in names:
        vals = []
        for r in rows:
            m = re.search(r'"%s"\s*:\s*([^,}]*)' % re.escape(k), r)
            vals.append(m.group(1).strip() if m else None)
        # a CONTAINER key is not a lever - its value differs only because a leaf inside it differs, and
        # demanding a search term for "AI_TWEAKS" would be noise.
        if any(v is not None and v.startswith('{') for v in vals):
            continue
        # VARIED means MORE THAN ONE DISTINCT VALUE AMONG THE ROWS THAT CARRY IT - absent-vs-present is NOT a
        # variation here. Found while building s73: a 5-cell suite sets `--assists` on its formula cell only, so
        # an absent-counts-as-different rule flagged DAMAGE, FUEL_RATE and TYRE_WEAR as levers and demanded an
        # archive search for each. They are per-cell configuration, not the thing under test. The present-in-
        # some-rows-only case has a proper home in check_rows_vary_only, which refuses it unless declared.
        present = [v for v in vals if v is not None]
        if len(set(present)) > 1:
            out.add(k)
    return out


def check_prior_cells(path, vary):
    """RUN the header's declared search terms and require every hit to be accounted for.

    WHY THIS AND NOT "PASTE THE OUTPUT": verve-47's point, and it is right - pasted output is still a claim.
    s72's header declared eight terms and a hits list I had compiled FROM MEMORY; the real grep returned 42
    lines for `FIX_GRIP_MULT` alone, including `LESSONS:997` ("IT IS NEW_LATERAL_GRIP_ESTIMATION, NOT
    FIX_GRIP_MULT"), which spoke directly against the cell's stated premise. The guard passed it because it
    checked only that the word TERMS appeared. **So the guard does the searching.**

    Every hit must be either CITED by line number in the header, or dismissed there with a reason. A hit that
    is neither refuses the launch. And a term with more than MAX_TERM_HITS hits refuses as TOO BROAD, because
    requiring eighty line numbers in a header would make the guard unusable and the first thing anyone would do
    is work around it - a guard nobody can satisfy is a guard that gets deleted.
    """
    raw = io.open(path, encoding='utf-8', errors='replace').read()
    head = '\n'.join(l for l in raw.splitlines() if l.lstrip().startswith('#'))
    if 'TERMS' in head.upper():
        terms = sorted(set(re.findall(r'"([^"]{3,40})"', head[head.upper().find('TERMS'):][:600])))
    else:
        terms = []
    if not terms:
        return False, 'PRIOR CELLS declares no quoted search TERMS, so there is nothing to verify'
    # THE DODGE THE HIT CAP OPENS, and verve-47 spotted it: pick terms narrow enough to return nothing
    # ("starclimb3") and the check passes having searched for something that was never going to be there.
    # So: EVERY KEY THE BATCH ACTUALLY VARIES must appear in at least one term. s72 varies the `--csp` key
    # FIX_GRIP_MULT, so it would be forced to search it - which is precisely the search it skipped.
    varied = _varied_keys(raw)
    uncovered = [k for k in varied if not any(k.lower() in t.lower() for t in terms)]
    if uncovered:
        return False, ('the batch VARIES %d key(s) that no search term covers: %s.'
                       ' A term list that omits the thing under test has not searched the archive for it.'
                       % (len(uncovered), ', '.join(sorted(uncovered))))

    cited = set(re.findall(r':(\d{1,5})\b', head)) | set(re.findall(r'\bL(\d{2,5})\b', head))
    missing, broad = [], []
    for t in terms:
        # COMPOUND TERMS: "A+B" matches a line containing BOTH parts, so a varied key with more hits than the
        # cap can be narrowed to a citable set instead of being dropped. Without this, the cap and the
        # coverage rule would contradict each other for any key the archive discusses a lot.
        parts = [p.strip().lower() for p in t.split('+') if p.strip()]
        hits = []
        for p in ARCHIVE_PATHS:
            if not os.path.exists(p):
                continue
            for i, line in enumerate(io.open(p, encoding='utf-8', errors='replace'), 1):
                low = line.lower()
                if all(q in low for q in parts):
                    hits.append((os.path.basename(p), i))
        if len(hits) > MAX_TERM_HITS:
            broad.append((t, len(hits)))
            continue
        for fn, i in hits:
            if str(i) not in cited:
                missing.append((t, fn, i))
    if broad:
        return False, ('%d search term(s) are TOO BROAD to have been searched - narrow them:\n%s'
                       % (len(broad), '\n'.join('      %-24s %d hits (cap %d)' % (t, n, MAX_TERM_HITS)
                                                for t, n in broad)))
    if missing:
        shown = missing[:8]
        return False, ('%d archive hit(s) are neither cited nor dismissed in the header'
                       ' - cite the line or say "not relevant: <reason>":\n%s%s'
                       % (len(missing),
                          '\n'.join('      %-24s %s:%d' % (t, fn, i) for t, fn, i in shown),
                          '\n      ... and %d more' % (len(missing) - 8) if len(missing) > 8 else ''))
    return True, 'all %d declared term(s) searched; every hit cited or dismissed' % len(terms)


def check_named_and_waited(path, vary):
    """A `<queue>.NAMED` sidecar must exist and be at least NAMED_WAIT_S old.

    WHY A FILE RATHER THAN A PROMISE: the naming window was broken five times in its "name then wait" form and
    three more in the "name before building" form, every time because elapsed time was judged rather than read.
    On 24/25 Oct my own clock statements drifted up to 72 MINUTES, and one of those wrong readings is what
    convinced me a launch was urgent. A sidecar's mtime is not a thing anyone has to remember or estimate.
    FAILS CLOSED: an unreadable or empty sidecar refuses the launch.
    """
    side = path + '.NAMED'
    if not os.path.exists(side):
        return False, ('no %s beside the queue - name the cell to the cloud, write what you named into that '
                       'file, then launch once it is %d s old' % (os.path.basename(side), NAMED_WAIT_S))
    try:
        body = io.open(side, encoding='utf-8', errors='replace').read().strip()
        age = time.time() - os.path.getmtime(side)
    except OSError as e:
        return False, 'cannot read %s (%s) - refusing, because a guard that cannot check must not pass' \
                      % (os.path.basename(side), e)
    if not body:
        return False, '%s is EMPTY - it must hold what was named, or it records nothing' % os.path.basename(side)
    if age < NAMED_WAIT_S:
        return False, ('named %d s ago; the window is %d s, so %d s still to wait'
                       % (int(age), NAMED_WAIT_S, int(NAMED_WAIT_S - age)))
    return True, 'named %d s ago (window %d s), %d chars recorded' % (int(age), NAMED_WAIT_S, len(body))


CHECKS = (check_queue_readable, check_rows_vary_only, check_owner_not_playing,
          check_branch_and_tree, check_no_stale_harness_lua,
          check_header_guard, check_prior_cells, check_named_and_waited)


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

        # 4c. THE HEADER GUARD. Each case removes exactly ONE declaration and demands a refusal naming it -
        #     a guard that passes a header missing a line is worse than none, because it certifies the gap.
        full_head = (''.join('# %s: filled in\n' % k for k, _ in REQUIRED_HEADER)
                     + '# hits: LESSONS:997, LESSONS:1234\n')
        rows2 = '--laps 3 --label a\n--laps 3 --label b\n'
        hdr_ok = os.path.join(tmp, 'h_ok.txt')
        io.open(hdr_ok, 'w', encoding='utf-8').write(full_head + rows2)
        ok, msg = check_header_guard(hdr_ok, [])
        assert ok, 'a COMPLETE header was refused, so every case below proves nothing: %s' % msg
        for k, _why in REQUIRED_HEADER:
            part = ''.join('# %s: filled in\n' % o for o, _ in REQUIRED_HEADER if o != k)
            p = os.path.join(tmp, 'h_%s.txt' % re.sub(r'\W', '', k))
            io.open(p, 'w', encoding='utf-8').write(part + rows2)
            ok, msg = check_header_guard(p, [])
            assert not ok, 'header missing %r PASSED - the guard certifies the gap' % k
            assert k in msg, 'the refusal does not name the missing %r: %s' % (k, msg)
        #     A HEADER WITH EVERY DECLARATION BUT NO CHECKABLE LINE REFERENCE MUST STILL REFUSE. This is the
        #     hole s72 went through: all seven declarations present, and a prior-cells list written from memory.
        noref = os.path.join(tmp, 'h_noref.txt')
        io.open(noref, 'w', encoding='utf-8').write(
            ''.join('# %s: filled in\n' % k for k, _ in REQUIRED_HEADER)
            + '# hits: I searched the archive and found the relevant cells\n' + rows2)
        ok, msg = check_header_guard(noref, [])
        assert not ok and 'checkable line reference' in msg, \
            'a prior-cells claim with NO line numbers passed - the guard accepts the claim as the evidence: %s' % msg
        #     one reference is not enough either, or the threshold is decorative
        oneref = os.path.join(tmp, 'h_oneref.txt')
        io.open(oneref, 'w', encoding='utf-8').write(
            ''.join('# %s: filled in\n' % k for k, _ in REQUIRED_HEADER)
            + '# hits: LESSONS:997\n' + rows2)
        ok, msg = check_header_guard(oneref, [])
        assert not ok, 'a single line reference passed where two are required'
        #     and a queue with no header at all is refused rather than treated as "nothing to check"
        bare = os.path.join(tmp, 'bare.txt')
        io.open(bare, 'w', encoding='utf-8').write(rows2)
        ok, msg = check_header_guard(bare, [])
        assert not ok and 'NO comment header' in msg, msg

        # 4c-bis. THE PRIOR-CELLS CHECK RUNS THE SEARCH ITSELF. verve-47's point: pasted grep output is still a
        #     claim, so the guard greps. Two cases, and the second is the real s72 shape.
        #     (i) a term narrow enough to have no archive hits, fully accounted for -> passes
        pc_ok = os.path.join(tmp, 'pc_ok.txt')
        io.open(pc_ok, 'w', encoding='utf-8').write(
            '# PRIOR CELLS. TERMS: "zzq_no_such_term_anywhere_42"\n'
            '# HITS: none.\n' + rows2)
        ok, msg = check_prior_cells(pc_ok, [])
        assert ok, 'a term with zero archive hits and nothing to cite was refused: %s' % msg
        #     (ii) NO declared terms at all -> refuses, or the check is skippable by omission
        pc_bad = os.path.join(tmp, 'pc_bad.txt')
        io.open(pc_bad, 'w', encoding='utf-8').write('# PRIOR CELLS: I looked at the archive.\n' + rows2)
        ok, msg = check_prior_cells(pc_bad, [])
        assert not ok and 'no quoted search TERMS' in msg, msg
        #     (ii-bis) A TERM WITH A FEW REAL HITS, NONE CITED -> must refuse naming them. Without this case
        #     the missing-hit path is NEVER EXERCISED: the s72 case below refuses as TOO BROAD and case (i) has
        #     no hits at all, so neutering the missing-hit branch left the selftest passing. Found by mutating
        #     it, which is the whole point of mutating every branch rather than every function.
        if any(os.path.exists(p) for p in ARCHIVE_PATHS):
            pc_few = os.path.join(tmp, 'pc_few.txt')
            io.open(pc_few, 'w', encoding='utf-8').write(
                '# PRIOR CELLS. TERMS: "SESSION_SALT"\n'
                '# HITS: none cited on purpose.\n' + rows2)
            ok, msg = check_prior_cells(pc_few, [])
            assert not ok and 'neither cited nor dismissed' in msg, \
                ('a term with real, UNCITED archive hits passed - the missing-hit branch is dead: %s' % msg)
            #   ...and citing them satisfies it, or the branch is unsatisfiable
            import re as _re
            lines = []
            for _p in ARCHIVE_PATHS:
                if os.path.exists(_p):
                    for _i, _l in enumerate(io.open(_p, encoding='utf-8', errors='replace'), 1):
                        if 'session_salt' in _l.lower():
                            lines.append(_i)
            pc_ok2 = os.path.join(tmp, 'pc_ok2.txt')
            io.open(pc_ok2, 'w', encoding='utf-8').write(
                '# PRIOR CELLS. TERMS: "SESSION_SALT"\n'
                '# HITS: %s\n' % ', '.join('LESSONS:%d' % i for i in lines) + rows2)
            ok, msg = check_prior_cells(pc_ok2, [])
            assert ok, 'citing every hit still refused, so the check cannot be satisfied: %s' % msg

        #     (ii-ter) THE ZERO-HIT DODGE: terms narrow enough to find nothing, while the batch varies a key
        #     none of them names. verve-47's catch - the hit cap would otherwise reward picking useless terms.
        dodge = os.path.join(tmp, 'pc_dodge.txt')
        io.open(dodge, 'w', encoding='utf-8').write(
            '# PRIOR CELLS. TERMS: "zzq_no_such_term_anywhere_42"\n'
            '# HITS: none.\n'
            '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":1}} --label a\n'
            '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":0}} --label b\n')
        ok, msg = check_prior_cells(dodge, [])
        assert not ok and 'VARIES' in msg and 'FIX_GRIP_MULT' in msg, \
            ('a batch varying FIX_GRIP_MULT passed with terms that never mention it: %s' % msg)
        #     and a key that is the SAME in every row is not "varied", so it must not be demanded
        same = os.path.join(tmp, 'pc_same.txt')
        io.open(same, 'w', encoding='utf-8').write(
            '# PRIOR CELLS. TERMS: "zzq_no_such_term_anywhere_42"\n'
            '# HITS: none.\n'
            '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":1}} --label a\n'
            '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":1}} --label b\n')
        ok, msg = check_prior_cells(same, [])
        assert ok, 'a key held CONSTANT across rows was demanded as a search term: %s' % msg
        #     COMPOUND TERMS: "A+B" needs both parts on the line, so a busy key can be narrowed to a citable
        #     set rather than dropped - otherwise the cap and the coverage rule contradict each other.
        if any(os.path.exists(p) for p in ARCHIVE_PATHS):
            comp = os.path.join(tmp, 'pc_comp.txt')
            io.open(comp, 'w', encoding='utf-8').write(
                '# PRIOR CELLS. TERMS: "FIX_GRIP_MULT+zzq_no_such_pairing_42"\n'
                '# HITS: none - the compound matches nothing.\n'
                '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":1}} --label a\n'
                '--laps 3 --csp {"AI_TWEAKS":{"FIX_GRIP_MULT":0}} --label b\n')
            ok, msg = check_prior_cells(comp, [])
            assert ok, ('a COMPOUND term covering the varied key and matching no lines was refused, so a busy'
                        ' key could never be narrowed: %s' % msg)

        #     (iii) THE s72 MUTANT: a broad term, uncited. `FIX_GRIP_MULT` returns ~42 lines in LESSONS and my
        #     header cited five. It must refuse - as TOO BROAD (the honest reading: a term with 42 hits was
        #     waved at, not searched) rather than demanding 42 line numbers, which nobody would comply with.
        if any(os.path.exists(p) for p in ARCHIVE_PATHS):
            pc_s72 = os.path.join(tmp, 'pc_s72.txt')
            io.open(pc_s72, 'w', encoding='utf-8').write(
                '# PRIOR CELLS. TERMS: "FIX_GRIP_MULT"\n'
                '# HITS: LESSONS:856, LESSONS:571\n' + rows2)
            ok, msg = check_prior_cells(pc_s72, [])
            assert not ok, ('THE s72 HEADER PASSED: a term with dozens of archive hits and five cited was'
                            ' accepted, which is the exact hole this check was added to close')
            assert 'TOO BROAD' in msg or 'neither cited nor dismissed' in msg, msg

        # 4d. THE NAMING WINDOW. The whole point is that it REFUSES A LAUNCH THAT IS TOO EARLY, so that is the
        #     case to prove; the window was broken eight times when it depended on judging elapsed time.
        nq = os.path.join(tmp, 'named.txt')
        io.open(nq, 'w', encoding='utf-8').write(full_head + rows2)
        ok, msg = check_named_and_waited(nq, [])
        assert not ok and 'no named.txt.NAMED' in msg, 'a missing sidecar must refuse: %s' % msg
        io.open(nq + '.NAMED', 'w', encoding='utf-8').write('')
        ok, msg = check_named_and_waited(nq, [])
        assert not ok and 'EMPTY' in msg, 'an empty sidecar records nothing and must refuse: %s' % msg
        io.open(nq + '.NAMED', 'w', encoding='utf-8').write('s99: named to the cloud at 04:40')
        ok, msg = check_named_and_waited(nq, [])
        assert not ok and 'still to wait' in msg, \
            'A JUST-NAMED CELL WAS ALLOWED TO LAUNCH - this is the exact failure the window exists to stop: %s' % msg
        #     and it ALLOWS once the window has passed (back-date the sidecar rather than sleep 10 minutes)
        old = time.time() - (NAMED_WAIT_S + 30)
        os.utime(nq + '.NAMED', (old, old))
        ok, msg = check_named_and_waited(nq, [])
        assert ok, 'a cell named %d s ago was still refused, so the check can never pass: %s' % (NAMED_WAIT_S, msg)
        assert 'named' in msg and 'chars recorded' in msg, msg

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
          'queue and duplicate labels all refuse; the --optional exemption covers '
          'only what is declared and does not leak; a header missing ANY ONE of '
          'the %d required declarations refuses AND the refusal names it, while a '
          'complete header passes; a queue with no header at all refuses; and the '
          'naming window refuses a missing sidecar, an EMPTY sidecar and a '
          'JUST-NAMED cell, then allows one named over %d s ago; the prior-cells '
          'check RUNS the declared terms against the archive and refuses a header '
          'with no terms, a term too broad to have been searched (cap %d hits) and '
          'a term whose real hits are uncited, while citing every hit satisfies it; '
          'it also refuses a batch whose terms omit a key the rows actually VARY '
          '(and does not demand one for a key held constant, nor for a JSON '
          'container), and accepts a COMPOUND "A+B" term so a busy key can be '
          'narrowed instead of dropped; a fully passing set allows'
          % (len(REQUIRED_HEADER), NAMED_WAIT_S, MAX_TERM_HITS))


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        sys.exit(main([a for a in sys.argv[1:]]))
