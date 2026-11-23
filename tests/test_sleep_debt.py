"""sleep_debt.debt: the last few nights against the person's own median, in words only.

Synthetic nights only (sleep.nights() shape: {night, wearable, proxy} in seconds, None when unknown).
"""
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import sleep_debt  # noqa: E402

H = 3600
TODAY = date(2030, 1, 28)


def night(ago, wearable=None, proxy=None):
    return {"night": (TODAY - timedelta(days=ago)).isoformat(),
            "wearable": None if wearable is None else int(wearable * H),
            "proxy": None if proxy is None else int(proxy * H)}


def baseline(hours=8.0, kind="wearable", n=14, first=4):
    return [night(a, **{kind: hours}) for a in range(first + n - 1, first - 1, -1)]


def recent(*hours, kind="wearable"):
    """One night per value, the last value the newest night (ago 1); None is a night with neither."""
    k = len(hours)
    return [night(k - i, **({kind: h} if h is not None else {})) for i, h in enumerate(hours)]


class Words(unittest.TestCase):
    def test_close_to_the_usual_is_little(self):
        out = sleep_debt.debt(recent(8, 7.8, 8.1), baseline(8))
        self.assertEqual(out["word"], "little sleep debt")
        self.assertEqual(out["label"], {"label": "little sleep debt", "tier": "T1", "modality": "measured"})
        self.assertEqual(out["modality"], "measured")

    def test_somewhat_short_is_some(self):
        out = sleep_debt.debt(recent(7, 7, 7), baseline(8))      # one eighth short of the usual
        self.assertEqual(out["word"], "some sleep debt")

    def test_well_short_is_a_lot(self):
        out = sleep_debt.debt(recent(5, 5.5, 6), baseline(8))
        self.assertEqual(out["word"], "a lot of sleep debt")

    def test_long_nights_are_not_debt(self):
        out = sleep_debt.debt(recent(10, 9, 9), baseline(8))
        self.assertEqual(out["word"], "little sleep debt")
        self.assertEqual(out["short_s"], 0)

    def test_relative_to_the_persons_own_median_not_a_norm(self):
        # six hours is "little" for a person whose usual is six hours, "a lot" for one whose usual is nine
        self.assertEqual(sleep_debt.debt(recent(6, 6, 6), baseline(6))["word"], "little sleep debt")
        self.assertEqual(sleep_debt.debt(recent(6, 6, 6), baseline(9))["word"], "a lot of sleep debt")

    def test_thresholds_are_named_shares_of_the_median(self):
        self.assertLess(0, sleep_debt.SOME_SHARE)
        self.assertLess(sleep_debt.SOME_SHARE, sleep_debt.A_LOT_SHARE)
        self.assertLess(sleep_debt.A_LOT_SHARE, 1)
        base = baseline(10)
        just_some = 10 * (1 - sleep_debt.SOME_SHARE)
        just_a_lot = 10 * (1 - sleep_debt.A_LOT_SHARE)
        self.assertEqual(sleep_debt.debt(recent(just_some, just_some, just_some), base)["word"], "some sleep debt")
        self.assertEqual(sleep_debt.debt(recent(just_a_lot, just_a_lot, just_a_lot), base)["word"],
                         "a lot of sleep debt")


class Sources(unittest.TestCase):
    def test_wearable_beats_proxy_on_the_same_date(self):
        ns = [night(3, wearable=8, proxy=4), night(2, wearable=8, proxy=4), night(1, wearable=8, proxy=4)]
        out = sleep_debt.debt(ns, baseline(8))
        self.assertEqual(out["word"], "little sleep debt")
        self.assertEqual((out["modality"], out["proxy_nights"]), ("measured", 0))
        self.assertNotIn("phone", out["label"]["label"])

    def test_wearable_beats_proxy_across_rows_of_one_date(self):
        ns = [night(1, proxy=4), night(1, wearable=8), night(2, wearable=8), night(3, wearable=8)]
        out = sleep_debt.debt(ns, baseline(8))
        self.assertEqual((out["word"], out["modality"]), ("little sleep debt", "measured"))

    def test_a_proxy_night_only_where_the_wearable_missed(self):
        ns = [night(3, wearable=8), night(2, proxy=5), night(1, wearable=8)]
        out = sleep_debt.debt(ns, baseline(8))
        self.assertEqual((out["modality"], out["proxy_nights"]), ("proxy", 1))
        self.assertTrue(out["label"]["label"].endswith(" (phone estimate)"))
        self.assertEqual(out["label"]["modality"], "proxy")

    def test_all_proxy_says_phone_estimate(self):
        out = sleep_debt.debt(recent(6, 6, 6, kind="proxy"), baseline(8, kind="proxy"))
        self.assertEqual(out["label"]["label"], "a lot of sleep debt (phone estimate)")
        self.assertEqual(out["modality"], "proxy")

    def test_a_proxy_baseline_night_also_says_phone_estimate(self):
        base = baseline(8)
        base[0] = dict(base[0], wearable=None, proxy=8 * H)
        out = sleep_debt.debt(recent(8, 8, 8), base)
        self.assertEqual(out["label"]["label"], "little sleep debt (phone estimate)")


