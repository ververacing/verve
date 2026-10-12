"""Are these races comparable? Prints the ARM each label ran with and names every switch that differs.

    python tools/arm_check.py c2_spa12_off_1 c2_spa12_off_2 car14_ev8_on_1
    python tools/arm_check.py "c2_spa12_*"            # globs (quote them)
    python tools/arm_check.py --group "rc16b_spa_*"   # group the labels by identical arm instead

Written 2026-10-12 after the fifth withdrawn claim of the week. Every one of them had the same shape: rows that
differed in more than the thing being compared got pooled, and the pooling looked rigorous because the rows came from
the same track and car. The arm is already in results.csv - harness.py:1251 writes {settings, recovery, racecraft,
drivers, troublespots, fault, csp, human, strategy, fuel} as one JSON blob in the `arm` column - so this was always
checkable and I was reading the queue files instead. I even concluded the column did not exist because there is no
column NAMED `racecraft`. There is: it is inside `arm`.

Use it before quoting any pooled number. If it says the arms differ, the pool is not a control.
"""
import csv
import fnmatch
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results", "results.csv")


def rows():
    with io.open(RESULTS, encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def arm_of(r):
    try:
        return json.loads(r.get("arm") or "{}")
    except ValueError:
        return {}


def flat(a, prefix=""):
    """{'racecraft.COLD_TYRE': 0.15, ...} - empty sub-dicts drop out, so a plain arm flattens to nothing."""
    out = {}
    for k, v in sorted((a or {}).items()):
        key = prefix + k
        if isinstance(v, dict):
            out.update(flat(v, key + "."))
        elif not (v is None or (isinstance(v, (dict, list, str)) and len(v) == 0)):
            # keep 0 and FALSE: `v not in (..., 0)` dropped settings.enabled=false, because False == 0 in Python,
            # which hid the one switch that matters most - a race run with Verve turned off entirely (caught by
            # this file's own self-test, 2026-10-12)
            out[key] = v
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip().splitlines()[0])
        return 2
    rs = rows()
    picked = []
    for pat in args:
        hit = [r for r in rs if r.get("label") and (r["label"] == pat or fnmatch.fnmatch(r["label"], pat))]
        if not hit:
            print(f"  (no results row matches {pat})")
        picked.extend(hit)
    if not picked:
        return 1
    seen = {}
    for r in picked:
        seen.setdefault(r["label"], r)       # a re-run of the same label: the first row wins
    labs = sorted(seen)
    arms = {l: flat(arm_of(seen[l])) for l in labs}

    keys = sorted({k for a in arms.values() for k in a})
    if "--group" in sys.argv:
        groups = {}
        for l in labs:
            groups.setdefault(json.dumps(arms[l], sort_keys=True), []).append(l)
        print(f"{len(labs)} label(s) in {len(groups)} arm group(s):")
        for a, ls in sorted(groups.items(), key=lambda x: -len(x[1])):
            print(f"  n={len(ls):<3} {a if a != '{}' else '(plain: no switches)'}")
            print(f"       {', '.join(ls)}")
        return 0
    if not keys:
        print(f"{len(labs)} label(s), ALL PLAIN (no switches on any of them) - comparable")
        return 0
    print(f"{len(labs)} label(s); switches that appear on any of them: {len(keys)}")
    print(f"  {'label':30s} " + "  ".join(f"{k.split('.')[-1][:14]:>14s}" for k in keys))
    for l in labs:
        print(f"  {l:30s} " + "  ".join(f"{str(arms[l].get(k, '-')):>14s}" for k in keys))
    differ = [k for k in keys if len({json.dumps(arms[l].get(k)) for l in labs}) > 1]
    print()
    if differ:
        print("  NOT COMPARABLE - these differ across the labels: " + ", ".join(differ))
        print("  Pooling them is not a control. Split by arm (--group) or pick one arm.")
        return 1
    print("  comparable: every switch above is identical across all labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
