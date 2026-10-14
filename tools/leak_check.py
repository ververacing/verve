"""Gate anything that is about to LEAVE this machine: does it carry the real name, an email, or a Windows path?

    python tools/leak_check.py <file-or-dir> [...]      # exit 1 if anything is found
    python tools/leak_check.py --list                   # show what it looks for, without the values

The identity rule: the public identity is TC Verve / ververacing, and the real name, the old tags, the work email and
Windows paths never appear in anything that leaves here - commits, issues, READMEs, changelogs, videos, and now the
race transcripts we push to the engineer's repo.

THIS FILE LIVES IN A PUBLIC REPO, so it cannot contain the strings it hunts for - writing them down here would leak
exactly what it exists to prevent. Instead it derives them at runtime from the machine (the OS user name, the home
directory) and matches generic shapes (any drive-letter path, any email address, any Users\\<name> fragment). Extra
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


def scan_text(label, text, rs):
    """-> hit count. Scans a text blob line by line, printing where and which rule, never the match itself."""
    hits = 0
    for i, line in enumerate(text.split("\n"), 1):
        if "noreply@anthropic.com" in line or line.lstrip().lower().startswith("co-authored-by:"):
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
        out += scan_text("<%s %s>" % (what, rng), r.stdout, rs)
    print("leak_check range %s: %s" % (rng, "CLEAN (diff and commit messages)" if out == 0 else "%d LEAK(S)" % out))
    return 1 if out else 0


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
    print("\n  %s" % ("all cases correct" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rs = rules()
    if "--selftest" in sys.argv:
        return selftest()
    for i, a in enumerate(sys.argv):
        if a == "--range" and i + 1 < len(sys.argv):
            return check_range(sys.argv[i + 1], rs)
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
                for i, line in enumerate(fh, 1):
                    if "noreply@anthropic.com" in line or line.lstrip().lower().startswith("co-authored-by:"):
                        continue          # the required attribution, not an identity leak
                    for name, rx in rs:
                        if rx.search(line):
                            # never echo the match itself - say where and which rule
                            # the last two path parts only: relpath can climb out of cwd and print the very
                            # Users\<name> fragment this tool exists to catch, and this output gets pasted about
                            short = os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f))
                            print(f"  LEAK  {short}:{i}  <- {name}")
                            hits += 1
                            break
        except OSError as e:
            print(f"  (unreadable: {f}: {e})")
    if hits:
        print(f"\nleak_check: {hits} line(s) in {checked} file(s) must be fixed before this leaves the machine")
        return 1
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
        return 1
    if not checked:
        print("\nleak_check: REFUSING A VERDICT - nothing was examined. 'clean' would be vacuously true.")
        return 1
    print(f"leak_check: {checked} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
