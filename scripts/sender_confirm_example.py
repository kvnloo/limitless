"""The synthetic sender-confirmation example in docs/sender-confirm.md: python3 -I scripts/sender_confirm_example.py

A made-up state dir, config, sender reply and kevin-push log in a temporary dir, at the fixture clock in UTC. The
owner's "push via <profile>" reply has just set the sender (push-sender.json, written here the way sender_reply
writes it). Passes of the sender_confirm job (sender_confirm_job.run, config sender_confirm "write") with a fake
push that prints what it was handed, appends the row kevin-push would log, and reports a failed send, a Sleep-mode
hold or a delivery; it never runs kevin-push or hermes. After each pass it prints the job's row and the doctor's
row (doctor.sender_confirm_row), which reads that log. Then one limitless-jobs pass (jobs_runner.run_once) with
the outage recap due on the same delivery: the confirmation goes first and the recap waits for the next pass.
Reads no real state, writes nothing outside the temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
import time
from datetime import timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, jobs_runner, sender_confirm_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = 1894708800.0   # 2030-01-15T12:00:00Z, the fixture clock
H = 3600

os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()


class FakePush:
    """Stands in for bin/limitless-jobs' kevin-push call: prints what it was handed, logs it like kevin-push."""

    def __init__(self, log, at, how):
        self.log, self.at, self.how = log, at, how

    def __call__(self, title, body, once=None, why=None):
        print(f"$ kevin-push limitless {json.dumps(title)} <body> --once {once} --why {json.dumps(why)}")
        print(body)
        how = self.how.split(" (exit")[0]
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": int(self.at), "tag": "limitless", "cls": "decision", "title": title,
                                "body": f"{body}\nWhy now: {why}", "how": how}) + "\n")
        print(f"kevin-push: {how}")
        return self.how


def setup(root, cfg):
    st = root / "state"
    st.mkdir()
    (root / "config.json").write_text(json.dumps(cfg))
    (st / "push-sender.json").write_text(json.dumps({"profile": "synthetic-bot", "at": NOW - 10 * 60}))
    return st, {"HOME": str(root), "LIMITLESS_CONFIG": str(root / "config.json")}


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "one"
    root.mkdir()
    cfg = {"sender_confirm": "write", "push_log": "push-log.jsonl"}
    st, env = setup(root, cfg)
    log = st / "push-log.jsonl"
    log.write_text("")
    passes = (("the reply set the sender; the new sender is broken", "log (telegram rc=1) (exit 3)", NOW),
              ("the owner fixed it; the phone is in Sleep mode", "held (sleep mode) (exit 3)", NOW + 300),
              ("Sleep mode is off", "telegram", NOW + 600),
              ("the next poll", "telegram", NOW + 900))
    for n, (what, how, now) in enumerate(passes):
        print(f"# pass {n + 1}: {what}")
        r = sender_confirm_job.run(st, now, push=FakePush(log, now, how), dry_run=False, env=env)
        print(f"{r['job']}: {r['action']}: {r['reason']}")
        d = doctor.sender_confirm_row(StateReader(st), cfg, now, env={})
        print(f"{d['name']}: {d['status']}: {doctor.words(d['reason'])}")
        print()

    root = Path(tmp) / "two"
    root.mkdir()
    cfg = {"sender_confirm": "write", "outage_recap": "write", "push_log": "push-log.jsonl"}
    st, env = setup(root, cfg)
    log = st / "push-log.jsonl"
    old = {"tag": "limitless", "cls": "decision", "body": "A synthetic message.\nWhy now: a synthetic reason"}
    rows = [dict(old, at=int(NOW - 5 * H), title="Wake-up brief", how="log (telegram rc=1)"),
            dict(old, at=int(NOW - 4 * H), title="Back from nap", how="log (no sender profile)"),
            dict(old, at=int(NOW - 20 * 60), title="Habit check-in", how="telegram")]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    for n, (what, now) in enumerate((("the sender changed and an outage just ended", NOW),
                                     ("the next limitless-jobs pass", NOW + 300))):
        print(f"# limitless-jobs pass {n + 1}: {what}")
        out = jobs_runner.run_once(st, now, push=FakePush(log, now, "telegram"), dry_run=False, env=env, tz=UTC)
        for r in out:
            if r["job"] in (sender_confirm_job.TITLE, "Outage recap"):
                print(f"{r['job']}: {r['action']}: {r['reason']}")
        if n == 0:
            print()
