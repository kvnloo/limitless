"""anki.week: this week's reviews in digit-free T1 words, from days with a review out of days so far.

Synthetic collections only. The words are wording, not targets: "no reviews this week" when the week so far
has none, "reviewed most days this week" when more than half of the days so far had a review, else "some
reviews this week". A day with no review is unlogged, never failed; unknown is never zero.
"""
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import anki  # noqa: E402
from test_anki_reviews import collection  # noqa: E402

UTC = timezone.utc
FIRST = date(2030, 1, 21)   # a synthetic week


def at(d: int, h: float = 12.0) -> float:
    """Epoch seconds of hour ``h`` on day ``d`` of the synthetic week (d = 0 is FIRST), UTC."""
    return datetime.combine(FIRST + timedelta(days=d), time(), tzinfo=UTC).timestamp() + h * 3600


class Week(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def week(self, stamps, today_d=6, **kw):
        db = collection(self.dir / f"c{len(list(self.dir.iterdir()))}.anki2", stamps)
        return anki.week(db, FIRST, FIRST + timedelta(days=today_d), UTC, **kw)

    def test_no_reviews_is_a_known_none(self):
        w = self.week([at(-3)])
        self.assertEqual((w["count"], w["days_with_review"], w["days_so_far"]), (0, 0, 7))
        self.assertEqual(w["label"], {"label": "no reviews this week", "tier": "T1", "modality": "measured"})
        self.assertTrue(w["set"])
        self.assertEqual(w["newest_s"], at(-3))

    def test_some_and_most_days(self):
        some = self.week([at(0), at(0, 13), at(2), at(4)])   # three of seven days
        self.assertEqual((some["count"], some["days_with_review"]), (4, 3))
        self.assertEqual(some["label"]["label"], "some reviews this week")
        most = self.week([at(d) for d in (0, 1, 3, 5)])      # four of seven days
        self.assertEqual(most["label"]["label"], "reviewed most days this week")

    def test_days_so_far_in_a_week_still_running(self):
        w = self.week([at(0), at(1)], today_d=2)             # two of three days so far
        self.assertEqual((w["days_with_review"], w["days_so_far"]), (2, 3))
        self.assertEqual(w["label"]["label"], "reviewed most days this week")
        w = self.week([at(0), at(1), at(3)], today_d=2)      # a review after today is not this week yet
        self.assertEqual(w["count"], 2)

    def test_the_week_has_seven_days_at_most(self):
        w = self.week([at(0), at(7), at(8)], today_d=9)
        self.assertEqual((w["count"], w["days_so_far"]), (1, 7))

    def test_days_are_local_days_in_tz(self):
        db = collection(self.dir / "tz.anki2", [at(0, 23.5), at(1, 0.5)])
        plus2 = timezone(timedelta(hours=2))
        self.assertEqual(anki.week(db, FIRST, FIRST + timedelta(days=6), UTC)["days_with_review"], 2)
        self.assertEqual(anki.week(db, FIRST, FIRST + timedelta(days=6), plus2)["days_with_review"], 1)

    def test_unknown_is_never_zero(self):
        for w in (anki.week(None, FIRST, FIRST, UTC), anki.week(self.dir / "nowhere", FIRST, FIRST, UTC),
                  self.week([at(0)], today_d=-1)):
            self.assertIsNone(w["count"])
            self.assertIsNone(w["days_with_review"])
            self.assertEqual(w["label"]["label"], "unknown")
            self.assertTrue(w["reason"])
        self.assertFalse(anki.week(None, FIRST, FIRST, UTC)["set"])
        self.assertEqual(anki.week(None, FIRST, FIRST, UTC)["reason"], "no Anki collection set")
        self.assertTrue(anki.week(self.dir / "nowhere", FIRST, FIRST, UTC)["set"])

    def test_every_label_is_digit_free_and_kind(self):
        for word in anki.LABELS:
            self.assertFalse(any(c.isdigit() for c in word), word)
            for bad in ("streak", "fail", "missed", "behind", "should", "goal", "target", "pm", "am"):
                self.assertNotIn(bad, word.split(), word)


if __name__ == "__main__":
    unittest.main()
