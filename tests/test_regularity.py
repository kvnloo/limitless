"""regularity.regularity: how regular sleep times have been, per source, never a target time.

Synthetic spans only, UTC as the local zone. A night is ``{"night", "wearable", "proxy"}`` with each source a
``(start_s, end_s)`` span or None (sleep.timed_nights). Wearable and phone estimate are kept apart; fewer than
min_nights spans of one source is unknown, never regular.
"""
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import regularity as reg  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 28)
H = 3600


def at(day, hour):
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + hour * H


def span(ago, start_h, hours):
    s = at(TODAY - timedelta(days=ago), start_h)
    return (s, s + hours * H)


def ns(starts, hours=8.0, kind="wearable", first_ago=None):
    """One night per start hour, oldest first, ending the night before TODAY."""
    n = len(starts)
    first_ago = n if first_ago is None else first_ago
    out = []
    for i, h in enumerate(starts):
        ago = first_ago - i
        sp = None if h is None else span(ago, h, hours)
        out.append({"night": (TODAY - timedelta(days=ago)).isoformat(),
                    "wearable": sp if kind == "wearable" else None, "proxy": sp if kind == "proxy" else None})
    return out


class Regularity(unittest.TestCase):
    def test_steady_nights_have_a_small_spread_and_no_drift(self):
        r = reg.regularity(ns([23, 23.25, 22.75, 23, 23.1, 22.9, 23]), tz=UTC)["wearable"]
        self.assertTrue(r["known"])
        self.assertEqual(r["nights"], 7)
        self.assertLess(r["mid_spread_min"], 20)
        self.assertLess(r["wake_spread_min"], 20)
        self.assertEqual((r["drift"], r["pattern"]), ("steady", "steady"))

    def test_nights_across_midnight_are_circular_not_a_day_apart(self):
        # bedtimes either side of midnight: a linear mean of clock times would call this wildly irregular
        r = reg.regularity(ns([23.5, 24.5, 23.75, 24.25, 23.9, 24.1]), tz=UTC)["wearable"]
        self.assertLess(r["mid_spread_min"], 40)
        self.assertLess(r["wake_spread_min"], 40)
        self.assertEqual(r["drift"], "steady")
        # midpoints themselves straddling midnight (bed 20:00, four hours)
        r = reg.regularity(ns([21.6, 22.4, 21.8, 22.2, 22, 22], hours=4), tz=UTC)["wearable"]
        self.assertLess(r["mid_spread_min"], 40)

    def test_a_steady_later_shift_is_drifting_later(self):
        r = reg.regularity(ns([22, 22.4, 22.8, 23.2, 23.6, 24, 24.4]), tz=UTC)["wearable"]
        self.assertEqual((r["drift"], r["pattern"]), ("later", "later"))
        self.assertGreater(r["drift_min"], 0)

    def test_a_steady_earlier_shift_is_drifting_earlier(self):
        r = reg.regularity(ns([25, 24.5, 24, 23.5, 23, 22.5, 22]), tz=UTC)["wearable"]
        self.assertEqual((r["drift"], r["pattern"]), ("earlier", "earlier"))
        self.assertLess(r["drift_min"], 0)

    def test_scattered_nights_vary_a_lot(self):
        r = reg.regularity(ns([21, 26, 22, 27, 23, 20.5, 25.5]), tz=UTC)["wearable"]
        self.assertGreater(r["mid_spread_min"], reg.STEADY_SPREAD_MIN)
        self.assertEqual(r["pattern"], "varies")

    def test_fewer_than_min_nights_of_one_source_is_unknown(self):
        out = reg.regularity(ns([23, 23, 23]), tz=UTC)
        self.assertFalse(out["wearable"]["known"])
        self.assertEqual(out["wearable"]["nights"], 3)
        self.assertIsNone(out["wearable"]["drift"])
        self.assertIsNone(out["wearable"]["pattern"])
        self.assertIsNone(out["wearable"]["mid_spread_min"])
        self.assertTrue(reg.regularity(ns([23, 23, 23]), min_nights=3, tz=UTC)["wearable"]["known"])
        self.assertEqual(reg.MIN_NIGHTS, 4)

    def test_sources_are_kept_apart(self):
        w = ns([23, None, 23, None, 23, None, 23])
        p = ns([None, 20, None, 26, None, 22, None], kind="proxy")
        mixed = [dict(a, proxy=b["proxy"]) for a, b in zip(w, p)]
        out = reg.regularity(mixed, tz=UTC)
        self.assertTrue(out["wearable"]["known"])
        self.assertEqual(out["wearable"]["drift"], "steady")     # the scattered phone nights never leak in
        self.assertFalse(out["proxy"]["known"])                  # three phone nights: unknown
        self.assertEqual(out["proxy"]["nights"], 3)

    def test_only_the_last_fourteen_nights_count(self):
        old = ns([20, 27, 21, 26, 22, 25] + [23] * 14, first_ago=20)
        r = reg.regularity(old, tz=UTC)["wearable"]
        self.assertEqual(r["nights"], 14)
        self.assertEqual(r["drift"], "steady")

    def test_bad_input_is_unknown_never_raises(self):
        for bad in (None, [], "x", [None, 3, {"night": "bad", "wearable": ("a", "b")}],
                    [{"night": "2030-01-20", "wearable": (10.0, 5.0)}]):
            out = reg.regularity(bad, tz=UTC)
            self.assertFalse(out["wearable"]["known"])
            self.assertFalse(out["proxy"]["known"])


if __name__ == "__main__":
    unittest.main()
