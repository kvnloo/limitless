"""habit_card.record(card_state, day, reply) -> a new state. Done and No set the day's entry; Skip leaves the day
with no entry (unlogged); no reply or any other word leaves the state as it was. Synthetic data only."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card  # noqa: E402

DAY = "2030-01-07"


class Record(unittest.TestCase):
    def test_done_and_no_set_the_days_entry(self):
        self.assertEqual(habit_card.record({}, DAY, "Done"), {"checkins": {DAY: "Done"}})
        self.assertEqual(habit_card.record({}, DAY, "No"), {"checkins": {DAY: "No"}})

    def test_a_reply_is_read_in_any_case_with_spaces_around(self):
        self.assertEqual(habit_card.record({}, DAY, " done ")["checkins"], {DAY: "Done"})
        self.assertEqual(habit_card.record({}, DAY, "NO")["checkins"], {DAY: "No"})

    def test_skip_is_stored_as_unlogged_the_day_has_no_entry(self):
        self.assertEqual(habit_card.record({}, DAY, "Skip"), {"checkins": {}})
        self.assertEqual(habit_card.record({"checkins": {DAY: "No"}}, DAY, "skip"), {"checkins": {}})

    def test_no_reply_or_another_word_leaves_the_state_as_it_was(self):
        s = {"checkins": {DAY: "Done"}}
        for junk in (None, "", "maybe", "Skipped", "Yes", 1, True):
            self.assertEqual(habit_card.record(s, DAY, junk), s, junk)

    def test_the_input_is_never_changed_and_other_keys_are_kept(self):
        s = {"habit": "Synthetic habit", "week_of": DAY, "checkins": {"2030-01-08": "No"}}
        out = habit_card.record(s, DAY, "Done")
        self.assertEqual(s, {"habit": "Synthetic habit", "week_of": DAY, "checkins": {"2030-01-08": "No"}})
        self.assertEqual(out, {"habit": "Synthetic habit", "week_of": DAY,
                               "checkins": {"2030-01-08": "No", DAY: "Done"}})
        self.assertIsNot(out["checkins"], s["checkins"])

    def test_a_missing_or_broken_state_starts_an_empty_table(self):
        self.assertEqual(habit_card.record(None, DAY, None), {"checkins": {}})
        self.assertEqual(habit_card.record({"checkins": "junk"}, DAY, "Done"), {"checkins": {DAY: "Done"}})

    def test_a_date_day_is_written_as_its_iso_form(self):
        self.assertEqual(habit_card.record({}, date(2030, 1, 7), "Done")["checkins"], {DAY: "Done"})

    def test_reply_word(self):
        self.assertEqual([habit_card.reply(w) for w in ("done", "No", " SKIP ", "x", None)],
                         ["Done", "No", "Skip", None, None])


if __name__ == "__main__":
    unittest.main()
