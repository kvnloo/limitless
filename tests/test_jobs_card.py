"""jobs.to_schedule_card: what a Hermes "Schedule this job?" card could show, in plain words."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs  # noqa: E402

ALL = list(jobs.SPECS.values()) + [jobs.wake_brief(decision=True), jobs.habit_checkin({"cue": "wind_down"})]


class ScheduleCard(unittest.TestCase):
    def test_speaks_line(self):
        card = jobs.to_schedule_card
        self.assertEqual(card(jobs.SPECS["wake_brief"])["speaks"], "when you wake up, at most once")
        self.assertEqual(card(jobs.SPECS["nap"])["speaks"], "when you are back from a nap, at most once")
        self.assertEqual(card(jobs.SPECS["miq"])["speaks"], "when your wind-down starts, at most once")
        self.assertEqual(card(jobs.SPECS["habit_checkin"])["speaks"], "at your habit's cue, at most once")

    def test_fields(self):
        c = jobs.to_schedule_card(jobs.SPECS["miq"])
        self.assertEqual(c["name"], "MIQ for tonight?")
        self.assertEqual(c["window"], "once your wind-down has started")
        self.assertEqual(c["ends"], "when Sleep mode goes on")
        self.assertIn("never sends by itself", c["delivery"])
        self.assertNotIn("answers", c)
        self.assertEqual(jobs.to_schedule_card(jobs.wake_brief(decision=True))["window"],
                         "in a peak window, at most one decision per window")

    def test_habit_answers_never_turn_silence_into_no(self):
        a = jobs.to_schedule_card(jobs.SPECS["habit_checkin"])["answers"]
        self.assertEqual(a, "Done, No or Skip in one tap; no answer stays unlogged")

    def test_no_internal_ids_or_clock_times(self):
        ids = {i for i in set(jobs.EVENTS) | set(jobs.SPECS) if "_" in i} | {"short_on", "anytime"}
        for spec in ALL:
            for k, v in jobs.to_schedule_card(spec).items():
                self.assertIsInstance(v, str)
                self.assertNotRegex(v, r"_|\bt_[0-9a-f]{6,}|\d{1,2}:\d{2}|\d", f"{spec.name}.{k}: {v!r}")
                for i in ids:
                    self.assertNotIn(i, v, f"{spec.name}.{k}: {v!r}")

    def test_card_is_plain_data(self):
        c = jobs.to_schedule_card(jobs.SPECS["nap"])
        self.assertEqual(set(c), {"name", "speaks", "window", "ends", "delivery"})
        self.assertTrue(all(re.fullmatch(r"[^\n]+", v) for v in c.values()))


if __name__ == "__main__":
    unittest.main()
