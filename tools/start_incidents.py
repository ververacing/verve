"""Where in a race do contacts actually happen? Separates THE START from "the opening lap".

    python tools/start_incidents.py <diag...> [--by-race] [--min-snaps N]
    python tools/start_incidents.py --selftest

The owner's question (2026-10-25): "how many incidents are happening on race start, not just lap one".
`lap1_tally.py` answers lap 0-1 as ONE bucket, which cannot tell a grid-getaway shunt from a lap-1
racing incident. This splits lap 0 at the two boundaries that Verve's own code uses:

  launch     lap 0, olS < 0           still BEFORE the timing line: the getaway off the grid
  convoy     lap 0, 0 <= olS < 0.45   CV.END - the zone Verve's lap-0 convoy throttle governs
  lap0_late  lap 0, olS >= 0.45       rest of the opening lap
  lap1       lap 1
  later      lap >= 2                 the baseline a start rate has to be judged against

olS is the HOUSE wrapped spline (racecraft.lua:929-933): on lap 0 a grid that sits before the timing
line reads spline 0.97-0.99, so olS = spline - 1 and those contacts are NEGATIVE, not late-lap. Reading
raw spline puts every grid shunt in `lap0_late` and makes the start look clean. That is the selftest's
control case.

SOURCE is {"ev":"contact"} records (diag.lua:231), which carry their own `t`, `lap`, `spline` and the
damage JUMP. They are written on a jump of 8+ (or a >=3 contact event), on EVERY lap - the block comment
at diag.lua:183 still says "cars on lap 0-1" but the inline comment at :200 records the widening, and
the data agrees. Severity uses the three NAMED thresholds, never a bare "heavy": jump8 / jump30 / jump40
(the owner's rule is 40).

NOT measured here: contacts too light to write a record. A race's `contacts` counter can be non-zero
with no records at all - the owner's 12:53 COTA race had 4 contacts and 0 damage. So this counts
DAMAGING contacts; "jumpiness" with no damage will not appear.
"""
import json, io, sys, glob, collections

CV_END = 0.45          # racecraft.lua:146 CV.END - the lap-0 convoy zone
BUCKETS = ["launch", "convoy", "lap0_late", "lap1", "later"]


def ol_s(lap, spline):
    """House wrapped spline (racecraft.lua:933): grid before the line reads 0.97-0.99 on lap 0."""
    if lap == 0 and spline > 0.5:
        return spline - 1.0
    return spline


def bucket(lap, spline, wrap_above):
    """Bucket a contact. `wrap_above` is the spline above which a LAP-0 car is still ON THE GRID, or None
    if this race's grid sits after the line (never wrap).

    AC's lapCount counts COMPLETED laps, and it does NOT increment at the first line crossing. So on a
    grid-before-line track LAP 0 SPANS BOTH the short grid stretch (spline ~0.98 -> 1.0) AND the entire
    first full lap (0.0 -> 1.0). That is exactly why the house wraps with olS (racecraft.lua:933) instead
    of shifting the lap index.

    An earlier version of this function shifted the lap index by one on such tracks, on the false premise
    that lapCount increments at the line. It therefore labelled THE WHOLE FIRST LAP as "launch" and
    inflated that bucket from 35.8 to 54.4 contacts per 100 car-laps. The falsifier was in the data the
    whole time: a 2-LAP race ends at lap 2, and its first snapshot has every car at lap 0 with spline
    0.977-0.997. If the line incremented the count, a 2-lap race would end at lap 3.

    `wrap_above` comes from the race's own grid splines rather than a fixed 0.5, because a bare "> 0.5"
    wraps a car that is merely 66% through its first lap into the grid phase. The house avoids this with
    cv2.crossed[i], which the diag does not carry.
    """
    if lap >= 2:
        return "later"
    if lap == 1:
        return "lap1"
    s = spline - 1.0 if (wrap_above is not None and spline >= wrap_above) else spline
    if s < 0:
        return "launch"
    if s < CV_END:
        return "convoy"
    return "lap0_late"


