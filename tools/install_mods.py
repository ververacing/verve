"""Install AC track / car mod archives: extract with 7-Zip to a staging folder, find the mod roots inside whatever
folder structure the archive uses (content/tracks/X, tracks/X, X/, or loose files), move them into the game's content
folders, then verify each one. Nothing is overwritten: an existing folder is left alone and reported.

    python tools/install_mods.py --tracks "%USERPROFILE%/Downloads/tracks" --cars "%USERPROFILE%/Downloads/car mods"
        [--staging <folder on a big drive>] [--ac <AC root, default: derived from this file>] [--dry]

Verification per track: every layout's ui_track.json (name, pit boxes, length), the AI line (ai/fast_lane.ai in the track
or the layout folder), models (*.kn5). Per car: ui/ui_car.json (name, class), data.acd or data/, sfx bank, skin count,
and a rough AI check (data/ai.ini readable if unpacked). Prints a table at the end.
"""
import argparse, json, os, re, shutil, subprocess, sys

SEVEN = os.environ.get("SEVENZIP", "C:/Program Files/7-Zip/7z.exe")


def extract(archive, dest):
    os.makedirs(dest, exist_ok=True)
    r = subprocess.run([SEVEN, "x", "-y", "-o" + dest, archive], capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[-400:]
    return True, ""


def is_track_root(p):
    if not os.path.isdir(p):
        return False
    names = set(os.listdir(p))
    has_kn5 = any(n.lower().endswith(".kn5") for n in names)
    return has_kn5 and ("ui" in names or "ai" in names or "data" in names or "models.ini" in names or any(n.lower().startswith("models") and n.lower().endswith(".ini") for n in names))


def is_car_root(p):
    if not os.path.isdir(p):
        return False
    names = set(n.lower() for n in os.listdir(p))
    return ("data.acd" in names or "data" in names) and ("ui" in names or "sfx" in names or any(n.endswith(".kn5") for n in names))


def find_roots(stage, kind):
    test = is_track_root if kind == "tracks" else is_car_root
    found = []
    for dirpath, dirnames, filenames in os.walk(stage):
        if test(dirpath):
            found.append(dirpath)
            dirnames[:] = []           # don't descend into a mod root
            continue
        # skip obvious non-mod folders
        dirnames[:] = [d for d in dirnames if d.lower() not in ("__macosx",)]
    return found


def read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        try:
            with open(p, encoding="latin-1") as f:
                txt = f.read()
            txt = re.sub(r",\s*([}\]])", r"\1", txt)
            return json.loads(txt)
        except Exception:
            return None


def verify_track(root):
    name = os.path.basename(root)
    layouts = []
    ui = os.path.join(root, "ui")
    if os.path.isfile(os.path.join(ui, "ui_track.json")):
        layouts.append(("", os.path.join(ui, "ui_track.json")))
    if os.path.isdir(ui):
        for d in sorted(os.listdir(ui)):
            if os.path.isfile(os.path.join(ui, d, "ui_track.json")):
                layouts.append((d, os.path.join(ui, d, "ui_track.json")))
    kn5 = [n for n in os.listdir(root) if n.lower().endswith(".kn5")]
    out = []
    for lay, uj in layouts:
        j = read_json(uj) or {}
        ai_dirs = [os.path.join(root, lay, "ai") if lay else None, os.path.join(root, "ai")]
        ai = any(d and os.path.isfile(os.path.join(d, "fast_lane.ai")) for d in ai_dirs)
        out.append({"track": name, "layout": lay or "(default)", "name": j.get("name", "?"), "pits": j.get("pitboxes", "?"),
                    "length": j.get("length", "?"), "ai": "yes" if ai else "NO", "kn5": len(kn5)})
    if not layouts:
        out.append({"track": name, "layout": "-", "name": "NO ui_track.json", "pits": "?", "length": "?", "ai": "?", "kn5": len(kn5)})
    return out


def verify_car(root):
    name = os.path.basename(root)
    j = read_json(os.path.join(root, "ui", "ui_car.json")) or {}
    names = set(n.lower() for n in os.listdir(root))
    data = "acd" if "data.acd" in names else ("dir" if "data" in names else "NONE")
    sfx = os.path.isdir(os.path.join(root, "sfx")) and any(n.lower().endswith(".bank") for n in os.listdir(os.path.join(root, "sfx")))
    skins = len(os.listdir(os.path.join(root, "skins"))) if os.path.isdir(os.path.join(root, "skins")) else 0
    kn5 = any(n.lower().endswith(".kn5") for n in names)
    ai_ini = os.path.isfile(os.path.join(root, "data", "ai.ini")) if data == "dir" else None
    return {"car": name, "name": j.get("name", "?"), "class": j.get("class", "?"), "brand": j.get("brand", "?"), "data": data,
            "sfx": "yes" if sfx else "NO", "kn5": "yes" if kn5 else "NO", "skins": skins, "ai.ini": ("yes" if ai_ini else "NO") if ai_ini is not None else "packed"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks"); ap.add_argument("--cars")
    ap.add_argument("--staging", default=r"D:\verve_mod_staging")
    ap.add_argument("--ac", default=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")))   # apps/lua/Verve/tools -> the AC root
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    results = {"tracks": [], "cars": []}
    skipped, failed = [], []
    for kind, src in (("tracks", a.tracks), ("cars", a.cars)):
        if not src:
            continue
        dest_base = os.path.join(a.ac, "content", kind)
        for arc in sorted(os.listdir(src)):
            arcp = os.path.join(src, arc)
            if not os.path.isfile(arcp):
                continue
            stage = os.path.join(a.staging, kind, re.sub(r"[^A-Za-z0-9_.-]+", "_", arc))
            if os.path.isdir(stage):
                shutil.rmtree(stage, ignore_errors=True)
            ok, err = extract(arcp, stage)
            if not ok:
                failed.append((arc, "extract failed: " + err.strip().splitlines()[-1] if err.strip() else "extract failed"))
                continue
            roots = find_roots(stage, kind)
            if not roots:
                failed.append((arc, "no %s root found in archive" % kind[:-1]))
                continue
            for root in roots:
                name = os.path.basename(root)
                dest = os.path.join(dest_base, name)
                if os.path.isdir(dest):
                    skipped.append((arc, name, "already installed, left alone"))
                    continue
                if a.dry:
                    print("DRY: would install", kind, name, "from", arc)
                else:
                    try:
                        shutil.copytree(root, dest)          # copy (staging may be on another drive), then best-effort cleanup
                    except Exception as e:                   # noqa: BLE001
                        shutil.rmtree(dest, ignore_errors=True)
                        failed.append((arc, name, "copy failed: %s" % e))
                        continue
                    shutil.rmtree(root, ignore_errors=True)
                vroot = dest if not a.dry else root
                if kind == "tracks":
                    for row in verify_track(vroot):
                        row["archive"] = arc; results["tracks"].append(row)
                else:
                    row = verify_car(vroot); row["archive"] = arc; results["cars"].append(row)
    print("\n=== TRACKS ===")
    print(f"{'track':34s} {'layout':16s} {'pits':>5s} {'len':>6s} {'AI':>3s} {'kn5':>4s}  name")
    for r in results["tracks"]:
        print(f"{r['track']:34s} {r['layout']:16s} {str(r['pits']):>5s} {str(r['length']):>6s} {r['ai']:>3s} {str(r['kn5']):>4s}  {r['name']}")
    print("\n=== CARS ===")
    print(f"{'folder':40s} {'data':5s} {'sfx':4s} {'kn5':4s} {'skins':>5s} {'ai.ini':7s} {'class':10s} name")
    for r in results["cars"]:
        print(f"{r['car']:40s} {r['data']:5s} {r['sfx']:4s} {r['kn5']:4s} {str(r['skins']):>5s} {r['ai.ini']:7s} {str(r['class'])[:10]:10s} {r['name']}")
    if skipped:
        print("\n=== SKIPPED (already present) ===")
        for s in skipped: print(" ", s)
    if failed:
        print("\n=== FAILED ===")
        for f in failed: print(" ", f)
    with open(os.path.join(a.staging, "install_report.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results, "skipped": skipped, "failed": failed}, f, indent=1)


if __name__ == "__main__":
    main()
