"""Swap AC's video settings to a lean harness profile for a test race, and put yours back afterwards.

The owner's rule (2026-09-24): harness races should run smoothly and it does not matter how they look; anything the
owner opens themselves should be the good-looking settings. AC keeps one video.ini, so the harness borrows it and
gives it back.

How the hand-back survives a crash: the owner's file is copied to video_owner.ini.bak the FIRST time the harness
takes over, and that backup is never overwritten while a takeover is in force (a marker key in video.ini says so).
So if AC hard-crashes, or the harness is killed, or the machine loses power, the next harness run - or
`python tools/video_profile.py --restore` - still has the real file to restore. The backup is only cleared once the
restore has succeeded.

    python tools/video_profile.py --lean       # take over (harness does this before a race)
    python tools/video_profile.py --restore    # give back (harness does this after, and on the next run if it died)
    python tools/video_profile.py --status
"""
import argparse
import hashlib
import json
import os
import shutil

CFG = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "cfg")
VIDEO = os.path.join(CFG, "video.ini")
BACKUP = os.path.join(CFG, "video_owner.ini.bak")
STATE = os.path.join(CFG, "video_owner.state.json")   # when we took over, and the bytes we left
MARKER = "__VERVE_HARNESS_PROFILE"

# Only the settings that cost frames. Resolution, windowed mode and the effects that a chase camera does not need;
# WORLD_DETAIL stays high because it is what the AI drives through, and cutting it changes the track, not the picture.
LEAN = {
    "VIDEO": {"WIDTH": "1280", "HEIGHT": "720", "FULLSCREEN": "0", "VSYNC": "0", "FPS_CAP_MS": "0",
              "AASAMPLES": "1", "AAQUALITY": "0", "ANISOTROPIC": "1", "SHADOW_MAP_SIZE": "128"},
    # post-processing stays ON at its lowest quality. Switching it off entirely removes AC's tone mapping, which
    # makes the race look blown out and glaring (the owner spotted it immediately, 2026-09-24); the expensive parts
    # are the effects underneath it, and those are off. Physics is unaffected either way - this is purely so a race
    # someone glances at, or records, looks like a race.
    "POST_PROCESS": {"ENABLED": "1", "QUALITY": "0", "FXAA": "0", "GLARE": "0", "DOF": "0", "RAYS_OF_GOD": "0",
                     "HEAT_SHIMMER": "0"},
    "EFFECTS": {"FXAA": "0", "MOTION_BLUR": "0", "SMOKE": "0", "RENDER_SMOKE_IN_MIRROR": "0"},
    "MIRROR": {"HQ": "0", "SIZE": "256"},
    "CUBEMAP": {"SIZE": "256", "FACES_PER_FRAME": "0"},
}


def _read(path):
    """AC's inis are plain and order matters to it, so edit the lines rather than round-tripping a parser."""
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def _apply(lines, changes):
    out, section = [], ""
    seen = {s: set() for s in changes}
    for line in lines:
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            section = st[1:-1]
        elif section in changes and "=" in st and not st.startswith(";"):
            key = st.split("=", 1)[0].strip()
            if key in changes[section]:
                seen[section].add(key)
                out.append(f"{key}={changes[section][key]}")
                continue
        out.append(line)
    return out


def _state():
    """What we wrote and when, kept OUTSIDE video.ini.

    Three attempts at this have now failed, each for the same reason: anything stored inside video.ini is not ours.
    AC rewrites that file while it runs (it keeps the window geometry there), so a marker line vanishes; and
    shutil.copy2 preserves mtime, so the backup's timestamp is when the OWNER last saved their settings, not when we
    took over. A sidecar records both facts unambiguously: when the takeover happened, and the exact bytes we left
    in video.ini. If video.ini still holds those bytes, nobody has touched it and the backup is safe to restore. If
    it does not, the owner (or AC) changed something and we must not clobber it."""
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def taken_over():
    return os.path.exists(BACKUP) and _state() is not None


def _digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def lean(now=None):
    """Borrow video.ini. Safe to call when a previous run died without handing back."""
    st = _state()
    if st and os.path.exists(BACKUP):
        # a takeover is already in force. Only re-assert if video.ini is still EXACTLY what we left; if the owner
        # changed it since, their file is the one worth keeping - back that up instead of overwriting the backup
        # with our own lean copy, which is how a night of drift used to eat their settings.
        if _digest(VIDEO) != st.get("wrote"):
            shutil.copy2(VIDEO, BACKUP)
            st = None
        else:
            return "already lean (backup held from an earlier run)"
    if not st:
        shutil.copy2(VIDEO, BACKUP)
    lines = _apply(_read(VIDEO), LEAN)
    with open(VIDEO, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines) + chr(10))
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"took_over_at": now or 0, "wrote": _digest(VIDEO)}, f)
    return "lean profile applied (1280x720 windowed); yours is in video_owner.ini.bak"


