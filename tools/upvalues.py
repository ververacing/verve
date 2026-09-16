"""Guard against LuaJIT's 120-upvalue limit: count file-level locals referenced inside each big function of a Lua file.
    python tools/upvalues.py lib/racecraft.lua
Verve failed to load on 2026-09-15 when R.evaluate's closure went over the limit (nothing in the log but 'failed to
compile bytecode'); run this after adding constants."""
import re, sys
for path in sys.argv[1:]:
    s = open(path, encoding="utf-8").read()
    names = set()
    for m in re.finditer(r"^local\s+([A-Za-z_][\w, ]*?)\s*(?:=|$)", s, re.M):
        for n in m.group(1).split(","):
            names.add(n.strip())
    for m in re.finditer(r"^local function\s+(\w+)", s, re.M):
        names.add(m.group(1))
    for m in re.finditer(r"^function\s+([\w.]+)\s*\(", s, re.M):
        start = m.end()
        nxt = re.search(r"^function\s+[\w.]+\s*\(", s[start:], re.M)
        body = s[start:start + nxt.start()] if nxt else s[start:]
        used = [n for n in names if n and re.search(r"\b" + re.escape(n) + r"\b", body)]
        flag = "  <-- near the limit" if len(used) > 105 else ""
        print(f"{path}: {m.group(1)}: {len(used)} upvalue candidates{flag}")
