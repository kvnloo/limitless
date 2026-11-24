"""The week review's rides line (rides.review_line, digit-free) after the body line; the card gets none.

Synthetic rows only, a fake push, a fixed clock.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import card, jobs, jobs_runner, weekly_target  # noqa: E402

KD = "\nReply: Keep / Drop"   # the week review's choices line (one_tap), always its last line
from limitless.state_reader import StateReader  # noqa: E402
from test_body_review import body_rows  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
FIX = ROOT / "tests" / "fixtures" / "state"


def ride_rows(this=(1, 4), last=(9,), kind="rehit"):
    return [{"start": f"{(TODAY - timedelta(days=d)).isoformat()}T07:00:00+00:00", "duration_s": 600, "kind": kind,
             "source": "synthetic-bike-app"} for d in tuple(last) + tuple(this)]


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def configure(self, **cfg):
        self.cfg.write_text(json.dumps(cfg))

    def write(self, name, rows):
        (self.st / name).write_text("".join(json.dumps(r) + "\n" for r in rows))

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")

    def test_body_puts_the_rides_line_after_the_body_line(self):
        text = jobs.week_review_text(self.habit) + "\n" + weekly_target.REVIEW_ON_THE_WAY
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, flow="Flow: x.", body_line="Body: y.",
                                          rides_line="Rides: z."),
                         text + "\nFlow: x.\nBody: y.\nRides: z." + KD)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, rides_line=""), text + KD)
        self.assertNotIn("Rides", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, rides_line="Rides: z."))

    def test_the_review_carries_the_ride_words(self):
        self.configure(rides_file="rides.jsonl")
        self.write("rides.jsonl", ride_rows())
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY,
                                         "Rides this week: two, more than last week."])

    def test_a_week_with_no_ride_says_none_never_missed(self):
        self.configure(rides_file="rides.jsonl")
        self.write("rides.jsonl", ride_rows(this=(), last=(8, 10)))
        lines = self.review()
        self.assertEqual(lines[-1], "Rides this week: none, fewer than last week.")
        self.assertNotIn("missed", "\n".join(lines[1:]).lower())

    def test_after_the_body_line_and_digit_free(self):
        self.configure(rides_file="rides.jsonl", body_file="body.jsonl")
        self.write("rides.jsonl", ride_rows())
        self.write("body.jsonl", body_rows())
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY, "Body fat trending down (calibrated estimate).",
                                     "Rides this week: two, more than last week."])
        self.assertEqual(re.findall(r"\d", lines[3]), [])

    def test_no_rides_file_or_no_ride_row_leaves_the_review_unchanged(self):
        self.write("rides.jsonl", ride_rows())
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])
        self.configure(rides_file="absent.jsonl")
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])
        self.configure(rides_file="rides.jsonl")
        self.write("rides.jsonl", ride_rows(kind="walking"))
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_week_rides_helper(self):
        self.configure(rides_file="rides.jsonl")
        self.write("rides.jsonl", ride_rows())
        self.assertEqual(jobs_runner.week_rides(self.st, self.env, self.root, TODAY),
                         "Rides this week: two, more than last week.")
        self.assertEqual(jobs_runner.week_rides(self.st, self.env, self.root), "")   # no today: no clock read
        self.configure()
        self.assertEqual(jobs_runner.week_rides(self.st, self.env, self.root, TODAY), "")

    def test_the_rides_file_is_never_written(self):
        self.configure(rides_file="rides.jsonl")
        self.write("rides.jsonl", ride_rows())
        p = self.st / "rides.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.review()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)


class CardHasNoRidesLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = Path(self.tmp.name) / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def build(self, raw=False):
        now = 1894708800.0
        today = datetime.fromtimestamp(now).date()
        return card.build(StateReader(self.st), now, today, raw=raw, env=self.env, owner={"value": None})["lines"]

    def test_the_card_is_the_same_five_lines_with_a_rides_file(self):
        before = self.build()
        self.assertEqual(len(before[1:]), 5)   # the header, then five label lines
        today = datetime.fromtimestamp(1894708800.0).date()
        rows = [{"start": f"{(today - timedelta(days=d)).isoformat()}T07:00:00+00:00", "duration_s": 600,
                 "kind": "rehit", "source": "synthetic-bike-app"} for d in (1, 3, 9)]
        (self.st / "rides.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg.write_text(json.dumps({"rides_file": "rides.jsonl"}))
        for raw in (False, True):
            lines = self.build(raw)
            self.assertEqual(len(lines), len(before))
            self.assertNotIn("ride", "\n".join(lines).lower())
        self.assertEqual(self.build(), before)


if __name__ == "__main__":
    unittest.main()
