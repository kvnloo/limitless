"""The synthetic limitless-context-packet example in docs/context-packet.md: python3 -I scripts/context_packet_example.py

A made-up state dir (a copy of the synthetic fixture state, tests/fixtures/state) in a temporary dir, at the
fixture clock, with the raw opt-in set to show it is ignored. Reads no real state, writes nothing outside the
temporary dir, sends nothing. It runs the real entry point (context_packet.main) four times: the dry run in
words, --write with no path set, --write with config context_packet_path set (then the file's mode and the
doctor row), and --json.
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import context_packet, doctor  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z, the fixture clock
TODAY = date(2030, 1, 15)
FIX = REPO / "tests" / "fixtures" / "state"

for k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[k]
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()


def run(*argv):
    print("$ limitless-context-packet" + "".join(" " + a for a in argv))
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = context_packet.main(list(argv), now=NOW, today=TODAY)
    sys.stdout.write(err.getvalue())
    print(f"(exit {code})")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    for f in FIX.iterdir():
        (st / f.name).write_bytes(f.read_bytes())
    cfg_file = root / "config.json"
    cfg = {"state": str(st)}
    cfg_file.write_text(json.dumps(cfg))
    os.environ.update(HOME=str(root), LIMITLESS_CONFIG=str(cfg_file), LIMITLESS_RAW_IN_PROMPT="1")
    run()
    run("--write")
    cfg["context_packet_path"] = "context-packet.json"
    cfg_file.write_text(json.dumps(cfg))
    run("--write")
    mode = stat.S_IMODE((st / "context-packet.json").stat().st_mode)
    print(f"$ stat -c %a context-packet.json\n{mode:o}")
    row = doctor.context_packet_row(cfg, NOW)
    print(f"$ limitless-doctor | grep 'context packet'\n{row['name']}: {row['status']}: {row['reason']}")
    run("--json")
