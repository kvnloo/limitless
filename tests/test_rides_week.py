"""rides.week: rides in the last seven days against the seven before, in T1 words only.

Synthetic rows only (the StateReader.ride_rows shape). No target, no score, no streak: a week with no
ride is "none", never "missed". Unknown (no file) is no line, not zero.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import itertools
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import rides  # noqa: E402

TODAY = date(2030, 1, 28)


def ride(days_ago, minutes=10, hour=7, offset="+00:00", source="synthetic-bike-app"):
    d = TODAY - timedelta(days=days_ago)
    return {"start": f"{d.isoformat()}T{hour:02d}:00:00{offset}", "duration_s": minutes * 60, "kind": "rehit",
            "source": source}


def rows(this=0, last=0):
    """``this`` rides in the last seven days and ``last`` in the seven before (one per day from the end)."""
    return [ride(13 - i) for i in range(last)] + [ride(6 - i) for i in range(this)]


class Week(unittest.TestCase):
    def label(self, this, last):
        return rides.week(rows(this, last), TODAY)["label"]["label"]

    def test_counts_the_last_seven_days_and_the_seven_before(self):
        w = rides.week([ride(0), ride(6), ride(7), ride(13), ride(14), ride(30)], TODAY)
        self.assertEqual((w["this_week"], w["last_week"]), (2, 2))

    def test_the_count_words(self):
        for n, word in ((0, "none"), (1, "one"), (2, "two"), (3, "a few"), (5, "a few"), (7, "a few")):
            self.assertEqual(rides.week(rows(n, n), TODAY)["count"], word, n)
            self.assertEqual(self.label(n, n), f"rides this week: {word}, same as last week")

    def test_the_comparison_words(self):
        self.assertEqual(self.label(2, 1), "rides this week: two, more than last week")
        self.assertEqual(self.label(1, 2), "rides this week: one, fewer than last week")
        self.assertEqual(self.label(0, 2), "rides this week: none, fewer than last week")
        self.assertEqual(self.label(0, 0), "rides this week: none, same as last week")
        self.assertEqual(self.label(4, 3), "rides this week: a few, more than last week")

    def test_the_label_is_t1_and_measured(self):
        self.assertEqual(rides.week(rows(2, 2), TODAY)["label"],
                         {"label": "rides this week: two, same as last week", "tier": "T1", "modality": "measured"})

    def test_no_label_has_a_digit_or_a_judgement(self):
        for this, last in itertools.product(range(8), range(8)):
            word = self.label(this, last)
            self.assertIn(word, rides.LABELS)
            self.assertEqual(re.findall(r"\d", word), [], word)
            for bad in ("missed", "streak", "target", "goal", "score", "behind", "should"):
                self.assertNotIn(bad, word)
        self.assertTrue(all(not re.search(r"\d", w) for w in rides.LABELS))

    def test_total_minutes_stay_in_the_result_for_code_only(self):
        w = rides.week([ride(1, 9), ride(3, 11), ride(8, 10)], TODAY)
        self.assertEqual((w["minutes_this_week"], w["minutes_last_week"]), (20, 10))
        self.assertNotIn("20", w["label"]["label"])

    def test_the_day_is_the_start_date_in_its_own_offset(self):
        # 23:30 at -05:00 on day six ago is still that day locally, though the next day in UTC
        w = rides.week([ride(7, hour=23, offset="-05:00"), ride(6, hour=23, offset="-05:00")], TODAY)
        self.assertEqual((w["this_week"], w["last_week"]), (1, 1))

    def test_a_ride_after_today_is_not_counted(self):
        self.assertEqual(rides.week([ride(-1), ride(0)], TODAY)["this_week"], 1)

    def test_no_file_is_unknown_and_unknown_is_not_zero(self):
        for bad in (None, "rows", 7):
            w = rides.week(bad, TODAY)
            self.assertIsNone(w["this_week"])
            self.assertIsNone(w["last_week"])
            self.assertEqual(w["label"]["label"], rides.UNKNOWN)
            self.assertEqual(rides.review_line(w), "")
        self.assertIsNone(rides.week(rows(1, 1), "not a date")["this_week"])

    def test_an_empty_file_is_none_not_unknown(self):
        self.assertEqual(rides.week([], TODAY)["label"]["label"], "rides this week: none, same as last week")

    def test_bad_rows_are_ignored_and_nothing_raises(self):
        junk = [None, 3, "x", {}, {"start": "bad"}, {"start": "2030-01-27T07:00:00"},
                {"start": "2030-01-27T07:00:00Z", "duration_s": "ten"}, {"start": 1894000000}]
        w = rides.week(junk + [ride(1)], TODAY)
        self.assertEqual((w["this_week"], w["last_week"], w["minutes_this_week"]), (1, 0, 10))

    def test_review_line(self):
        self.assertEqual(rides.review_line(rides.week(rows(2, 1), TODAY)),
                         "Rides this week: two, more than last week.")
        self.assertEqual(rides.review_line(rides.week(rows(0, 0), TODAY)),
                         "Rides this week: none, same as last week.")
        for bad in (None, {}, {"label": {"label": "made up"}}, "x"):
            self.assertEqual(rides.review_line(bad), "")

    def test_nothing_here_reads_the_clock(self):
        with open(rides.__file__) as f:
            src = f.read()
        for call in ("time.time", "date.today", "datetime.now", "open(", "write"):
            self.assertNotIn(call, src)


if __name__ == "__main__":
    unittest.main()
