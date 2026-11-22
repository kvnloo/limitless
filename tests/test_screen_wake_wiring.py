"""Screen-event wakes on real-shaped rows: seconds or milliseconds, and the jobs runner uses them.

Synthetic rows only. NOW is an arbitrary epoch; only differences between times matter.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, wake_proxy  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0


def night(scale):
    """An evening unlock, a quiet night, a morning unlock; ``ts`` multiplied by ``scale`` (1 = s, 1000 = ms)."""
    return [{"ts": (NOW - 9 * H) * scale, "type": "KEYGUARD_HIDDEN", "pkg": "p"},
            {"ts": (NOW - 0.5 * H) * scale, "type": "KEYGUARD_HIDDEN", "pkg": "p"}]


class TimestampUnits(unittest.TestCase):
    def test_seconds_and_milliseconds_give_the_same_wake(self):
        s = wake_proxy.events_from_screen(night(1))
        ms = wake_proxy.events_from_screen(night(1000))
        self.assertEqual(len(s), 1)
        self.assertEqual(s, ms)
        self.assertEqual(s[0]["at"], NOW - 0.5 * H)


class RunnerUsesScreenWakes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_screen_wake_triggers_the_wake_brief_without_sleep_mode(self):
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in night(1)))
        rows = {r["job"]: r for r in jobs_runner.run_once(self.st, NOW, env=self.env, home=self.root)}
        self.assertNotEqual(rows["Wake-up brief"]["action"], jobs.NOT_TRIGGERED, rows["Wake-up brief"])


if __name__ == "__main__":
    unittest.main()
