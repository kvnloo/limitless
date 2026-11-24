"""The week review's sleep line (sleep.review_line, digit-free) after the rides line; the card gets none.

Synthetic rows only, a fake push, a fixed clock, UTC as the local zone.
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
from test_flow_week_hooks import FakePush  # noqa: E402
from test_rides_review import ride_rows  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
FIX = ROOT / "tests" / "fixtures" / "state"
H = 3600


def sleep_rows(nights=(1, 2, 3, 4, 5, 6), hours=7.0):
    return [{"night": (TODAY - timedelta(days=d)).isoformat(), "asleep_s": int(hours * H),
             "source": "synthetic-ring"} for d in nights]


def screen_rows(nights=(1,), start_h=23.0, hours=8.0):
    out = []
    for d in nights:
        day = TODAY - timedelta(days=d)
        s = datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + start_h * H
        out += [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN"}, {"ts": int((s + hours * H) * 1000),
                                                                   "type": "KEYGUARD_HIDDEN"}]
    return out


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

    def test_body_puts_the_sleep_line_after_the_rides_line(self):
        text = jobs.week_review_text(self.habit) + "\n" + weekly_target.REVIEW_ON_THE_WAY
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, body_line="Body: y.", rides_line="Rides: z.",
                                          sleep_line="Sleep: w."),
                         text + "\nBody: y.\nRides: z.\nSleep: w." + KD)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, sleep_line=""), text + KD)
        self.assertNotIn("Sleep", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, sleep_line="Sleep: w."))
        self.assertNotIn("Sleep", jobs_runner.body(jobs.MIQ, self.habit, sleep_line="Sleep: w."))

    def test_the_review_carries_the_sleep_words_after_the_rides_line(self):
        self.configure(sleep_file="sleep.jsonl", rides_file="rides.jsonl")
        self.write("sleep.jsonl", sleep_rows())
        self.write("rides.jsonl", ride_rows())
        self.write("screen-events.jsonl", screen_rows((1, 2, 3)))
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY, "Rides this week: two, more than last week.",
                                     "Sleep: wearable on most nights; phone proxy says longer."])
        self.assertEqual(re.findall(r"\d", lines[-1]), [])

    def test_the_phone_alone_is_labelled_a_proxy_not_a_measure(self):
        self.write("screen-events.jsonl", screen_rows((1, 2)))
        self.assertEqual(self.review()[-1], "Sleep: wearable on no nights; phone proxy has no night to compare.")

    def test_no_sleep_data_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])
        self.configure(sleep_file="absent.jsonl")
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_week_sleep_helper(self):
        self.configure(sleep_file="sleep.jsonl")
        self.write("sleep.jsonl", sleep_rows((2, 5)))
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root, TODAY, UTC),
                         "Sleep: wearable on some nights; phone proxy has no night to compare.")
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root), "")   # no today: no clock read
        self.configure()
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root, TODAY, UTC), "")
        self.configure(sleep_file="sleep.jsonl")
        self.write("sleep.jsonl", sleep_rows((20,)))      # data, but none in the last seven nights
        self.assertEqual(jobs_runner.week_sleep(self.st, self.env, self.root, TODAY, UTC),
                         "Sleep: wearable on no nights; phone proxy has no night to compare.")

    def test_a_broken_sleep_file_does_not_stop_the_review(self):
        self.configure(sleep_file="sleep.jsonl")
        (self.st / "sleep.jsonl").mkdir()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_the_sleep_file_is_never_written(self):
        self.configure(sleep_file="sleep.jsonl")
        self.write("sleep.jsonl", sleep_rows())
        p = self.st / "sleep.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.review()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)


class CardHasNoSleepToolLine(unittest.TestCase):
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

    def test_the_card_is_the_same_five_lines_with_a_sleep_file(self):
        before = {raw: self.build(raw) for raw in (False, True)}
        self.assertEqual(len(before[False][1:]), 5)   # the header, then five label lines
        today = datetime.fromtimestamp(1894708800.0).date()
        rows = [{"night": (today - timedelta(days=d)).isoformat(), "asleep_s": 25200, "source": "synthetic-ring"}
                for d in (1, 2, 3)]
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))
        for raw in (False, True):
            lines = self.build(raw)
            self.assertEqual(lines, before[raw])
            self.assertNotIn("wearable", "\n".join(lines).lower())


if __name__ == "__main__":
    unittest.main()
