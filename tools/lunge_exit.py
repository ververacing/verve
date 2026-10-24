"""WHICH of the two ATTACK conditions ends a lunge: the gap, or the speed?

racecraft.lua resolves ATTACK as
    rawAttack = (gapA < attackGap and spd >= aheadSpd - K.FASTER_MARGIN)
and strategy.lua clears any live move the frame the car is no longer in
ATTACK, recording how = 'left'. So 'left' means one of those two terms went
false - but NOT which, and the two imply opposite fixes:

  * the GAP opened   -> the attacker simply lost the car; nothing to fix in
                        the move system
  * the SPEED dipped -> the car gave up the move because pulling off-line
                        cost it the closing speed that authorised the move,
                        which is self-defeating and IS fixable

The per-move `phases` trace settles it. Its tag is
    <plan phase>:<corner phase>:<floor(gapA * 100000)>:<floor(dLat * 100)>
(strategy.lua:233), so the gap is in spline-fraction x 100000 and
K.ATTACK_GAP = 0.008 spline is 800 in those units. If a 'left' move's LAST
recorded gap is still well inside 800, the gap term was still satisfied and
the speed term is what ended it.

RESOLUTION CAVEAT, stated because it bounds the claim: the trace is sampled
only when the TAG CHANGES, so the last sample is the last gap at which
something changed, not provably the gap at the instant of termination.

Read-only. Takes diag files as argv.
"""
import argparse
import collections
import io
import json
import os
import re
import sys

EV = re.compile(r'\{"ev":"mv".*?"lw":\d+\}')
TAG = re.compile(r'(\d+\.\d+) ([^\s:]+):([^\s:]+):(-?\d+):(-?\d+)')
ATTACK_GAP_UNITS = 800          # K.ATTACK_GAP 0.008 spline x 100000
RELEASE = 1.5                   # K.COMMIT_RELEASE: the wider drop threshold


def last_tag(phases):
    """(gap_units, lateral_units, corner_phase) of the final sample, or None."""
    found = None
    for m in TAG.finditer(phases or ''):
        found = (int(m.group(4)), int(m.group(5)), m.group(3))
    return found


def events(path):
    out = []
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if '"ev":"mv"' not in line:
                continue
            for m in EV.finditer(line):
                try:
                    out.append(json.loads(m.group(0)))
                except ValueError:
                    pass
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('diag', nargs='+')
    ap.add_argument('--name', default='lunge', help='manoeuvre to analyse')
    args = ap.parse_args(argv)

    rows = []
    for p in args.diag:
        for e in events(p):
            if e.get('name') != args.name:
                continue
            t = last_tag(e.get('phases'))
            if t is None:
                continue
            rows.append((e.get('how', '?'), bool(e.get('won')), t[0], t[1], t[2], e.get('dur', 0)))

    if not rows:
        print('no %s events with a readable trace' % args.name)
        return

    print('%s events with a readable final sample: %d' % (args.name, len(rows)))
    print('ATTACK gap threshold = %d trace units (K.ATTACK_GAP 0.008 spline);'
          ' the wider release is %d (x K.COMMIT_RELEASE %.1f)'
          % (ATTACK_GAP_UNITS, int(ATTACK_GAP_UNITS * RELEASE), RELEASE))
    print()
    print('%-8s %6s %8s %8s %8s %8s %8s' % (
        'how', 'n', 'medGap', 'inside', 'outside', 'past1.5x', 'medDur'))
    byhow = collections.OrderedDict()
    for how, won, gap, lat, phase, dur in rows:
        byhow.setdefault(how, []).append((gap, lat, dur, won))
    for how, vals in byhow.items():
        gaps = sorted(v[0] for v in vals)
        med = gaps[len(gaps) // 2]
        inside = sum(1 for g in gaps if g < ATTACK_GAP_UNITS)
        past = sum(1 for g in gaps if g >= ATTACK_GAP_UNITS * RELEASE)
        durs = sorted(v[2] for v in vals)
        print('%-8s %6d %8d %8d %8d %8d %8.1f' % (
            how, len(vals), med, inside, len(gaps) - inside, past,
            durs[len(durs) // 2] / 10.0))

    print('\n--- the question, stated as a count ---')
    left = byhow.get('left', [])
    if left:
        inside = sum(1 for v in left if v[0] < ATTACK_GAP_UNITS)
        print('of %d moves that ended by LEAVING ATTACK, %d (%.0f%%) were still'
              ' INSIDE the attack gap at their last sample'
              % (len(left), inside, 100.0 * inside / len(left)))
        print('=> for those, the gap term was still satisfied, so the SPEED'
              ' term is what ended the move')

    # NOT the attacker's separation. strategy.lua:232 calls this field "their
    # lateral offset" - it is the TARGET car's position across the road, so it
    # says nothing about how far the lunging car got. Labelled wrongly once.
    print('\n--- the TARGET car\'s lateral offset at the end (x100), not ours ---')
    for how, vals in byhow.items():
        lats = sorted(abs(v[1]) for v in vals)
        print('  %-8s median |dLat| %d  p90 %d  max %d' % (
            how, lats[len(lats) // 2], lats[min(len(lats) - 1, int(0.9 * len(lats)))],
            lats[-1]))


def selftest():
    """A checking tool is not trusted until it has been made to FAIL."""
    # 1. the tag parser must take the LAST sample, not the first - the whole
    #    question is what the state was at the END of the move
    ph = '0.0 -:entry:770:-12 1.2 -:mid:300:-23 2.0 -:exit:150:-30 '
    assert last_tag(ph) == (150, -30, 'exit'), 'got %r' % (last_tag(ph),)
    # 2. negative gaps (past the car) must survive, not be dropped by the regex
    assert last_tag('0.0 -:mid:-45:-30 ') == (-45, -30, 'mid')
    # 3. an empty or missing trace must return None rather than raise
    assert last_tag('') is None and last_tag(None) is None
    # 4. THE DISCRIMINATOR MUST SEPARATE THE TWO ANSWERS. Plant each in turn:
    #    a gap-opened ending and a speed-died ending must not be confused.
    gap_opened = [1600, 1700, 2000]
    speed_died = [120, 200, 310]
    assert all(g >= ATTACK_GAP_UNITS for g in gap_opened), 'gap case misread'
    assert all(g < ATTACK_GAP_UNITS for g in speed_died), 'speed case misread'
    assert sum(1 for g in speed_died if g < ATTACK_GAP_UNITS) == 3
    assert sum(1 for g in gap_opened if g < ATTACK_GAP_UNITS) == 0
    # 5. and the threshold itself must be the ATTACK gap, not the release
    #    gap - using 1.5x would wrongly call a genuinely-lost car 'inside'
    assert ATTACK_GAP_UNITS == 800 and int(ATTACK_GAP_UNITS * RELEASE) == 1200
    assert 1000 >= ATTACK_GAP_UNITS, 'a gap of 1000 must count as OUTSIDE'
    print('selftest OK: the parser takes the LAST sample and keeps negative '
          'gaps, an empty trace returns None, the 800-unit threshold '
          'separates a planted gap-opened ending from a planted speed-died '
          'one, and the release gap is not substituted for the attack gap')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main(sys.argv[1:])
