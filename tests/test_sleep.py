"""sleep.nights and sleep.label: the wearable and the phone proxy side by side, per night, in T1 words.

Synthetic rows only, UTC as the local zone. A night is the evening it began; the proxy is the longest
screen-off gap that starts in the evening half (noon on) of that day. A night with neither is unknown, never zero.
"""
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import sleep  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 28)
H = 3600


def at(day, hour):
    """Epoch seconds of ``hour`` (may be >= 24: the next day) on ``day`` in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + hour * H


def night(ago):
    return TODAY - timedelta(days=ago)


def wear(ago, hours=7.0, source="synthetic-ring"):
    return {"night": night(ago).isoformat(), "asleep_s": int(hours * H), "source": source}


def gap(ago, start_h=23.0, hours=8.0):
    s = at(night(ago), start_h)
    return (s, s + hours * H)


def words(ns):
    return sleep.label(ns)["label"]


class Gaps(unittest.TestCase):
    def test_screen_gaps_are_the_quiet_spans_between_person_actions(self):
        rows = [{"ts": 1000, "type": "KEYGUARD_HIDDEN"}, {"ts": 5000_000, "type": "SCREEN_ON"},
                {"ts": 4000, "type": "USER_INTERACTION"}, {"ts": 9000, "type": "KEYGUARD_HIDDEN"}]
        self.assertEqual(sleep.screen_gaps(rows), [(1000.0, 4000.0), (4000.0, 9000.0)])
        self.assertEqual(sleep.screen_gaps([]), [])
        self.assertEqual(sleep.screen_gaps(None), [])


class Nights(unittest.TestCase):
    def test_the_last_seven_nights_oldest_first_with_neither_as_unknown(self):
        ns = sleep.nights([], [], TODAY, tz=UTC)
        self.assertEqual([n["night"] for n in ns], [night(a).isoformat() for a in range(7, 0, -1)])
        self.assertEqual({(n["wearable"], n["proxy"]) for n in ns}, {(None, None)})
        self.assertEqual(len(sleep.nights([], [], TODAY, days=3, tz=UTC)), 3)

    def test_wearable_seconds_and_the_longest_evening_gap(self):
        ns = sleep.nights([wear(1, 7)], [gap(1, 22, 3), gap(1, 23, 8.5), gap(2, 21, 6)], TODAY, tz=UTC)
        by = {n["night"]: n for n in ns}
        self.assertEqual(by[night(1).isoformat()], {"night": night(1).isoformat(), "wearable": 7 * H,
                                                    "proxy": int(8.5 * H)})
        self.assertEqual(by[night(2).isoformat()], {"night": night(2).isoformat(), "wearable": None,
                                                    "proxy": 6 * H})

    def test_a_gap_that_starts_in_the_morning_half_is_not_a_night(self):
        ns = sleep.nights([], [gap(2, 1, 7), gap(2, 11.9, 5), gap(3, 12, 4)], TODAY, tz=UTC)
        by = {n["night"]: n["proxy"] for n in ns}
        self.assertIsNone(by[night(2).isoformat()])
        self.assertEqual(by[night(3).isoformat()], 4 * H)

    def test_the_local_zone_decides_the_evening(self):
        plus9 = timezone(timedelta(hours=9))
        g = gap(2, 14, 8)          # 14:00 UTC is 23:00 at +09:00, the same date
        self.assertEqual({n["night"]: n["proxy"] for n in sleep.nights([], [g], TODAY, tz=plus9)}
                         [night(2).isoformat()], 8 * H)
        g = gap(2, 6, 8)           # 06:00 UTC is morning in UTC but 15:00 at +09:00
        self.assertIsNone({n["night"]: n["proxy"] for n in sleep.nights([], [g], TODAY, tz=UTC)}
                          [night(2).isoformat()])
        self.assertEqual({n["night"]: n["proxy"] for n in sleep.nights([], [g], TODAY, tz=plus9)}
                         [night(2).isoformat()], 8 * H)

    def test_a_gap_of_a_day_or_more_is_missing_data_not_sleep(self):
        ns = sleep.nights([], [gap(3, 22, 24), gap(3, 22, 30)], TODAY, tz=UTC)
        self.assertEqual({n["proxy"] for n in ns}, {None})

    def test_rows_outside_the_window_and_bad_rows_are_ignored(self):
        ns = sleep.nights([wear(0), wear(8), {"night": "bad"}, None, {"night": night(1).isoformat()}],
                          [gap(0), gap(8), (5, 1), "x", (None, 3)], TODAY, tz=UTC)
        self.assertEqual({(n["wearable"], n["proxy"]) for n in ns}, {(None, None)})

    def test_two_wearable_sources_for_one_night_keep_the_first(self):
        ns = sleep.nights([wear(1, 7), wear(1, 6, "synthetic-watch")], [], TODAY, tz=UTC)
        self.assertEqual(ns[-1]["wearable"], 7 * H)

    def test_never_raises_on_bad_input(self):
        for args in ((None, None, TODAY), ("x", 5, TODAY), ([], [], "2030-01-28"), ([], [], None)):
            out = sleep.nights(*args, tz=UTC)
            self.assertIsInstance(out, list)


class Label(unittest.TestCase):
    def test_coverage_words(self):
        self.assertTrue(words(sleep.nights([wear(a) for a in range(1, 8)], [], TODAY, tz=UTC))
                        .startswith("sleep: wearable on most nights;"))
        six = sleep.nights([wear(a) for a in range(1, 7)], [], TODAY, tz=UTC)     # six of seven: >= 80%
        self.assertTrue(words(six).startswith("sleep: wearable on most nights;"))
        five = sleep.nights([wear(a) for a in range(1, 6)], [], TODAY, tz=UTC)    # five of seven: under 80%
        self.assertTrue(words(five).startswith("sleep: wearable on some nights;"))
        one = sleep.nights([wear(4)], [], TODAY, tz=UTC)
        self.assertTrue(words(one).startswith("sleep: wearable on some nights;"))
        self.assertTrue(words(sleep.nights([], [gap(1)], TODAY, tz=UTC)).startswith("sleep: wearable on no nights;"))

    def test_proxy_compare_words(self):
        def both(proxy_h):
            return sleep.nights([wear(a, 7) for a in (1, 2, 3)], [gap(a, 23, proxy_h) for a in (1, 2, 3)],
                                TODAY, tz=UTC)
        self.assertEqual(words(both(7.25)), "sleep: wearable on some nights; phone proxy says about the same")
        self.assertEqual(words(both(6.75)), "sleep: wearable on some nights; phone proxy says about the same")
        self.assertEqual(words(both(8)), "sleep: wearable on some nights; phone proxy says longer")
        self.assertEqual(words(both(5.5)), "sleep: wearable on some nights; phone proxy says shorter")

    def test_the_median_night_decides_not_one_odd_night(self):
        ns = sleep.nights([wear(a, 7) for a in (1, 2, 3)], [gap(1, 23, 7), gap(2, 23, 7.1), gap(3, 23, 1)],
                          TODAY, tz=UTC)
        self.assertEqual(words(ns), "sleep: wearable on some nights; phone proxy says about the same")

    def test_no_night_with_both_has_nothing_to_compare(self):
        self.assertEqual(words(sleep.nights([wear(1)], [gap(2)], TODAY, tz=UTC)),
                         "sleep: wearable on some nights; phone proxy has no night to compare")
        self.assertEqual(words(sleep.nights([], [], TODAY, tz=UTC)),
                         "sleep: wearable on no nights; phone proxy has no night to compare")

    def test_label_is_t1_with_the_given_modality_and_every_label_is_digit_free(self):
        lab = sleep.label(sleep.nights([wear(1)], [], TODAY, tz=UTC), "measured")
        self.assertEqual((lab["tier"], lab["modality"]), ("T1", "measured"))
        self.assertEqual(sleep.label([])["modality"], "proxy")
        for w in sleep.LABELS:
            self.assertEqual(re.findall(r"\d", w), [], w)
        self.assertIn(sleep.label(None)["label"], sleep.LABELS)

    def test_counts(self):
        ns = sleep.nights([wear(1), wear(2)], [gap(2), gap(3)], TODAY, tz=UTC)
        self.assertEqual(sleep.counts(ns), {"wearable_nights": 2, "proxy_only_nights": 1, "unknown_nights": 4})
        self.assertEqual(sleep.counts(None), {"wearable_nights": 0, "proxy_only_nights": 0, "unknown_nights": 0})

    def test_newest_datum(self):
        # a wearable night's datum is dated at the local midnight that ends its evening (never fresher)
        self.assertEqual(sleep.newest_at([wear(2)], [], tz=UTC), at(night(1), 0))
        self.assertEqual(sleep.newest_at([wear(2)], [gap(2, 23, 8)], tz=UTC), at(night(2), 31))
        self.assertEqual(sleep.newest_at([wear(1)], [gap(5)], tz=UTC), at(TODAY, 0))
        self.assertIsNone(sleep.newest_at([], [], tz=UTC))
        self.assertIsNone(sleep.newest_at(None, None, tz=UTC))

    def test_review_line(self):
        ns = sleep.nights([wear(1, 7)], [gap(1, 23, 9)], TODAY, tz=UTC)
        self.assertEqual(sleep.review_line(sleep.label(ns)), "Sleep: wearable on some nights; phone proxy says longer.")
        self.assertEqual(sleep.review_line(None), "")
        self.assertEqual(sleep.review_line({"label": "sleep 7 h", "tier": "T1"}), "")

    def test_no_targets_advice_or_clock_rules_in_the_words(self):
        text = " ".join(sleep.LABELS).lower()
        for bad in ("should", "need", "target", "goal", "bed at", "o'clock", "try", "aim", "missed", "zero"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
