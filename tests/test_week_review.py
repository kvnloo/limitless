"""Day seven sends one number: the week review. Synthetic data only; fake push only.

The week review wakes on the first habit cue event on or after day seven of a started week (an event,
never a clock time), says the habit, "N of M logged days" and ends in "Reply: Keep / Drop", and goes out once
per week (event key ``week_review:<week_of>``). Skipped and unlogged days stay out of M.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, weekly_target  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0          # an arbitrary epoch; only differences matter
H = 3600.0
DAY_S = 24 * H
TODAY = datetime.fromtimestamp(NOW, UTC).date()


def week(days_back, habit="Synthetic habit", **kw):
    """A habit.json whose week_of is ``days_back`` days before TODAY (six back: today is day seven)."""
    return dict({"week_of": (TODAY - timedelta(days=days_back)).isoformat(), "habit": habit, "checkins": {}}, **kw)


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Spec(unittest.TestCase):
    def test_week_review_is_a_job_on_the_habit_cue(self):
        s = jobs.SPECS["week_review"]
        self.assertEqual(s, jobs.WEEK_REVIEW)
        self.assertEqual((s.trigger_event, s.window_class, s.max_per_window), ("habit_cue", "anytime", 1))
        self.assertEqual(s.answers, ("Keep", "Drop"))
        self.assertEqual(s.send_title, "Week review")

    def test_follows_the_habits_own_cue_event(self):
        self.assertEqual(jobs.week_review({"cue": "wind_down"}).trigger_event, "wind_down")
        self.assertEqual(jobs.week_review({"cue": "at 9pm"}), jobs.WEEK_REVIEW)   # never a clock time
        self.assertEqual(jobs.week_review(None), jobs.WEEK_REVIEW)


class Gate(unittest.TestCase):
    def test_a_cue_on_day_seven_or_later_passes(self):
        for back in (6, 7, 10):
            self.assertIsNone(jobs.week_review_gate(week(back), TODAY), back)

    def test_a_cue_before_day_seven_is_not_triggered(self):
        for back in (0, 3, 5):
            v = jobs.week_review_gate(week(back), TODAY)
            self.assertEqual(v, jobs.Verdict(jobs.NOT_TRIGGERED, "no habit cue on or after day seven yet"), back)

    def test_no_started_week_drops(self):
        for h in (None, {}, {"habit": "Synthetic habit"}, week(6, habit=" "), week(-1),
                  {"week_of": "not a date", "habit": "x"}):
            self.assertEqual(jobs.week_review_gate(h, TODAY), jobs.Verdict(jobs.DROP, "no habit week started"), h)

    def test_once_per_week(self):
        v = jobs.week_review_gate(week(7), TODAY, reviewed=[TODAY - timedelta(days=1)])
        self.assertEqual(v, jobs.Verdict(jobs.DROP, "this week's review was already sent"))
        # a review sent for an earlier week (before this week's day seven) does not count
        self.assertIsNone(jobs.week_review_gate(week(6), TODAY, reviewed=[TODAY - timedelta(days=9)]))

    def test_a_decided_week_drops(self):
        v = jobs.week_review_gate(week(6, decision="Keep"), TODAY)
        self.assertEqual(v, jobs.Verdict(jobs.DROP, "this week already has a decision"))

    def test_reasons_are_plain_words(self):
        for v in (jobs.week_review_gate(None, TODAY), jobs.week_review_gate(week(2), TODAY),
                  jobs.week_review_gate(week(6, decision="Drop"), TODAY),
                  jobs.week_review_gate(week(6), TODAY, reviewed=[TODAY])):
            self.assertRegex(v.reason, r"^[a-z' ]+$")


class Text(unittest.TestCase):
    def test_one_number_from_done_and_no_only(self):
        h = week(6, checkins={(TODAY - timedelta(days=6)).isoformat(): "Done",
                              (TODAY - timedelta(days=5)).isoformat(): "No",
                              (TODAY - timedelta(days=4)).isoformat(): "Skipped",
                              (TODAY - timedelta(days=3)).isoformat(): "Done"})
        self.assertEqual(jobs.week_logged(h), (2, 3))
        self.assertEqual(jobs.week_review_text(h),
                         "Synthetic habit: 2 of 3 logged days this week.")

    def test_sync_verdicts_count_and_taps_win(self):
        d0, d1 = (TODAY - timedelta(days=6)).isoformat(), (TODAY - timedelta(days=5)).isoformat()
        h = week(6, checkins={d0: "No"})
        self.assertEqual(jobs.week_logged(h, {d0: "met", d1: "met"}), (1, 2))

    def test_days_outside_the_week_do_not_count(self):
        before, after = (TODAY - timedelta(days=7)).isoformat(), (TODAY + timedelta(days=1)).isoformat()
        self.assertEqual(jobs.week_logged(week(6, checkins={before: "Done", after: "Done"})), (0, 0))

    def test_no_logged_days_says_so_never_failed(self):
        h = week(6, checkins={(TODAY - timedelta(days=2)).isoformat(): "Skipped"})
        text = jobs.week_review_text(h)
        self.assertEqual(text, "Synthetic habit: no days were logged this week.")
        self.assertNotIn("fail", text.lower())

    def test_runner_body_is_the_review_text(self):
        h = week(6, checkins={TODAY.isoformat(): "Done"})
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, h),
                         jobs.week_review_text(h) + "\n" + weekly_target.REVIEW_ON_THE_WAY + "\nReply: Keep / Drop")


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return "telegram"


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def cue(self, *ats):
        write_rows(self.st / "events.jsonl", [{"event": "habit_cue", "at": t} for t in ats])

    def run_pass(self, habit, now=NOW, push=None):
        if habit is not None:
            (self.st / "habit.json").write_text(json.dumps(habit))
        push = push or FakePush()
        rows = jobs_runner.run_once(self.st, now, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        return {r["job"]: r for r in rows}["Week review"], [c for c in push.calls if c[0] == "Week review"]

    def sent(self):
        p = self.st / "jobs-sent.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def test_day_seven_cue_sends_one_number_with_the_week_key(self):
        self.cue(NOW - 60)
        h = week(6, checkins={(TODAY - timedelta(days=6)).isoformat(): "Done",
                              (TODAY - timedelta(days=1)).isoformat(): "No"})
        row, calls = self.run_pass(h)
        self.assertEqual(row["action"], jobs.DELIVER, row)
        self.assertEqual(calls, [("Week review", "Synthetic habit: 1 of 2 logged days this week.\nhabit: on the way\nReply: Keep / Drop",
                                  f"week_review:{h['week_of']}")])
        self.assertEqual([s["job"] for s in self.sent()].count("week_review"), 1)

    def test_before_day_seven_nothing_triggers(self):
        self.cue(NOW - 60)
        row, calls = self.run_pass(week(5))
        self.assertEqual((row["action"], row["reason"]), (jobs.NOT_TRIGGERED, "no habit cue on or after day seven yet"))
        self.assertEqual(calls, [])

    def test_day_six_cue_then_no_cue_on_day_seven_is_not_triggered(self):
        self.cue(NOW - DAY_S + 60)            # yesterday's cue (day six); today (day seven) has none yet
        row, calls = self.run_pass(week(6), now=NOW)
        self.assertEqual(row["action"], jobs.NOT_TRIGGERED)
        self.assertEqual(calls, [])

    def test_no_cue_is_not_triggered(self):
        row, calls = self.run_pass(week(6))
        self.assertEqual(row["action"], jobs.NOT_TRIGGERED)
        self.assertEqual(calls, [])

    def test_no_started_week_drops_in_plain_words(self):
        self.cue(NOW - 60)
        row, calls = self.run_pass(None)
        self.assertEqual((row["action"], row["reason"]), (jobs.DROP, "no habit week started"))
        self.assertEqual(calls, [])

    def test_fires_once_per_week_even_on_a_later_cue(self):
        self.cue(NOW - 60)
        h = week(6)
        _, first = self.run_pass(h)
        self.cue(NOW - 60, NOW + DAY_S - 60)                  # the next day's cue (day eight)
        row, second = self.run_pass(h, now=NOW + DAY_S)
        self.assertEqual(len(first), 1)
        self.assertEqual((row["action"], row["reason"]), (jobs.DROP, "this week's review was already sent"))
        self.assertEqual(second, [])

    def test_missed_day_seven_goes_out_on_the_first_later_cue(self):
        self.cue(NOW - 60)
        row, calls = self.run_pass(week(8))                   # day nine, no review sent yet
        self.assertEqual(row["action"], jobs.DELIVER)
        self.assertEqual(len(calls), 1)

    def test_event_key_is_the_week_key(self):
        self.cue(NOW - 60)
        h = week(6)
        (self.st / "habit.json").write_text(json.dumps(h))
        k = jobs_runner.event_key(self.st, NOW, job="week_review", env=self.env, home=self.root, tz=UTC)
        self.assertEqual(k, f"week_review:{h['week_of']}")
        (self.st / "habit.json").write_text(json.dumps(week(3)))
        self.assertIsNone(jobs_runner.event_key(self.st, NOW, job="week_review", env=self.env, home=self.root, tz=UTC))

    def test_dry_run_never_pushes(self):
        self.cue(NOW - 60)
        (self.st / "habit.json").write_text(json.dumps(week(6)))
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        self.assertEqual(push.calls, [])
        self.assertFalse((self.st / "jobs-sent.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
