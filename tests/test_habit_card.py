"""habit_card: the habit card as one generic, data-free module. A card is a name, an event cue (never a clock
time), a start of at most two minutes and the replies Done / No / Skip. Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card  # noqa: E402
from limitless.habit_card import HabitCard  # noqa: E402


class Card(unittest.TestCase):
    def test_a_card_is_a_name_an_event_cue_a_short_start_and_three_replies(self):
        c = HabitCard("Synthetic habit", "habit_cue")
        self.assertEqual((c.name, c.cue, c.start_s, c.replies), ("Synthetic habit", "habit_cue", 120, ("Done", "No", "Skip")))
        self.assertEqual(habit_card.REPLIES, ("Done", "No", "Skip"))
        self.assertEqual(habit_card.MAX_START_S, 120)

    def test_the_start_is_two_minutes_or_less(self):
        self.assertEqual(HabitCard("Synthetic habit", "wake", start_s=30).start_s, 30)
        self.assertEqual(HabitCard("Synthetic habit", "wake", start_s=120).start_s, 120)
        for bad in (121, 0, -5, 1.5, True, "60", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                HabitCard("Synthetic habit", "wake", start_s=bad)

    def test_the_cue_is_an_event_name_never_a_clock_time(self):
        for ok in ("wake", "sleep_mode_off", "wind_down", "habit_cue", "focus_end"):
            self.assertEqual(HabitCard("Synthetic habit", ok).cue, ok)
        for bad in ("07:00", "7am", "7 pm", "0 7 * * *", "@daily", "every morning", "at_7", "Wake", "",
                    " wake", "wake_", None, 7):
            with self.assertRaises(ValueError, msg=repr(bad)):
                HabitCard("Synthetic habit", bad)

    def test_the_name_is_plain_text(self):
        self.assertEqual(HabitCard("  Synthetic habit  ", "wake").name, "Synthetic habit")
        for bad in ("", "   ", None, 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                HabitCard(bad, "wake")

    def test_the_replies_are_fixed(self):
        with self.assertRaises(ValueError):
            HabitCard("Synthetic habit", "wake", replies=("Yes", "No"))

    def test_a_card_is_immutable(self):
        c = HabitCard("Synthetic habit", "wake")
        with self.assertRaises(Exception):
            c.cue = "wind_down"


if __name__ == "__main__":
    unittest.main()
