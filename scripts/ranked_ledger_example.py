"""The synthetic limitless-ranked example in docs/ranked-ledger.md: python3 -I scripts/ranked_ledger_example.py

A made-up ledger and a made-up Hermes session DB (tests/hermes_db_fixture.py) in a temporary dir; invented ids
only. It runs the real bin/limitless-ranked: agent adds (a dry run, writes, two refusals), list, one owner drop
reply through ingest, list again, then prints the ledger. Reads no real state, sends nothing.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "bin" / "limitless-ranked"
sys.path.insert(0, str(REPO / "tests"))
from hermes_db_fixture import make_db  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    ledger = root / "ranked-ledger.jsonl"
    env = {"HOME": str(root), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(st),
           "LIMITLESS_CONFIG": str(root / "config.json"), "LIMITLESS_RANKED_LEDGER": str(ledger)}
    now = time.time()
    db = root / "state.db"
    make_db(db, [("user", "drop: synthetic-item-b, synthetic-item-z", now - 600),
                 ("user", "thanks", now - 300)], started=now - 3600)

    def run(*args):
        print("$ limitless-ranked " + " ".join(f'"{a}"' if " " in a else a for a in args))
        r = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=60)
        sys.stdout.write(r.stdout)
        if r.returncode:
            print(f"(exit {r.returncode})")

    run("add", "synthetic-item-a", "built")
    run("add", "synthetic-item-a", "built", "--write")
    run("add", "synthetic-item-b", "open", "--write")
    run("add", "synthetic-item-c", "open", "--write")
    run("add", "synthetic-item-a", "verified", "--write")
    run("add", "synthetic-item-a", "verified", "--evidence", "a synthetic test run", "--write")
    run("add", "synthetic-item-c", "dropped", "--write")
    run("list")
    env["LIMITLESS_HERMES_DB"] = str(db)
    run("ingest")
    run("ingest", "--write")
    run("list")
    print("$ cat ranked-ledger.jsonl")
    sys.stdout.write(ledger.read_text())
