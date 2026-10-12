"""WHICH CARS does Verve park, and WHY - per model, across any set of diagnostics files.

    python tools/park_models.py                         # every diag written in the last 36 h
    python tools/park_models.py "diag_race_*vint*"      # a glob (quote it)
    python tools/park_models.py --hours 6

Verve's retirement path is parkInPits(i, why), and the reason lands in the diag as `pw` beside each car, while the
header carries each car's model. Joining the two answers two questions no other tool does: does a particular CAR get
parked more than its share, and which of the eight reasons is firing.

Written 2026-10-11 for two jobs at once. BTeam saw both strandings in a 50-lap race land on the same model and
wondered about a car pattern; across 45 GT3 diags here the rate is 0.5 % and even (Huracan 1 of 135, Ferrari 1 of 135,
Nissan 1 of 90), so that hypothesis died on a larger sample. And every reason in those 765 car-races was
`terminal_susp` - a genuine wreck - with no `box_limbo`, `pit_stuck` or `park_time` at all, which matters for the
community bug where Verve retires most of a small grid of 1960s cars with zero contact: the pit-lane paths that fit
that report do not fire in GT3. This is the scorer for that repro.

Slot 0 is excluded throughout: it is the harness autopilot and Verve never parks the player's car.
"""
import collections
import glob
import json
import os
import sys
import time

VERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    """(models by car index, last snapshot) from a diag, or (None, None)."""
    hdr = last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue          # a half-written line at the tail of a live race
                if hdr is None and isinstance(d.get("cars"), list) and d.get("track"):
                    hdr = d
                elif d.get("t") and isinstance(d.get("grid"), list):
                    last = d
    except OSError:
        return None, None
    if not hdr or not last:
        return None, None
    return {c["i"]: c.get("model", "?") for c in hdr["cars"] if "i" in c}, last


def main():
    argv, args, hours = sys.argv[1:], [], 36.0
    k = 0
    while k < len(argv):                      # consume --hours' VALUE, or it is read as the glob (caught 22:35)
        a = argv[k]
        if a.startswith("--hours="):
            hours = float(a.split("=", 1)[1])
        elif a == "--hours" and k + 1 < len(argv):
            hours = float(argv[k + 1]); k += 1
        elif not a.startswith("--"):
            args.append(a)
        k += 1
    pattern = args[0] if args else "diag_race_*.jsonl"
    if not os.path.isabs(pattern):
        pattern = os.path.join(VERVE, pattern)
    if not pattern.endswith(".jsonl"):
        pattern += ".jsonl" if "*" not in os.path.basename(pattern) else ""
    cut = time.time() - hours * 3600

    raced = collections.Counter()
    parked = collections.Counter()
    why = collections.defaultdict(collections.Counter)
    races = zero_contact = 0
    for f in sorted(glob.glob(pattern)):
        if os.path.getmtime(f) < cut:
            continue
        models, last = read(f)
        if not models:
            continue
        races += 1
        n_parked = 0
        for c in last["grid"]:
            i = c.get("i")
            if i == 0:
                continue
            m = models.get(i, "?")
            raced[m] += 1
            if c.get("park"):
                parked[m] += 1
                n_parked += 1
                why[m][str(c.get("pw") or "?")] += 1
        # the signature of the community bug: cars parked in a race with no damage-causing contact at all
        if n_parked and not any((c.get("dmg") or 0) >= 8 for c in last["grid"]):
            zero_contact += 1
            print(f"  ZERO-CONTACT PARKS: {os.path.basename(f)} - {n_parked} parked, no car over the damage threshold")

    if not races:
        print(f"park_models: no diags matched {pattern} in the last {hours:g} h")
        return 1
    print(f"\n{races} diags, slot 0 excluded")
    print(f"{'model':36s} {'raced':>6s} {'parked':>7s} {'rate':>7s}   reasons")
    for m, n in raced.most_common():
        p = parked[m]
        print(f"  {m:34s} {n:6d} {p:7d} {100 * p / n:6.1f} %   {dict(why[m]) if p else ''}")
    tr, tp = sum(raced.values()), sum(parked.values())
    print(f"  {'TOTAL':34s} {tr:6d} {tp:7d} {100 * tp / max(tr, 1):6.1f} %")
    allwhy = collections.Counter()
    for c in why.values():
        allwhy.update(c)
    print(f"  reasons overall: {dict(allwhy.most_common())}")
    if zero_contact:
        print(f"  {zero_contact} race(s) parked cars with NO damage-causing contact - the community-bug signature")
    return 0


if __name__ == "__main__":
    sys.exit(main())
