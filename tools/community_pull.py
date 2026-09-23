"""Pull the outside race reports straight from the database, instead of waiting for the desk export.

These are opted-in reports from other people's installs (the app inserts them with a publishable, INSERT-only key).
Reading needs the database password, which lives in a gitignored .env and is never printed, logged or committed -
this script reads it, uses it and forgets it. Read-only by construction: it will not run anything but SELECT.

The four rules the data needs, applied here so every analysis starts from the same base:
  * drop unattended=true rows - those are our own harness, not players;
  * collapse duplicate sends (the client resends until the server acknowledges), keyed the way the broadcast agent
    keys them: install_id, session_type, track, cars, duration_s, player_best_lap_s, incidents;
  * never write install_id anywhere - it is replaced by left(md5(install_id), 6) as `inst`;
  * laps = 0 means a timed race: read duration_s instead.

    python tools/community_pull.py                 # new rows since the last pull, into harness_results/
    python tools/community_pull.py --since 2d      # a window, regardless of what was pulled before
    python tools/community_pull.py --sql "select track, count(*) from race_reports group by 1 order by 2 desc limit 10"
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "harness_results", "community")
STATE = os.path.join(OUT, "pull_state.json")

HOST = "aws-0-us-east-1.pooler.supabase.com"
PORT = 5432
DB = "postgres"
USER = "postgres.qcdnlochctwfsvslnqxo"
# where the password may live, in order; the first hit wins. Never printed.
ENV_VAR = "VERVE_DB_PASSWORD"
ENV_FILES = [os.path.join(HERE, os.pardir, ".env"),
             os.path.join(os.path.expanduser("~"), "Desktop", "verve-broadcast", ".env")]
ENV_KEYS = ("SUPABASE_VERVE_DB_PASSWORD", "VERVE_DB_PASSWORD")

DEDUPE_KEY = ("install_id", "session_type", "track", "cars", "duration_s", "player_best_lap_s", "incidents")


def password():
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    for path in ENV_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() in ENV_KEYS and v.strip():
                    return v.strip().strip('"').strip("'")
    raise SystemExit(f"no database password found (set {ENV_VAR} or put it in a gitignored .env); nothing pulled")


def connect():
    """Verified TLS only, trying each trust source this machine might have.

    Python's own store rejects the pooler here with "self-signed certificate in certificate chain" - something local
    is terminating TLS - so certifi's bundle and the Windows trust store are tried as well. Verification is never
    turned off: if all of them fail, that is a finding about the machine, not something to paper over."""
    try:
        import pg8000.dbapi
    except ImportError:
        raise SystemExit("pg8000 is not installed: pip install pg8000")
    import ssl
    ca = os.path.join(HERE, os.pardir, "supabase-ca.crt")   # Supabase signs database connections with its own root
    attempts = []
    if os.path.exists(ca):
        def pinned():
            """Verify against Supabase's own root, pinned - signature, chain, expiry and hostname all enforced.

            Python 3.13+ turns on VERIFY_X509_STRICT by default, and Supabase's 2021 root predates it: the root
            carries no keyUsage extension, so strict RFC 5280 checking rejects a chain that is otherwise perfectly
            valid (openssl s_client -CAfile against this same root returns 0/ok). Only that strictness flag is
            cleared, and only for this pinned-root context; nothing about who we trust changes."""
            ctx = ssl.create_default_context(cafile=ca)
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            return ctx
        attempts.append(("Supabase Root 2021 CA (pinned)", pinned))
    attempts.append(("python default store", lambda: ssl.create_default_context()))
    try:
        import certifi
        attempts.append(("certifi bundle", lambda: ssl.create_default_context(cafile=certifi.where())))
    except ImportError:
        pass
    try:
        import truststore
        attempts.append(("windows trust store", lambda: truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
    except ImportError:
        pass
    last = None
    for name, make in attempts:
        try:
            conn = pg8000.dbapi.Connection(user=USER, password=password(), host=HOST, port=PORT,
                                           database=DB, ssl_context=make())
            if name != "python default store":
                print(f"  (TLS verified via {name})")
            return conn
        except ssl.SSLError as e:
            last = f"{name}: {e}"
            print(f"  [tls] {name} did not verify: {str(e)[:110]}")
        except Exception as e:                      # pg8000 wraps some handshake failures
            last = f"{name}: {type(e).__name__}: {e}"
    raise SystemExit("TLS to the reports database failed every verified way: " + str(last)[:140]
                     + " -- try: pip install truststore certifi")


def query(sql, args=None):
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise SystemExit("read-only: only SELECT / WITH statements are allowed here")
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, args or ())
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def clean(rows):
    """Drop our own harness rows, collapse duplicate sends, replace install_id with a short hash."""
    out, seen = [], set()
    for r in rows:
        if r.get("unattended"):
            continue
        key = tuple(str(r.get(k)) for k in DEDUPE_KEY)
        if key in seen:
            continue
        seen.add(key)
        iid = r.pop("install_id", None)
        r["inst"] = hashlib.md5(str(iid).encode()).hexdigest()[:6] if iid else None
        for k, v in list(r.items()):
            if isinstance(v, (datetime.datetime, datetime.date)):
                r[k] = v.isoformat()
        out.append(r)
    return out



def tls_check():
    """Why TLS fails to the pooler: does verified HTTPS to the same project work on 443?

    If 443 verifies and 5432 does not, something local is intercepting the database port specifically (antivirus TLS
    scanning does this), which is a machine finding - not something to fix by trusting less."""
    import socket
    import ssl
    import urllib.request
    print("verified HTTPS to the project on 443:")
    try:
        req = urllib.request.Request("https://qcdnlochctwfsvslnqxo.supabase.co/rest/v1/", method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"  ok ({r.status}) - public CAs verify fine from this Python")
    except urllib.error.HTTPError as e:
        print(f"  ok (HTTP {e.code}) - TLS verified, the endpoint just refused the request")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
    print(f"verified TLS to {HOST}:{PORT} (the database port):")
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((HOST, PORT), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ss:
                print(f"  ok - {ss.version()}")
    except ssl.SSLError as e:
        print(f"  FAILED: {str(e)[:140]}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
    print("  (note: Postgres on 5432 starts in the clear and upgrades with STARTTLS, so a bare TLS handshake here")
    print("   failing is expected - the line above only tells you whether something answers and how)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="window like 6h / 2d, instead of 'since the last pull'")
    ap.add_argument("--sql", help="run one read-only query and print the rows as JSON")
    ap.add_argument("--tls-check", action="store_true", help="diagnose the TLS failure, change nothing")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    if a.tls_check:
        tls_check()
        return

    if a.sql:
        for row in query(a.sql):
            print(json.dumps(row, default=str))
        return

    if a.since:
        m = re.fullmatch(r"(\d+)([hd])", a.since)
        if not m:
            raise SystemExit("--since wants something like 6h or 2d")
        hours = int(m.group(1)) * (24 if m.group(2) == "d" else 1)
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).isoformat()
    else:
        state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
        cutoff = state.get("last_created_at") or "1970-01-01T00:00:00+00:00"

    rows = clean(query("select * from race_reports where created_at > %s order by created_at", (cutoff,)))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    if rows:
        path = os.path.join(OUT, f"pull_{stamp}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        newest = max(str(r.get("created_at")) for r in rows)
        if not a.since:
            json.dump({"last_created_at": newest, "pulled_at": stamp},
                      open(STATE, "w", encoding="utf-8"), indent=1)
        races = [r for r in rows if (r.get("session_type") or "").lower() == "race"]
        print(f"{len(rows)} new reports since {cutoff[:19]} -> {os.path.basename(path)}")
        print(f"  {len(races)} races, {len({r['inst'] for r in rows if r.get('inst')})} installs, "
              f"newest {newest[:19]}")
    else:
        print(f"nothing new since {cutoff[:19]}")


if __name__ == "__main__":
    main()