def read_diag(path):
    """-> (header, n_snaps, [contact records], laps). Tolerates partial lines: a diag is appended live.

    `laps` is the leader's final lap count, needed to normalise by EXPOSURE. Without it the only
    available figure is "% of all contacts", which is confounded by race length: in a 12-lap race the
    `later` bucket covers ten laps and the start covers seconds, so a share understates the start RATE
    by an order of magnitude.
    """
    hdr, snaps, cons, laps, gbl = None, 0, [], 0, None
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"hdr"' in line and hdr is None:
                try:
                    hdr = json.loads(line)
                except Exception:
                    pass
                continue
            if '"ev":"contact"' in line:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if "lap" in o and "spline" in o:
                    cons.append(o)
                continue
            if '"grid"' in line:
                snaps += 1
                try:
                    o = json.loads(line)
                    laps = max(laps, o.get("leaderLap") or 0)
                    if gbl is None:
                        # GRID GEOMETRY from this race's OWN first snapshot: if the lap-0 cars are sitting
                        # at a high spline they are still behind the timing line, and the wrap threshold is
                        # just under the lowest of them. A fixed 0.5 would wrap a car merely 66% through
                        # its first lap into the grid phase (seen on acu_unitedstates/east, 23 Oct).
                        sp = [c.get("spline", 0) / 1000.0 for c in o.get("grid", []) if (c.get("lap") or 0) == 0]
                        # A real pre-line grid sits at 0.97-0.99, so test against 0.90, not 0.5. With 0.5
                        # a single car 66% through its first lap set a 0.65 wrap on 3 races (COTA East,
                        # 23 Oct, where only one car was still on lap 0 by the first snapshot).
                        hi = [x for x in sp if x > 0.90]
                        if sp:
                            gbl = (min(hi) - 0.01) if (len(hi) > len(sp) / 2.0) else False
                except Exception:
                    pass
    return hdr, snaps, cons, laps, (gbl if isinstance(gbl, float) else None)


def arm_token(stem):
    """stock / ON / None from the label tokens alone. PURE, so the selftest can reach it.

    The track slug has a variable number of underscores (acu_unitedstates_east), so the label CANNOT be
    split off by position - that was this tool's first bug: it read the owner's track name as a label and
    called their session an ON arm. Only an explicit arm token counts.
    """
    toks = stem.lower().split("_")
    if "off" in toks or "stock" in toks:
        return "stock"
    if "on" in toks:
        return "ON"
    return None


def label_of(path, track):
    """The harness LABEL, using the header's own track to strip the slug - the only reliable way, since
    both the track and the label contain underscores. '' means no label.

    An earlier version used "is there a race_out_<stamp>.json" as the harness marker. It was wrong on
    real data: race_out files get cleaned up, so every one of 138 races - Monza 18-car harness rows
    included - came back 'owner'. A discriminator that degrades to one value when its evidence is
    missing reports a confident population that is entirely false.
    """
    base = path.replace("\\", "/").split("/")[-1]
    stem = base[len("diag_race_"):].rsplit(".", 1)[0]
    rest = "_".join(stem.split("_")[2:])          # drop YYYYMMDD_HHMMSS
    slug = (track or "").replace("/", "_")
    if slug and rest.startswith(slug):
        rest = rest[len(slug):]
    return rest.strip("_")


