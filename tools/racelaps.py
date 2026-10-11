"""Per-car lap times for one harness race: AC's race_out when it has laps, else Verve's own feed. One place, so every
pace tool sees the same races.

WHY. AC writes out/race_out.json when Verve shuts it down, but in 10-40 % of harness races a day (every day since at least
2026-09-25; ten in a row on 2026-10-10 13:00-14:33) the race session in it has NO laps: laps [], lapstotal all 0. The
harness copies race_out only when it has laps, so those races were silently missing from every race_out-based pace
figure - a selection, not a sample. lib/feed.lua's `lap` event carries AC's own lap time (lap_ms): checked against a
good race_out, 72 of 72 laps identical to the millisecond (2026-10-10). Feed lap n == race_out lap index n-1.

What the feed lacks: the CUT flag until lib/feed.lua adds "cuts" to its lap events (staged 2026-10-10; read when present,
None before), and a car's last lap if it
ended in the final second before shutdown. And its finishing order is the live order when the feed stopped, not AC's
classification. Every result says which source it came from.

    from racelaps import race_laps
    r = race_laps("ers_ab_smart_1")       # by harness label (results.csv -> diag stamp -> race_out or feed)
    r["src"], r["models"], r["laps"][car] -> [(index, seconds, cuts)], r["order"]  (cuts None from the feed)
"""
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import paths  # noqa: E402

_rows = None


def results_rows(res):
    global _rows
    if _rows is None:
        _rows = {}
        for f in sorted(glob.glob(os.path.join(res, "results*.csv"))):
            try:
                for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
                    if r.get("label"):
                        _rows.setdefault(r["label"], []).append(r)
            except OSError:
                continue
    return _rows


def labels(prefix, res):
    return sorted(l for l in results_rows(res) if l.startswith(prefix))


def stamp_of(label, res):
    """the session stamp of the label's LATEST run (diag file name in results*.csv; the newest stamp wins, whatever
    file order the rotated results files come back in)"""
    st = [m.group(1) for r in results_rows(res).get(label) or []
          for m in [re.search(r"diag_race_(\d{8}_\d{6})_", r.get("file") or "")] if m]
    return max(st) if st else None


def from_race_out(path):
    try:
        d = json.load(open(path, encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    ss = [s for s in d.get("sessions", []) if s.get("type") == 3] or d.get("sessions", [])[-1:]
    if not ss or not ss[0].get("laps"):
        return None
    s, out = ss[0], {}
    for lp in s["laps"]:
        t = lp.get("time")
        if isinstance(t, int) and t > 10000:
            out.setdefault(lp["car"], []).append((lp.get("lap", 0), t / 1000.0, lp.get("cuts", 0)))
    return {"src": "race_out", "models": [p.get("car") for p in d.get("players", [])], "laps": out,
            "order": [c for c in (s.get("raceResult") or []) if isinstance(c, int)]}


def from_feed(stamp):
    hits = [p for d in paths.feed_dirs(warn=False) for p in glob.glob(os.path.join(d, stamp + "_*.jsonl"))]
    if not hits:
        return None
    models, out, last = [], {}, None
    for line in open(hits[0], encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ty = d.get("type") or d.get("e")
        if ty == "header":
            models = [c.get("model") for c in sorted(d.get("cars", []), key=lambda c: c.get("i", 0))]
        elif ty == "lap" and d.get("lap_ms") and d.get("car") is not None:
            out.setdefault(d["car"], []).append((int(d.get("lap", 0)) - 1, d["lap_ms"] / 1000.0, d.get("cuts")))
        elif ty == "state":
            last = d
    order = [c["i"] for c in sorted((last or {}).get("cars", []), key=lambda c: c.get("pos") or 999)] if last else []
    return {"src": "feed", "models": models, "laps": out, "order": order} if out else None


def race_laps(label, res=None):
    res = res or os.path.join(HERE, "harness_results")
    for p in sorted(glob.glob(os.path.join(res, "race_out_*_%s.json" % label)), reverse=True):
        r = from_race_out(p)
        if r:
            return r
    st = stamp_of(label, res)
    return from_feed(st) if st else None
