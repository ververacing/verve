"""One-click set-up for the owner's penalty test: writes a harness.lua that arms lib/fault.lua with penalties ENFORCED
and the free allowance at zero, autopilot OFF (you drive), no auto-shutdown, valid for 30 minutes. Then launch any race
from Content Manager as normal.

    python tools/penalty_test.py            # arm (30 min)
    python tools/penalty_test.py --off      # disarm now

What should happen: every contact is judged live (CSP log: "Verve fault: ..."). The first culpable contact of any car
already costs a 5 s penalty (free allowance 0). An AI car that gets one runs at 55 % throttle for ~9 s; if YOU get
one, AC shows its own slow-down penalty message and you must lift off the gas for 5 s. The race feed logs each
penalty as a "penalty" event. Run tools/fault_live.py on the race's diag file afterwards to compare.
"""
import os, sys, time
VERVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS_LUA = os.path.join(VERVE, "harness.lua")
if "--off" in sys.argv:
    if os.path.exists(HARNESS_LUA): os.remove(HARNESS_LUA)
    print("penalty test disarmed"); sys.exit(0)
body = ("-- written by tools/penalty_test.py; self-expiring; never shipped\n"
        "return { expires = %d, autopilot = false, label = 'penalty_test', shutdownAtEnd = false,\n"
        "         settings = { raceFeed = true }, fault = { ENABLED = true, ENFORCE = true, FREE = 0 } }\n" % (int(time.time()) + 1800))
open(HARNESS_LUA, "w", encoding="utf-8").write(body)
print("penalty test ARMED for 30 minutes: launch any race from Content Manager now. Disarm with --off.")
