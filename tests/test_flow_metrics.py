"""flow_metrics.metrics: per-day fragmentation of work from app-activity rows. Synthetic rows only, UTC days."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import flow_metrics as fm  # noqa: E402

UTC = timezone.utc
DAY0 = datetime(2033, 5, 16, tzinfo=UTC).timestamp()
M = 60.0
H = 3600.0
WORK = ("editor", "title:design doc")
GAP = 10 * M


def row(start_min, end_min, app, day=0, title=None):
    r = {"start": DAY0 + day * 86400 + start_min * M, "end": DAY0 + day * 86400 + end_min * M, "app": app}
    if title is not None:
        r["title"] = title
    return r


def run(rows, work=WORK, **kw):
    return fm.metrics(rows, work, GAP, tz=UTC, **kw)


class Unknown(unittest.TestCase):
    def test_no_work_apps_is_unknown_never_zero(self):
        rows = [row(0, 60, "editor")]
        for work in ((), None, ["", "  "], ["title:"]):
            self.assertIsNone(run(rows, work))

    def test_no_rows_is_unknown(self):
        self.assertIsNone(run(None))
        self.assertIsNone(run([]))

    def test_only_bad_rows_is_unknown(self):
        self.assertIsNone(run([{"start": "x", "end": 5}, {"start": 10, "end": 5, "app": "editor"}, "junk"]))


class Switches(unittest.TestCase):
    def test_one_day_with_no_switch(self):
        (d,) = run([row(0, 120, "editor")])
        self.assertEqual(d["day"], "2033-05-16")
        self.assertEqual(d["work_h"], 2.0)
        self.assertEqual(d["switches"], 0)
        self.assertEqual(d["switches_per_work_h"], 0.0)

    def test_switches_away_from_work_per_work_hour(self):
        rows = [row(0, 30, "editor"), row(30, 33, "chat"), row(33, 60, "editor"), row(60, 62, "feed"),
                row(62, 90, "editor"), row(90, 91, "feed"), row(91, 92, "chat"), row(92, 120, "editor")]
        (d,) = run(rows)
        self.assertEqual(d["switches"], 3)               # chat-then-feed in a row is one switch away
        self.assertAlmostEqual(d["work_h"], (30 + 27 + 28 + 28) / 60)
        self.assertAlmostEqual(d["switches_per_work_h"], 3 / ((30 + 27 + 28 + 28) / 60))

    def test_a_title_match_is_work(self):
        rows = [row(0, 60, "browser", title="Design doc - draft"), row(60, 61, "browser", title="news"),
                row(61, 120, "browser", title="design doc - draft")]
        (d,) = run(rows)
        self.assertEqual(d["switches"], 1)
        self.assertAlmostEqual(d["work_h"], 119 / 60)

    def test_leaving_after_a_long_gap_is_not_a_switch(self):
        # no row for longer than the gap (away, or afk-cut), then another app: not a switch from work
        rows = [row(0, 60, "editor"), row(60 + 30, 100, "feed"), row(100, 160, "editor")]
        (d,) = run(rows)
        self.assertEqual(d["switches"], 0)

    def test_a_day_with_rows_but_no_work_is_unknown_per_hour_not_zero(self):
        days = run([row(0, 60, "editor"), row(0, 60, "feed", day=1)])
        self.assertEqual([d["day"] for d in days], ["2033-05-16", "2033-05-17"])
        self.assertEqual(days[1]["work_h"], 0.0)
        self.assertIsNone(days[1]["switches_per_work_h"])

    def test_days_are_split_in_the_given_zone(self):
        days = run([row(0, 60, "editor"), row(60, 62, "feed"), row(62, 120, "editor"), row(0, 60, "editor", day=2)])
        self.assertEqual([(d["day"], d["switches"]) for d in days], [("2033-05-16", 1), ("2033-05-18", 0)])


class LongBlockShare(unittest.TestCase):
    def test_share_of_work_time_in_blocks_of_at_least_break_after(self):
        # a 100-minute block (one short look away inside it) and a 20-minute block, gap over GAP between
        rows = [row(0, 50, "editor"), row(50, 52, "chat"), row(52, 100, "editor"),
                row(130, 150, "editor")]
        (d,) = run(rows, break_after_s=90 * M)
        self.assertAlmostEqual(d["long_block_share"], 98 / 118)

    def test_no_long_block_is_zero_share_when_there_is_work(self):
        (d,) = run([row(0, 30, "editor"), row(60, 90, "editor")], break_after_s=90 * M)
        self.assertEqual(d["long_block_share"], 0.0)

    def test_all_in_one_long_block(self):
        (d,) = run([row(0, 120, "editor")], break_after_s=90 * M)
        self.assertEqual(d["long_block_share"], 1.0)

    def test_the_default_break_after_is_the_blocks_default(self):
        (d,) = run([row(0, 95, "editor")])
        self.assertEqual(d["long_block_share"], 1.0)          # default break_after_min is ninety
        (d,) = run([row(0, 85, "editor")])
        self.assertEqual(d["long_block_share"], 0.0)

    def test_no_work_time_is_unknown_share(self):
        (d,) = run([row(0, 60, "feed")])
        self.assertIsNone(d["long_block_share"])


class TimeBack(unittest.TestCase):
    def test_median_time_back_to_work_after_a_switch(self):
        rows = [row(0, 30, "editor"), row(30, 32, "chat"), row(32, 60, "editor"),        # back in two
                row(60, 65, "feed"), row(65, 66, "chat"), row(66, 90, "editor"),         # back in six
                row(90, 93, "feed"), row(93, 120, "editor")]                             # back in three
        (d,) = run(rows)
        self.assertEqual(d["returns"], 3)
        self.assertEqual(d["median_return_s"], 3 * M)

    def test_even_count_takes_the_middle_two(self):
        rows = [row(0, 30, "editor"), row(30, 32, "chat"), row(32, 60, "editor"),
                row(60, 64, "feed"), row(64, 90, "editor")]
        (d,) = run(rows)
        self.assertEqual(d["median_return_s"], 3 * M)

    def test_no_return_that_day_is_not_counted(self):
        rows = [row(0, 30, "editor"), row(30, 32, "chat"), row(32, 60, "editor"), row(60, 120, "feed")]
        (d,) = run(rows)
        self.assertEqual((d["switches"], d["returns"], d["median_return_s"]), (2, 1, 2 * M))

    def test_a_hole_with_no_row_before_the_return_is_a_break_not_a_return(self):
        # a switch, then nothing for longer than the gap (away), then work: not a time back to work
        rows = [row(0, 30, "editor"), row(30, 32, "feed"), row(32 + 40, 120, "editor")]
        (d,) = run(rows)
        self.assertEqual((d["switches"], d["returns"]), (1, 0))
        self.assertIsNone(d["median_return_s"])

    def test_no_switch_is_unknown_time_back_not_zero(self):
        (d,) = run([row(0, 120, "editor")])
        self.assertIsNone(d["median_return_s"])


if __name__ == "__main__":
    unittest.main()
