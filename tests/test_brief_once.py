"""The wake brief's two senders (bin/limitless-brief and bin/limitless-jobs) share one event key.

Synthetic data only. NOW is an arbitrary epoch; only differences between times matter.
Nothing sends: the push is a fake.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class OncePush:
    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return self.result


def touch(t):
    return {"ts": int(t * 1000), "type": "USER_INTERACTION", "pkg": "com.example.app"}


class EventKeyMatchesRunOnce(unittest.TestCase):
    """event_key is the key run_once passes for the same events, for every kind of wake."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, now):
        return jobs_runner.event_key(self.st, now, env=self.env, home=self.root)

    def pushed_key(self, now):
        push = OncePush()
        jobs_runner.run_once(self.st, now, push=push, dry_run=False, env=self.env, home=self.root)
        wake = [c for c in push.calls if c[0] == jobs.WAKE_BRIEF.send_title]
        self.assertEqual(len(wake), 1, push.calls)
        return wake[0][2]

    def assert_same(self, now, expect_at):
        k = self.key(now)
        self.assertEqual(k, f"wake_brief:{int(expect_at)}")
        self.assertEqual(self.pushed_key(now), k)

    def test_sleep_mode_wake(self):
        off = NOW - 0.2 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": off, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])
        self.assert_same(NOW, off)

    def test_screen_event_wake(self):
        wake = NOW - 0.5 * H
        write_rows(self.st / "screen-events.jsonl", [{"ts": NOW - 9 * H, "type": "KEYGUARD_HIDDEN", "pkg": "p"},
                                                     {"ts": wake, "type": "KEYGUARD_HIDDEN", "pkg": "p"}])
        self.assert_same(NOW, wake)

    def test_short_night_wake(self):
        t0 = NOW - 6 * H                           # quiet from t0+2h to t0+5.5h, the only long gap
        wake = t0 + 5.5 * H
        write_rows(self.st / "screen-events.jsonl", [touch(t0), touch(t0 + 2 * H), touch(wake), touch(t0 + 5.8 * H)])
        self.assert_same(NOW, wake)

    def test_no_trigger_is_none(self):
        self.assertIsNone(self.key(NOW))
        write_rows(self.st / "screen-events.jsonl", [touch(NOW - 2 * H), touch(NOW - H)])
        self.assertIsNone(self.key(NOW))

    def test_key_stays_after_the_runner_already_sent(self):
        # The runner sent first and logged it; a later sender still needs the same key so it is dropped.
        off = NOW - 0.2 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": off, "on": False}])
        jobs_runner.run_once(self.st, NOW, push=OncePush(), dry_run=False, env=self.env, home=self.root)
        self.assertTrue((self.st / jobs_runner.SENT_LOG).exists())
        self.assertEqual(self.key(NOW + 60), f"wake_brief:{int(off)}")

    def test_other_jobs_by_name(self):
        off = NOW - 0.2 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - H, "on": True}, {"at": off, "on": False}])
        self.assertEqual(jobs_runner.event_key(self.st, NOW, job="nap", env=self.env, home=self.root),
                         f"nap:{int(off)}")
        self.assertIsNone(self.key(NOW))           # a nap is not a wake
        with self.assertRaises(ValueError):
            jobs_runner.event_key(self.st, NOW, job="no_such_job", env=self.env, home=self.root)


if __name__ == "__main__":
    unittest.main()
