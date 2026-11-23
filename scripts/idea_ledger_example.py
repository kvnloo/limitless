"""The synthetic idea-ledger example in docs/idea-ledger.md: python3 -I scripts/idea_ledger_example.py

Three synthetic captures (two quick captures, one bedtime message, one of them captured twice) in a temporary
state dir; reads no real state, writes nothing outside that dir, sends nothing. It runs the real
bin/limitless-ledger-append, then the limitless_ideas tool and the week review line, at a fixed clock.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import jobs_runner, schedule_cards, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = datetime(2033, 5, 18, 23, 0, tzinfo=UTC).timestamp()
CAPS = [("2033-05-17T19:10:00+00:00", "Synthetic: a shelf for the hallway", "hermes"),
        ("2033-05-18T21:40:00+00:00", "Synthetic: try a paper notebook for the week review", "hermes"),
        ("2033-05-18T22:15:00+00:00", "synthetic:  a SHELF for the hallway", "bedtime"),
        ("2033-05-18T22:30:00+00:00", "Synthetic: ask about the bike seat", "bedtime")]
CLI = REPO / "bin" / "limitless-ledger-append"


def run(env, *args):
    r = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True, timeout=30)
    print(f"$ limitless-ledger-append {' '.join(args)}".rstrip())
    print(r.stdout, end="")
    print(f"(exit {r.returncode})")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "captures.jsonl").write_text("".join(json.dumps({"at": a, "text": t, "source": s}) + "\n"
                                               for a, t, s in CAPS))
    base = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
    base.update(HOME=str(root), LIMITLESS_STATE=str(st), LIMITLESS_CONFIG=str(root / "config.json"))
    print("# no ledger set")
    run(base, "--write")
    env = dict(base, LIMITLESS_IDEA_LEDGER="ideas.jsonl")       # relative: in the state dir
    print("\n# ledger set to ideas.jsonl in the state dir")
    run(env)
    run(env, "--write")
    run(env, "--write")
    print("\n# the ledger (ideas.jsonl)")
    for ln in (st / "ideas.jsonl").read_text().splitlines():
        r = json.loads(ln)
        print(json.dumps({k: r[k] for k in ("kind", "id", "at", "source", "status")}) + "  # text left out")
    print("\n# limitless_ideas (no raw opt-in)")
    res = tools.ideas(StateReader(st), NOW, env=env, home=root)
    print(json.dumps({k: res[k] for k in ("value", "modality", "age_h", "evidence_tier")}))
    print("\n# week review line")
    print(jobs_runner.week_ideas(st, NOW, env, root))
    print("\n# its schedule card")
    print(schedule_cards.ledger_card()["description"])
