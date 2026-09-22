"""The Verve gauntlet: build anonymised race cards for two sides (or a side and a reference), shuffle them, and write the
blind-critic prompt plus the answer key. The critic is a fresh agent that sees only the prompt file.

    python tools/gauntlet.py --a "diag_race_*d20_suite_base_monza*.jsonl" --b "diag_race_*d21_tow05_monza*.jsonl" \
        --question realism --name tow_vs_base --out <dir>

Writes <out>/<name>_prompt.md (the cards, labelled Race 1..N in random order, and the question) and
<out>/<name>_key.json (which label is which side). The critic's verdict is appended by hand / by the caller to
verve_desk/gauntlet/verdicts.jsonl as {"name","critic","picks":[labels in order of realism],"tells":[...]}.

Questions:
  realism  - "Rank these races by how much they look like real racing; for each, say what gave it away."
  which    - "Two races of the same event: which is the more realistic race, and why?" (two cards only)
"""
import argparse
import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import race_card  # noqa: E402

QUESTIONS = {
    "realism": (
        "You are a motorsport analyst. Below are {n} race summaries in the format of a timing screen: lap chart, results,\n"
        "incidents, overtakes, pit stops. Some may be from real racing, some from a simulator with AI drivers; you are not\n"
        "told which. Rank them from most to least like real racing. For EACH race give two or three concrete tells - the\n"
        "specific numbers or patterns that make it look real or artificial (for example the number of overtakes per lap,\n"
        "incident timing, gaps at the flag, lap-time spread, what happens in the first thirty seconds). Be specific and\n"
        "quantitative; do not hedge. Answer with a JSON object on the last line: {{\"ranking\": [race numbers most real\n"
        "first], \"tells\": {{\"1\": [..], \"2\": [..]}}}}."
    ),
    "which": (
        "You are a motorsport analyst. Below are two race summaries in the format of a timing screen. Both are from the\n"
        "same class and circuit. Which is the more realistic race - closer to what a real race of this class produces -\n"
        "and why? Name the specific numbers that decided it. Answer with a JSON object on the last line:\n"
        "{{\"pick\": <race number>, \"confidence\": 0-1, \"tells\": [..]}}."
    ),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="glob of diag files, side A")
    ap.add_argument("--b", required=True, help="glob of diag files, side B (or reference cards: *.md)")
    ap.add_argument("--question", default="realism", choices=list(QUESTIONS))
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "Documents", "Assetto Corsa", "verve_desk", "gauntlet"))
    ap.add_argument("--per-side", type=int, default=2)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--ref-format", action="store_true", help="sim cards in the reference format (for a vote against real cards)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rnd = random.Random(a.seed)
    sides = {}
    for side, pat in (("A", a.a), ("B", a.b)):
        files = sorted(glob.glob(pat), key=os.path.getmtime)
        cards = []
        for f in files:
            if len(cards) >= a.per_side and not f.endswith('.md'):
                cards = cards[-a.per_side:]

            if f.endswith(".md"):
                cards.append((f, open(f, encoding="utf-8").read()))
            else:
                c = race_card.build(f, label="RACE", ref_format=a.ref_format or any(x.endswith(".md") for x in glob.glob(a.b)))
                if c:
                    cards.append((f, c))
        sides[side] = cards[-a.per_side:]
    items = [(s, f, c) for s, cards in sides.items() for f, c in cards]
    rnd.shuffle(items)
    key, body = [], []
    for k, (s, f, c) in enumerate(items, 1):
        key.append({"label": k, "side": s, "file": os.path.basename(f)})
        body.append(c.replace("# RACE", f"# Race {k}", 1).replace("# Race A", f"# Race {k}", 1))
    q = QUESTIONS[a.question].format(n=len(items))
    prompt = q + "\n\n---\n\n" + "\n---\n\n".join(body)
    pp = os.path.join(a.out, f"{a.name}_prompt.md"); kp = os.path.join(a.out, f"{a.name}_key.json")
    open(pp, "w", encoding="utf-8").write(prompt)
    json.dump({"name": a.name, "question": a.question, "key": key}, open(kp, "w", encoding="utf-8"), indent=1)
    print("prompt:", pp); print("key:", kp); print("labels:", [(x["label"], x["side"]) for x in key])


if __name__ == "__main__":
    main()