def arm_of(path, track):
    """ON / stock / owner. No label at all = an owner play session (they launch from the game, so the
    harness never names the file). A label with an off/stock token is the stock arm."""
    label = label_of(path, track)
    if not label:
        return "owner"
    return arm_token(label) or "ON"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    by_race = "--by-race" in sys.argv
    # AI-ONLY BY DEFAULT (owner's rule): slot 0 is the autopilot player, ignores Verve's level and grip
    # and starts on a different fuel load, so its contacts are not AI racecraft. --include-player to keep it.
    ai_only = "--include-player" not in sys.argv
    min_snaps = 5
    for a in sys.argv[1:]:
        if a.startswith("--min-snaps"):
            min_snaps = int(a.split("=")[1]) if "=" in a else 5
    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print("no diag files matched"); return

    # POPULATION FIRST - a count whose population was never printed is the defect this project keeps hitting.
    pop = collections.Counter()
    rows, skipped = [], []
    for p in paths:
        hdr, snaps, cons, laps, gbl = read_diag(p)
        if ai_only and cons:
            cons = [e for e in cons if e.get("car") != 0]
        if hdr is None or snaps < min_snaps:
            skipped.append((p, "hdr" if hdr is None else "%d snaps" % snaps)); continue
        track = hdr.get("track", "?")
        cars = len(hdr.get("cars", []))
        arm = arm_of(p, track)
        pop[(track, cars, arm)] += 1
        rows.append((p, track, cars, arm, cons, laps, gbl))

    print("POPULATION (%d scorable, %d skipped)   contacts: %s" % (
        len(rows), len(skipped), "AI ONLY, slot 0 excluded" if ai_only else "ALL CARS incl. slot 0"))
    for (track, cars, arm), n in sorted(pop.items(), key=lambda kv: -kv[1]):
        print("   %-34s %2d cars  %-6s  %d races" % (track, cars, arm, n))
    if skipped:
        print("   skipped: " + ", ".join("%s (%s)" % (p.split("/")[-1][:34], w) for p, w in skipped[:6])
              + (" ..." if len(skipped) > 6 else ""))
    if not rows:
        return

    for thresh, name in ((8, "jump8"), (30, "jump30"), (40, "jump40")):
        tally = collections.Counter()
        per_race = collections.defaultdict(list)
        for p, track, cars, arm, cons, laps, gbl in rows:
            c = collections.Counter()
            for e in cons:
                if e.get("dmg", 0) >= thresh:
                    c[bucket(e["lap"], e["spline"] / 1000.0, gbl)] += 1
            for b in BUCKETS:
                tally[b] += c[b]
                per_race[b].append(c[b])
        total = sum(tally[b] for b in BUCKETS)
        print("\n%s  (damage jump >= %d)   %d contacts over %d races" % (name, thresh, total, len(rows)))
        if total == 0:
            print("   none at this threshold - says nothing about lighter contact")
            continue
        for b in BUCKETS:
            vals = per_race[b]
            share = 100.0 * tally[b] / total
            print("   %-10s %4d  %5.1f%%   per race: %s" % (
                b, tally[b], share, " ".join(str(v) for v in vals[:14]) + (" ..." if len(vals) > 14 else "")))
        start = tally["launch"] + tally["convoy"]
        print("   -> START (launch+convoy) %d of %d = %.1f%%;  lap1 %d;  later %d" % (
            start, total, 100.0 * start / total, tally["lap1"], tally["later"]))

    # WITHIN-CELL ON vs STOCK. A pooled percentage is confounded by race length: a 12-lap race has one
    # opening lap and eleven later ones, so "% of all contacts" shrinks the start even if its RATE is high.
    # Contacts PER RACE inside one (track, cars) cell is the comparable figure, and only cells holding both
    # arms can say anything about Verve's start logic at all.
    # EXPOSURE-NORMALISED. This is the figure that answers "how many at the START, not just lap one".
    # Each bucket covers a different amount of racing, so counts and shares are not comparable:
    #   launch    the grid getaway, treated as 0.10 lap of exposure (it is seconds, not a lap)
    #   convoy    0.45 lap  (olS 0 -> CV.END)
    #   lap0_late 0.55 lap
    #   lap1      1.00 lap
    #   later     (leader laps - 2) laps, skipped for any race that never reached lap 2
    # The 0.10 for the launch window is a STATED ASSUMPTION, not a measurement: the diag gives no
    # green-flag timestamp, so the grid phase cannot be expressed as a lap fraction from the data. Treat
    # the launch row as order-of-magnitude only; the convoy row and below are grounded in olS.
    EXPOSURE = {"launch": 0.10, "convoy": CV_END, "lap0_late": 1.0 - CV_END, "lap1": 1.0}
    print("")
    print("PER CAR-LAP OF EXPOSURE (the length-confound removed)")
    for thresh, name in ((8, "jump8"), (40, "jump40")):
        cnt = collections.Counter()
        exp = collections.Counter()
        for p_, track, cars, arm, cons, laps, gbl in rows:
            for b in BUCKETS:
                if b == "later":
                    if laps >= 2:
                        exp[b] += cars * (laps - 2)
                else:
                    exp[b] += cars * EXPOSURE[b]
            for e in cons:
                if e.get("dmg", 0) >= thresh:
                    b = bucket(e["lap"], e["spline"] / 1000.0, gbl)
                    if b != "later" or laps >= 2:
                        cnt[b] += 1
        base = (cnt["later"] / exp["later"]) if exp["later"] else 0.0
        print("   %s   contacts per 100 car-laps        (x the later-race rate)" % name)
        for b in BUCKETS:
            if not exp[b]:
                continue
            rate = cnt[b] / exp[b]
            rel = ("%.1fx" % (rate / base)) if base else "-"
            print("      %-10s %6.2f   n=%-5d exposure %8.1f car-laps   %s" % (
                b, 100.0 * rate, cnt[b], exp[b], rel))

    print("")
    print("PER-RACE RATES, within (track, cars) cells that hold BOTH arms   [jump8 / jump40]")
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    for p_, track, cars, arm, cons, laps, gbl in rows:
        for thresh in (8, 40):
            c = collections.Counter()
            for e in cons:
                if e.get("dmg", 0) >= thresh:
                    c[bucket(e["lap"], e["spline"] / 1000.0, gbl)] += 1
            cells[(track, cars)][(arm, thresh)].append(
                (c["launch"] + c["convoy"], c["lap1"], c["later"]))
    any_cell = False
    for (track, cars), arms in sorted(cells.items()):
        present = {a for (a, t) in arms}
        if not ({"ON", "stock"} <= present):
            continue
        any_cell = True
        print("   %s  %d cars" % (track, cars))
        for thresh in (8, 40):
            for arm in ("ON", "stock"):
                v = arms[(arm, thresh)]
                n = len(v)
                st = [x[0] for x in v]; l1 = [x[1] for x in v]; lt = [x[2] for x in v]
                print("      jump%-2d %-5s n=%-3d START %.2f/race %-26s lap1 %.2f  later %.2f" % (
                    thresh, arm, n, sum(st) / n, "(" + " ".join(map(str, st[:10])) + ")",
                    sum(l1) / n, sum(lt) / n))
    if not any_cell:
        print("   no (track, cars) cell holds both arms - nothing here can attribute a start rate to Verve")

    if by_race:
        print("\nPER RACE (jump8)")
        for p, track, cars, arm, cons, laps, gbl in rows:
            c = collections.Counter(bucket(e["lap"], e["spline"] / 1000.0, gbl)
                                    for e in cons if e.get("dmg", 0) >= 8)
            print("   %-46s %-6s " % (p.replace("\\", "/").split("/")[-1][:46], arm)
                  + " ".join("%s=%d" % (b, c[b]) for b in BUCKETS))