class Unknown(unittest.TestCase):
    UNKNOWN = "unknown: too few nights"

    def test_too_few_recent_nights_is_unknown(self):
        out = sleep_debt.debt(recent(None, None, 5), baseline(8))
        self.assertIsNone(out["word"])
        self.assertEqual(out["label"]["label"], self.UNKNOWN)
        self.assertIsNone(out["short_s"])

    def test_too_few_baseline_nights_is_unknown(self):
        out = sleep_debt.debt(recent(5, 5, 5), baseline(8, n=sleep_debt.MIN_BASELINE - 1))
        self.assertEqual(out["label"]["label"], self.UNKNOWN)
        self.assertIsNone(out["baseline_median_s"])

    def test_no_nights_at_all_is_unknown(self):
        for ns, base in (([], []), (None, None), ("bad", 7), ([{"night": "bad"}, 3], [None])):
            self.assertEqual(sleep_debt.debt(ns, base)["label"]["label"], self.UNKNOWN)

    def test_a_gap_night_is_not_zero_sleep(self):
        with_gap = sleep_debt.debt(recent(8, None, 8), baseline(8))
        self.assertEqual(with_gap["word"], "little sleep debt")
        self.assertEqual((with_gap["recent_nights"], with_gap["unknown_nights"]), (2, 1))
        self.assertEqual(with_gap["short_s"], 0)

    def test_a_zero_negative_or_impossible_night_is_unknown_not_short(self):
        for bad in (0, -5 * H, 24 * H, 30 * H, True, "8h", float("nan")):
            ns = recent(8, 8, 8)
            ns[1] = dict(ns[1], wearable=bad)
            out = sleep_debt.debt(ns, baseline(8))
            self.assertEqual((out["word"], out["recent_nights"]), ("little sleep debt", 2), bad)

    def test_baseline_gaps_shrink_nothing_they_are_skipped(self):
        base = baseline(8)
        for i in range(0, len(base), 2):
            base[i] = dict(base[i], wearable=None)
        out = sleep_debt.debt(recent(8, 8, 8), base)
        self.assertEqual((out["word"], out["baseline_nights"]), ("little sleep debt", 7))

    def test_only_the_last_recent_nights_count(self):
        ns = recent(3, 3, 3, 3, 8, 8, 8)                  # the short nights are older than RECENT_NIGHTS
        self.assertEqual(sleep_debt.RECENT_NIGHTS, 3)
        out = sleep_debt.debt(ns, baseline(8, first=8))
        self.assertEqual((out["word"], out["recent_nights"]), ("little sleep debt", 3))

    def test_a_baseline_night_on_a_recent_date_is_not_counted_twice(self):
        base = baseline(8, n=4) + [night(1, wearable=8), night(2, wearable=8)]
        out = sleep_debt.debt(recent(8, 8, 8), base)
        self.assertEqual(out["label"]["label"], self.UNKNOWN)   # four distinct baseline nights: too few


class Tiers(unittest.TestCase):
    def test_t0_numbers_stay_in_the_dict(self):
        out = sleep_debt.debt(recent(7, 7, 7), baseline(8))
        self.assertEqual(out["baseline_median_s"], 8 * H)
        self.assertEqual(out["recent_mean_s"], 7 * H)
        self.assertEqual(out["short_s"], 3 * H)
        self.assertAlmostEqual(out["short_share"], 0.125)
        self.assertEqual((out["recent_nights"], out["baseline_nights"]), (3, 14))

    def test_every_label_is_digit_free_and_listed(self):
        self.assertEqual(len(sleep_debt.LABELS), 7)
        for word in sleep_debt.LABELS:
            self.assertEqual(re.findall(r"\d", word), [], word)
        seen = set()
        for hours in (4, 5, 6, 6.5, 7, 7.5, 8, 9, 12):
            for kind in ("wearable", "proxy"):
                out = sleep_debt.debt(recent(hours, hours, hours, kind=kind), baseline(8))
                seen.add(out["label"]["label"])
                self.assertIn(out["label"]["label"], sleep_debt.LABELS)
        seen.add(sleep_debt.debt([], [])["label"]["label"])
        self.assertEqual(seen, set(sleep_debt.LABELS))

    def test_no_advice_no_score_no_clock_in_the_words(self):
        for word in sleep_debt.LABELS:
            for bad in ("should", "try", "bed", "score", "goal", "aim", "pm", "am ", "%", "hour", "minute"):
                self.assertNotIn(bad, word.lower())
            self.assertIsNone(re.search(r"\d\s*:\s*\d|o'clock", word))

    def test_pure_the_inputs_are_not_changed(self):
        ns, base = recent(7, None, 6), baseline(8)
        before = (repr(ns), repr(base))
        sleep_debt.debt(ns, base)
        self.assertEqual((repr(ns), repr(base)), before)


if __name__ == "__main__":
    unittest.main()
