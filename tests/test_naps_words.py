"""naps words: the day label and the week line, T1 and digit-free. Synthetic events only."""
import re
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import naps as N  # noqa: E402

UTC = timezone.utc


def at(day, hh, mm=0):
    return datetime(2030, 3, day, hh, mm, tzinfo=UTC).timestamp()


def pair(d1, h1, m1, d2, h2, m2):
    return [{"event": "sleep_mode_on", "at": at(d1, h1, m1)}, {"event": "sleep_mode_off", "at": at(d2, h2, m2)}]


NIGHTS = pair(10, 23, 0, 11, 7, 0) + pair(11, 23, 0, 12, 7, 0)
EARLY_NAP = pair(11, 12, 0, 11, 12, 30)        # ends well before the night
LATE_NAP = pair(11, 20, 0, 11, 20, 40)         # ends a little before the night's start
D = date(2030, 3, 11)


class DayWords(unittest.TestCase):
    def word(self, evs, **kw):
        return N.day(evs, D, tz=UTC, **kw)["label"]

    def test_none_one_a_few_and_unknown(self):
        self.assertEqual(self.word(NIGHTS)["label"], "naps yesterday: none")
        self.assertEqual(self.word(NIGHTS + EARLY_NAP)["label"], "naps yesterday: one short nap")
        self.assertEqual(self.word(NIGHTS + EARLY_NAP + pair(11, 15, 0, 11, 15, 20))["label"],
                         "naps yesterday: a few short naps")
        self.assertEqual(self.word([])["label"], "naps yesterday: unknown")

    def test_close_to_the_night_clause(self):
        self.assertEqual(self.word(NIGHTS + LATE_NAP)["label"], "naps yesterday: one short nap, close to the night")
        self.assertEqual(self.word(NIGHTS + EARLY_NAP + LATE_NAP)["label"],
                         "naps yesterday: a few short naps, close to the night")

    def test_near_night_h_is_wording_only(self):
        self.assertEqual(N.NEAR_NIGHT_H, 4.0)
        self.assertEqual(self.word(NIGHTS + LATE_NAP, near_h=1)["label"], "naps yesterday: one short nap")
        self.assertEqual(self.word(NIGHTS + EARLY_NAP, near_h=12)["label"],
                         "naps yesterday: one short nap, close to the night")
        self.assertEqual(N.near_night_h({"nap_near_night_h": 6}), 6.0)
        self.assertEqual(N.near_night_h({"nap_near_night_h": "x"}), 4.0)

    def test_no_night_after_the_nap_is_not_close(self):
        evs = pair(10, 23, 0, 11, 7, 0) + LATE_NAP
        self.assertEqual(self.word(evs)["label"], "naps yesterday: one short nap")

    def test_label_is_t1_proxy_and_digit_free(self):
        for evs in ([], NIGHTS, NIGHTS + LATE_NAP, NIGHTS + EARLY_NAP + LATE_NAP):
            lab = self.word(evs)
            self.assertEqual((lab["tier"], lab["modality"]), ("T1", "proxy"))
            self.assertIn(lab["label"], N.DAY_LABELS)
            self.assertEqual(re.findall(r"\d", lab["label"]), [])

    def test_day_keeps_the_raw_spans_in_code(self):
        got = N.day(NIGHTS + LATE_NAP, D, tz=UTC)
        self.assertEqual(got["naps"], [{"start_s": at(11, 20), "end_s": at(11, 20, 40)}])
        self.assertEqual(got["close"], 1)
        self.assertIsNone(N.day([], D, tz=UTC)["naps"])


class WeekLine(unittest.TestCase):
    def line(self, evs):
        return N.week_line(N.week(evs, date(2030, 3, 9), date(2030, 3, 15), tz=UTC))

    def test_words(self):
        self.assertEqual(self.line(NIGHTS), "Naps this week: none (phone Sleep mode)")
        self.assertEqual(self.line(NIGHTS + EARLY_NAP), "Naps this week: one, not close to the night (phone Sleep mode)")
        self.assertEqual(self.line(NIGHTS + LATE_NAP), "Naps this week: one, close to the night (phone Sleep mode)")
        self.assertEqual(self.line(NIGHTS + EARLY_NAP + pair(11, 15, 0, 11, 15, 20)),
                         "Naps this week: a few, none close to the night (phone Sleep mode)")
        self.assertEqual(self.line(NIGHTS + EARLY_NAP + LATE_NAP),
                         "Naps this week: a few, some close to the night (phone Sleep mode)")
        self.assertEqual(self.line(NIGHTS + LATE_NAP + pair(11, 21, 0, 11, 21, 30)),
                         "Naps this week: a few, all close to the night (phone Sleep mode)")

    def test_unknown_is_no_line(self):
        self.assertEqual(self.line([]), "")
        self.assertEqual(N.week_line(None), "")
        self.assertEqual(N.week_line({"naps": None}), "")

    def test_every_line_is_digit_free_and_listed(self):
        for evs in (NIGHTS, NIGHTS + EARLY_NAP, NIGHTS + LATE_NAP, NIGHTS + EARLY_NAP + LATE_NAP):
            s = self.line(evs)
            self.assertIn(s, N.WEEK_LINES)
            self.assertEqual(re.findall(r"\d", s), [])

    def test_no_advice_words(self):
        for s in N.DAY_LABELS + N.WEEK_LINES:
            for bad in ("should", "try", "target", "streak", "too ", "limit", "avoid"):
                self.assertNotIn(bad, s.lower())


if __name__ == "__main__":
    unittest.main()
