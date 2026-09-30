"""The twice-daily community report (owner 2026-09-30: the broadcast agent stops its hourly export; racecraft runs it 1-2x a day).

    python tools/community_daily.py

1. tools/community_pull.py: new opted-in race reports since the last pull (read-only SELECT; the DB password stays in .env).
2. tools/community_watch.py --full: the standing questions over every report so far (the old desk export + every pull),
   then the plain run: what MOVED since the last report.
3. Writes both to verve_desk/community/racecraft_<date>.md (appended per run, timestamped) and racecraft_latest.md, where the
   broadcast agent can read them. Nothing else on the desk is touched.
"""
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DESK = os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "community")


def run(args):
    p = subprocess.run([sys.executable, "-B"] + args, cwd=os.path.dirname(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.returncode and p.stderr else "")
    return "\n".join(line for line in out.splitlines() if "TLS verified" not in line).strip()


def main():
    now = datetime.datetime.now()
    pull = run([os.path.join(HERE, "community_pull.py")])
    moved = run([os.path.join(HERE, "community_watch.py")])
    full = run([os.path.join(HERE, "community_watch.py"), "--full"])
    text = ("## %s community report (racecraft)\n\n### Pull\n```\n%s\n```\n\n### What moved since the last report\n```\n%s\n```\n\n"
            "### Standing questions (all reports so far)\n```\n%s\n```\n" % (now.strftime("%Y-%m-%d %H:%M"), pull, moved, full))
    os.makedirs(DESK, exist_ok=True)
    day = os.path.join(DESK, "racecraft_%s.md" % now.strftime("%Y-%m-%d"))
    with open(day, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(DESK, "racecraft_latest.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
