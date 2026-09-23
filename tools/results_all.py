"""Every harness result ever scored, across the rotated CSVs.

harness.py rotates results.csv whenever the columns change (a new metric = a new file), so by 2026-09-23 the
history was spread over 26 files and results.csv itself held one row. Any analysis that opens results.csv alone
silently reads a fraction of the data - and gets a different fraction depending on the day it runs.

    from results_all import rows           # list of dicts, oldest first, union of all columns ("" where absent)
    python tools/results_all.py            # how many rows, which files, which columns came in when
"""
import csv
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "harness_results")


def files():
    """results_until_* oldest first (they are named by rotation time), then the live results.csv."""
    old = sorted(glob.glob(os.path.join(RESULTS, "results_until_*.csv")))
    live = os.path.join(RESULTS, "results.csv")
    return old + ([live] if os.path.exists(live) else [])


def rows(label_prefix=None):
    out = []
    for path in files():
        try:
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if label_prefix and not (r.get("label") or "").startswith(label_prefix):
                        continue
                    r["_file"] = os.path.basename(path)
                    out.append(r)
        except OSError:
            pass
    keys = set()
    for r in out:
        keys |= set(r)
    for r in out:                       # union the columns so callers can index anything without KeyError
        for k in keys:
            r.setdefault(k, "")
    return out


def num(r, key, default=0.0):
    """A CSV cell as a float; blanks, '-' and junk come back as the default."""
    try:
        return float(r.get(key) or default)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    all_rows = rows()
    print(f"{len(all_rows)} scored races across {len(files())} files")
    seen, first = set(), {}
    for r in all_rows:
        for k in r:
            if k not in seen:
                seen.add(k); first[k] = r["_file"]
    late = [(k, v) for k, v in first.items() if v != os.path.basename(files()[0])]
    print(f"{len(seen)} columns; the most recent additions:")
    for k, v in late[-8:]:
        print(f"  {k:28s} first seen in {v}")
