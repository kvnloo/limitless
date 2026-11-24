"""Pre-sleep heart rate in words, wearable rows only (presleep_hr.py). Synthetic rows only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import presleep_hr as p  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 15)
NOW = datetime(2030, 1, 15, 9, 0, tzinfo=UTC).timestamp()    # nine hours after the last night's midnight


def night(back: int) -> str:
    """The night that began ``back`` evenings before TODAY (1 = last night)."""
    return (TODAY - timedelta(days=back)).isoformat()


def rows(values: dict, modality: str = "measured") -> list:
    """{back: bpm} -> synthetic rows."""
    return [{"night": night(b), "bpm": v, "modality": modality} for b, v in sorted(values.items(), reverse=True)]


def history(last: float, n: int = 14, usual: float = 60.0) -> list:
    """``n`` earlier wearable nights at ``usual``, then last night at ``last``."""
    return rows({b: usual for b in range(2, n + 2)}) + rows({1: last})


class Latest(unittest.TestCase):
    def test_the_three_words_against_the_median_of_the_earlier_nights(self):
        for last, word in ((50.0, "lower than usual"), (60.0, "about usual"), (61.5, "about usual"),
                           (70.0, "higher than usual")):
            got = p.latest(history(last), NOW, tz=UTC)
            self.assertEqual(got["word"], word, last)
            self.assertEqual(got["label"], {"label": f"pre-sleep heart rate {word} (wearable)", "tier": "T1",
                                            "modality": "measured"})
            self.assertEqual(got["modality"], "measured")
            self.assertIsNone(got["reason"])

    def test_the_band_edge_is_about_usual_and_just_past_it_is_not(self):
        self.assertEqual(p.latest(history(60.0 + p.ABOUT_BPM), NOW, tz=UTC)["word"], "about usual")
        self.assertEqual(p.latest(history(60.0 - p.ABOUT_BPM - 0.1), NOW, tz=UTC)["word"], "lower than usual")

    def test_the_baseline_is_the_median_of_the_previous_fourteen_measured_nights(self):
        # twenty earlier nights: the six oldest are high and must not count; one odd night does not move it
        old = rows({b: 90.0 for b in range(16, 22)})
        recent = rows({b: 60.0 for b in range(2, 16)})
        recent[0]["bpm"] = 99.0
        got = p.latest(old + recent + rows({1: 60.0}), NOW, tz=UTC)
        self.assertEqual(got["word"], "about usual")
        self.assertEqual(got["baseline_nights"], p.BASELINE_NIGHTS)
        self.assertEqual(got["baseline_bpm"], 60.0)
        self.assertEqual(got["bpm"], 60.0)

    def test_phone_rows_are_never_used(self):
        mixed = history(60.0) + rows({b: 80.0 for b in range(1, 16)}, modality="proxy")
        self.assertEqual(p.latest(mixed, NOW, tz=UTC)["word"], "about usual")
        # a phone reading for last night does not stand in for a missing wearable one
        phone_last = rows({b: 60.0 for b in range(2, 16)}) + rows({1: 80.0}, modality="proxy")
        got = p.latest(phone_last, NOW, tz=UTC)
        self.assertEqual(got["night"], night(2))      # the newest WEARABLE night is compared, not the phone's

    def test_only_phone_rows_is_unknown_and_says_so(self):
        got = p.latest(rows({b: 60.0 for b in range(1, 16)}, modality="proxy"), NOW, tz=UTC)
        self.assertIsNone(got["word"])
        self.assertEqual(got["reason"], p.PHONE_ONLY)
        self.assertEqual(got["label"]["label"], p.PHONE_ONLY)

    def test_no_rows_is_unknown_never_zero(self):
        for bad in ([], None, "x", [{"night": night(1), "bpm": 0, "modality": "measured"}],
                    [{"night": night(1), "bpm": True, "modality": "measured"}],
                    [{"night": night(1), "bpm": float("nan"), "modality": "measured"}],
                    [{"night": "yesterday", "bpm": 60, "modality": "measured"}], [None, 3]):
            got = p.latest(bad, NOW, tz=UTC)
            self.assertIsNone(got["word"], bad)
            self.assertIsNone(got["bpm"], bad)
            self.assertEqual(got["reason"], p.NO_WEARABLE, bad)

    def test_fewer_than_five_earlier_measured_nights_is_unknown(self):
        got = p.latest(history(70.0, n=p.MIN_NIGHTS - 1), NOW, tz=UTC)
        self.assertIsNone(got["word"])
        self.assertEqual(got["reason"], p.TOO_FEW)
        self.assertEqual(p.latest(history(70.0, n=p.MIN_NIGHTS), NOW, tz=UTC)["word"], "higher than usual")

    def test_missing_nights_are_skipped_not_zero(self):
        # earlier wearable nights with holes between them still make a baseline; holes are not zeros
        got = p.latest(rows({b: 60.0 for b in range(2, 30, 3)}) + rows({1: 60.0}), NOW, tz=UTC)
        self.assertEqual(got["word"], "about usual")

    def test_data_older_than_a_day_and_a_half_is_unknown(self):
        h = history(60.0)
        self.assertLessEqual(p.latest(h, NOW, tz=UTC)["age_h"], p.MAX_AGE_H)
        late = NOW + 28 * 3600                       # last night's midnight is now 37 hours ago
        got = p.latest(h, late, tz=UTC)
        self.assertIsNone(got["word"])
        self.assertEqual(got["reason"], p.STALE)
        self.assertGreater(got["age_h"], p.MAX_AGE_H)

    def test_age_is_from_the_local_midnight_after_the_newest_wearable_night(self):
        self.assertEqual(p.latest(history(60.0), NOW, tz=UTC)["age_h"], 9.0)

    def test_a_night_after_now_is_ignored(self):
        tomorrow = (TODAY + timedelta(days=1)).isoformat()   # tonight (TODAY) may already have a reading
        future = history(60.0) + [{"night": tomorrow, "bpm": 99.0, "modality": "measured"}]
        self.assertEqual(p.latest(future, NOW, tz=UTC)["night"], night(1))

    def test_the_first_wearable_row_of_a_night_wins(self):
        dup = history(60.0) + rows({1: 99.0})
        self.assertEqual(p.latest(dup, NOW, tz=UTC)["bpm"], 60.0)

    def test_every_label_and_reason_is_digit_free_with_no_advice(self):
        for word in p.LABELS:
            self.assertFalse(any(c.isdigit() for c in word), word)
            for bad in ("should", "try", "lower it", "caffeine", "target", "score", "goal"):
                self.assertNotIn(bad, word.lower())


class Week(unittest.TestCase):
    def test_most_nights_when_one_word_holds_the_majority(self):
        base = rows({b: 60.0 for b in range(8, 30)})
        week = rows({b: 60.0 for b in range(1, 8)})
        w = p.week(base + week, TODAY)
        self.assertEqual(w["word"], "about usual")
        self.assertEqual(p.review_line(w), "Pre-sleep heart rate: about usual most nights (wearable).")

    def test_no_clear_pattern_when_no_word_holds_the_majority(self):
        base = rows({b: 60.0 for b in range(8, 30)})
        week = rows({1: 50.0, 2: 50.0, 3: 70.0, 4: 70.0, 5: 60.0, 6: 60.0})
        w = p.week(base + week, TODAY)
        self.assertEqual(p.review_line(w), "Pre-sleep heart rate: no clear pattern this week (wearable).")

    def test_too_few_compared_nights_this_week_says_nothing(self):
        base = rows({b: 60.0 for b in range(8, 30)})
        week = rows({b: 60.0 for b in range(1, p.MIN_WEEK_NIGHTS)})
        self.assertEqual(p.review_line(p.week(base + week, TODAY)), "")

    def test_phone_only_or_nothing_says_nothing(self):
        self.assertEqual(p.review_line(p.week(rows({b: 60.0 for b in range(1, 30)}, "proxy"), TODAY)), "")
        self.assertEqual(p.review_line(p.week([], TODAY)), "")
        self.assertEqual(p.review_line(None), "")
        self.assertEqual(p.review_line({"word": "5 bpm"}), "")

    def test_the_line_is_digit_free(self):
        base = rows({b: 60.0 for b in range(8, 30)})
        for v in (50.0, 60.0, 70.0):
            line = p.review_line(p.week(base + rows({b: v for b in range(1, 8)}), TODAY))
            self.assertTrue(line)
            self.assertFalse(any(c.isdigit() for c in line), line)


if __name__ == "__main__":
    unittest.main()
