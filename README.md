# Verve — AI that feels human

A Custom Shaders Patch (CSP) Lua app for Assetto Corsa that makes the AI feel human and keep
racing, on **any** car and track. Toggle and tune everything in the in‑game panel.

## Features
- **Human pace variability** — per‑driver personality, slow lap‑to‑lap pace drift, end‑of‑stint
  tyre fade, nerves under pressure, and a slipstream tow on straights.
- **Class‑aware physics** — cold‑tyre warm‑up (slicks need heat, vintage barely), wet‑weather
  caution, and dirty‑air grip loss following closely through corners. Scaled by car class, which
  is auto‑detected (tags → name → car data) and overridable per car.
- **Our own racecraft** — cars close up and pressure, dive the inside of a corner when it's open,
  pass on the side the defender isn't, and make one clean defensive move. Per‑class tactics (an
  F1 slipstreams from far and passes precisely; a touring car dive‑bombs the inside) and per‑car
  levels (chill / clean / intense). Collision‑awareness stays on, so they position, not ram.
- **Human errors** — occasional *gentle* bobbles on forgiving cars, never on high‑downforce
  open‑wheelers. Grip changes are slew‑limited so an error never snaps a car into a spin.
- **Self‑recovery** — spun or beached AI that aren't wrecked get themselves going again: gentle
  throttle + steering back to the line, reversing off walls and out of car‑to‑car locks, waiting
  for traffic before rejoining. Never touches the race start or pit exit.
- **Formula DRS discipline** — closes DRS when the game says it isn't available (outside a zone /
  out of range); in‑zone DRS is left to the game.

## Requirements
- A recent **Custom Shaders Patch**. `REQUIRED_VERSION` in `manifest.ini` is the minimum CSP
  build (currently a conservative placeholder — validate against the oldest CSP you want to
  support before a public release).
- Content Manager recommended.

## Install
- **Content Manager:** drag the `Verve` zip onto CM and confirm.
- **Manual:** unzip so the folder lands at `assettocorsa/apps/lua/Verve` (the zip is structured
  `apps/lua/Verve/…` for this). Then enable the **Verve AI** app in CM's app settings.

In game, open the **Verve AI** app from the app sidebar and enable it. You can review each car's
detected class and set per‑car levels on the grid before the lights.

## Notes
- Verve controls AI grip via CSP's public physics API. If you also run another AI‑grip mod
  (e.g. AI Whisperer), they'll fight over the setting — Verve detects common ones and lets you
  defer ("Control AI grip" off; self‑recovery keeps working). **Use one AI‑grip layer at a time.**
- Pace still scales with the **race difficulty %**. **Base AI grip** 1.20 = stock AC (default);
  lower for a more human, on‑the‑edge feel; above 1.20 for extra stick.
- The **aggression slider** in Quick Race is respected — Verve uses it as the racecraft baseline.
- Settings and per‑car overrides are stored via CSP app storage, so **updates never wipe your
  tuning**.

## Updating
The app checks a small `version.json` on load and shows a banner with a download link if a newer
release exists. It only **notifies and links** — it never downloads or overwrites anything.

## Packaging a release (for maintainers)
- Keep the folder name **Verve** forever (renaming orphans everyone's saved settings).
- Zip with the internal structure `apps/lua/Verve/…` so drag‑and‑drop lands correctly.
- Bump `VERSION` in `manifest.ini` **and** `LOCAL_VERSION` in `lib/update.lua` every release, and
  update `changelog.txt` and `version.json`.
- Tag the GitHub release, attach the zip, then upload the same zip + notes to OverTake.

## Credits
Verve is **original work** and contains **no code** from other AI mods. It was inspired by the
AI‑tuning ideas the community explored — notably **AI Whisperer** by Benovic Boucharenski (itself
descended from Damgam's work) — and is built on the **Custom Shaders Patch** Lua SDK by
**Ilja Jusupov (x4fab)**. Thanks to all of them.

## License
Free to use and share unmodified with a link to the official source. No selling, no re‑hosting on
mirror sites, no redistributing modified copies as your own. See `LICENSE.txt`.
