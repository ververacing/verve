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
git add -A
git commit -q -m "Release $TAG" ${COMMIT_TRAILER:+-m "$COMMIT_TRAILER"} || echo "(nothing to commit)"
git tag -f "$TAG"

# --- 4. push (if a remote exists) ---
if git remote get-url origin >/dev/null 2>&1; then
    git push origin HEAD
    git push -f origin "$TAG"
    echo "pushed to origin + tag $TAG"
    # --- 5. GitHub Release with the zip (needs gh, authed once via `gh auth login`) ---
    GH_BIN="$(command -v gh 2>/dev/null || true)"
    [[ -z "$GH_BIN" && -x "/c/Program Files/GitHub CLI/gh.exe" ]] && GH_BIN="/c/Program Files/GitHub CLI/gh.exe"
    if [[ -n "$GH_BIN" ]] && "$GH_BIN" auth status >/dev/null 2>&1; then
        printf '%s\n' "$NOTES" > "$DIST/notes.txt"
        "$GH_BIN" release create "$TAG" "$ZIP" --title "Verve $TAG" --notes-file "$DIST/notes.txt" \
            && echo "GitHub Release $TAG created with zip attached"
    else
        echo ">> gh not found or not logged in ('gh auth login'): create the Release on GitHub's"
        echo "   web UI (Releases -> Draft) and attach $ZIP"
    fi
else
    echo ">> no 'origin' remote yet: add it, then re-run (or push manually). Zip is at $ZIP"
fi

echo ""
echo "== DONE for $TAG =="
echo "Manual step (always): upload $ZIP + the notes to the OverTake resource page."
echo "Then announce in Discord / Reddit for anything major."
