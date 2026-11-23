"""stop_rule.verdict(habit_week, rule) -> keep | drop | your call | unknown. Skipped and unanswered days are
unlogged and never count against the habit; a week with no Done or No answer is unknown, never drop.
Synthetic data only."""
import itertools
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import stop_rule  # noqa: E402

START = date(2030, 1, 7)


def week(*answers, rule=None):
    """habit.json for a synthetic week; answers in day order, None = no answer that day."""
    h = {"habit": "Synthetic habit", "week_of": START.isoformat(),
         "checkins": {(START + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}}
    if rule:
        h["stop_rule"] = rule
    return h


class Verdict(unittest.TestCase):
    def test_the_four_words(self):
        self.assertEqual(stop_rule.VERDICTS, ("keep", "drop", "your call", "unknown"))

    def test_most_done_keeps_when_most_logged_days_were_done(self):
        self.assertEqual(stop_rule.verdict(week("Done", "Done", "No", "Done"), "most_done"), "keep")
        self.assertEqual(stop_rule.verdict(week("Done", "No", "No"), "most_done"), "drop")
        self.assertEqual(stop_rule.verdict(week("Done", "No"), "most_done"), "drop")   # half is not most

    def test_skipped_and_unanswered_days_never_count_against_the_habit(self):
        h = week("Done", "Skipped", "Skipped", None, "Skipped", "Done", "No")
        self.assertEqual(stop_rule.verdict(h, "most_done"), "keep")
        self.assertEqual(stop_rule.verdict(week("Done", None, None, None, None, None, None), "most_done"), "keep")
        self.assertEqual(stop_rule.verdict(week("Done", "Skipped", "Skipped", "Skipped"), "any_done"), "keep")

    def test_any_done(self):
        self.assertEqual(stop_rule.verdict(week("No", "No", "No", "Done"), "any_done"), "keep")
        self.assertEqual(stop_rule.verdict(week("No", "Skipped", "No"), "any_done"), "drop")

    def test_not_a_chore_keeps_and_the_feeling_is_the_reply(self):
        self.assertEqual(stop_rule.verdict(week("No", "No"), "not_a_chore"), "keep")

    def test_no_rule_is_your_call(self):
        self.assertEqual(stop_rule.verdict(week("Done", "No"), "no_rule"), "your call")

    def test_no_answers_is_unknown_for_every_rule(self):
        for rid in stop_rule.RULES:
            for h in (week(), week("Skipped", "Skipped"), week(None, None)):
                self.assertEqual(stop_rule.verdict(h, rid), "unknown", rid)

    def test_no_rule_set_or_an_unlisted_one_is_unknown(self):
        for bad in (None, "", "drop it whenever", 4):
            self.assertEqual(stop_rule.verdict(week("Done", "No"), bad), "unknown", bad)

    def test_no_started_week_is_unknown(self):
        for h in (None, {}, {"habit": "Synthetic habit"}, {"habit": "", "week_of": START.isoformat()}):
            self.assertEqual(stop_rule.verdict(h, "most_done"), "unknown", h)

    def test_the_sync_fills_a_day_without_a_tap(self):
        synced = {(START + timedelta(days=i)).isoformat(): "met" for i in range(3)}
        self.assertEqual(stop_rule.verdict(week(None, None, None, "No"), "most_done", synced), "keep")
        self.assertEqual(stop_rule.verdict(week(None, None, None, "No"), "most_done"), "drop")

    def test_unknown_never_becomes_drop(self):
        for answers in itertools.product(("Done", "No", "Skipped", None), repeat=4):
            for rid in stop_rule.RULES:
                v = stop_rule.verdict(week(*answers), rid)
                self.assertIn(v, stop_rule.VERDICTS)
                if "Done" not in answers and "No" not in answers:
                    self.assertEqual(v, "unknown", (answers, rid))

    def test_turning_a_skip_into_no_answer_never_changes_the_verdict(self):
        for answers in itertools.product(("Done", "No", "Skipped", None), repeat=4):
            blank = tuple(None if a == "Skipped" else a for a in answers)
            for rid in stop_rule.RULES:
                self.assertEqual(stop_rule.verdict(week(*answers), rid), stop_rule.verdict(week(*blank), rid))

    def test_days_after_day_seven_are_not_read(self):
        h = week("No", "No", "No", "No", "No", "No", "No")
        h["checkins"][(START + timedelta(days=7)).isoformat()] = "Done"
        self.assertEqual(stop_rule.verdict(h, "any_done"), "drop")


if __name__ == "__main__":
    unittest.main()
