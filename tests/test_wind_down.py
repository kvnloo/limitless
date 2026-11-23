"""wind_down.line: one gentle, digit-free wind-down line chosen from a fixed list, or nothing.

Config ``wind_down_line`` picks the line ("off" disables it); Glide's own nudge already sent tonight
(attention.json ``nudged`` == tonight's night date) means nothing more is said. Synthetic data only."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import one_tap, wind_down  # noqa: E402

DEFAULT = "Screens down and lights low when you're ready."
NIGHT = "2033-05-18"
# Words a wind-down suggestion never carries: orders, clock words, health or dosing advice.
BANNED = re.compile(r"(?i)\b(must|should|need|needs|have to|now|tonight at|pm|am|o'?clock|hours?|minutes?|"
                    r"melatonin|magnesium|supplements?|pills?|tablets?|drugs?|medication|medicine|dose|"
                    r"doses|dosing|dosage|mg|caffeine|alcohol|sleep aid)\b")
CLOCK = re.compile(r"(?i)\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}\b|\bat\s+\w+\s*(am|pm)\b")


class Choice(unittest.TestCase):
    def test_default_line(self):
        self.assertEqual(wind_down.line({}, None), DEFAULT)
        self.assertEqual(wind_down.line(None, None), DEFAULT)
        self.assertEqual(wind_down.DEFAULT, DEFAULT)
        self.assertIn(DEFAULT, wind_down.LINES)

    def test_off_disables_it(self):
        for v in ("off", "OFF", " Off "):
            self.assertEqual(wind_down.line({"wind_down_line": v}, None), "", v)

    def test_config_picks_a_listed_line(self):
        for ln in wind_down.LINES:
            self.assertEqual(wind_down.line({"wind_down_line": ln}, None), ln)
            self.assertEqual(wind_down.line({"wind_down_line": f"  {ln.upper()} "}, None), ln)

    def test_free_text_is_never_sent(self):
        for v in ("Go to bed at 11 pm", "anything else", 3, ["off"], True, ""):
            self.assertEqual(wind_down.line({"wind_down_line": v}, None), DEFAULT, v)

    def test_a_small_fixed_list(self):
        self.assertIsInstance(wind_down.LINES, tuple)
        self.assertTrue(2 <= len(wind_down.LINES) <= 5)
        self.assertEqual(len(set(wind_down.LINES)), len(wind_down.LINES))


class GlideAlreadyNudged(unittest.TestCase):
    def test_glide_nudge_tonight_means_no_line(self):
        self.assertEqual(wind_down.line({}, {"nudged": NIGHT}, night=NIGHT), "")

    def test_glide_nudge_another_night_keeps_the_line(self):
        self.assertEqual(wind_down.line({}, {"nudged": "2033-05-17"}, night=NIGHT), DEFAULT)
        self.assertEqual(wind_down.line({}, {"nudged": ""}, night=NIGHT), DEFAULT)

    def test_no_or_broken_glide_state_keeps_the_line(self):
        for g in (None, {}, [], "x", {"nudged": None}, {"nudged": 20330518}):
            self.assertEqual(wind_down.line({}, g, night=NIGHT), DEFAULT, g)

    def test_off_and_glide_both_say_nothing(self):
        self.assertEqual(wind_down.line({"wind_down_line": "off"}, {"nudged": NIGHT}, night=NIGHT), "")

    def test_without_a_night_any_glide_nudge_counts(self):
        # Fewer messages is the safe side: with no night to compare, a recorded Glide nudge wins.
        self.assertEqual(wind_down.line({}, {"nudged": NIGHT}), "")
        self.assertEqual(wind_down.line({}, {"nudged": ""}), DEFAULT)


class Wording(unittest.TestCase):
    def test_every_line_is_a_short_digit_free_suggestion(self):
        for ln in wind_down.LINES:
            self.assertEqual(re.findall(r"\d", ln), [], ln)
            self.assertIsNone(CLOCK.search(ln), ln)
            self.assertIsNone(BANNED.search(ln), ln)
            self.assertTrue(ln.endswith("when you're ready."), ln)   # a suggestion, never an order
            self.assertLessEqual(len(ln.split()), 10, ln)
            self.assertNotIn("\n", ln)

    def test_a_line_asks_nothing(self):
        for ln in wind_down.LINES:
            self.assertFalse(one_tap.asks(ln), ln)          # one_tap stays the choices line's job

    def test_pure(self):
        src = (ROOT / "limitless" / "wind_down.py").read_text()
        for word in ("import time", "datetime", "open(", "subprocess", "urllib", "socket"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
