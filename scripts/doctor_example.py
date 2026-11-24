"""The synthetic limitless-doctor example in docs/doctor.md: python3 -I scripts/doctor_example.py

A made-up state dir: the synthetic fixture state (tests/fixtures/state: six inputs, one of them down, a sync
run log) plus a made-up idea ledger and a made-up Hermes home (~/.hermes under the temp HOME) that holds
kevin-push's default sender profile, with a made-up bot token and a made-up chat for the default target's name,
at the fixture clock. Reads no real state, writes nothing outside a
temporary dir, sends nothing. It runs the real limitless-doctor entry point (doctor.main) twice: the plain-text
report, then --strict, whose exit code it prints.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z, the fixture clock
FIX = REPO / "tests" / "fixtures" / "state"

for k in [k for k in os.environ if k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "TELEGRAM_")) or k.startswith("HERMES_")]:
    del os.environ[k]
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    for f in FIX.iterdir():
        (st / f.name).write_bytes(f.read_bytes())
    (st / "ideas.jsonl").write_text(json.dumps({"kind": "idea", "id": "i1", "at": "2030-01-14T09:00:00Z",
                                                "text": "a made-up idea", "source": "hermes",
                                                "status": "new"}) + "\n")
    sender = root / ".hermes" / "profiles" / "intake"     # a made-up Hermes home with the sender profile
    sender.mkdir(parents=True)
    (sender / ".env").write_text("TELEGRAM_BOT_TOKEN=made-up-token\n")                 # never printed
    (sender / "channel_aliases.json").write_text(json.dumps({"telegram": {"100001": "kevin"}}))   # a made-up chat
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"state": str(st), "idea_ledger": "ideas.jsonl"}))
    os.environ["HOME"] = str(root)
    os.environ["LIMITLESS_CONFIG"] = str(cfg)
    print("$ limitless-doctor")
    code = doctor.main([], now=NOW)
    print("$ limitless-doctor --strict > /dev/null; echo $?")
    with contextlib.redirect_stdout(io.StringIO()):
        strict = doctor.main(["--strict"], now=NOW)
    print(strict)
