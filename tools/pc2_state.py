"""PC #2's state, read off the shared desk instead of asked for.

    python tools/pc2_state.py            # one or two lines for the hourly check
    python tools/pc2_state.py --selftest

WHY THIS EXISTS. The hourly routine learns PC #2's state by sending BTeam a message and waiting for a reply. That
works only while BTeam's session is AWAKE. If it is asleep at 04:15 - which is exactly when a queue hands over -
the hour passes and nothing is learned, which is the shape of the 8-hour idle the owner noticed on 7 Oct. BTeam
now writes `pc2/status.md` every chain poll, and `pc2/QUEUE_STOPPED_EARLY.md` when a queue dies without finishing.
Those files need no liveness on its side. **But a file nobody reads on a schedule is this project's oldest
failure mode** - a ten-row repro of the owner's top item sat unread for four days, and tools/unscored.py exists
because a rule written in a document does not fire by itself. So this is the reading half, and it goes in the
hourly pass beside procs / sweep / docs_check.

THE STALENESS CHECK IS THE PART BTEAM CANNOT DO FOR ITSELF. If its chain dies, status.md simply stops being
rewritten; the file still sits there saying "running", and both an asleep session and a dead chain look identical
from the outside. Only a reader comparing the stamp against NOW can tell. That is why this refuses to report
"fine" on a stale file, and why the threshold is generous: the chain polls every 120 s, so anything under ~15 min
is normal jitter and anything past 30 min means the writer is gone, not slow.
"""
import argparse
import datetime
import os
import re
import sys

DESK = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "pc2")
STATUS = "status.md"
EARLY = "QUEUE_STOPPED_EARLY.md"
STALE_MIN = 30          # minutes without a rewrite before the writer is presumed dead (poll is 120 s)


def parse_stamp(text):
    """The `updated: YYYY-MM-DD HH:MM:SS` line, or None. Tolerates a missing seconds field."""
    m = re.search(r"updated:\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", text or "")
    if not m:
        return None
    s = m.group(1).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def report(desk=DESK, now=None, stale_min=STALE_MIN):
    """-> (lines, problem). `problem` True when the hourly must act rather than move on."""
    now = now or datetime.datetime.now()
    lines, problem = [], False

    early = os.path.join(desk, EARLY)
    if os.path.exists(early):
        try:
            body = open(early, encoding="utf-8", errors="replace").read().strip()
        except OSError as e:
            body = "(unreadable: %s)" % e
        head = " | ".join(l.strip() for l in body.splitlines() if l.strip())[:400]
        lines.append("!! PC #2 QUEUE STOPPED EARLY - a human decides, do NOT assume thermal: %s" % head)
        lines.append("   (the marker is %s - act on it, then delete it deliberately)" % early)
        return lines, True        # an early stop outranks everything else; report it alone

    path = os.path.join(desk, STATUS)
    if not os.path.isdir(desk):
        return ["PC #2: desk folder not found (%s) - cannot read state, ask BTeam directly" % desk], True
    if not os.path.exists(path):
        return ["PC #2: no status.md on the desk yet - ask BTeam directly" % ()], True

    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return ["PC #2: status.md unreadable (%s) - ask BTeam directly" % e], True

    body = [l.strip() for l in text.splitlines()
            if l.strip() and not l.startswith("#") and not l.lower().startswith("updated:")]
    state = body[0] if body else "(no state line)"
    extra = body[1:]
    stamp = parse_stamp(text)
    if stamp is None:
        lines.append("PC #2: %s" % state)
        lines.append("   (no parseable `updated:` stamp - cannot tell a live writer from a dead one)")
        return lines, True

    age = (now - stamp).total_seconds() / 60.0
    if age > stale_min:
        lines.append("!! PC #2 status is STALE by %.0f min (stamp %s) - the chain that writes it is presumed DEAD."
                     % (age, stamp.strftime("%H:%M:%S")))
        lines.append("   Last state it recorded: %s" % state)
        lines.append("   A stale file still says 'running'. Verify on PC #2 before trusting it.")
        return lines, True
    if age < -5:
        lines.append("PC #2: %s" % state)
        lines.append("   (stamp %s is in the FUTURE - clocks disagree between machines; treat the state as soft)"
                     % stamp.strftime("%H:%M:%S"))
        return lines, False
    lines.append("PC #2: %s  (desk status %.0f min old)" % (state, max(0.0, age)))
    hw, hw_problem = hardware(extra)
    lines.extend(hw)
    return lines, hw_problem


# Lines BTeam added at my suggestion so the hourly needs no message at all: a storage/WHEA event count and free
# space. PARSING SOMEONE ELSE'S FREE TEXT IS BRITTLE, so this is deliberately timid: every extra line is PRINTED
# whatever it says, and only a confident match on a label plus an integer is allowed to decide anything. A label
# we cannot parse is reported as unparseable and treated as a PROBLEM - never as zero. That is the blanks-are-not-
# zeros rule: a hardware check that silently reads "unknown" as "fine" is worse than no hardware check, because
# it manufactures reassurance. If BTeam changes the wording, this says so rather than going quietly green.
HW_LABEL = re.compile(r"(whea|storage|disk|controller)", re.I)
HW_COUNT = re.compile(r":\s*(\d+)\b")


