"""post_wake_peak: open from the detected wake event for peak_h hours; unknown without a wake. Synthetic only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
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
        self.assertEqual(out, {"open": False, "in_use": False, "why": "unknown: no wake seen", "label": None})

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


M = 60.0
LONG = 90 * M


class PeakInUse(unittest.TestCase):
    """A focus block (blocks.focus_blocks) that started inside the peak uses it: still going, or long."""

    def at(self, now, blocks, **kw):
        return peak.post_wake_peak(WAKE, now, blocks=blocks, long_s=LONG, **kw)

    def test_no_blocks_stays_open(self):
        for bs in (None, []):
            out = self.at(WAKE + H, bs)
            self.assertEqual((out["open"], out["in_use"], out["label"]), (True, False, "post-wake peak: open"))

    def test_running_block_started_inside_the_peak_is_in_use(self):
        out = self.at(WAKE + H, [(WAKE + 20 * M, WAKE + H - M)])
        self.assertTrue(out["open"])
        self.assertTrue(out["in_use"])
        self.assertEqual(out["label"], "post-wake peak: in use")

    def test_long_finished_block_inside_the_peak_is_in_use(self):
        out = self.at(WAKE + 115 * M, [(WAKE + 5 * M, WAKE + 100 * M)])
        self.assertEqual(out["label"], "post-wake peak: in use")

    def test_short_finished_block_does_not_use_the_peak(self):
        out = self.at(WAKE + H, [(WAKE + 5 * M, WAKE + 15 * M)])
        self.assertEqual((out["in_use"], out["label"]), (False, "post-wake peak: open"))

    def test_block_that_started_before_the_wake_does_not_count(self):
        out = self.at(WAKE + 30 * M, [(WAKE - 3 * H, WAKE - 2 * H), (WAKE - 5 * M, WAKE + 29 * M)])
        self.assertEqual(out["label"], "post-wake peak: open")

    def test_block_rows_after_now_are_not_read(self):
        out = self.at(WAKE + 30 * M, [(WAKE + 40 * M, WAKE + 50 * M)])
        self.assertEqual(out["label"], "post-wake peak: open")

    def test_in_use_ends_with_the_peak(self):
        out = self.at(WAKE + 2 * H + M, [(WAKE + 20 * M, WAKE + 2 * H)])
        self.assertEqual((out["open"], out["in_use"], out["label"]), (False, False, None))

    def test_unknown_wake_ignores_blocks(self):
        out = peak.post_wake_peak(None, WAKE, blocks=[(WAKE - H, WAKE)], long_s=LONG)
        self.assertEqual((out["open"], out["label"]), (False, None))

    def test_bad_block_rows_are_skipped(self):
        out = self.at(WAKE + H, ["x", (None, 1), (WAKE + 20 * M,)])
        self.assertEqual(out["label"], "post-wake peak: open")

    def test_in_use_words_are_digit_free(self):
        out = self.at(WAKE + H, [(WAKE + 20 * M, WAKE + H - M)])
        self.assertFalse(any(c.isdigit() for c in out["why"] + out["label"]))


if __name__ == "__main__":
    unittest.main()
