import json,glob,sys
for f in sys.argv[1:]:
    rows=[]
    for l in open(f,encoding="utf-8"):
        try: rows.append(json.loads(l))
        except ValueError: pass
    snaps=[r for r in rows if "grid" in r]; ok=lost=0
    for r in rows:
        if r.get("ev")=="drop" and r["age"]==0:
            car,t=r["car"],r["t"]
            before=[x for x in snaps if x["t"]<=t]; after=[x for x in snaps if x["t"]>t]
            if not before: continue
            b=[x for x in before[-1]["grid"] if x["i"]==car][0]; lap0=b["lap"]
            seq=[b]+[[x for x in s["grid"] if x["i"]==car][0] for s in after[:45]]
            for a,c in zip(seq,seq[1:]):
                if a["spline"]>900 and c["spline"]<100:
                    if c["lap"]>lap0: ok+=1
                    else: lost+=1
                    break
    print(f.split("_ks_")[0][-20:], "laps counted after a drop:", ok, "| lost:", lost)
