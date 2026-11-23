"""The synthetic flow-ledger example in docs/flow-ledger.md: python3 -I scripts/flow_ledger_example.py

A synthetic ActivityWatch DB (the tests' make_db) and work queue in a temporary dir; reads no real state, writes
nothing else, sends nothing. UTC stands in for the local zone.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from limitless import jobs_runner, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week import make_db  # noqa: E402

UTC = timezone.utc
DS = datetime(2033, 5, 17, tzinfo=UTC).timestamp()
NOW = DS + 86400 + 8 * 3600
M, H = 60, 3600


def block(at, minutes, look):
    mid = at + 40 * M
    return [(at, mid, "editor"), (mid, mid + 2 * M, look), (mid + 2 * M, at + minutes * M, "editor")]


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    for sub in ("done", "failed", "running"):
        (st / "lanes" / sub).mkdir(parents=True)
    make_db(st / "aw.db", spans=block(DS + 9 * H, 110, "chat") + block(DS + 13 * H, 95, "feed")
            + block(DS + 16 * H, 30, "feed"))
    for i, (sub, at) in enumerate((("done", 11), ("done", 15), ("done", 17), ("failed", 12), ("running", 18))):
        p = st / "lanes" / sub / f"synthetic-{i}.md"
        p.write_text("synthetic\n")
        os.utime(p, (DS + at * H, DS + at * H))
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"aw_db": "aw.db", "flow_work_apps": ["editor"], "feed_apps": ["feed"],
                               "work_queue_dir": "lanes"}))
    env = {"LIMITLESS_CONFIG": str(cfg)}
    r = StateReader(st)
    print("## tool, default")
    print(json.dumps(tools.flow_ledger(r, NOW, env=env, home=root, tz=UTC), indent=1))
    print("## tool, LIMITLESS_RAW_IN_PROMPT=1")
    print(json.dumps(tools.flow_ledger(r, NOW, raw=True, env=env, home=root, tz=UTC), indent=1))
    print("## wake brief line")
    print(jobs_runner.brief_flow_ledger(st, NOW, env, root, UTC))
    print("## the same morning with no work apps set")
    cfg.write_text(json.dumps({"aw_db": "aw.db"}))
    print(json.dumps(tools.flow_ledger(r, NOW, env=env, home=root, tz=UTC), indent=1))
    print(repr(jobs_runner.brief_flow_ledger(st, NOW, env, root, UTC)))
