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
import os
import shutil

CFG = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "cfg")
VIDEO = os.path.join(CFG, "video.ini")
BACKUP = os.path.join(CFG, "video_owner.ini.bak")
MARKER = "__VERVE_HARNESS_PROFILE"

# Only the settings that cost frames. Resolution, windowed mode and the effects that a chase camera does not need;
# WORLD_DETAIL stays high because it is what the AI drives through, and cutting it changes the track, not the picture.
LEAN = {
    "VIDEO": {"WIDTH": "1280", "HEIGHT": "720", "FULLSCREEN": "0", "VSYNC": "0", "FPS_CAP_MS": "0",
              "AASAMPLES": "1", "AAQUALITY": "0", "ANISOTROPIC": "1", "SHADOW_MAP_SIZE": "128"},
    "POST_PROCESS": {"ENABLED": "0", "QUALITY": "0", "FXAA": "0", "GLARE": "0", "DOF": "0", "RAYS_OF_GOD": "0",
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


def taken_over(lines):
    return any(l.strip().startswith(MARKER) for l in lines)


def lean():
    lines = _read(VIDEO)
    if taken_over(lines):
        return "already lean (a previous run did not restore; the backup is still yours)"
    shutil.copy2(VIDEO, BACKUP)                      # only ever written when NOT already taken over
    lines = _apply(lines, LEAN)
    lines.insert(0, f"{MARKER}=1")
    with open(VIDEO, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return "lean profile applied (1280x720 windowed, effects off); yours is in video_owner.ini.bak"


def restore():
    if not os.path.exists(BACKUP):
        return "nothing to restore (no backup)"
    if not taken_over(_read(VIDEO)):
        os.remove(BACKUP)
        return "video.ini was already yours; stale backup removed"
    shutil.copy2(BACKUP, VIDEO)
    os.remove(BACKUP)
    return "your video settings are back"


def status():
    lines = _read(VIDEO) if os.path.exists(VIDEO) else []
    who = "HARNESS (lean)" if taken_over(lines) else "owner"
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lean", action="store_true")
    g.add_argument("--restore", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    print(lean() if a.lean else restore() if a.restore else status())


if __name__ == "__main__":
    main()
