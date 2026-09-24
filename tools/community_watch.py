"""What changed in the outside race reports since I last looked.

The reports are other people's installs, opted in, exported to the desk by the broadcast agent. This reads that
export, answers the standing questions the same way every time so the numbers are comparable hour to hour, and
prints only what MOVED since the last run (state in tools/harness_results/community_state.json).

Two rules baked in, because getting them wrong is how we published a wrong headline (2026-09-23):
  * practice / qualifying / hotlap sessions are NOT races - never pool them into an incident rate;
  * a race abandoned on lap 2 has 100% of its incidents on lap 1 by definition, so lap-1 shares are only meaningful
    over races that actually ran (>= 600 s here, reported with the qualifier attached).

    python tools/community_watch.py              # what moved since last time
    python tools/community_watch.py --full       # the standing questions in full, no diff
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DESK = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "community")
EXPORT = os.path.join(DESK, "reports.jsonl")
STATE = os.path.join(HERE, "harness_results", "community_state.json")
RAN = 600          # seconds: a race that ran long enough for its lap-1 share to mean anything


PULLS = os.path.join(HERE, "harness_results", "community")      # what community_pull.py fetched directly
DEDUPE = ("inst", "session_type", "track", "cars", "duration_s", "player_best_lap_s", "incidents")


def load():
    """The desk export plus anything pulled directly, deduped. The export can be up to an hour stale and the
    direct pulls are live, so reading both means the check-in never works from the older of the two."""
    import glob
    paths = ([EXPORT] if os.path.exists(EXPORT) else []) + sorted(glob.glob(os.path.join(PULLS, "pull_*.jsonl")))
    out, seen = [], set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("unattended"):
                        continue
                    key = tuple(str(r.get(k)) for k in DEDUPE)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(r)
        except OSError:
            pass
    return out


def views(rows):
    races = [r for r in rows if (r.get("session_type") or "").lower() == "race"]
    ran = [r for r in races if (r.get("duration_s") or 0) >= RAN]
    def share(rs):
        v = [(r.get("incidents_lap1") or 0) / (r.get("incidents") or 1) for r in rs if r.get("incidents")]
        return statistics.median(v) if v else None
    def per_car(rs):
        v = [(r.get("incidents") or 0) / (r.get("cars") or 1) for r in rs if r.get("cars")]
        return statistics.median(v) if v else None
    builds = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if r.get("repositions"):
            b = builds[str(r.get("csp_build") or "?")]
            b[0] += r["repositions"]; b[1] += r.get("repositions_ok") or 0
    return {
        "rows": len(rows),
        "races": len(races),
        "races_ran": len(ran),
        "reached_flag": sum(1 for r in races if r.get("completed") or r.get("player_finished")),
        "median_race_s": statistics.median([r.get("duration_s") or 0 for r in races]) if races else None,
        "lap1_share_ran": share(ran),
        "incidents_per_car_ran": per_car(ran),
        "repositions": {b: {"n": v[0], "ok_pct": round(100 * v[1] / v[0], 1)} for b, v in builds.items() if v[0] >= 10},
        "installs": len({r.get("inst") for r in rows if r.get("inst")}),
        "versions": dict(collections.Counter(r.get("verve_version") or "?" for r in rows).most_common(4)),
        "tracks_new": sorted({r.get("track") for r in rows if r.get("track")}),
        "wet_races": sum(1 for r in races if r.get("is_wet")),
        "lua_errors": sum(1 for r in rows if r.get("lua_errors")),
    }


def main():
    rows = load()
    if not rows:
        print(f"no export at {EXPORT} - the broadcast agent writes it; ask for a refresh")
        return
    now = views(rows)
    full = "--full" in sys.argv
    old = {}
    if os.path.exists(STATE) and not full:
        try:
            old = json.load(open(STATE, encoding="utf-8"))
        except ValueError:
            old = {}
    def line(k, fmt="{}"):
        a, b = old.get(k), now.get(k)
        if b is None:
            return
        if full or not old or a != b:
            was = f"   (was {fmt.format(a)})" if old and a is not None and a != b else ""
            print(f"  {k:24s} {fmt.format(b)}{was}")
    print(f"outside race reports: {now['rows']} rows, {now['installs']} installs"
          + (f"  (+{now['rows'] - old['rows']} since last look)" if old.get("rows") else ""))
    line("races"); line("races_ran"); line("reached_flag")
    line("median_race_s", "{:.0f}s")
    line("lap1_share_ran", "{:.0%}"); line("incidents_per_car_ran", "{:.2f}")
    line("wet_races"); line("lua_errors")
    if full or now["versions"] != old.get("versions"):
        print(f"  versions                 {now['versions']}")
    oldrep = old.get("repositions") or {}
    for b, v in sorted(now["repositions"].items()):
        was = oldrep.get(b)
        if full or not was or was["ok_pct"] != v["ok_pct"]:
            delta = f"   (was {was['ok_pct']}% of {was['n']})" if was else ""
            print(f"  repositions CSP {b:<8} {v['ok_pct']:5.1f}% ok of {v['n']:>4}{delta}")
    newtracks = set(now["tracks_new"]) - set(old.get("tracks_new") or [])
    if newtracks and old:
        print(f"  tracks not seen before:  {', '.join(sorted(newtracks))}")
    print(f"\n  (lap-1 share and incidents per car are over races that ran >= {RAN} s; "
          "practice/qualifying are never pooled in)")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(now, open(STATE, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
