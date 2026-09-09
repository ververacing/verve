# Verve — AI that feels human

A Custom Shaders Patch (CSP) Lua app for Assetto Corsa that makes the AI feel human and keep
racing, on **any** car and track:

- **Human pace variability** — per-driver personality, slow lap-to-lap pace drift, end-of-stint
  tyre fade, nerves under pressure, and a slipstream tow on straights.
- **Class-aware physics** — cold-tyre warm-up (slicks need heat, vintage barely), wet-weather
  caution, and dirty-air grip loss when following closely through corners. Scaled by car class.
- **Human errors** — occasional *gentle* bobbles on forgiving cars, never on high-downforce
  open-wheelers. Grip changes are slew-limited so an error never snaps a car into a spin.
- **Racecraft** — AI close up and pressure the car ahead, pull off-line to pass on straights,
  and make one clean defensive move to cover. Collision-awareness stays on, so they position
  and race rather than ram.
- **Self-recovery** — spun or beached AI that aren't wrecked get themselves going again:
  gentle throttle + steering back to the racing line, reversing off walls and out of
  car-to-car locks. Never touches the race start or pit exit.

Everything toggles and tunes in the in-game app panel.

## Install
1. Requires a recent **Custom Shaders Patch**.
2. Drag the `Verve` zip onto Content Manager (or unzip into `assettocorsa/apps/lua/Verve`).
3. In game, open the **Verve AI** app from the app sidebar and enable it.

## Notes
- Verve controls AI grip via CSP's public physics API. If you also run another AI-grip mod,
  they'll fight over the setting — Verve detects common ones and lets you defer (turn off
  "Control AI grip"; self-recovery keeps working). Use one grip layer at a time.
- Pace still scales with the race difficulty %. "Base AI grip" 1.00 = no grip cheat (more
  human); 1.20 = stock AC AI feel.

## Status
v0.4 — everything from v0.3 plus an auto-save / session-only model (edit live for one race, persist on Save), per-car and global Reset, and a review list that shows every car's detected class + override + level (editable on the grid before lights).

Original work. Not affiliated with, and contains no code from, other AI mods.