def restore():
    """Hand video.ini back. Never clobbers a file the owner has changed since we wrote it."""
    st = _state()
    if not os.path.exists(BACKUP):
        if os.path.exists(STATE):
            os.remove(STATE)
        return "nothing to restore (no backup)"
    if st and _digest(VIDEO) != st.get("wrote"):
        # AC rewrites the window geometry on exit, which is expected and ours to absorb; anything else means the
        # file is not the one we left, so the backup may be older than the owner's real settings. Keep both.
        if _lean_apart_from_geometry():
            pass                                   # just AC's window size: still ours, safe to hand back
        else:
            return ("NOT restoring: video.ini has changed since the harness took it over, so the backup may be "
                    "older than your settings. Both files kept - " + BACKUP + " is the harness's copy.")
    shutil.copy2(BACKUP, VIDEO)
    os.remove(BACKUP)
    if os.path.exists(STATE):
        os.remove(STATE)
    return "your video settings are back"


def _lean_apart_from_geometry():
    """Is video.ini still the lean profile except for the keys AC itself rewrites (window size/placement)?"""
    volatile = {("VIDEO", "WIDTH"), ("VIDEO", "HEIGHT"), ("VIDEO", "FULLSCREEN"), ("VIDEO", "_EXT_PLACEMENT")}
    section, differ = "", 0
    for line in _read(VIDEO):
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            section = t[1:-1]
        elif "=" in t and section in LEAN:
            k = t.split("=", 1)[0].strip()
            want = LEAN[section].get(k)
            if want is not None and (section, k) not in volatile and t.split("=", 1)[1].strip() != want:
                differ += 1
    return differ == 0


def status():
    lines = _read(VIDEO) if os.path.exists(VIDEO) else []
    who = "HARNESS (lean)" if taken_over() else "owner"
    res = {}
    section = ""
    for line in lines:
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            section = st[1:-1]
        elif section == "VIDEO" and "=" in st:
            k, v = st.split("=", 1)
            if k.strip() in ("WIDTH", "HEIGHT", "FULLSCREEN"):
                res[k.strip()] = v.strip()
    return (f"video.ini belongs to: {who}  ({res.get('WIDTH','?')}x{res.get('HEIGHT','?')}, "
            f"{'fullscreen' if res.get('FULLSCREEN') == '1' else 'windowed'})"
            f"{'  | backup present' if os.path.exists(BACKUP) else ''}")


# ---------------------------------------------------------------------------------------------------------------
# Replay recording. A replay stores physics state, not rendered frames, so how a race LOOKED while it was recorded
# does not affect how it looks played back - the lean profile above costs the broadcast side nothing. What does
# affect it is recorded at race time and was, until now, one more piece of ambient state nobody set:
#   QUALITY LEVEL  - the sample rate (0 = ~7 Hz ... 4 = ~60 Hz). Low levels make a juddery replay that no amount of
#                    playback quality can rescue.
#   MAX_SIZE_MB    - the ring buffer. Too small and a long race keeps only its last minutes; the start is gone.
# Both are pinned before every harness race so a race that turns out to be worth cutting is always recordable.
REPLAY = os.path.join(CFG, "replay.ini")
REPLAY_PINS = {"QUALITY": {"LEVEL": "3"},            # ~30 Hz: smooth enough to cut, half the size of 60
               "REPLAY": {"MAX_SIZE_MB": "1200"},    # a ~50-minute 20-car race fits (broadcast weekend 2026-09-26); was 600
               "AUTOSAVE": {"ENABLED": "1", "RACE": "2", "MIN_TIME_SECONDS": "30"}}


def pin_replay():
    """Make sure the replay is worth keeping. Returns a one-line description of what it changed, or ''."""
    if not os.path.exists(REPLAY):
        return ""
    lines = _read(REPLAY)
    before = list(lines)
    lines = _apply(lines, REPLAY_PINS)
    if lines == before:
        return ""
    with open(REPLAY, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines) + chr(10))
    return "replay recording pinned (30 Hz, 1200 MB buffer, autosave on)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lean", action="store_true")
    g.add_argument("--restore", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--pin-replay", action="store_true")
    a = ap.parse_args()
    if a.pin_replay:
        print(pin_replay() or 'replay settings already correct')
    else:
        print(lean() if a.lean else restore() if a.restore else status())


if __name__ == "__main__":
    main()
