"""post_wake_peak: open from the detected wake event for peak_h hours; unknown without a wake. Synthetic only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import peak  # noqa: E402
from limitless.window import MAX_AWAKE_H  # noqa: E402

WAKE = 2_000_000_000.0
H = 3600.0


class PostWakePeak(unittest.TestCase):
    def test_open_right_after_the_wake(self):
        out = peak.post_wake_peak(WAKE, WAKE + 0.5 * H)
        self.assertTrue(out["open"])
        self.assertEqual(out["label"], "post-wake peak: open")

    def test_open_at_the_wake_itself(self):
        self.assertTrue(peak.post_wake_peak(WAKE, WAKE)["open"])

    def test_closed_after_peak_h(self):
        out = peak.post_wake_peak(WAKE, WAKE + 2 * H)
        self.assertFalse(out["open"])
        self.assertIsNone(out["label"])
        self.assertTrue(out["why"].startswith("closed"))

    def test_default_peak_is_two_hours(self):
        self.assertEqual(peak.PEAK_H, 2.0)
        self.assertTrue(peak.post_wake_peak(WAKE, WAKE + 1.99 * H)["open"])

    def test_peak_h_is_configurable(self):
        self.assertTrue(peak.post_wake_peak(WAKE, WAKE + 2.5 * H, peak_h=3)["open"])
        self.assertFalse(peak.post_wake_peak(WAKE, WAKE + 1.5 * H, peak_h=1)["open"])

    def test_bad_peak_h_falls_back_to_the_default(self):
        for bad in (0, -1, None, "two", True, float("nan")):
            self.assertTrue(peak.post_wake_peak(WAKE, WAKE + 1.5 * H, peak_h=bad)["open"], bad)

    def test_no_wake_is_unknown_never_guessed(self):
        out = peak.post_wake_peak(None, WAKE)
        self.assertEqual(out, {"open": False, "why": "unknown: no wake seen", "label": None})

    def test_bad_wake_is_unknown(self):
        for bad in ("x", True, float("nan")):
            self.assertEqual(peak.post_wake_peak(bad, WAKE)["why"], "unknown: no wake seen")

    def test_wake_older_than_max_awake_is_unknown(self):
        out = peak.post_wake_peak(WAKE, WAKE + (MAX_AWAKE_H + 1) * H, peak_h=MAX_AWAKE_H + 5)
        self.assertFalse(out["open"])
        self.assertTrue(out["why"].startswith("unknown"))

    def test_future_wake_is_unknown(self):
        out = peak.post_wake_peak(WAKE + H, WAKE)
        self.assertFalse(out["open"])
        self.assertTrue(out["why"].startswith("unknown"))

    def test_words_are_digit_free(self):
        for now in (WAKE, WAKE + H, WAKE + 3 * H, WAKE + 30 * H, WAKE - H):
            out = peak.post_wake_peak(WAKE, now)
            text = out["why"] + (out["label"] or "")
            self.assertFalse(any(c.isdigit() for c in text), text)
        self.assertFalse(any(c.isdigit() for c in peak.post_wake_peak(None, WAKE)["why"]))


if __name__ == "__main__":
    unittest.main()
