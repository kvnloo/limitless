"""explain_back.offer: one optional explain-back line, only when work landed since the last offer, in a trough,
at most once per wake day (keyed on the wake event). Never in a peak, asleep, an unknown window, a focus block
or focused mode. Pure: synthetic inputs only, no clock.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import explain_back, modes, one_tap  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402
from limitless.envelope import envelope  # noqa: E402

LINE = "Explain back: say what landed in one breath. Reply: Voice / Later"


def win(cls):
    return envelope(cls, "proxy", 0.1)


class Offer(unittest.TestCase):
    def test_trough_with_landed_work_offers_the_one_line(self):
        for state in (WindowState("trough", since="wake"), win("trough"), {"cls": "trough"}):
            self.assertEqual(explain_back.offer(1, state, False), LINE)
        self.assertEqual(explain_back.OFFER, LINE)
        self.assertFalse(any(c.isdigit() for c in LINE))

    def test_the_choices_are_one_taps_line(self):
        self.assertTrue(LINE.endswith(one_tap.choices_line(("Voice", "Later"))))
        self.assertEqual(explain_back.CHOICES, ("Voice", "Later"))

    def test_nothing_landed_no_offer(self):
        for n in (0, -1, None, True, "two", 1.5, float("nan")):
            self.assertEqual(explain_back.offer(n, WindowState("trough"), False), "", n)

    def test_many_landed_is_still_one_line(self):
        self.assertEqual(explain_back.offer(7, WindowState("trough"), False), LINE)

    def test_never_outside_a_trough(self):
        for state in (WindowState("peak"), win("peak"), win("asleep"), {"cls": "asleep"}, win("unknown"),
                      WindowState("unknown"), WindowState("anytime"), WindowState("wind_down"), None,
                      WindowState("trough", confidence=0.2), "trough", 42):
            self.assertEqual(explain_back.offer(1, state, False), "", state)

    def test_never_in_a_focus_block_or_focused_mode(self):
        self.assertEqual(explain_back.offer(1, WindowState("trough", hold_asks=True), False), "")
        focused = modes.apply(WindowState("trough"), modes.FOCUSED)
        self.assertEqual(explain_back.offer(1, focused, False), "")

    def test_at_most_once_per_wake_day(self):
        self.assertEqual(explain_back.offer(1, WindowState("trough"), True), "")
        for flag in (None, "no", 0):   # only a real False offers: unknown is treated as already offered
            self.assertEqual(explain_back.offer(1, WindowState("trough"), flag), "", flag)


if __name__ == "__main__":
    unittest.main()
