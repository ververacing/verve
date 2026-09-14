# Contributing to Verve

Verve is one person's project with a lot of unattended testing behind it. Contributions are welcome; here is how they fit.

**Bugs.** Open an issue with the bug template. The track, cars and lap of the problem matter more than anything else; a
line or two from `Documents/Assetto Corsa/logs/custom_shaders_patch.log` containing "Verve" helps.

**Suggestions.** Use the suggestion template. The bar is "makes the racing more like real racing" -- consistent drivers,
close finishes, few retirements, across all classes and tracks. Ideas that only work for one car or one track usually
become a class rule rather than a special case.

**Code.** Fork, branch, keep changes small and behaviour-focused. Everything lives in `Verve.lua` and `lib/`:
`human.lua` (pace and mistakes), `racecraft.lua` (overtaking, defending, flags), `recovery.lua` (stuck cars, repairs,
retirements), `drivers.lua` (profiles), `difficulty.lua` / `career.lua` (the meter), `telemetry.lua` (opt-in reports).
Run at least one full race with your change before opening a pull request, and say which one in the PR.

**Driver profiles.** New real-name profiles are fine for private play, with stats sourced from real results. Published
videos use fictional names, so nothing you add needs to be "video-safe".

**Race scenario requests** belong on the board at https://ververacing.github.io/verve-site/, not in issues.
