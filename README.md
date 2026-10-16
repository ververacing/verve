<img src="icon.png" width="96" align="left" alt="Verve">

# Verve — AI that feels human

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/ververacing)


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
  F1 slipstreams from far and passes precisely; a touring car dive‑bombs the inside).
  Collision‑awareness stays on, so they position, not ram.
- **Human errors** — one visible mistake per driver every few laps: a late brake and lock‑up, a
  missed apex, a snap and lift. The rate follows pace, so a rookie errs every two or three laps
  while a class's quickest driver rarely does. Offs are rare and spins rarer — open‑wheelers,
  prototypes and hypercars get half those odds, and on NASCAR and drift cars a mistake never
  becomes an off or a spin.
- **Self‑recovery** — spun or beached AI that aren't wrecked get themselves going again: gentle
  throttle + steering back to the line, reversing off walls and out of car‑to‑car locks, waiting
  for traffic before rejoining. Never touches the race start or pit exit.
- **Formula DRS discipline** — closes DRS when the game says it isn't available (outside a zone /
  out of range); in‑zone DRS is left to the game.

## Requirements
- **Custom Shaders Patch** build 3465 or newer (`REQUIRED_VERSION` in `manifest.ini`).
  Tested on 3465 and the preview builds players are on (3749–4157).
- Content Manager recommended.

## Install
- **Content Manager:** drag the `Verve` zip onto CM and confirm.
- **Manual:** unzip so the folder lands at `assettocorsa/apps/lua/Verve` (the zip is structured
  `apps/lua/Verve/…` for this). Then enable the **Verve AI** app in CM's app settings.

In game, open the **Verve AI** app from the app sidebar and enable it. You can review each car's
detected class and set per‑car levels on the grid before the lights.

## Before you race (three things that matter)
1. **The difficulty slider is real.** 80 is a beginner field, 90 an intermediate one, 100 a strong club racer.
   Verve makes the launcher's number the truth for every car without a driver (Content Manager's per-car grid
   levels only keep their spread around it, unless you hand-set them more than 10 apart), so start where you
   actually are — 100 is not the default, it's the top. **Driver profiles are opt-in**: unless you hit
   Randomize or assign one yourself, every car on the grid is governed by that slider.
   A car you *do* give a driver runs at that driver's own pace instead, whatever the slider says. Roughly, on a
   GT3 field: Rookie ≈ 83, Midfielder ≈ 87, Veteran ≈ 93, and the quickest named driver in a class runs at the
   **full 100** — each class's best sits at the ceiling by design, so a profiled grid is led at expert pace and
   strung out below it. The exact numbers shift by class (the same drivers on a formula field read about 82, 85,
   90 and 100) because every class has its own difficulty curve. Career events use their own curve again.
2. **Keep damage on, 50 % or more.** With damage off nothing ever retires, a wrecked car sits on the line all
   race, and the field never strings out the way a real one does.
3. **Turn off other AI mods and CSP's AI rubber‑banding / adaptation.** They write the same AI values Verve
   does. Verve watches for this and says so in its window; when it does, switch the other one off.

## Troubleshooting

**My formula / open-wheel races fall apart — cars spinning and retiring everywhere.**
Set `NEW_LATERAL_GRIP_ESTIMATION = 0` under `[AI_TWEAKS]` in Custom Shaders Patch's `new_behaviour.ini`.
CSP's lateral-grip estimation and Verve's own grip control both adjust AI grip. Each is sensible on its own —
CSP's setting genuinely *improves* stock AC — but together, on open-wheel cars, they can take a 20-car field
down to a handful of finishers. In our own testing a 20-car formula grid lost 12–20 cars with the key at 1 and
0–1 with it at 0. GT and touring cars are not affected, you do **not** need to change `FIX_GRIP_MULT`, and none
of this applies to CSP 3465 or older, where the setting does not exist.

**Cars retire or get parked more than I expect.**
Two settings matter most. Leave **damage on** at a real value rather than zero — with damage off Verve cannot
tell a wreck from a tap. And leave **Recovery on**: it is what clears a stricken car before the rest of the
field arrives. Turning Recovery off makes races worse, not purer — a field that finished intact with it on lost
five to seven cars of eighteen with it off, with roughly twice the incidents and no pace gained.

**The AI feels slower than the difficulty I chose.**
If you have assigned driver profiles, a profiled car sets its own pace and **ignores the slider** by design;
expect the quickest driver in a class to run at the level you chose and the rest to sit below it. If you have
not assigned any, every car follows the slider — see "Before you race" above for what each level means.

**The app does not appear, or every car sits still at the lights.**
That is Verve failing to load rather than a racing problem. Check CSP's Lua log for an error on startup, and
make sure you copied the whole `Verve` folder, `lib` included.

## Notes
- Verve controls AI grip via CSP's public physics API. If you also run another AI‑grip mod
  (e.g. AI Whisperer), they'll fight over the setting — Verve detects common ones and lets you
  defer ("Control AI grip" off; self‑recovery keeps working). **Use one AI‑grip layer at a time.**
- Pace still scales with the **race difficulty %** for cars without a driver (a car with a driver runs at
  that driver's pace). **Base AI grip** 1.20 = stock AC (default);
  lower for a more human, on‑the‑edge feel; above 1.20 for extra stick.
- The **aggression slider** in Quick Race is respected — Verve uses it as the racecraft baseline for cars
  without a driver (a car with a driver uses that driver's aggression).
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