def hardware(extra):
    out, problem = [], False
    if not extra:
        return ["   (no hardware lines on the desk yet - ask BTeam, or its chain has not written a poll since the"
                " format changed)"], False
    for line in extra:
        out.append("   %s" % line)
        if not HW_LABEL.search(line):
            continue
        m = HW_COUNT.search(line)
        if not m:
            out.append("   !! that hardware line carries no readable count - treating as UNKNOWN, not as zero")
            problem = True
        elif int(m.group(1)) > 0:
            out.append("   !! NON-ZERO hardware events on PC #2 - this is the SATA path we have been watching."
                       " Do not start a new queue there until it is explained.")
            problem = True
    return out, problem


def selftest():
    import shutil
    import tempfile
    ok = True
    now = datetime.datetime(2026, 10, 16, 4, 0, 0)
    d = tempfile.mkdtemp()
    try:
        def write(name, body):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        def drop(name):
            try:
                os.remove(os.path.join(d, name))
            except OSError:
                pass

        print("=== pc2_state selftest ===")
        # 1. fresh and healthy -> quiet, no problem
        write(STATUS, "# PC#2 status\n\nupdated: 2026-10-16 03:58:00\nstarclimb2 running: rows 5/10 done; ETA ~04:15\n")
        lines, prob = report(d, now)
        good = (not prob) and any("rows 5/10" in l for l in lines)
        print("  a fresh status reads clean?                      %s" % ("yes" if good else "NO - BROKEN"))
        ok &= good

        # 1b. THE HARDWARE LINES. Printed whatever they say; only a confident parse decides anything.
        base = "# PC#2 status\n\nupdated: 2026-10-16 03:58:00\nstarclimb2 running: rows 6/10 done\n"
        write(STATUS, base + "storage/WHEA events (last 1h): 0\nC: free GB: 681.5\n")
        lines, prob = report(d, now)
        good = (not prob) and any("681.5" in l for l in lines) and any("WHEA" in l for l in lines)
        print("  extra desk lines shown, zero events stays quiet?  %s" % ("yes" if good else "NO - BROKEN"))
        ok &= good

        write(STATUS, base + "storage/WHEA events (last 1h): 3\nC: free GB: 681.5\n")
        lines, prob = report(d, now)
        good = prob and any("NON-ZERO" in l for l in lines)
        print("  a NON-ZERO event count raised loudly?             %s" % ("yes" if good else "NO - BROKEN, the SATA path is what we watch"))
        ok &= good

        write(STATUS, base + "storage/WHEA events: none seen\n")
        lines, prob = report(d, now)
        good = prob and any("UNKNOWN" in l for l in lines)
        print("  an unreadable count = UNKNOWN, not zero?          %s" % ("yes" if good else "NO - BROKEN, it would manufacture reassurance"))
        ok &= good

        write(STATUS, base)
        lines, prob = report(d, now)
        good = (not prob) and any("no hardware lines" in l for l in lines)
        print("  missing hardware lines noted but not alarming?    %s" % ("yes" if good else "NO - BROKEN"))
        ok &= good

        # 2. STALE -> must be a problem. This is the case BTeam cannot detect for itself.
        write(STATUS, "# PC#2 status\n\nupdated: 2026-10-16 02:10:00\nstarclimb2 running: rows 5/10 done\n")
        lines, prob = report(d, now)
        good = prob and any("STALE" in l for l in lines)
        print("  a 110-min-old status reported as STALE?          %s" % ("yes" if good else "NO - BROKEN, a dead chain reads as 'running'"))
        ok &= good

        # 2b. and the threshold has teeth in the other direction: 20 min is NOT stale
        write(STATUS, "# PC#2 status\n\nupdated: 2026-10-16 03:40:00\nstarclimb2 running: rows 5/10 done\n")
        _, prob20 = report(d, now)
        print("  a 20-min-old status NOT called stale (teeth)?    %s" % ("yes" if not prob20 else "NO - threshold too tight, normal jitter would alarm"))
        ok &= not prob20

        # 3. an unparseable stamp must NOT read as healthy
        write(STATUS, "# PC#2 status\n\nstarclimb2 running: rows 5/10 done\n")
        lines, prob = report(d, now)
        good = prob and any("stamp" in l for l in lines)
        print("  a status with no stamp refused, not trusted?     %s" % ("yes" if good else "NO - BROKEN"))
        ok &= good

        # 4. the early-stop marker outranks a perfectly healthy status
        write(STATUS, "# PC#2 status\n\nupdated: 2026-10-16 03:59:00\nall fine here\n")
        write(EARLY, "starclimb2 stopped early\nrows 4 of 10\nstorage/WHEA last 8h: 0\nhuman decides\n")
        lines, prob = report(d, now)
        good = prob and any("STOPPED EARLY" in l for l in lines) and not any("all fine" in l for l in lines)
        print("  early-stop marker outranks a healthy status?     %s" % ("yes" if good else "NO - BROKEN, the marker could be missed"))
        ok &= good
        drop(EARLY)

        # 5. a missing desk must say so rather than report healthy
        lines, prob = report(os.path.join(d, "nope"), now)
        good = prob and any("not found" in l for l in lines)
        print("  a missing desk folder refused, not 'fine'?       %s" % ("yes" if good else "NO - BROKEN"))
        ok &= good
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n  %s" % ("every rule holds" if ok else "SELFTEST FAILED - do not trust this module"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--desk", default=DESK)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    lines, problem = report(a.desk)
    for l in lines:
        print(l)
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
