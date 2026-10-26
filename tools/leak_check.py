"""Gate anything that is about to LEAVE this machine: does it carry the real name, an email, or a Windows path?

    python tools/leak_check.py <file-or-dir> [...]      # exit 1 if anything is found
    python tools/leak_check.py --list                   # show what it looks for, without the values

The identity rule: the public identity is TC Verve / ververacing, and the real name, the old tags, the work email and
Windows paths never appear in anything that leaves here - commits, issues, READMEs, changelogs, videos, and now the
race transcripts we push to the engineer's repo.

THIS FILE LIVES IN A PUBLIC REPO, so it cannot contain the strings it hunts for - writing them down here would leak
exactly what it exists to prevent. Instead it derives them at runtime from the machine (the OS user name, the home
directory) and matches generic shapes: any email address, any Users\\<name> fragment, and a drive-letter path ONLY
where Users, Program Files or Documents follows the drive letter - a bare C:\\Windows\\Temp or D:\\New Volume PASSES,
which is deliberate (see the canary comment in --selftest) and pinned by a selftest case. So "leak_check clean"
NEVER means "no Windows path in here"; say which rules it checked. Extra
terms - the old tags, anything else the owner wants barred - go one per line in tools/.identity_deny, which is
gitignored and never read aloud: the report says WHICH RULE matched and the line number, never the matched text.

Written 2026-10-11, when the first race transcripts were about to be pushed to a repo. PC #2 checked its own output
before letting it onto the shared desk; this is the same check, made repeatable and made part of the push.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DENY_FILE = os.path.join(HERE, ".identity_deny")
TEXT_EXT = {".md", ".txt", ".json", ".jsonl", ".csv", ".lua", ".py", ".ini", ".yml", ".yaml", ".html", ".sh", ""}


def rules():
    """(name, compiled pattern) pairs. Values derived at runtime so none of them is written down here."""
    out = [
        ("a Windows absolute path", re.compile(r"\b[A-Za-z]:[\\/]+(?:Users|Program Files|Documents)", re.I)),
        ("a Users\\<name> fragment", re.compile(r"\bUsers[\\/]+[A-Za-z0-9._-]+", re.I)),
        ("an email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ]
    for var in ("USERNAME", "USER"):
        v = (os.environ.get(var) or "").strip()
        if len(v) >= 3:
            out.append(("the OS user name", re.compile(r"\b" + re.escape(v) + r"\b", re.I)))
    home = os.path.basename(os.path.expanduser("~")).strip()
    if len(home) >= 3:
        out.append(("the home directory name", re.compile(r"\b" + re.escape(home) + r"\b", re.I)))
    if os.path.isfile(DENY_FILE):
        n = 0
        for line in open(DENY_FILE, encoding="utf-8", errors="replace"):
            t = line.strip()
            if t and not t.startswith("#"):
                out.append((f"a barred term (.identity_deny line {n + 1})", re.compile(re.escape(t), re.I)))
                n += 1
    # the public identity is allowed, so drop any rule that would match it
    # The public identity is allowed. The commit attribution is NOT listed here: a rule is dropped when it matches
    # anything in this tuple, and the email-address rule matches an email address - so putting one here deletes
    # email detection altogether. It cost me a self-test to see that. Attribution is skipped per LINE instead.

    allowed = ("tcverve", "ververacing", "tc verve")
    keep = []
    for name, rx in out:
        if any(rx.search(a) for a in allowed):
            continue
        keep.append((name, rx))
    return keep


def files_of(paths, unresolved=None):
    """Yield the files to scan. A path that resolves to NOTHING is recorded in `unresolved`, never ignored.

    It used to be silently skipped, which made the tool able to say "clean" about files it never opened:
    one real file plus two bogus paths reported "1 file(s) clean", and a path mangled by shell word-splitting
    reported "0 file(s) clean" with exit 0 - a vacuous pass. PC #2 hit exactly that composing this tool into a
    ledger stamper (2026-10-12): unquoted paths containing "Assetto Corsa" split, nothing resolved, and the
    wrapper minted a PASS for an unexamined file. A gate that cannot tell "I checked these and they are clean"
    from "I checked nothing" is not a gate.
    """
    for p in paths:
        if os.path.isdir(p):
            found = False
            for root, _, names in os.walk(p):
                for n in names:
                    if os.path.splitext(n)[1].lower() in TEXT_EXT:
                        found = True
                        yield os.path.join(root, n)
            if not found and unresolved is not None:
                unresolved.append(p + "  (directory, no scannable files in it)")
        elif os.path.isfile(p):
            yield p
        elif unresolved is not None:
            unresolved.append(p)


# Deliberate fake fixtures in THIS FILE's own selftest. They must match the rules - that is their job - so when
# this file's source turns up inside a diff the tool detects its own canaries. Excused in DIFF MODE ONLY, never
# when scanning fixtures directly, so selftest() still requires every one of them to fire.
# The third entry is PROSE, not the path itself, on purpose. The docstring below explains the escaped-path bug
# by quoting a path with four literal backslashes, and matching that by substring means counting backslashes
# through two layers of escaping - which is the exact trap that makes this a rule of its own ("write files
# directly; never generate them through nested escaping"). I got the count wrong on the first attempt and the
# gate still reported one leak. The surrounding sentence is unambiguous and cannot be miscounted.
OWN_FIXTURES = ("someone@example.org", "C:/Users/someone",
                "with two backslashes and the rule never fired")


def scan_text(label, text, rs, diff_mode=False, excuse_fixtures=False):
    """-> hit count. Scans a text blob line by line, printing where and which rule, never the match itself.

    diff_mode changes two things, and both were found by running this tool over a real 130-commit release range
    where it reported SIX leaks and every one was a false positive:

      1. ONLY ADDED LINES ARE SCANNED. A `-` line is being DELETED by this range, so it is a FIX, not a leak -
         the range removed an absolute path from harness.py and the tool reported that removal as a leak. The
         already-pushed history still holds the old line either way, so a forward-looking gate cares only about
         what the range ADDS.
      2. THIS FILE'S OWN SELFTEST FIXTURES ARE EXCUSED (see OWN_FIXTURES). Three of the six were this tool's own
         canaries appearing in its own diff, which is the self-match trap procs.py documents.

    KNOWN LIMITATION, left deliberately: the OS-user-name rule fired on a racing reference table's driver name -
    a real NASCAR competitor who happens to share a first name with the OS user. Those lines were removals so
    (1) silenced them, but an ADDED reference row would fire again. Left strict on purpose: loosening a name
    rule is exactly how a real name gets out, and the right response to a hit is to look at it.

    AND THE NAME IS NOT REPEATED HERE, WHICH IS THE POINT. Documenting that false positive by quoting the name
    put the OS user's own first name into this file and into a commit message, and the gate immediately flagged
    both - correctly, because the rule is about the string leaving the machine, not about whose name it is. A
    coincidence is not an exemption. Describe such a hit, never quote it.
    """
    hits = 0
    for i, line in enumerate(text.split("\n"), 1):
        if "noreply@anthropic.com" in line or line.lstrip().lower().startswith("co-authored-by:"):
            continue
        if diff_mode:
            if not line.startswith("+") or line.startswith("+++"):
                continue
        # THIS TOOL'S OWN FIXTURES ARE EXCUSED IN EVERY MODE. The excusal used to sit inside the diff_mode branch
        # above, while FILE scanning ran a SEPARATE inline copy of this loop in main() that had no excusal at all
        # - so the identity gate reported 4 leaks in leak_check.py on every run, permanently, all of them this
        # file's own canaries and comment examples. A gate that always fails on a known false positive is a gate
        # everyone learns to wave through, which is worse than no gate. main() now calls this function instead.
        # SCOPED TO THIS FILE, not excused globally: a placeholder path or example.org address has a legitimate
        # reason to exist HERE and nowhere else in the app, so the same token in any other file still fires.
        if (diff_mode or excuse_fixtures or os.path.basename(str(label)).lower() == "leak_check.py") \
                and any(f in line for f in OWN_FIXTURES):
            continue
        for name, rx in rs:
            if rx.search(line):
                print("  LEAK  %s:%d  <- %s" % (label, i, name))
                hits += 1
                break
    return hits


def check_range(rng, rs):
    """Gate a git range: the DIFF and the COMMIT MESSAGES, which also leave the machine.

    WHY A RANGE MODE EXISTS. On 2026-10-14 this tool reported "15 file(s) clean" on a push that carried four
    absolute Windows paths, and the push went out needing a 27th commit to remove them. Two separate gaps:
      1. The path rules assumed ONE separator after the drive letter - `[A-Za-z]:[\\/]` - but Python SOURCE holds
         those paths escaped, so the text is `C:\\\\Program Files` with two backslashes and the rule never fired.
         The Users-fragment rule missed it for the same reason. Both now use `[\\/]+`.
      2. COMMIT MESSAGES WERE NEVER SCANNED AT ALL. The tool took file paths, so a message naming a local path or
         the real name would have published it with a clean verdict from this very tool.
    Checking the messages by hand before a push was my habit, which is not a gate. Now it is the tool's job.
    """
    out = 0
    for what, cmd in (("diff", ["git", "diff", rng]), ("messages", ["git", "log", "--format=%B", rng])):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        except Exception as e:                                             # noqa: BLE001
            print("  REFUSED: cannot read the %s for %s (%s)" % (what, rng, e))
            return 1
        if r.returncode != 0:
            print("  REFUSED: `%s` failed - not vouching for anything" % " ".join(cmd))
            return 1
        if not r.stdout.strip():
            print("  REFUSED: the %s for %s is EMPTY - a vacuous pass is how this tool failed before" % (what, rng))
            return 1
        # The DIFF is scanned additions-only; the MESSAGES are scanned whole, because every commit message in
        # the range is new text leaving the machine - there is no "removed" message.
        out += scan_text("<%s %s>" % (what, rng), r.stdout, rs, diff_mode=(what == "diff"))
    print("leak_check range %s: %s" % (rng, "CLEAN (diff and commit messages)" if out == 0 else "%d LEAK(S)" % out))
    return 1 if out else 0


TEXT_EXT = (".lua", ".md", ".ini", ".json", ".txt", ".py", ".sh", ".csv", ".cfg", ".yml", ".yaml", "")


def refs_of(kind):
    """Every ref of a kind, as git itself lists them - never a hand-kept list.

    A hand-kept list is how the first scan of this repo came to cover three branches and MISS ALL 34 TAGS.
    """
    spec = {"branches": ["refs/remotes/origin"], "tags": ["refs/tags"],
            "all": ["refs/remotes/origin", "refs/tags"]}[kind]
    r = subprocess.run(["git", "for-each-ref", "--format=%(refname:short)"] + spec,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return []
    out = [x.strip() for x in r.stdout.split("\n") if x.strip() and not x.strip().endswith("/HEAD")]
    return out


def check_tree(ref, rs, quiet=False):
    """Scan the files a ref PUBLISHES - its TREE as someone checking it out sees it, not its history.

    WHY THIS IS A SEPARATE MODE, and the gap it closes. --history answers "what does pushing this range
    reveal?". It does NOT answer "what does someone who opens this tag see?" - and those differ, because a TAG
    CARRIES ITS OWN TREE FOR EVER. A string removed from main on Monday is still in the current content of
    every tag cut before Monday, and GitHub serves each tag as a browsable tree plus a source download. So a
    repo can have a clean main, a clean push range, and still publish the string on 20 release pages.

    Found by verve-47 on 2026-10-16: the three-branch scan this tool had just been given passed, while tags
    carried identity material in the CURRENT CONTENT of three files. A tag is not history; it is a live page.
    """
    r = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("  REFUSED: cannot list the tree of %s - not vouching for anything" % ref)
        return 1
    paths = [p.strip() for p in r.stdout.split("\n") if p.strip()]
    if not paths:
        print("  REFUSED: the tree of %s is EMPTY - a vacuous pass is how this tool failed before" % ref)
        return 1
    hits = scanned = 0
    for p in paths:
        if not p.lower().endswith(TEXT_EXT):
            continue
        b = subprocess.run(["git", "show", "%s:%s" % (ref, p)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if b.returncode != 0:
            continue
        scanned += 1
        hits += scan_text("%s:%s" % (ref, p), b.stdout, rs, excuse_fixtures=True)
    if not scanned:
        print("  REFUSED: %s has no scannable text file - refusing a vacuous pass" % ref)
        return 1
    if not quiet:
        print("  tree %-28s %s (%d file(s) scanned)"
              % (ref, "%d FLAGGED LINE(S)" % hits if hits else "clean", scanned))
    return 1 if hits else 0


def check_refs(kind, mode, rs):
    """Run the gate over EVERY ref of a kind and report per ref. Returns non-zero if any ref is dirty."""
    refs = refs_of(kind)
    if not refs:
        print("  REFUSED: no %s refs found - refusing a vacuous pass" % kind)
        return 1
    print("leak_check over %d %s ref(s), mode=%s" % (len(refs), kind, mode))
    dirty = []
    for ref in refs:
        bad = 0
        if mode in ("tree", "both"):
            bad += check_tree(ref, rs, quiet=False)
        if mode in ("history", "both"):
            bad += check_history(ref, rs)
        if bad:
            dirty.append(ref)
    print("")
    if dirty:
        print("leak_check: %d of %d %s ref(s) carry identity material:" % (len(dirty), len(refs), kind))
        for d in dirty:
            print("    " + d)
        print("  A TAG CANNOT BE FIXED FORWARD: it is a fixed tree. Retagging or deleting a published tag is")
        print("  the owner's call, and anyone who already downloaded it keeps what they got.")
        return 1
    print("leak_check: all %d %s ref(s) clean (mode=%s)" % (len(refs), kind, mode))
    return 0


def already_public(ref, rs, timeout=600):
    """-> set of hashes of every rule-matching line ALREADY in `ref`'s history, or None if it cannot be read.

    WHY THIS EXISTS. After a history rewrite, `--history` over the rewritten span re-reports every flagged line
    in it, including ones that have been public for weeks - on 2026-10-22 it blocked a push on 15 such lines:
    selftest fixtures with a synthetic user component, and a standard third-party install path. None was
    identity, none was new, and the current tree was clean of all of them.

    The two obvious ways out are both bad. Loosening a name rule to let a push through is how a real name
    escapes, and the file says so. Hand-listing the fixture strings in OWN_FIXTURES rebuilds the maintained list
    whose forgetting is the failure mode we keep hitting elsewhere - a list only ever covers what someone
    thought to name.

    So this answers the question the gate actually means: does this push publish anything barred that is NOT
    ALREADY OUT THERE? A flagged line whose exact text is already in the remote's history is not newly
    published by a rewrite that carries it forward unchanged. Matching is on the LINE TEXT, deliberately
    context-free: the question is whether the string is already public, not where it sits.

    Returns None rather than an empty set when the remote cannot be read, so the caller can fail CLOSED - an
    unreachable remote must never read as "nothing is public yet", which would excuse everything.
    """
    try:
        r = subprocess.run(["git", "log", "-p", "--format=%H", ref], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:                                                     # noqa: BLE001
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    seen = set()
    for line in r.stdout.split("\n"):
        if any(rx.search(line) for _, rx in rs):
            seen.add(hash(line.rstrip()))
    return seen


def check_identity(rng, rs, quiet=False):
    """Item 12: gate the AUTHOR and COMMITTER fields of every commit a push would publish. -> hit count.

    WHY THIS IS A SEPARATE CHECK rather than more text fed to scan_text: the public identity's own address WOULD
    be flagged by the generic email rule, because `rules()` drops a rule only when it matches an allow-listed
    string and 'tcverve' has no '@' in it. Pipe `%ae` through scan_text and every commit ever made flags - a gate
    that always fails is a gate everyone waves through. So this check INVERTS the logic: it asks whether each
    field IS the public identity, and reports the ones that are not, by FIELD NAME, never by value.

    The allowance is deliberately narrow: a name equal to the public name or handle, and an email whose local
    part is one of those handles, plus the forge/assistant no-reply addresses that commits legitimately carry.
    Anything else is a hit - a personal address, a work address, a machine account, a real name - without this
    file having to know what any of them look like.
    """
    fields = ("author name", "author email", "committer name", "committer email")
    SEP = chr(31)
    cmd = ["git", "log", "--format=%H" + SEP + "%an" + SEP + "%ae" + SEP + "%cn" + SEP + "%ce", rng]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except Exception as e:                                                # noqa: BLE001
        print("  REFUSED: cannot read the identity fields for %s (%s)" % (rng, e))
        return 1
    if r.returncode != 0:
        print("  REFUSED: git log failed for %s" % rng)
        return 1
    handles = tuple(a.replace(" ", "") for a in ("tcverve", "ververacing"))
    noreply = ("noreply@anthropic.com", "noreply@github.com")
    hits, commits = 0, 0
    for row in r.stdout.splitlines():
        if not row.strip():
            continue
        parts = row.split(SEP)
        if len(parts) != 5:
            continue
        commits += 1
        sha, vals = parts[0], parts[1:]
        for fname, val in zip(fields, vals):
            v = (val or "").strip()
            low = v.lower()
            if "email" in fname:
                ok = (low in noreply or low.endswith("@users.noreply.github.com")
                      or low.split("@")[0] in handles)
            else:
                ok = low.replace(" ", "") in handles
            if not ok:
                print("  LEAK  %s %s  <- not the public identity" % (sha[:12], fname))
                hits += 1
    if not quiet:
        print("  identity fields %-28s %s (%d commit(s))"
              % (rng, "clean" if not hits else "%d FLAGGED FIELD(S)" % hits, commits))
    return hits


def check_history(rng, rs, against=None):
    """Gate a range the way it will actually be PUBLISHED: every commit's patch, ADDITIONS AND REMOVALS ALIKE.

    WHY THIS EXISTS, and it is a correction to check_range's own reasoning. check_range scans `git diff <range>`
    additions-only, on the stated grounds that a `-` line is a FIX and "the already-pushed history still holds
    the old line either way". That is sound for history that is ALREADY PUBLIC and wrong for a range about to be
    pushed: on push, every commit in the range becomes public, so a line this range REMOVES is a line it
    PUBLISHES. The distinction that matters is not added-versus-removed, it is pushed-versus-unpushed.

    AND THE BIGGER GAP IS `git diff` ITSELF: it reports the NET change. A path added in one commit and removed in
    a later one of the SAME RANGE cancels out and appears in NEITHER side of the net diff. On 2026-10-16 exactly
    that happened here - an absolute path carrying the OS user folder was committed, then fixed forward seven
    commits later - and `leak_check --range` reported the push range "13 file(s) clean" while two commits in it
    carried the name. `git log -p` is the only view that sees both. A fix-forward cannot un-publish a name; it
    adds a second copy, as a removal line.

    So this mode scans `git log -p` (patches AND messages in one stream) with NO additions-only filter. The
    fixture excusal stays on, or this tool's own canaries fire out of its own history.
    The remedy for a hit here is a squash or a rewrite, never another forward fix - and if the range is already
    pushed, it is the owner's call, because it means rewriting public history.
    """
    # The commit hash is emitted INTO the stream so every hit can be attributed. Without it the scan can only
    # give a line offset into a 60,000-line blob, which is useless for deciding what to rewrite - and "counts by
    # commit" was the whole point of being asked for this.
    MARK = "~~LEAKCHECK~COMMIT~~ "   # printable: a NUL here made git refuse with "embedded null character"
    cmd = ["git", "log", "-p", "--format=" + MARK + "%H%n%B", rng]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except Exception as e:                                                # noqa: BLE001
        print("  REFUSED: cannot read the history for %s (%s)" % (rng, e))
        return 1
    if r.returncode != 0:
        print("  REFUSED: `%s` failed - not vouching for anything" % " ".join(cmd))
        return 1
    if not r.stdout.strip():
        print("  REFUSED: the history for %s is EMPTY - a vacuous pass is how this tool failed before" % rng)
        return 1

    # `against` names a ref whose history is already public. A flagged line already there is reported as
    # PRE-EXISTING instead of blocking. None (the default) keeps the old strict behaviour, and an unreadable
    # ref also yields None, so the gate fails CLOSED rather than excusing everything.
    public = already_public(against, rs) if against else None
    if against and public is None:
        print("  NOTE: cannot read %s - every flagged line will BLOCK, including any already public" % against)
    per, flagged, pre = {}, [0], [0]
    cur = "(before the first commit marker)"
    for line in r.stdout.split("\n"):
        if line.startswith(MARK):
            cur = line[len(MARK):].strip()[:12]
            continue
        if "noreply@anthropic.com" in line or line.lstrip().lower().startswith("co-authored-by:"):
            continue
        if any(f in line for f in OWN_FIXTURES):
            continue
        # EVERY matching rule is recorded, not just the first. Breaking on the first match hid the triage that
        # matters: a line holding an install path and a line holding the user folder BOTH match "a Windows
        # absolute path" first, so the user-fragment rule read ZERO on a branch that demonstrably carries it.
        # Severity differs sharply between those two, so the report must be able to tell them apart.
        hit = [name for name, rx in rs if rx.search(line)]
        if hit and public is not None and hash(line.rstrip()) in public:
            # Already public in the comparison ref, so this rewrite does not newly publish it. Counted and
            # reported separately - never silently dropped, because "it was already out" is a reason to stop
            # BLOCKING, not a reason to stop SAYING.
            pre[0] += 1
            continue
        for name in hit:
            per[(cur, name)] = per.get((cur, name), 0) + 1
        if hit:
            flagged[0] += 1
    total = flagged[0]
    if per:
        print("  hits by COMMIT and RULE (the matched text is never printed):")
        for (c, name), n in sorted(per.items(), key=lambda kv: (-kv[1], kv[0])):
            print("    %-12s %-28s %d line(s)" % (c, name, n))
    if pre[0]:
        print("  %d flagged line(s) were ALREADY PUBLIC in %s - reported, not blocking" % (pre[0], against))
    print("leak_check history %s: %s" % (rng, "CLEAN (patches and messages, additions AND removals)"
                                         if total == 0 else
                                         "%d FLAGGED LINE(S) across %d commit/rule pair(s) - squash or "
                                         "rewrite, do NOT fix forward" % (total, len(per))))
    # Item 12 rides on the push gate rather than on a flag of its own, so it cannot be forgotten: release.sh
    # already calls --history before a push, and the author/committer fields are published by that same push.
    # A field hit is as blocking as a line hit - a rewrite can fix the patch and leave the author untouched.
    ident = check_identity(rng, rs)
    return 1 if (total or ident) else 0


def selftest():
    """Canaries, including the exact form that slipped through. A rule is not trusted until it has been made to fire."""
    rs = rules()
    B = chr(92)
    cases = [
        ("escaped Users path in Python source", "C:" + B * 2 + "Users" + B * 2 + "T" + B * 2 + "AppData", True),
        ("escaped Program Files in source", "C:" + B * 2 + "Program Files" + B * 2 + "Git", True),
        ("plain single-separator path", "C:" + B + "Users" + B + "someone", True),
        ("forward-slash drive path", "C:/Users/someone", True),
        ("an email address", "someone@example.org", True),
        # PINS THE SCOPE, does not endorse it: the path rule needs Users|Program Files|Documents after the drive
        # letter, so these two PASS. If you deliberately widen the rule, change this case in the same commit -
        # it exists so the narrowness can only ever be a decision, never a surprise. BTeam read the behaviour as
        # "it flags paths carrying an identity string", which is wrong in both directions: Program Files carries
        # none and IS flagged, while a bare Windows\Temp carries none and is NOT.
        ("bare system path, NOT flagged", "C:" + B + "Windows" + B + "Temp was flat", False),
        ("bare second drive, NOT flagged", "D:/New Volume/diag holds the overflow", False),
        ("synthetic POSIX fixture", "/apps/store/WindowsApps/python.exe -u tools/batch.py", False),
        ("a relative project path", "tools/harness_results/results.csv", False),
        ("the required attribution", "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>", False),
    ]
    ok = True
    for desc, text, want in cases:
        got = any(rx.search(text) for _, rx in rs)
        if text.lstrip().lower().startswith("co-authored-by:"):
            got = False                                      # scan_text skips it; mirror that here
        good = (got == want)
        print("  %-38s %-12s %s" % (desc, "FIRES" if got else "silent",
                                    "ok" if good else ("WRONG - expected " + ("a hit" if want else "silence"))))
        ok &= good

    # THE ADD-THEN-REMOVE REPO. The whole reason check_history exists, proven in a throwaway repo rather than
    # asserted: commit a canary absolute path, then commit its removal. `git diff` over the range nets to
    # nothing, so --range sees a clean tree and PASSES; --history reads every commit's patch and FAILS. If the
    # old mode ever starts failing this repo, the net-diff blindness is gone and this case can be retired.
    import shutil
    import tempfile
    repo = tempfile.mkdtemp(prefix="leakcheck_")
    try:
        G = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", repo]
        # The canary must actually MATCH a rule. My first attempt used C:\canary\... and the path rule requires
        # Users|Program Files|Documents after the drive letter, so it matched nothing and the new mode reported a
        # correct clean - a fixture that proves nothing, caught only because the result was implausible.
        canary = "C:" + chr(92) + "Users" + chr(92) + "canaryname" + chr(92) + "probe.txt"
        run = lambda a: subprocess.run(a, capture_output=True, text=True, timeout=60)   # noqa: E731
        run(["git", "init", "-q", repo])
        with open(os.path.join(repo, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("clean first line\n")
        run(G + ["add", "-A"]); run(G + ["commit", "-q", "-m", "base"])
        with open(os.path.join(repo, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("clean first line\nPATH = r\"%s\"\n" % canary)
        run(G + ["add", "-A"]); run(G + ["commit", "-q", "-m", "adds the canary"])
        # The third commit removes the canary AND adds an unrelated clean line. The second part matters: without
        # it the net diff over the range is EMPTY, and check_range REFUSES on an empty diff rather than passing -
        # so the fixture tested a refusal, not the gap. The real case had 13 files of genuine changes around the
        # cancelled path, which is what let --range report clean. This now reproduces that.
        with open(os.path.join(repo, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("clean first line\nan unrelated clean change\n")
        run(G + ["add", "-A"]); run(G + ["commit", "-q", "-m", "removes it, fixing forward"])
        rng = "HEAD~2..HEAD"
        me = os.path.abspath(__file__)
        rr = subprocess.run([sys.executable, "-I", me, "--range", rng, "--allow-no-denylist"],
                            capture_output=True, text=True, cwd=repo, timeout=120)
        rh = subprocess.run([sys.executable, "-I", me, "--history", rng], capture_output=True, text=True,
                            cwd=repo, timeout=120)
        print("  --range PASSES an add-then-remove range (the gap)?      %s (exit %d)"
              % ("yes" if rr.returncode == 0 else "NO - the gap is gone, retire this case", rr.returncode))
        ok &= rr.returncode == 0
        print("  --history CATCHES it?                                   %s (exit %d)"
              % ("yes" if rh.returncode == 1 else "NO - BROKEN, the new mode does not see removals", rh.returncode))
        ok &= rh.returncode == 1

        # THE TAG CASE, and it is the one that matters most, because it is the asymmetry a branch scan cannot
        # see: tag the commit that CARRIES the canary, leave the branch tip clean, and the tag must stay dirty
        # for ever. This is the real defect found on 2026-10-16 - three branches scanned clean while published
        # tags served identity material in their current content. A tag is a live page, not history.
        run(G + ["tag", "v_dirty", "HEAD~1"])          # the commit that holds the canary
        run(G + ["tag", "v_clean", "HEAD"])            # the fixed-forward tip
        rtd = subprocess.run([sys.executable, "-I", me, "--tree", "v_dirty"], capture_output=True, text=True,
                             cwd=repo, timeout=120)
        rtc = subprocess.run([sys.executable, "-I", me, "--tree", "v_clean", "--allow-no-denylist"],
                             capture_output=True, text=True, cwd=repo, timeout=120)
        rta = subprocess.run([sys.executable, "-I", me, "--refs", "tags", "--mode", "tree"],
                             capture_output=True, text=True, cwd=repo, timeout=300)
        print("  a CLEAN TIP still leaves the TAG dirty - caught?        %s (exit %d)"
              % ("yes" if rtd.returncode == 1 else "NO - BROKEN, a published tag is unguarded", rtd.returncode))
        ok &= rtd.returncode == 1
        print("  the clean tag is NOT flagged (no crying wolf)?          %s (exit %d)"
              % ("yes" if rtc.returncode == 0 else "NO - BROKEN, it flags a clean tree", rtc.returncode))
        ok &= rtc.returncode == 0
        print("  --refs tags finds it and NAMES the tag?                 %s (exit %d)"
              % ("yes" if (rta.returncode == 1 and "v_dirty" in rta.stdout and "v_clean" not in
                           rta.stdout.split("carry identity material")[-1]) else "NO - BROKEN", rta.returncode))
        ok &= rta.returncode == 1 and "v_dirty" in rta.stdout

        # FAIL-CLOSED ON A MISSING DENYLIST (verve-47, 2026-10-26). tools/.identity_deny is absent here, so a
        # GATING run must exit non-zero: the owner-specific terms were never checked, so "clean" overstates it.
        # The sole bypass is the EXPLICIT --allow-no-denylist flag (the subprocesses above pass it to test the
        # other modes); it MUST be absent here, or this case proves nothing. No env var can reopen the gate.
        cf = os.path.join(repo, "clean.txt")
        with open(cf, "w", encoding="utf-8") as fh:
            fh.write("a perfectly clean line, no identity in it\n")
        rfc = subprocess.run([sys.executable, "-I", me, cf], capture_output=True, text=True, cwd=repo,
                             timeout=60)
        print("  a clean file with NO denylist FAILS CLOSED (non-zero)?  %s (exit %d)"
              % ("yes" if rfc.returncode != 0 else "NO - BROKEN, fails OPEN", rfc.returncode))
        ok &= rfc.returncode != 0
        rfo = subprocess.run([sys.executable, "-I", me, cf, "--allow-no-denylist"], capture_output=True,
                             text=True, cwd=repo, timeout=60)
        print("  ...and PASSES with the explicit --allow-no-denylist flag? %s (exit %d)"
              % ("yes" if rfo.returncode == 0 else "NO - BROKEN", rfo.returncode))
        ok &= rfo.returncode == 0
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


# Set True ONLY by --selftest-driven subprocesses, via the EXPLICIT CLI flag --allow-no-denylist, so the
# selftest can exercise the gating modes with no denylist present. Deliberately NOT an environment variable:
# an env var is inherited into child shells and hooks and would silently reopen the gate - the exact
# fail-open this file exists to prevent. The real pre-push gate never passes the flag.
_ALLOW_NO_DENY = False


def _finalize(rc):
    """Fail CLOSED when tools/.identity_deny is absent. The generic rules (paths, email, OS user name, home
    dir) ran, but the OWNER-SPECIFIC terms - the real name, the old tags, the work email - live ONLY in that
    gitignored, owner-supplied file. Without it a 0 verdict claims a clean the tool never checked for, which
    is exactly how a "clean" with no denylist has misled before. So a gating run with no denylist exits
    non-zero (code 3) whatever the generic rules found - a hit still returns 1. The _ALLOW_NO_DENY module flag
    (set only by the explicit --allow-no-denylist CLI flag, used only by this file's selftest) is the sole
    bypass; main() prints a LOUD line whenever that flag is present."""
    if not os.path.isfile(DENY_FILE) and not _ALLOW_NO_DENY:
        print("  REFUSING A FULL PASS: tools/.identity_deny is ABSENT, so the owner-specific terms "
              "(real name, old tags, work email) were NOT checked - only the generic rules ran above. "
              "This is NOT a clean on identity; add the owner-supplied denylist before trusting a pass.")
        return rc or 3
    return rc


def main():
    global _ALLOW_NO_DENY
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rs = rules()
    if "--selftest" in sys.argv:
        return selftest()
    if "--allow-no-denylist" in sys.argv:
        _ALLOW_NO_DENY = True
        print("  !! --allow-no-denylist IS SET: the missing-denylist identity gate is DISABLED for this run. "
              "This must NEVER appear in a real pre-push gate. !!")
    for i, a in enumerate(sys.argv):
        if a == "--range" and i + 1 < len(sys.argv):
            return _finalize(check_range(sys.argv[i + 1], rs))
        if a == "--history" and i + 1 < len(sys.argv):
            # --against <ref> reports a flagged line that is ALREADY in that ref's history instead of blocking
            # on it. Omit it and every flagged line blocks, which stays the default.
            against = None
            for j, b in enumerate(sys.argv):
                if b == "--against" and j + 1 < len(sys.argv):
                    against = sys.argv[j + 1]
            return _finalize(check_history(sys.argv[i + 1], rs, against=against))
        if a == "--tree" and i + 1 < len(sys.argv):
            return _finalize(check_tree(sys.argv[i + 1], rs))
        if a == "--refs" and i + 1 < len(sys.argv):
            mode = "both"
            for j, b in enumerate(sys.argv):
                if b == "--mode" and j + 1 < len(sys.argv):
                    mode = sys.argv[j + 1]
            if sys.argv[i + 1] not in ("branches", "tags", "all"):
                print("  --refs takes branches, tags or all")
                return 2
            if mode not in ("tree", "history", "both"):
                print("  --mode takes tree, history or both")
                return 2
            return _finalize(check_refs(sys.argv[i + 1], mode, rs))
    if "--list" in sys.argv:
        print("leak_check looks for:")
        for name, _ in rs:
            print("  -", name)
        print(f"\nextra terms: {'yes' if os.path.isfile(DENY_FILE) else 'none'} (tools/.identity_deny, gitignored)")
        return 0
    if not args:
        print(__doc__.strip().splitlines()[2])
        return 2
    hits = checked = 0
    unresolved = []
    for f in files_of(args, unresolved):
        checked += 1
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            # ONE SCANNER, NOT TWO. This loop used to be a second inline copy of scan_text's logic, and that is
            # exactly how the two drifted apart: scan_text learned to excuse this file's own selftest fixtures
            # (44ba3ed) and the copy here never did, so the identity gate reported 4 leaks in leak_check.py on
            # every run - permanently, all of them canaries and comment examples. A duplicated check is a check
            # that will disagree with itself eventually; the fix is to delete the duplicate, not to patch both.
            # The label stays the last two path parts, because a relpath can climb out of cwd and print the very
            # Users\<name> fragment this tool exists to catch, and this output gets pasted about.
            short = os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f))
            hits += scan_text(short, text, rs)
        except OSError as e:
            print(f"  (unreadable: {f}: {e})")
    if hits:
        print(f"\nleak_check: {hits} line(s) in {checked} file(s) must be fixed before this leaves the machine")
        return _finalize(1)
    # A clean verdict must say what it examined. Refuse one that covers less than it was asked about, or nothing
    # at all - otherwise the tool mints a pass for files it never opened (see files_of).
    if unresolved:
        print(f"\nleak_check: REFUSING A VERDICT - {len(unresolved)} of {len(args)} path(s) resolved to no file:")
        for p in unresolved[:10]:
            # the last two parts only, as everywhere else here: this output gets pasted about, and a tool whose
            # job is keeping absolute paths out of shared text must not print them in its own refusal. The first
            # version of this line used `os.sep in p`, which is '\\' on Windows and so never matched a path the
            # shell had handed over with forward slashes - and it printed the full path (2026-10-12).
            parts = p.replace("\\", "/").rstrip("/").split("/")
            print("    " + "/".join(parts[-2:]) if len(parts) > 1 else "    " + p)
        if len(unresolved) > 10:
            print(f"    ... and {len(unresolved) - 10} more")
        print(f"  {checked} file(s) were clean, but this is NOT a pass for the {len(args)} path(s) given."
              "  Usually shell word-splitting on a path with a space - quote it.")
        return _finalize(1)
    if not checked:
        print("\nleak_check: REFUSING A VERDICT - nothing was examined. 'clean' would be vacuously true.")
        return _finalize(1)
    print(f"leak_check: {checked} file(s) clean")
    return _finalize(0)


if __name__ == "__main__":
    sys.exit(main())
