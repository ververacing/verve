"""Parse check for the Lua files (luaparser). Exit 1 on the first syntax error."""
import sys
from luaparser import ast
rc = 0
for p in sys.argv[1:]:
    try:
        ast.parse(open(p, encoding="utf-8").read()); print("%s: parse OK" % p)
    except Exception as e:
        print("%s: PARSE ERROR %s" % (p, e)); rc = 1
sys.exit(rc)
