"""The synthetic memory palace example in docs/palace.md: python3 -I scripts/palace_example.py

The repo's synthetic fixture state (tests/fixtures/state) copied to a temporary dir, a fixed clock and window
bands that put the fixture's wake in a trough, and the example link ``palace://example``. It reads
limitless_palace with no link set, sets the link, runs the real pre_llm_call hook twice, reads limitless_palace
and limitless_propose, and reads limitless_palace in a peak and with an Anki collection set. Reads no real
state, writes nothing outside the temporary dir, sends nothing.
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
from limitless import card, palace, plugin  # noqa: E402

NOW = 1894708800.0                 # the fixture clock; the fixture's wake is about five hours before it
TODAY = date(2030, 1, 15)
TROUGH = {"peak": [6, 8], "trough": [1, 6]}


def hook(env):
    h = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY, bands=TROUGH)
    lines = h(session_id="s", user_message="hi")["context"].splitlines()
    print(f"card ends: {lines[-1]}")


def tool(name, env):
    with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
        out = json.loads(plugin._handler(plugin.TOOLS[name][1], name)({}))
    print(f"$ {name} {{}}")
    if name == "limitless_propose":
        out = {"label": out["label"], "rule_id": out["value"]["rule_id"]}
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    shutil.copytree(REPO / "tests" / "fixtures" / "state", st)
    cfg = root / "config.json"
    env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(cfg), "LIMITLESS_RAW_IN_PROMPT": "0"}

    print("# no palace_link set: off")
    cfg.write_text(json.dumps({"window_bands": TROUGH}))
    tool("limitless_palace", env)
    print("# palace_link set, a trough")
    cfg.write_text(json.dumps({"window_bands": TROUGH, "palace_link": "palace://example"}))
    tool("limitless_palace", env)
    tool("limitless_propose", env)
    print("# the first trough turn")
    hook(env)
    print(f"mark: {sorted(json.loads((st / palace.MARK_FILE).read_text()))}")
    print("# the next turn, same wake event")
    hook(env)
    tool("limitless_palace", env)
    (st / palace.MARK_FILE).unlink()
    print("# a peak (the fixture's own bands)")
    cfg.write_text(json.dumps({"palace_link": "palace://example"}))
    tool("limitless_palace", env)
    print("# an Anki collection set too: the Anki offer wins the trough")
    col = root / "collection.anki2"
    col.write_bytes(b"")
    cfg.write_text(json.dumps({"window_bands": TROUGH, "palace_link": "palace://example", "anki_collection": str(col)}))
    tool("limitless_palace", env)
    tool("limitless_propose", env)
