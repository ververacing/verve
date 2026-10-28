#!/usr/bin/env bash
# Verve release script (maintainer tool -- not shipped in the zip).
# Usage:  ./release.sh 0.6.7
# Steps: 1) edit changelog.txt first, adding a block at the top for the new version:
#              0.6.7
#              - what changed
#        2) run ./release.sh 0.6.7
# It bumps every version string, builds the drag-and-drop zip, commits, tags, pushes, and
# (if the GitHub CLI `gh` is installed + authed) creates the Release with the zip + notes.
set -euo pipefail

VER="${1:-}"
if [[ ! "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Usage: ./release.sh X.Y.Z  (e.g. ./release.sh 0.6.7)"; exit 1
fi
cd "$(dirname "$0")"
TAG="v$VER"
DIST="dist"
STAGE="$DIST/stage"
ZIP="$DIST/Verve-$TAG.zip"

# =============================================================================================
# --- PREFLIGHT GATE (owner-approved 2026-10-15). Nothing below runs until all of this passes. ---
# Every check here exists because this script's own steps are destructive and irreversible once
# step 4 pushes: it force-tagged, force-pushed that tag, and committed `git add -A` from whatever
# happened to be in the tree. A release is the one action we cannot take back, so the gate is
# deliberately a refusal and not a warning - and it NEVER prints DONE after a failure.
RELEASE_BRANCH="${RELEASE_BRANCH:-main}"
fail() { echo ""; echo "!! RELEASE REFUSED: $*"; echo "!! Nothing was built, committed, tagged or pushed."; exit 1; }
# After the build step something HAS been built/committed/tagged/pushed, so each caller states what it left instead.
fail_late() { echo ""; echo "!! RELEASE STOPPED PART-WAY: $*"; exit 1; }

# 0a. the tree must be clean. `git add -A` below would otherwise sweep in anything lying around.
[[ -z "$(git status --porcelain)" ]] || {
    git status --short | head -20
    fail "the working tree is dirty (above). Commit or stash first."
}

# 0b. the right branch. A release built from a feature branch ships code main has never seen.
BR="$(git branch --show-current)"
[[ "$BR" == "$RELEASE_BRANCH" ]] || fail "on branch '$BR', not '$RELEASE_BRANCH'. Set RELEASE_BRANCH= to override deliberately."

# 0c. the tag must NOT already exist, locally or on the remote. The old `git tag -f` + `push -f`
#     would silently move a published tag, so anyone who had already downloaded $TAG would hold
#     different code from the next person to download it, with no way to tell.
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && fail "tag $TAG already exists locally. Bump the version or delete the tag deliberately."
if git remote get-url origin >/dev/null 2>&1; then
    [[ -z "$(git ls-remote --tags origin "refs/tags/$TAG" 2>/dev/null)" ]] || fail "tag $TAG already exists on origin. It has been published - bump the version."
fi

# 0d. identity: no real name, work email or Windows path in anything that leaves the machine.
echo "-- preflight: identity gate (leak_check over the files this release publishes)"
LEAK_FILES="$(git diff --name-only "origin/$RELEASE_BRANCH..HEAD" 2>/dev/null || true)"
[[ -n "$LEAK_FILES" ]] || LEAK_FILES="$(git ls-files 'lib/*.lua' '*.lua' README.md changelog.txt manifest.ini version.json)"
python -I tools/leak_check.py $LEAK_FILES || fail "leak_check found identity material. Fix every line it names."
# AND THE HISTORY, which the file scan above cannot see. On 2026-10-16 the file scan reported "13 file(s) clean"
# on a range where two commits carried the OS user folder: a path was committed and then fixed forward, so the
# NET diff cancelled it out and no file's current content held it. A push publishes every commit in the range,
# so a line the range REMOVES is a line it PUBLISHES. --history reads `git log -p` and scans additions AND
# removals. THE REMEDY FOR A HIT HERE IS A SQUASH OR A REWRITE, never another forward fix, which only adds a
# second copy of the string as a removal line.
# SCOPE (owner decision 2026-10-28, option (a)): the history gate scans only commits NOT YET ON ANY origin branch
# (`git log HEAD --not --remotes=origin`), not origin/$RELEASE_BRANCH..HEAD. Releasing main from dev016 made the
# old range re-scan commits public on origin/dev016 for two weeks, and 13 lines in 5 of them (generic install
# paths and a one-letter placeholder user, nothing personal) blocked the release with only a rewrite of public
# history as the remedy. The gate exists to stop NEW material going public, so it scans what is new. The fetch
# (with --prune) is mandatory: a tracking ref left over from a branch since rewritten or deleted on origin would
# excuse commits that are no longer published. The --tree scan below is unchanged and still checks every file the
# tag will publish.
if git remote get-url origin >/dev/null 2>&1; then
    echo "-- preflight: identity gate over the HISTORY not yet on origin"
    git fetch -q --prune origin || fail "git fetch origin failed, so what is already published cannot be known."
    python -I tools/leak_check.py --history-unpublished \
        || fail "leak_check found identity material in the UNPUBLISHED COMMIT HISTORY. A forward fix will not help: squash or rewrite those commits before they are pushed."
fi
# AND THE WHOLE TREE, because `git tag` below FREEZES IT AND SERVES IT FOR EVER. The two gates above look at a
# DIFF and at a HISTORY; a tag publishes neither - it publishes every file at this commit, as a browsable tree
# and a source download, whether or not the file was touched in this release. On 2026-10-16 a three-branch scan
# passed while 24 published tags served identity material in their current content, because nothing had ever
# scanned a tree. A string in an untouched file is invisible to a range gate and permanent in a tag.
# This is also the LAST point a fix is cheap: once the tag is pushed, retagging or deleting a published tag is
# the owner's call and anyone who already downloaded it keeps what they got.
echo "-- preflight: identity gate over the TREE this tag will freeze"
python -I tools/leak_check.py --tree HEAD \
    || fail "leak_check found identity material in the TREE $TAG would publish. Fix the files it names and commit, then re-run - a tag cannot be fixed forward."

# 0e. the release gate itself: suite freshness, completeness and not-worse.
echo "-- preflight: release_check"
python -I tools/release_check.py ${RELEASE_CHECK_ARGS:-} || fail "release_check says NOT RELEASABLE. Read its output; a REFUSED line counts as a failure."

# 0f. the Lua must COMPILE and stay under LuaJIT's 120-upvalue ceiling. Over it, the app fails to
#     load and every race 'sits at the lights' - a release that does that is unusable, and it is
#     the one defect our own test harness cannot catch because the harness never presses Drive.
echo "-- preflight: Lua parse + upvalue ceiling"
python -I tools/parsecheck.py Verve.lua diag.lua lib/*.lua || fail "a Lua file does not parse."
python -I tools/upvalues.py lib/racecraft.lua lib/recovery.lua diag.lua Verve.lua > dist_upv.txt 2>&1 || true
python - <<'PY' || exit 1
import re, sys
worst, name = 0, ""
for line in open("dist_upv.txt", encoding="utf-8", errors="replace"):
    m = re.search(r"([\w.:]+): (\d+) upvalue", line)
    if m and int(m.group(2)) > worst:
        worst, name = int(m.group(2)), m.group(1)
print("   worst function: %s at %d of 120" % (name, worst))
if worst >= 120:
    print("!! RELEASE REFUSED: %s has %d upvalue candidates (limit 120). The app will not load." % (name, worst))
    sys.exit(1)
PY
rm -f dist_upv.txt

# 0g. (item 11 P1) THE UPDATE NOTICE MUST POINT AT THE BRANCH BEING RELEASED. update.lua fetches
#     version.json from a hard-coded branch; release.sh commits the bumped version.json to whatever branch it
#     is run on. Release from a branch the notice does not read, and every existing install keeps seeing the
#     old version until someone remembers to move the other branch - players get no update banner for a
#     release that shipped. dev016 has been 76+ commits ahead of main, so this was live, not theoretical.
#     Derived from the source rather than restated, so the two cannot drift apart again: the branch is parsed
#     out of U.VERSION_URL, and a URL shape this cannot parse is a REFUSAL, not a pass.
echo "-- preflight: the update notice reads the branch being released"
NOTIFY_BRANCH="$(python -I - <<'PY'
import io, re, sys
src = io.open("lib/update.lua", encoding="utf-8").read()
m = re.search(r'U\.VERSION_URL\s*=\s*"([^"]+)"', src)
if not m:
    sys.stderr.write("cannot find U.VERSION_URL in lib/update.lua\n"); sys.exit(1)
u = m.group(1)
b = re.search(r"raw\.githubusercontent\.com/[^/]+/[^/]+/([^/]+)/", u)
if not b:
    sys.stderr.write("cannot parse a branch out of U.VERSION_URL\n"); sys.exit(1)
print(b.group(1))
PY
)" || fail "could not determine which branch the update notice reads. Fix lib/update.lua or this gate."
[[ -n "$NOTIFY_BRANCH" ]] || fail "the update-notice branch came back empty."
echo "   update.lua reads: $NOTIFY_BRANCH   releasing from: $RELEASE_BRANCH"
[[ "$NOTIFY_BRANCH" == "$RELEASE_BRANCH" ]] || fail "update.lua fetches version.json from '$NOTIFY_BRANCH' but this release ships from '$RELEASE_BRANCH', so no installed copy would see it. Merge into '$NOTIFY_BRANCH' and release from there, or point U.VERSION_URL at '$RELEASE_BRANCH'."

echo "-- preflight: PASSED. Building $TAG."
# =============================================================================================

# --- 0. changelog must already describe this version (top block) ---
NOTES="$(awk -v v="$VER" '$0==v{g=1;next} g&&/^[0-9]+\.[0-9]+/{exit} g{print}' changelog.txt)"
if [[ -z "${NOTES// /}" ]]; then
    echo "!! changelog.txt has no block for $VER. Add one at the top, then re-run."; exit 1
fi

# --- 1. bump every version string (read-first, never truncate) ---
python - "$VER" <<'PY'
import sys, re
ver = sys.argv[1]
def sub(path, pat, repl):
    s = open(path, encoding="utf-8").read()
    s2 = re.sub(pat, repl, s, count=1)
    open(path, "w", encoding="utf-8").write(s2)
sub("manifest.ini",      r"(?m)^VERSION\s*=.*$",            f"VERSION = {ver}")
sub("lib/update.lua",    r'(?m)^(U\.LOCAL_VERSION\s*=\s*)".*?"', rf'\g<1>"{ver}"')
sub("version.json",      r'("version"\s*:\s*")[^"]*"',      rf'\g<1>{ver}"')
print("bumped ->", ver)
PY

# --- 2. build the drag-and-drop zip: internal structure apps/lua/Verve/... ---
rm -rf "$STAGE"; mkdir -p "$STAGE/apps/lua/Verve/lib"
cp manifest.ini Verve.lua version.json changelog.txt README.md LICENSE.txt "$STAGE/apps/lua/Verve/"
cp lib/*.lua "$STAGE/apps/lua/Verve/lib/"
# optional icon
[[ -f icon.png ]] && cp icon.png "$STAGE/apps/lua/Verve/"
rm -f "$ZIP"
WIN_SRC="$(cygpath -w "$STAGE/apps")"
WIN_ZIP="$(cygpath -w "$ZIP")"
powershell.exe -NoProfile -Command "Compress-Archive -Path '$WIN_SRC' -DestinationPath '$WIN_ZIP' -Force"
echo "built $ZIP"

# --- 3. commit + tag ---
# Only the files this script itself bumped. The old `git add -A` swept in whatever was lying
# around, which is why the dirty-tree gate above exists - but staging explicitly means even a
# future stray file cannot ride along inside a release commit.
git add manifest.ini lib/update.lua version.json changelog.txt
git commit -q -m "Release $TAG" ${COMMIT_TRAILER:+-m "$COMMIT_TRAILER"} || echo "(nothing to commit)"
# NOT `tag -f`. The gate above proved this tag does not exist; forcing it would silently move a
# published tag so two people downloading $TAG get different code with no way to tell.
git tag "$TAG" || fail_late "could not create tag $TAG - the zip is built and the release commit is local; nothing is tagged or pushed"

# --- 4. push (if a remote exists) ---
if git remote get-url origin >/dev/null 2>&1; then
    git push origin HEAD || fail_late "push of HEAD failed - the tag is local only, nothing is published"
    # NOT `push -f`. A force-push of a tag rewrites what a published version points at.
    git push origin "$TAG" || fail_late "push of tag $TAG failed - HEAD is pushed but the tag is not"
    echo "pushed to origin + tag $TAG"
    # --- 5. GitHub Release with the zip (needs gh, authed once via `gh auth login`) ---
    GH_BIN="$(command -v gh 2>/dev/null || true)"
    [[ -z "$GH_BIN" && -x "/c/Program Files/GitHub CLI/gh.exe" ]] && GH_BIN="/c/Program Files/GitHub CLI/gh.exe"
    if [[ -n "$GH_BIN" ]] && "$GH_BIN" auth status >/dev/null 2>&1; then
        printf '%s\n' "$NOTES" > "$DIST/notes.txt"
        "$GH_BIN" release create "$TAG" "$ZIP" --title "Verve $TAG" --notes-file "$DIST/notes.txt" \
            && echo "GitHub Release $TAG created with zip attached"
    else
        INCOMPLETE="gh not found or not logged in, so NO GitHub Release was created"
        echo ">> $INCOMPLETE: create the Release on GitHub's web UI (Releases -> Draft) and attach $ZIP"
    fi
else
    INCOMPLETE="no 'origin' remote, so nothing was pushed and no Release exists"
    echo ">> $INCOMPLETE: add the remote, then re-run (or push manually). Zip is at $ZIP"
fi

echo ""
# NEVER PRINT A BARE "DONE" AFTER A STEP FELL THROUGH. The old script printed "== DONE ==" even
# when it had skipped the push or the GitHub Release entirely, which reads as a finished release
# and is how a half-published version gets announced.
if [[ -n "${INCOMPLETE:-}" ]]; then
    echo "== INCOMPLETE for $TAG: $INCOMPLETE =="
    echo "   The zip is built and the tag is local. Finish the remaining step by hand before announcing."
    exit 2
fi
echo "== DONE for $TAG =="
echo "Manual step (always): upload $ZIP + the notes to the OverTake resource page."
echo "Then announce in Discord / Reddit for anything major."
