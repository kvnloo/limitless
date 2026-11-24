"""The synthetic Sleep mode row example in docs/doctor.md: python3 -I scripts/sleep_mode_doctor_example.py

Made-up sleepmode.jsonl files (old rows without rule or left_on, newer rows with them) and a made-up poll
heartbeat, one temporary state dir each, at a fixed clock in UTC. Reads no real state, writes nothing outside
those dirs, sends nothing. Prints the doctor's own Sleep mode row (doctor.sleep_mode_row) for each.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor  # noqa: E402

UTC = timezone.utc
NOW = datetime(2033, 5, 18, 12, 0, tzinfo=UTC).timestamp()
H = 3600
LEFT = {"on": False, "inferred": "Sleep left on, owner up", "left_on": "rule-b"}


def iso(t):
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


CASES = [
    ("a night that ended (old rows: no rule, no left_on)", [{"at": NOW - 14 * H, "on": True},
                                                           {"at": NOW - 5 * H, "on": False}], NOW - 60),
    ("on since a nap began, poll fresh", [{"at": NOW - 3 * H, "on": True, "rule": "rule-a"}], NOW - 60),
    ("the same, but the poll stopped", [{"at": NOW - 3 * H, "on": True, "rule": "rule-a"}], NOW - 2 * H),
    ("a rule left on, not closed yet", [{"at": NOW - 37 * H, "on": True, "rule": "rule-b"}], NOW - 60),
    ("the poller closed it once the owner was seen up", [{"at": NOW - 37 * H, "on": True, "rule": "rule-b"},
                                                        dict(LEFT, at=NOW - 3 * H)], NOW - 60),
    ("no sleepmode.jsonl at all", None, None),
]

for k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[k]
for title, rows, poll in CASES:
    with tempfile.TemporaryDirectory() as tmp:
        st = Path(tmp)
        if rows is not None:
            (st / "sleepmode.jsonl").write_text("".join(json.dumps(dict(r, at=iso(r["at"]))) + "\n" for r in rows))
        if poll is not None:
            (st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(poll), "ok": True}))
        r = doctor.sleep_mode_row({"state": str(st)}, NOW, env={})
    print(f"# {title}")
    print(f"{r['name']}: {r['status']}: {doctor.words(r['reason'])}")
