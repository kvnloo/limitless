"""feed_reflex.reflex: unlocks whose first phone app, within the gap, is a feed app; per day. Synthetic rows only."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import feed_reflex  # noqa: E402

UTC = timezone.utc
DAY0 = datetime(2030, 1, 7, tzinfo=UTC).timestamp()   # a synthetic Monday, midnight UTC
H = 3600.0
FEEDS = ("FeedApp", "com.example.feed")


def row(start, app, dur=60.0, source=None, package=""):
    r = {"start": start, "end": start + dur, "names": [n for n in (app, package) if n], "title": ""}
    if source is not None:
        r["source"] = source
    return r


def run(unlocks, rows, feeds=FEEDS, **kw):
    kw.setdefault("tz", UTC)
    return feed_reflex.reflex(unlocks, rows, feeds, **kw)


class Reflex(unittest.TestCase):
    def test_a_feed_first_within_the_gap_counts(self):
        u = DAY0 + 10 * H
        got = run([u], [row(u + 2, "FeedApp"), row(u + 600, "Notes")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 1), got)
        self.assertEqual(got["days"], [{"day": "2030-01-07", "unlocks": 1, "feed_first": 1}])
        self.assertEqual(got["why"], "")

    def test_package_names_and_case_match(self):
        u = DAY0 + H
        got = run([u], [row(u + 1, "", package="COM.EXAMPLE.FEED"), row(u + 900, "Notes")])
        self.assertEqual(got["feed_first"], 1, got)

    def test_an_app_opened_after_the_gap_does_not_count(self):
        u = DAY0 + H
        late = u + feed_reflex.REFLEX_GAP_S + 1
        got = run([u], [row(late, "FeedApp")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 0), got)

    def test_a_non_feed_first_then_a_feed_does_not_count(self):
        u = DAY0 + H
        got = run([u], [row(u + 1, "Notes", dur=3), row(u + 5, "FeedApp")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 0), got)

    def test_desktop_rows_never_count(self):
        u = DAY0 + H
        rows = [row(u + 1, "FeedApp", source="desktop"), row(u + 3, "Notes", source="phone")]
        got = run([u], rows)
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 0), got)
        only_desk = run([u], [row(u + 1, "FeedApp", source="desktop", dur=4000)])
        self.assertIsNone(only_desk["unlocks"], only_desk)   # no phone row at all: unknown

    def test_the_first_app_is_bounded_by_the_next_unlock(self):
        u1, u2 = DAY0 + H, DAY0 + H + 10
        got = run([u1, u2], [row(u2 + 1, "FeedApp"), row(u2 + 900, "Notes")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (2, 1), got)

    def test_the_gap_is_a_parameter(self):
        u = DAY0 + H
        rows = [row(u + 40, "FeedApp"), row(u + 900, "Notes")]
        self.assertEqual(run([u], rows, gap_s=30)["feed_first"], 0)
        self.assertEqual(run([u], rows, gap_s=60)["feed_first"], 1)

    def test_per_day_counts_in_the_given_zone(self):
        a, b, c = DAY0 + H, DAY0 + 2 * H, DAY0 + 25 * H
        rows = [row(a + 1, "FeedApp"), row(b + 1, "Notes"), row(c + 1, "FeedApp"), row(c + 900, "Notes")]
        got = run([a, b, c], rows)
        self.assertEqual(got["days"], [{"day": "2030-01-07", "unlocks": 2, "feed_first": 1},
                                       {"day": "2030-01-08", "unlocks": 1, "feed_first": 1}])
        self.assertEqual((got["unlocks"], got["feed_first"]), (3, 2))

    def test_unlock_rows_from_aw_reader_are_read(self):
        u = DAY0 + H
        unlocks = [{"ts": u, "type": "KEYGUARD_HIDDEN"}, {"ts": u + 5, "type": "USER_INTERACTION"}]
        got = run(unlocks, [row(u + 1, "FeedApp"), row(u + 900, "Notes")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 1), got)

    def test_an_unlock_the_data_stops_inside_the_gap_of_is_left_out(self):
        u1, u2 = DAY0 + H, DAY0 + 2 * H
        got = run([u1, u2], [row(u1 + 1, "FeedApp", dur=5)])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 1), got)

    def test_no_feed_apps_is_unknown_with_a_reason(self):
        u = DAY0 + H
        for feeds in ((), None, ["  "]):
            got = run([u], [row(u + 1, "FeedApp")], feeds=feeds)
            self.assertIsNone(got["unlocks"])
            self.assertIsNone(got["feed_first"])
            self.assertEqual(got["days"], [])
            self.assertIn("feed_apps", got["why"])

    def test_no_unlock_data_is_unknown_never_zero(self):
        for unlocks in (None, [], [{"ts": DAY0, "type": "USER_INTERACTION"}], ["bad", True]):
            got = run(unlocks, [row(DAY0 + 1, "FeedApp")])
            self.assertIsNone(got["unlocks"], got)
            self.assertIsNone(got["feed_first"], got)
            self.assertIn("unlock", got["why"])

    def test_no_app_rows_is_unknown(self):
        for rows in (None, []):
            got = run([DAY0 + H], rows)
            self.assertIsNone(got["unlocks"], got)
            self.assertTrue(got["why"])

    def test_zero_is_a_known_zero(self):
        u = DAY0 + H
        got = run([u], [row(u + 1, "Notes"), row(u + 900, "Notes")])
        self.assertEqual((got["unlocks"], got["feed_first"]), (1, 0))
        self.assertEqual(got["why"], "")

    def test_bad_rows_are_skipped(self):
        u = DAY0 + H
        rows = ["x", {"start": "a"}, {"start": u + 1, "end": u}, row(u + 2, "FeedApp"), row(u + 900, "Notes")]
        self.assertEqual(run([u], rows)["feed_first"], 1)

    def test_nothing_is_mutated(self):
        u = DAY0 + H
        rows = [row(u + 1, "FeedApp")]
        before = [dict(r) for r in rows]
        run([u], rows)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
