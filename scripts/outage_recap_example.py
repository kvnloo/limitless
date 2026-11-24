"""The synthetic outage-recap example in docs/outage-recap.md: python3 -I scripts/outage_recap_example.py

A made-up state dir, config and kevin-push log in a temporary dir, at the fixture clock in UTC. Three passes of
the outage_recap job (outage_recap_job.run, config outage_recap "write") with a fake push that records what it was
handed and reports a delivery; it never runs kevin-push or hermes. After each pass it prints the job's row and
the doctor's row (doctor.outage_recap_row). Pass one: pushes are still failing. Pass two: a push was delivered,
so the recap goes out once (its title, once key, why and body are printed). Pass three: a repeat poll, nothing
sent. Reads no real state, writes nothing outside the temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, outage_recap_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = 1894708800.0   # 2030-01-15T12:00:00Z, the fixture clock
RC1, NO_SENDER = "log (telegram rc=1)", "log (no sender profile)"

os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()


def at(day, hour):
    return int(datetime(2030, 1, day, hour, 0, tzinfo=UTC).timestamp())


def log_row(t, title, how):
    return {"at": t, "tag": "limitless", "cls": "decision", "title": title, "how": how,
            "body": "A synthetic message.\nWhy now: a synthetic reason"}


ROWS = [log_row(at(13, 21), "Week review", "telegram"),
        log_row(at(14, 7), "Wake-up brief", RC1), log_row(at(14, 7) + 300, "Wake-up brief", RC1),
        log_row(at(14, 21), "MIQ for tonight?", NO_SENDER), log_row(at(14, 23), "Pick one", "held (sleep mode)"),
        log_row(at(15, 9), "Back from nap", RC1)]
BACK = log_row(at(15, 11), "Habit check-in", "telegram")


class FakePush:
    """Stands in for bin/limitless-jobs' kevin-push call: prints what it was handed, reports a delivery."""

    def __call__(self, title, body, once=None, why=None):
        print(f"$ kevin-push limitless {json.dumps(title)} <body> --once {once} --why {json.dumps(why)}")
        print(body)
        return "telegram"


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg = {"outage_recap": "write", "push_log": "push-log.jsonl"}
    (root / "config.json").write_text(json.dumps(cfg))
    env = {"HOME": str(root), "LIMITLESS_CONFIG": str(root / "config.json")}
    log = st / "push-log.jsonl"
    passes = (("pushes are still failing", ROWS, NOW - 2 * 3600),
              ("a push was delivered: the outage is over", ROWS + [BACK], NOW - 3600 + 120),
              ("the next poll", ROWS + [BACK], NOW - 3600 + 420))
    for n, (what, rows, now) in enumerate(passes):
        log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"# pass {n + 1}: {what}")
        r = outage_recap_job.run(st, now, push=FakePush(), dry_run=False, env=env, tz=UTC)
        print(f"{r['job']}: {r['action']}: {r['reason']}")
        d = doctor.outage_recap_row(StateReader(st), cfg, now)
        print(f"{d['name']}: {d['status']}: {doctor.words(d['reason'])}")
        if n + 1 < len(passes):
            print()
