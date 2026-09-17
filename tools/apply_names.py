"""Apply the public (fictional) driver names to lib/drivers.lua. Names only: keys, buckets and the four stats are untouched.

    python tools/apply_names.py "%USERPROFILE%/Documents/Assetto Corsa/verve_desk/roster_names.csv" [lib/drivers.lua]

The CSV (kept OUTSIDE the repo, on the desk: it holds the real names) has columns roster, driver, newname, say_it (phonetic).
Every entry whose display name matches a `driver` gets name=<newname> and say='<phonetic>' (kart variants share the real
name, so they are renamed too). Entries not in the CSV are left as they are and listed at the end, so the owner can see
which names are still real. Run with the game CLOSED (CSP hot-reloads on any write here). Idempotent: a second run
finds the new names already in place and changes nothing.
"""
import csv, re, sys

names_csv = sys.argv[1]
lua_path = sys.argv[2] if len(sys.argv) > 2 else "lib/drivers.lua"

mapping = {}
with open(names_csv, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        real = (r.get("driver") or "").strip()
        new = (r.get("newname") or "").strip()
        say = (r.get("say_it (phonetic)") or r.get("say") or "").strip()
        if real and new:
            mapping[real] = (new, say)
already = {new for new, _ in mapping.values()}

src = open(lua_path, encoding="utf-8").read()
pat = re.compile(r"(\{ key='([^']+)', name=')([^']+)('(?:, say='[^']*')?)(, bucket='([^']+)')")
changed, kept, real_left = 0, 0, []


def q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def sub(m):
    global changed, kept
    head, key, name, _tail, rest, bucket = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
    if bucket == "archetype":
        return m.group(0)
    if name in mapping:
        new, say = mapping[name]
        changed += 1
        return f"{head}{q(new)}', say='{q(say)}'{rest}"
    if name in already:
        kept += 1
        return m.group(0)
    real_left.append((bucket, key, name))
    return m.group(0)


out = pat.sub(sub, src)
if out != src:
    open(lua_path, "w", encoding="utf-8", newline="\n").write(out)
print(f"renamed {changed}, already public {kept}, still real-named {len(real_left)}")
for b, k, n in real_left:
    print(f"  {b:9s} {k:32s} {n}")