def selftest():
    ok = True

    def check(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print("  FAIL %-46s got %r want %r" % (name, got, want))
        else:
            print("  pass %-46s %r" % (name, got))

    # CONTROL CASE, and the whole reason this tool needs a selftest: a grid that sits before the timing
    # line reads spline ~0.98 on lap 0. Without the house wrap that is "97% round the opening lap".
    # GRID BEFORE THE LINE: wrap_above ~0.97, so lap 0 holds BOTH the grid stretch AND the first full lap.
    W = 0.97
    check("on the grid, spline 0.980",            bucket(0, 0.980, W), "launch")
    check("on the grid, spline 0.995",            bucket(0, 0.995, W), "launch")
    check("just after the line, lap 0",           bucket(0, 0.010, W), "convoy")
    check("mid convoy zone, lap 0",               bucket(0, 0.440, W), "convoy")
    check("past CV.END, lap 0",                   bucket(0, 0.460, W), "lap0_late")
    # THE REGRESSION THIS CAUGHT: 66% through the FIRST lap is NOT the grid phase. A bare "> 0.5" wrap, or
    # a lap-index shift, called this launch and inflated the launch bucket by half.
    check("66% through the first lap is NOT launch", bucket(0, 0.659, W), "lap0_late")
    check("19% through the first lap is convoy",     bucket(0, 0.194, W), "convoy")
    check("second full lap",                      bucket(1, 0.100, W), "lap1")
    check("third lap is later",                   bucket(2, 0.100, W), "later")
    # GRID AFTER THE LINE: never wrap, so a high lap-0 spline is the END of the first lap, not the grid.
    check("no wrap: lap 0 at 0.98 is late, not launch", bucket(0, 0.980, None), "lap0_late")
    check("no wrap: lap 0 at 0.01 is convoy",           bucket(0, 0.010, None), "convoy")
    # a 2-LAP race ends at lap 2, which is the fact that disproves the lap-shift premise
    check("lap 2 is later even at a low spline", bucket(2, 0.010, W), "later")

    # MUTANT: reinstate the two bugs this function has actually had, and the controls MUST flip.
    def naive_no_wrap(lap, spline):
        if lap >= 2: return "later"
        if lap == 1: return "lap1"
        return "convoy" if spline < CV_END else "lap0_late"

    def naive_lapshift(lap, spline):
        openlap = lap - 1
        if openlap < 0: return "launch"
        if openlap >= 2: return "later"
        if openlap == 1: return "lap1"
        return "convoy" if spline < CV_END else "lap0_late"

    if naive_no_wrap(0, 0.980) == "launch":
        ok = False; print("  FAIL mutant 1: no-wrap bucketing still found the grid shunt")
    else:
        print("  pass mutant 1 without the wrap, a grid shunt becomes %r" % naive_no_wrap(0, 0.980))
    if naive_lapshift(0, 0.194) != "launch":
        ok = False; print("  FAIL mutant 2: the lap-shift bug did not reproduce - test has no teeth")
    else:
        print("  pass mutant 2 the lap-shift bug calls 19%% of the FIRST LAP 'launch', as it did in the "
              "reported numbers")

    # ARM TOKENS - pure, no filesystem. The control is the owner's own filename: its TRACK contains no
    # arm token, and the first version of this tool read that track slug as a label and said "ON".
    # CONTROL: the owner's filename is ALL stamp + track, so the label must come out EMPTY. The first
    # version read the track slug as a label; the second used race_out presence and called 138 harness
    # races 'owner' once those files were cleaned up. Both failed on the population line.
    check("owner session -> empty label",
          label_of("diag_race_20261025_125303_acu_unitedstates_east.jsonl", "acu_unitedstates/east"), "")
    check("owner session -> arm 'owner'",
          arm_of("diag_race_20261025_125303_acu_unitedstates_east.jsonl", "acu_unitedstates/east"), "owner")
    check("harness label survives slug strip",
          label_of("diag_race_20261025_075930_monza_fgm_off_4.jsonl", "monza"), "fgm_off_4")
    check("multi-underscore track slug stripped whole",
          label_of("diag_race_20261023_141119_acu_unitedstates_a_s52_wkdiag_1.jsonl", "acu_unitedstates/a"), "s52_wkdiag_1")
    check("harness arm from label", arm_of("diag_race_20261025_075930_monza_fgm_off_4.jsonl", "monza"), "stock")
    check("owner track slug yields NO arm token",
          arm_token("20261025_125303_acu_unitedstates_east"), None)
    check("off arm token", arm_token("20261025_075930_monza_fgm_off_4"), "stock")
    check("on arm token", arm_token("20261025_075930_monza_fgm_on_4"), "ON")
    check("'on' must be a whole token, not a substring of 'unitedstates'",
          arm_token("20261025_1_acu_unitedstates_east"), None)

    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
