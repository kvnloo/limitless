"""delivery_audit: a run of transport failures (kevin-push's "log (telegram rc=N)") at the end of the window is
worded "the last pushes failed to send" and makes the goal not met; the counts stay T0 (raw opt-in only).

Synthetic kevin-push log rows, a fixed clock, UTC. Nothing is written or sent."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit as da, jobs, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
WHY = "Why now: you are awake and this fits any moment"
FAILED = "the last pushes failed to send"


def row(days_ago=0, how="telegram", hour=9, title="Pick one", minute=0):
    at = int(datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute, tzinfo=UTC).timestamp()) - days_ago * 86400
    return {"at": at, "tag": "x", "cls": "decision", "title": title, "how": how,
            "body": f"Keep the loop?\nReply: Yes / No\n{WHY}"}


def brief(days_ago, how="telegram"):
    return dict(row(days_ago, how, hour=7, title=jobs.WAKE_BRIEF.send_title),
                body="Good morning.\nReply: Yes / No\nWhy now: you woke up")


def rc(n=1):
    return f"log (telegram rc={n})"


def full_week(tail=()):
    """Every day of the window logged, a delivered brief on each wake day, then ``tail`` rows today."""
    rows = [brief(d) for d in range(6, -1, -1)] + [row(d, hour=10) for d in range(6, -1, -1)]
    return rows + list(tail)


SIGNALS = {"replies": [], "quiet": None, "why": None}
WAKES = [TODAY.fromordinal(TODAY.toordinal() - d) for d in range(7)]


def run(rows, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("tz", UTC)
    kw.setdefault("signals", SIGNALS)
    kw.setdefault("wake_days", WAKES)
    return da.audit(rows, **kw)


class TrailingFailures(unittest.TestCase):
    def test_a_clean_week_is_met_and_says_nothing_about_failures(self):
        a = run(full_week())
        self.assertEqual(da.goal(a), da.GOAL_MET)
        self.assertNotIn(FAILED, a["label"]["label"])
        self.assertEqual(a["send_failures"], {"failed": 0, "trailing": 0, "failing": False})

    def test_trailing_failures_are_worded_and_make_the_goal_not_met(self):
        a = run(full_week([row(0, rc(), hour=12), row(0, rc(), hour=13), row(0, rc(2), hour=14)]))
        self.assertIn(FAILED, a["label"]["label"])
        self.assertEqual(a["labels"]["send"], FAILED)
        self.assertEqual(da.goal(a), da.GOAL_NOT_MET)
        self.assertEqual(a["send_failures"], {"failed": 3, "trailing": 3, "failing": True})

    def test_the_words_hold_no_count(self):
        a = run(full_week([row(0, rc(), hour=h) for h in range(11, 20)]))
        self.assertFalse(any(c.isdigit() for c in a["label"]["label"]), a["label"]["label"])

    def test_a_delivery_after_the_failures_ends_the_run(self):
        a = run(full_week([row(0, rc(), hour=12), row(0, rc(), hour=13), row(0, hour=14)]))
        self.assertNotIn(FAILED, a["label"]["label"])
        self.assertEqual(da.goal(a), da.GOAL_MET)
        self.assertEqual(a["send_failures"], {"failed": 2, "trailing": 0, "failing": False})

    def test_one_trailing_failure_is_not_a_run(self):
        a = run(full_week([row(0, rc(), hour=12)]))
        self.assertNotIn(FAILED, a["label"]["label"])
        self.assertEqual(a["send_failures"]["trailing"], 1)
        self.assertFalse(a["send_failures"]["failing"])

    def test_rows_that_never_reached_the_transport_do_not_break_the_run(self):
        tail = [row(0, rc(), hour=12), row(0, "log", hour=13), row(0, "held (sleep mode)", hour=14),
                row(0, rc(), hour=15), row(0, "log (duplicate)", hour=16)]
        a = run(full_week(tail))
        self.assertEqual(a["send_failures"], {"failed": 2, "trailing": 2, "failing": True})
        self.assertIn(FAILED, a["label"]["label"])

    def test_the_run_is_read_in_time_order_not_file_order(self):
        tail = [row(0, rc(), hour=13), row(0, rc(), hour=14), row(0, hour=12)]
        self.assertTrue(run(full_week(tail))["send_failures"]["failing"])
        tail = [row(0, rc(), hour=12), row(0, rc(), hour=13), row(0, hour=14, minute=1)]
        self.assertFalse(run(full_week(tail[::-1]))["send_failures"]["failing"])

    def test_failures_before_the_window_do_not_count(self):
        a = run([row(9, rc(), hour=12), row(9, rc(), hour=13)] + full_week())
        self.assertEqual(a["send_failures"], {"failed": 0, "trailing": 0, "failing": False})

    def test_failing_on_the_last_day_spans_days(self):
        rows = [r for r in full_week() if r["at"] < row(0, hour=0)["at"]]   # nothing delivered today
        a = run(rows + [row(1, rc(), hour=23), row(0, rc(), hour=6)])
        self.assertEqual(a["send_failures"], {"failed": 2, "trailing": 2, "failing": True})

    def test_an_otherwise_unknown_week_is_still_not_met(self):
        a = run([row(0, rc(), hour=12), row(0, rc(), hour=13)], signals=None, wake_days=None)
        self.assertEqual(da.goal(a), da.GOAL_NOT_MET)


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        self.st.mkdir()
        log = self.st / "log.jsonl"
        tail = [row(0, rc(), hour=10, minute=30), row(0, rc(), hour=11)]
        log.write_text("".join(json.dumps(r) + "\n" for r in full_week(tail)))
        self.cfg = Path(self.tmp.name) / "config.json"
        self.cfg.write_text(json.dumps({"state": str(self.st), "push_log": "log.jsonl"}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "HOME": self.tmp.name}

    def get(self, raw):
        return tools.delivery(StateReader(self.st), NOW, raw=raw, env=self.env, home=Path(self.tmp.name), tz=UTC)

    def test_words_without_raw_and_the_counts_with_it(self):
        out = self.get(False)
        self.assertIn(FAILED, out["value"]["label"])
        self.assertNotIn("send_failures", out["value"])
        out = self.get(True)
        self.assertEqual(out["value"]["send_failures"], {"failed": 2, "trailing": 2, "failing": True})


if __name__ == "__main__":
    unittest.main()
