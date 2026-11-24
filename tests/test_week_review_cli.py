"""bin/limitless-jobs dry run on a synthetic day-seven state shows the week review. Synthetic data only.

The state is written relative to the real clock (the CLI reads it): a habit week whose seventh day is
today, two check-ins (one Done, one No, one Skipped) and a habit cue a minute ago. No kevin-push is on
PATH and the dry run never pushes or writes.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
UTC = timezone.utc


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class WeekReviewDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        cue_at = time.time() - 60
        day7 = datetime.fromtimestamp(cue_at, UTC).date()
        self.week_of = day7 - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit", "start": "Synthetic start",
                      "checkins": {self.week_of.isoformat(): "Done",
                                   (self.week_of + timedelta(days=1)).isoformat(): "No",
                                   (self.week_of + timedelta(days=2)).isoformat(): "Skipped"}}
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": iso(cue_at)}) + "\n")
        self.env = {"HOME": str(self.home), "PATH": str(self.home / "no-bin"), "TZ": "UTC",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def dry_run(self):
        r = subprocess.run([sys.executable, "-I", str(CLI)], env=child_env(self.env), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ln for ln in r.stdout.splitlines() if ln.startswith("Week review: ")]

    def test_day_seven_shows_the_week_review_row(self):
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir())
        rows = self.dry_run()
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].startswith("Week review: deliver: habit cue event"), rows)
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir()), before)

    def test_no_started_week_drops_in_plain_words(self):
        self.assertEqual(self.dry_run(), ["Week review: drop: no habit week started"])
        self.assertFalse((self.st / "jobs-sent.jsonl").exists())

    def test_before_day_seven_is_not_triggered(self):
        early = dict(self.habit, week_of=(self.week_of + timedelta(days=2)).isoformat())
        (self.st / "habit.json").write_text(json.dumps(early))
        self.assertEqual(self.dry_run(), ["Week review: not_triggered: no habit cue on or after day seven yet"])


if __name__ == "__main__":
    unittest.main()
