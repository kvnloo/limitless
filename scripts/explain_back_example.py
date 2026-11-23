"""The synthetic explain-back example in docs/explain-back.md: python3 -I scripts/explain_back_example.py

The repo's synthetic fixture state (tests/fixtures/state) copied to a temporary dir, one synthetic work item
landed, a fixed clock and window bands that put the fixture's wake in a trough. It runs the real pre_llm_call
hook twice, saves a Later and an answer through the limitless_capture handler, reads limitless_explain_back
with and without the raw opt-in and runs the idea ledger job. Reads no real state, writes nothing outside the
temporary dir, sends nothing.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import capture, card, explain_back, idea_ledger, plugin  # noqa: E402

NOW = 1894708800.0                 # the fixture clock; the fixture's wake is about five hours before it
TODAY = date(2030, 1, 15)
TROUGH = {"peak": [6, 8], "trough": [1, 6]}
ANSWER = ("The synthetic parser now reads the new field and old files still load. "
          "I could not explain why the retry waits twice.")


def hook(env):
    h = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY, bands=TROUGH)
    lines = h(session_id="s", user_message="hi")["context"].splitlines()
    print(f"card ends: {lines[-1]}")


def tool(name, args, env):
    with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
        out = json.loads(plugin._handler(plugin.TOOLS[name][1], name)(args))
    raw = " (LIMITLESS_RAW_IN_PROMPT=1)" if env.get("LIMITLESS_RAW_IN_PROMPT") == "1" else ""
    print(f"$ {name} {json.dumps(args, ensure_ascii=False)}{raw}")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    shutil.copytree(REPO / "tests" / "fixtures" / "state", st)
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))
    env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(cfg), "LIMITLESS_RAW_IN_PROMPT": "0"}
    item = st / "lanes" / "done" / "synthetic-parser.md"
    item.parent.mkdir(parents=True)
    item.write_text("synthetic body that is never read\n")
    os.utime(item, (NOW - 3600, NOW - 3600))

    print("# first trough turn after one item landed")
    hook(env)
    print(f"mark: {sorted(json.loads((st / explain_back.MARK_FILE).read_text()))}")
    print("# the next turn, same wake event")
    hook(env)

    print("# a Later tap, and a voice answer (its transcript), each through limitless_capture")
    tool("limitless_capture", {"text": "Later", "kind": "explain_back"}, env)
    tool("limitless_capture", {"text": ANSWER, "kind": "explain_back"}, env)
    row = json.loads((st / capture.FILE).read_text().splitlines()[-1])
    print(f"captures.jsonl row: kind={row['kind']} source={row['source']} unknowns={row['unknowns']}")

    print("# read back")
    tool("limitless_explain_back", {}, env)
    tool("limitless_explain_back", {}, dict(env, LIMITLESS_RAW_IN_PROMPT="1"))

    print("# the idea ledger job, with a ledger set")
    out = idea_ledger.run(st, env=dict(env, LIMITLESS_IDEA_LEDGER=str(st / "ideas.jsonl")), write=True)
    print(idea_ledger.words(out, True))
